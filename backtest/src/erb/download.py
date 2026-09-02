"""J-Quants から5年分を落とす。

全銘柄 x 約1,225営業日 = 500万行を超えるので、次の方針で作る。

  - 1営業日ずつ取り、月ごとの parquet に落とす
  - すでにある月は飛ばす（中断しても再開できる）
  - 429 / 5xx は指数バックオフで待って再試行する
  - 最後に月次ファイルを1本に束ねる

途中で止めても、もう一度同じコマンドを打てば続きから走る。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .config import Config
from .fetch import JQuantsClient, _extract_records, fmt_date

#: TOPIX のパスは Free では 403 で確認できなかったため候補を順に試す。
TOPIX_CANDIDATES = ["/indices/daily-topix", "/indices/topix", "/indices/daily_topix"]

#: 日付ごとに取る表。銘柄マスタは月次スナップショットで足りる。
BY_DATE_TABLES = ("daily", "summary")


@dataclass
class Progress:
    fetched_months: int = 0
    skipped_months: int = 0
    rows: int = 0
    empty_days: int = 0
    errors: list[str] = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


class Downloader:
    def __init__(self, cfg: Config, data_dir: Path, sleep: float | None = None) -> None:
        self.cfg = cfg
        self.client = JQuantsClient(cfg)
        self.raw = data_dir / "raw"
        self.data_dir = data_dir
        self.sleep = self.client.sleep if sleep is None else sleep
        self.progress = Progress()

    # ------------------------------------------------------------------ 取得

    def get_with_retry(self, path: str, params: dict, attempts: int = 5) -> list[dict]:
        """1リクエスト。ページ送りを最後まで辿る。429/5xx は待って再試行。"""
        out: list[dict] = []
        page_params = dict(params)
        while True:
            delay = 1.0
            for attempt in range(attempts):
                try:
                    body = self.client.get(path, page_params)
                    break
                except Exception as exc:  # noqa: BLE001
                    msg = str(exc)
                    retriable = any(s in msg for s in ("429", "500", "502", "503", "504", "Timeout", "timed out"))
                    if not retriable or attempt == attempts - 1:
                        raise
                    time.sleep(delay)
                    delay *= 2
            out.extend(_extract_records(body))
            key = body.get("pagination_key") if isinstance(body, dict) else None
            if not key:
                return out
            page_params["pagination_key"] = key
            time.sleep(self.sleep)

    # -------------------------------------------------------------- カレンダー

    def fetch_calendar(self, start: date, end: date) -> pd.DataFrame:
        """取引カレンダー。以降の日付ループの土台になるので最初に取る。"""
        path = self.cfg["api"]["endpoints"]["calendar"]
        rows: list[dict] = []
        # 期間が長いと弾かれることがあるので1年ずつ刻む
        cursor = start
        while cursor <= end:
            chunk_end = min(date(cursor.year, 12, 31), end)
            rows += self.get_with_retry(path, {"from": fmt_date(cursor), "to": fmt_date(chunk_end)})
            time.sleep(self.sleep)
            cursor = chunk_end + timedelta(days=1)
        df = pd.DataFrame(rows)
        if df.empty:
            raise RuntimeError("取引カレンダーが空です。期間指定を確認してください。")
        out = self.data_dir / "calendar.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False)
        print(f"  カレンダー: {len(df)}件 -> {out}")
        return df

    def business_days(self, calendar_df: pd.DataFrame, start: date, end: date) -> list[date]:
        div = calendar_df["HolDiv"].astype(str).str.strip()
        days = pd.to_datetime(calendar_df.loc[div == "0", "Date"]).dt.date
        return sorted(d for d in days if start <= d <= end)

    # ------------------------------------------------------------ 日付ループ

    def fetch_by_date(self, table: str, days: list[date]) -> None:
        """1営業日ずつ取り、月単位の parquet に落とす。既にある月は飛ばす。"""
        path = self.cfg["api"]["endpoints"][table]
        outdir = self.raw / table
        outdir.mkdir(parents=True, exist_ok=True)

        by_month: dict[str, list[date]] = {}
        for d in days:
            by_month.setdefault(f"{d.year:04d}-{d.month:02d}", []).append(d)

        for month in sorted(by_month):
            target = outdir / f"{month}.parquet"
            if target.exists():
                self.progress.skipped_months += 1
                continue

            rows: list[dict] = []
            for d in by_month[month]:
                try:
                    recs = self.get_with_retry(path, {"date": fmt_date(d)})
                except Exception as exc:  # noqa: BLE001
                    self.progress.errors.append(f"{table} {d}: {exc}")
                    print(f"    ! {table} {d} 取得失敗: {exc}")
                    continue
                if not recs:
                    self.progress.empty_days += 1
                rows.extend(recs)
                time.sleep(self.sleep)

            df = pd.DataFrame(rows)
            # 空の月でもファイルを作る。作らないと毎回取りに行ってしまう。
            df.to_parquet(target, index=False)
            self.progress.fetched_months += 1
            self.progress.rows += len(df)
            print(f"  {table} {month}: {len(df):>7,}行 ({len(by_month[month])}営業日)")

    # ---------------------------------------------------------- 銘柄マスタ

    def fetch_master(self, days: list[date]) -> None:
        """月初の営業日でスナップショットを取る。

        信用区分や市場区分は時期によって変わるため、1枚で済ませず
        月次で持つ。イベント時点の区分で判定できるようにするため。
        """
        path = self.cfg["api"]["endpoints"]["master"]
        outdir = self.raw / "master"
        outdir.mkdir(parents=True, exist_ok=True)

        firsts: dict[str, date] = {}
        for d in days:
            firsts.setdefault(f"{d.year:04d}-{d.month:02d}", d)

        for month, d in sorted(firsts.items()):
            target = outdir / f"{month}.parquet"
            if target.exists():
                self.progress.skipped_months += 1
                continue
            try:
                recs = self.get_with_retry(path, {"date": fmt_date(d)})
            except Exception as exc:  # noqa: BLE001
                self.progress.errors.append(f"master {d}: {exc}")
                print(f"    ! master {d} 取得失敗: {exc}")
                continue
            pd.DataFrame(recs).to_parquet(target, index=False)
            self.progress.fetched_months += 1
            self.progress.rows += len(recs)
            print(f"  master {month}: {len(recs):>7,}行")
            time.sleep(self.sleep)

    # ---------------------------------------------------------------- TOPIX

    def fetch_topix(self, days: list[date]) -> str | None:
        """TOPIX 日足。パスが未確定なので候補を順に試す。

        超過リターンの判定に必須。取れなければその旨を返して続行する。
        """
        configured = self.cfg["api"]["endpoints"].get("topix")
        candidates = [configured] + [c for c in TOPIX_CANDIDATES if c != configured]

        probe_day = days[len(days) // 2]
        path = None
        for cand in candidates:
            if not cand:
                continue
            try:
                recs = self.get_with_retry(cand, {"date": fmt_date(probe_day)}, attempts=1)
            except Exception as exc:  # noqa: BLE001
                print(f"  topix {cand}: {exc}")
                continue
            if recs:
                path = cand
                print(f"  topix パス確定: {cand}")
                break
        if path is None:
            print("  ! TOPIX が取得できませんでした。超過リターンの判定ができません。")
            self.progress.errors.append("topix: パスが特定できない")
            return None

        outdir = self.raw / "topix"
        outdir.mkdir(parents=True, exist_ok=True)
        by_month: dict[str, list[date]] = {}
        for d in days:
            by_month.setdefault(f"{d.year:04d}-{d.month:02d}", []).append(d)

        for month in sorted(by_month):
            target = outdir / f"{month}.parquet"
            if target.exists():
                self.progress.skipped_months += 1
                continue
            rows: list[dict] = []
            for d in by_month[month]:
                try:
                    rows.extend(self.get_with_retry(path, {"date": fmt_date(d)}))
                except Exception as exc:  # noqa: BLE001
                    self.progress.errors.append(f"topix {d}: {exc}")
                time.sleep(self.sleep)
            pd.DataFrame(rows).to_parquet(target, index=False)
            self.progress.fetched_months += 1
            print(f"  topix {month}: {len(rows):>5,}行")
        return path

    # ---------------------------------------------------------------- 束ねる

    def consolidate(self, table: str) -> Path | None:
        """月次ファイルを1本の parquet にまとめる。"""
        outdir = self.raw / table
        if not outdir.exists():
            return None
        parts = sorted(outdir.glob("*.parquet"))
        if not parts:
            return None
        frames = [pd.read_parquet(p) for p in parts]
        frames = [f for f in frames if not f.empty]
        if not frames:
            print(f"  {table}: データが空です")
            return None
        df = pd.concat(frames, ignore_index=True)
        # 同じ日を二度取った場合に備えて重複を落とす
        keys = [c for c in ("Date", "Code", "DiscNo") if c in df.columns]
        if keys:
            before = len(df)
            df = df.drop_duplicates(subset=keys, keep="last")
            if before != len(df):
                print(f"  {table}: 重複 {before - len(df):,}行を除去")
        target = self.data_dir / f"{table}.parquet"
        df.to_parquet(target, index=False)
        print(f"  {table}: {len(df):,}行 -> {target}")
        return target


def run(cfg: Config, data_dir: Path, start: date, end: date,
        tables: tuple[str, ...] | None = None) -> Progress:
    dl = Downloader(cfg, data_dir)

    print(f"期間: {start} 〜 {end}")
    print("\n[1/5] 取引カレンダー")
    cal = dl.fetch_calendar(start, end)
    days = dl.business_days(cal, start, end)
    print(f"  営業日: {len(days)}日")

    want = tables or ("daily", "summary", "master", "topix")

    if "daily" in want:
        print(f"\n[2/5] 株価日足（{len(days)}営業日）")
        dl.fetch_by_date("daily", days)
    if "summary" in want:
        print(f"\n[3/5] 財務サマリー（{len(days)}営業日）")
        dl.fetch_by_date("summary", days)
    if "master" in want:
        print("\n[4/5] 銘柄マスタ（月次スナップショット）")
        dl.fetch_master(days)
    if "topix" in want:
        print("\n[5/5] TOPIX 日足")
        dl.fetch_topix(days)

    print("\n[束ねる]")
    for table in ("daily", "summary", "master", "topix"):
        if table in want:
            dl.consolidate(table)

    p = dl.progress
    print(f"\n取得した月: {p.fetched_months} / 既存で飛ばした月: {p.skipped_months}")
    print(f"行数: {p.rows:,}  開示のなかった日: {p.empty_days}")
    if p.errors:
        print(f"\nエラー {len(p.errors)}件（先頭10件）:")
        for e in p.errors[:10]:
            print(f"  {e}")
        print("\n同じコマンドをもう一度打つと、取れなかった月だけ取り直します。")
    return p
