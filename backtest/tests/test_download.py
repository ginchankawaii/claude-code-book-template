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
    d.base_sleep = 0.0
    d.sleep = 0.0
    d.rate_limit_hits = 0
    d.consecutive_ok = 0
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
    """HolDiv は 0=非営業日 / 1=営業日 / 2=東証半日立会日 / 3=祝日取引の非営業日。

    ここを取り違えると、土日祝だけを取りに行って全部0行になる。
    """
    cal = pd.DataFrame([
        {"Date": "2024-01-01", "HolDiv": "0"},   # 元日
        {"Date": "2024-01-04", "HolDiv": "1"},   # 営業日
        {"Date": "2024-01-05", "HolDiv": "1"},   # 営業日
        {"Date": "2024-01-06", "HolDiv": "0"},   # 土曜
        {"Date": "2024-01-09", "HolDiv": "2"},   # 半日立会日 -> 営業日として扱う
        {"Date": "2024-01-10", "HolDiv": "3"},   # 祝日取引（デリバのみ）-> 除く
        {"Date": "2024-02-01", "HolDiv": "1"},
    ])
    days = dl.business_days(cal, date(2024, 1, 1), date(2024, 1, 31))
    assert days == [date(2024, 1, 4), date(2024, 1, 5), date(2024, 1, 9)]


def test_business_days_raises_when_nothing_matches(dl):
    """営業日が0日なら黙って進まず止まる。前回はここで気づけなかった。"""
    cal = pd.DataFrame([{"Date": "2024-01-04", "HolDiv": "9"}])
    with pytest.raises(RuntimeError, match="営業日が0日"):
        dl.business_days(cal, date(2024, 1, 1), date(2024, 1, 31))


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


def test_incomplete_month_is_refetched(dl, tmp_path):
    """1日でも落ちた月は、次回に取り直すこと。"""
    calls = []
    real = dl.client.get

    def flaky(path, params, attempts=8):
        calls.append(params.get("date"))
        if params.get("date") == "20240105":
            raise RuntimeError("boom")
        return real(path, params)["data"]

    dl.get_with_retry = flaky
    days = _days((2024, 1, 4), (2024, 1, 5))
    dl.fetch_by_date("daily", days)
    assert len(dl.progress.errors) == 1

    calls.clear()
    dl.fetch_by_date("daily", days)
    assert calls, "落ちた日がある月は取り直されるべき"


def test_zero_row_daily_month_is_not_treated_as_done(dl, tmp_path):
    """日足が0行の月は異常なので、完了扱いにしないこと。

    HolDiv を取り違えて非営業日を取りに行った回は全月0行になった。
    それを「取得済み」として記録してしまうと、直しても取り直されない。
    """
    dl.client.rows_per_day = 0
    days = _days((2024, 1, 4))
    dl.fetch_by_date("daily", days)
    assert not dl.month_is_complete("daily", "2024-01", 1)

    dl.client.rows_per_day = 3
    dl.fetch_by_date("daily", days)
    assert len(pd.read_parquet(tmp_path / "raw" / "daily" / "2024-01.parquet")) == 3


def test_stale_version_invalidates_existing_months(dl, tmp_path):
    """保存形式の版を上げると、古い月ファイルは取り直しになる。"""
    import json

    from erb.download import MANIFEST_VERSION

    outdir = tmp_path / "raw" / "daily"
    outdir.mkdir(parents=True)
    pd.DataFrame([{"Date": "2024-01-04", "Code": "10000"}]).to_parquet(
        outdir / "2024-01.parquet", index=False)
    (outdir / "2024-01.meta.json").write_text(json.dumps(
        {"version": MANIFEST_VERSION - 1, "expected_days": 1, "rows": 1, "failed_days": []}))
    assert not dl.month_is_complete("daily", "2024-01", 1)


def test_rate_limit_widens_the_interval_and_waits(dl, monkeypatch):
    """429 は Retry-After に従って待ち、以後の間隔も広げること。"""
    from erb.fetch import JQuantsHTTPError

    slept: list[float] = []
    monkeypatch.setattr("erb.download.time.sleep", lambda s: slept.append(s))

    calls = {"n": 0}

    def limited(path, params):
        calls["n"] += 1
        if calls["n"] == 1:
            raise JQuantsHTTPError(429, path, "Too Many Requests", retry_after=7.0)
        return {"data": [{"Date": "2024-01-04", "Code": "10000"}]}

    dl.client.get = limited
    before = dl.sleep
    rows = dl.get_with_retry("/equities/bars/daily", {"date": "20240104"})

    assert len(rows) == 1
    assert 7.0 in slept                      # Retry-After に従った
    assert dl.rate_limit_hits == 1
    assert dl.sleep > before                 # 間隔が広がった


def test_server_error_is_retried_but_403_is_not(dl, monkeypatch):
    from erb.fetch import JQuantsHTTPError

    monkeypatch.setattr("erb.download.time.sleep", lambda s: None)

    calls = {"n": 0}

    def flaky(path, params):
        calls["n"] += 1
        if calls["n"] < 3:
            raise JQuantsHTTPError(503, path, "Service Unavailable")
        return {"data": [{"Date": "2024-01-04"}]}

    dl.client.get = flaky
    assert len(dl.get_with_retry("/x", {})) == 1
    assert calls["n"] == 3

    def forbidden(path, params):
        raise JQuantsHTTPError(403, path, "Forbidden")

    dl.client.get = forbidden
    with pytest.raises(JQuantsHTTPError):
        dl.get_with_retry("/x", {}, attempts=5)


def test_a_bug_in_our_code_is_not_retried(dl, monkeypatch):
    """こちらの不具合を通信エラーと同じに扱わないこと。

    以前は except Exception で拾っていたため、属性名の打ち間違いを
    5秒→10秒→…と待ちながら8回再試行し、10分近く固まっていた。
    """
    slept: list[float] = []
    monkeypatch.setattr("erb.download.time.sleep", lambda s: slept.append(s))

    def broken(path, params):
        raise AttributeError("'Downloader' object has no attribute 'typo'")

    dl.client.get = broken
    with pytest.raises(AttributeError):
        dl.get_with_retry("/x", {})
    assert slept == []      # 1秒も待たずに落ちる
