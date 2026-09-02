"""ダウンローダ。実際のAPIは叩かず、クライアントを差し替えて検証する。

5年分は500万行を超え、途中で止まることが前提になる。
「再開できること」と「取り直さないこと」が壊れていないかを固定する。
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from erb.download import Downloader


class StubClient:
    """呼ばれた回数を数えるだけのクライアント。"""

    def __init__(self, rows_per_day: int = 3) -> None:
        self.rows_per_day = rows_per_day
        self.calls: list[tuple[str, dict]] = []
        self.sleep = 0.0

    def get(self, path: str, params: dict) -> dict:
        self.calls.append((path, dict(params)))
        d = params.get("date")
        if d is None:
            return {"data": []}
        return {"data": [
            {"Date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "Code": f"1000{i}", "C": 100 + i}
            for i in range(self.rows_per_day)
        ]}


@pytest.fixture
def dl(cfg, tmp_path) -> Downloader:
    d = Downloader.__new__(Downloader)
    d.cfg = cfg
    d.client = StubClient()
    d.raw = tmp_path / "raw"
    d.data_dir = tmp_path
    d.sleep = 0.0
    from erb.download import Progress
    d.progress = Progress()
    return d


def _days(*specs) -> list[date]:
    return [date(*s) for s in specs]


def test_fetch_writes_one_file_per_month(dl, tmp_path):
    days = _days((2024, 1, 4), (2024, 1, 5), (2024, 2, 1))
    dl.fetch_by_date("daily", days)
    assert (tmp_path / "raw" / "daily" / "2024-01.parquet").exists()
    assert (tmp_path / "raw" / "daily" / "2024-02.parquet").exists()
    assert len(pd.read_parquet(tmp_path / "raw" / "daily" / "2024-01.parquet")) == 6


def test_existing_month_is_not_refetched(dl, tmp_path):
    """再開したとき、取得済みの月にリクエストを飛ばさないこと。"""
    days = _days((2024, 1, 4), (2024, 2, 1))
    dl.fetch_by_date("daily", days)
    first_round = len(dl.client.calls)
    assert first_round == 2

    dl.fetch_by_date("daily", days)
    assert len(dl.client.calls) == first_round      # 1回も増えない
    assert dl.progress.skipped_months == 2


def test_empty_month_still_creates_a_file(dl, tmp_path):
    """開示が1件も無い月でもファイルを作る。

    作らないと、再開のたびに同じ月を取りに行き続けることになる。
    """
    dl.client.rows_per_day = 0
    days = _days((2024, 1, 4))
    dl.fetch_by_date("summary", days)
    f = tmp_path / "raw" / "summary" / "2024-01.parquet"
    assert f.exists()
    assert pd.read_parquet(f).empty

    calls = len(dl.client.calls)
    dl.fetch_by_date("summary", days)
    assert len(dl.client.calls) == calls


def test_a_failing_day_does_not_lose_the_rest_of_the_month(dl, tmp_path):
    """1日が落ちても、その月の他の日は保存されること。"""
    good = dl.client.get

    def flaky(path, params, attempts=5):
        if params.get("date") == "20240105":
            raise RuntimeError("500 Internal Server Error（再試行しても復旧せず）")
        return good(path, params)["data"]

    dl.get_with_retry = flaky
    dl.fetch_by_date("daily", _days((2024, 1, 4), (2024, 1, 5), (2024, 1, 8)))
    df = pd.read_parquet(tmp_path / "raw" / "daily" / "2024-01.parquet")
    assert len(df) == 6                       # 2日分は残る
    assert len(dl.progress.errors) == 1


def test_consolidate_merges_months_and_drops_duplicates(dl, tmp_path):
    outdir = tmp_path / "raw" / "daily"
    outdir.mkdir(parents=True)
    pd.DataFrame([
        {"Date": "2024-01-04", "Code": "10000", "C": 100},
        {"Date": "2024-01-05", "Code": "10000", "C": 101},
    ]).to_parquet(outdir / "2024-01.parquet", index=False)
    pd.DataFrame([
        {"Date": "2024-01-05", "Code": "10000", "C": 999},   # 重複（取り直した分）
        {"Date": "2024-02-01", "Code": "10000", "C": 102},
    ]).to_parquet(outdir / "2024-02.parquet", index=False)

    dl.consolidate("daily")
    df = pd.read_parquet(tmp_path / "daily.parquet")
    assert len(df) == 3
    # 後から取った方を残す
    assert df.loc[df["Date"] == "2024-01-05", "C"].iloc[0] == 999


def test_consolidate_skips_empty_parts(dl, tmp_path):
    outdir = tmp_path / "raw" / "summary"
    outdir.mkdir(parents=True)
    pd.DataFrame([{"DiscDate": "2024-01-04", "Code": "10000", "DiscNo": "1"}]).to_parquet(
        outdir / "2024-01.parquet", index=False)
    pd.DataFrame().to_parquet(outdir / "2024-02.parquet", index=False)

    dl.consolidate("summary")
    assert len(pd.read_parquet(tmp_path / "summary.parquet")) == 1


def test_business_days_uses_holdiv_and_range(dl):
    cal = pd.DataFrame([
        {"Date": "2024-01-01", "HolDiv": "1"},   # 元日
        {"Date": "2024-01-04", "HolDiv": "0"},
        {"Date": "2024-01-05", "HolDiv": "0"},
        {"Date": "2024-01-06", "HolDiv": "1"},   # 土曜
        {"Date": "2024-02-01", "HolDiv": "0"},
    ])
    days = dl.business_days(cal, date(2024, 1, 1), date(2024, 1, 31))
    assert days == [date(2024, 1, 4), date(2024, 1, 5)]


def test_master_is_snapshotted_once_per_month(dl, tmp_path):
    """銘柄マスタは月初だけ取る。信用区分は変わりうるので1枚では足りない。"""
    days = _days((2024, 1, 4), (2024, 1, 5), (2024, 1, 9), (2024, 2, 1), (2024, 2, 2))
    dl.fetch_master(days)
    assert len(dl.client.calls) == 2
    assert {c[1]["date"] for c in dl.client.calls} == {"20240104", "20240201"}


def test_topix_is_fetched_by_range_not_by_day(dl, tmp_path):
    """TOPIX は銘柄指定のない1本の系列なので from/to で期間取得する。

    date で1日ずつ叩くと 403 になるうえ、リクエスト数が20倍になる。
    """
    captured: list[dict] = []

    def stub(path, params, attempts=5):
        captured.append({"path": path, **params})
        return [{"Date": "2024-01-04", "O": 2000.0, "C": 2010.0}]

    dl.get_with_retry = stub
    days = _days((2024, 1, 4), (2024, 1, 5), (2024, 1, 9), (2024, 2, 1))
    path = dl.fetch_topix(days)

    assert path == "/indices/bars/daily/topix"
    # 2か月ぶん = 2リクエスト（日数ぶんではない）
    assert len(captured) == 2
    assert captured[0]["from"] == "20240104" and captured[0]["to"] == "20240109"
    assert captured[1]["from"] == "20240201" and captured[1]["to"] == "20240201"
    assert "date" not in captured[0]


def test_topix_months_already_present_are_skipped(dl, tmp_path):
    calls = []
    dl.get_with_retry = lambda path, params, attempts=5: (
        calls.append(params) or [{"Date": "2024-01-04", "O": 2000.0, "C": 2010.0}])
    days = _days((2024, 1, 4))
    dl.fetch_topix(days)
    dl.fetch_topix(days)
    assert len(calls) == 1
