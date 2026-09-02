"""J-Quants から5年分を落とす。

全銘柄 x 約1,225営業日 = 500万行を超えるので、次の方針で作る。

  - 1営業日ずつ取り、月ごとの parquet に落とす
  - すでにある月は飛ばす（中断しても再開できる）
  - 429 / 5xx は指数バックオフで待って再試行する
  - 最後に月次ファイルを1本に束ねる

途中で止めても、もう一度同じコマンドを打てば続きから走る。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

from .calendar import BUSINESS_DAY_DIVISIONS
from .config import Config
from .fetch import JQuantsClient, JQuantsHTTPError, _extract_records, fmt_date

#: TOPIX 日足。公式クライアント(IdxBarsDailyTopixApiV2)と公式ドキュメントで確認済み。
#: 銘柄指定が無い1本の系列なので、date ではなく from/to を取る。
TOPIX_PATH = "/indices/bars/daily/topix"

#: 日付ごとに取る表。銘柄マスタは月次スナップショットで足りる。
BY_DATE_TABLES = ("daily", "summary")

#: 保存形式の版。上げると既存の月ファイルを取り直す。
#: v1 は HolDiv を取り違えて非営業日を取りに行っていたため、中身が空だった。
MANIFEST_VERSION = 2

#: 429 が返ったときの待機。Retry-After が無ければこの秒数から倍々にする。
RATE_LIMIT_BASE_WAIT = 5.0
RATE_LIMIT_MAX_WAIT = 300.0

#: 429 を食らうたびにリクエスト間隔を伸ばす倍率と上限。
THROTTLE_GROWTH = 1.5
THROTTLE_MAX_SLEEP = 10.0

#: 再試行してよい通信起因の例外。
#: ここを Exception にすると、こちらのバグ（属性名の間違いなど）まで
#: 何分も待って再試行してしまい、原因が見えなくなる。
RETRIABLE_NETWORK_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


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
        self.base_sleep = self.client.sleep if sleep is None else sleep
        self.sleep = self.base_sleep
        self.rate_limit_hits = 0
        self.consecutive_ok = 0
        self.progress = Progress()

    # ------------------------------------------------------------------ 取得

    def get_with_retry(self, path: str, params: dict, attempts: int = 8) -> list[dict]:
        """1リクエスト。ページ送りを最後まで辿る。

        429 は Retry-After に従い、無ければ 5 秒から倍々で待つ。
        429 を食らうたびに以後のリクエスト間隔そのものを伸ばして、
        同じ壁に繰り返しぶつからないようにする。
        """
        out: list[dict] = []
        page_params = dict(params)
        while True:
            body = None
            wait = RATE_LIMIT_BASE_WAIT
            for attempt in range(attempts):
                try:
                    body = self.client.get(path, page_params)
                    self._on_success()
                    break
                except JQuantsHTTPError as exc:
                    if not exc.is_retriable or attempt == attempts - 1:
                        raise
                    if exc.is_rate_limited:
                        self._on_rate_limited()
                        pause = exc.retry_after if exc.retry_after else wait
                    else:
                        pause = wait
                    pause = min(pause, RATE_LIMIT_MAX_WAIT)
                    print(f"    待機 {pause:.0f}秒 (HTTP {exc.status}, {attempt + 1}/{attempts})")
                    time.sleep(pause)
                    wait = min(wait * 2, RATE_LIMIT_MAX_WAIT)
                except RETRIABLE_NETWORK_ERRORS as exc:
                    if attempt == attempts - 1:
                        raise
                    print(f"    待機 {wait:.0f}秒 ({type(exc).__name__}, "
                          f"{attempt + 1}/{attempts})")
                    time.sleep(wait)
                    wait = min(wait * 2, RATE_LIMIT_MAX_WAIT)
            if body is None:
                raise RuntimeError(f"再試行を使い切りました: {path} {params}")

            out.extend(_extract_records(body))
            key = body.get("pagination_key") if isinstance(body, dict) else None
            if not key:
                return out
            page_params["pagination_key"] = key
            time.sleep(self.sleep)

    def _on_rate_limited(self) -> None:
        self.rate_limit_hits += 1
        before = self.sleep
        self.sleep = min(max(self.sleep, 0.2) * THROTTLE_GROWTH, THROTTLE_MAX_SLEEP)
        if self.sleep != before:
            print(f"    リクエスト間隔を {before:.2f}秒 -> {self.sleep:.2f}秒 に広げます")

    def _on_success(self) -> None:
        self.consecutive_ok += 1
        # 十分に成功が続いたら少しだけ間隔を戻す（戻しすぎない）
        if self.consecutive_ok >= 200 and self.sleep > self.base_sleep:
            self.sleep = max(self.base_sleep, self.sleep / 1.2)
            self.consecutive_ok = 0

    # ------------------------------------------------------- 月ファイルの検証

    def _manifest_path(self, table: str, month: str) -> Path:
        return self.raw / table / f"{month}.meta.json"

    def month_is_complete(self, table: str, month: str, expected_days: int) -> bool:
        """その月を取り直す必要があるか。

        版が古い、日数が合わない、日足なのに0行、のいずれかなら取り直す。
        前回の実行は非営業日を取りに行って全月0行のファイルを作ってしまったので、
        版を上げてそれらを自動的に無効化する。
        """
        target = self.raw / table / f"{month}.parquet"
        if not target.exists():
            return False
        meta_path = self._manifest_path(table, month)
        if not meta_path.exists():
            return False
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if meta.get("version") != MANIFEST_VERSION:
            return False
        if meta.get("expected_days") != expected_days:
            return False
        if meta.get("failed_days"):
            return False
        # 日足は全銘柄が返るはずなので、0行は異常
        if table == "daily" and meta.get("rows", 0) == 0:
            return False
        return True

    def _write_manifest(self, table: str, month: str, expected_days: int,
                        rows: int, failed_days: list[str]) -> None:
        self._manifest_path(table, month).write_text(
            json.dumps({
                "version": MANIFEST_VERSION,
                "expected_days": expected_days,
                "rows": rows,
                "failed_days": failed_days,
            }, ensure_ascii=False),
            encoding="utf-8",
        )

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
        """営業日だけを返す。

        HolDiv は 0=非営業日 / 1=営業日 / 2=東証半日立会日 /
        3=祝日取引のある非営業日（デリバティブのみ）。
        """
        div = calendar_df["HolDiv"].astype(str).str.strip()
        days = pd.to_datetime(
            calendar_df.loc[div.isin(BUSINESS_DAY_DIVISIONS), "Date"]).dt.date
        out = sorted(d for d in days if start <= d <= end)
        if not out:
            raise RuntimeError(
                f"営業日が0日です。HolDiv の値を確認してください: {sorted(div.unique())}")
        return out

    # ------------------------------------------------------------ 日付ループ

    def fetch_by_date(self, table: str, days: list[date]) -> None:
        """1営業日ずつ取り、月単位の parquet に落とす。

        マニフェストで「その月を取り切れたか」を記録し、取り切れた月だけ飛ばす。
        1日でも落ちた月は次回に取り直す。
        """
        path = self.cfg["api"]["endpoints"][table]
        outdir = self.raw / table
        outdir.mkdir(parents=True, exist_ok=True)

        by_month: dict[str, list[date]] = {}
        for d in days:
            by_month.setdefault(f"{d.year:04d}-{d.month:02d}", []).append(d)

        for month in sorted(by_month):
            span = by_month[month]
            if self.month_is_complete(table, month, len(span)):
                self.progress.skipped_months += 1
                continue

            rows: list[dict] = []
            failed: list[str] = []
            for d in span:
                try:
                    recs = self.get_with_retry(path, {"date": fmt_date(d)})
                except Exception as exc:  # noqa: BLE001
                    failed.append(d.isoformat())
                    self.progress.errors.append(f"{table} {d}: {exc}")
                    print(f"    ! {table} {d} 取得失敗: {exc}")
                    continue
                if not recs:
                    self.progress.empty_days += 1
                rows.extend(recs)
                time.sleep(self.sleep)

            pd.DataFrame(rows).to_parquet(outdir / f"{month}.parquet", index=False)
            self._write_manifest(table, month, len(span), len(rows), failed)
            self.progress.fetched_months += 1
            self.progress.rows += len(rows)
            note = f"  ※{len(failed)}日が未取得（次回取り直します）" if failed else ""
            print(f"  {table} {month}: {len(rows):>7,}行 ({len(span)}営業日){note}")

    # ---------------------------------------------------------- 銘柄マスタ

    def fetch_master(self, days: list[date]) -> None:
        """月初の営業日でスナップショットを取る。

        信用区分や市場区分は時期によって変わるため、1枚で済ませず月次で持つ。
        イベント時点の区分で判定できるようにするため。
        """
        path = self.cfg["api"]["endpoints"]["master"]
        outdir = self.raw / "master"
        outdir.mkdir(parents=True, exist_ok=True)

        firsts: dict[str, date] = {}
        for d in days:
            firsts.setdefault(f"{d.year:04d}-{d.month:02d}", d)

        for month, d in sorted(firsts.items()):
            if self.month_is_complete("master", month, 1):
                self.progress.skipped_months += 1
                continue
            try:
                recs = self.get_with_retry(path, {"date": fmt_date(d)})
            except Exception as exc:  # noqa: BLE001
                self.progress.errors.append(f"master {d}: {exc}")
                print(f"    ! master {d} 取得失敗: {exc}")
                continue
            pd.DataFrame(recs).to_parquet(outdir / f"{month}.parquet", index=False)
            self._write_manifest("master", month, 1, len(recs), [])
            self.progress.fetched_months += 1
            self.progress.rows += len(recs)
            print(f"  master {month}: {len(recs):>7,}行")
            time.sleep(self.sleep)

    # ---------------------------------------------------------------- TOPIX

    def fetch_topix(self, days: list[date]) -> str | None:
        """TOPIX 日足。超過リターンの判定に必須。

        銘柄別ではなく1本の系列なので from/to で期間指定する。
        月単位に1リクエストで済むため、日足の1/20の回数で終わる。
        """
        path = self.cfg["api"]["endpoints"].get("topix") or TOPIX_PATH
        outdir = self.raw / "topix"
        outdir.mkdir(parents=True, exist_ok=True)

        by_month: dict[str, list[date]] = {}
        for d in days:
            by_month.setdefault(f"{d.year:04d}-{d.month:02d}", []).append(d)

        for month in sorted(by_month):
            span = by_month[month]
            if self.month_is_complete("topix", month, len(span)):
                self.progress.skipped_months += 1
                continue
            try:
                rows = self.get_with_retry(
                    path, {"from": fmt_date(span[0]), "to": fmt_date(span[-1])})
            except Exception as exc:  # noqa: BLE001
                self.progress.errors.append(f"topix {month}: {exc}")
                print(f"    ! topix {month} 取得失敗: {exc}")
                continue
            pd.DataFrame(rows).to_parquet(outdir / f"{month}.parquet", index=False)
            self._write_manifest("topix", month, len(span), len(rows), [])
            self.progress.fetched_months += 1
            self.progress.rows += len(rows)
            print(f"  topix {month}: {len(rows):>5,}行")
            time.sleep(self.sleep)
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
    if dl.rate_limit_hits:
        print(f"レート制限(429): {dl.rate_limit_hits}回  最終的な間隔: {dl.sleep:.2f}秒")
    print(f"行数: {p.rows:,}  開示のなかった日: {p.empty_days}")
    if p.errors:
        print(f"\nエラー {len(p.errors)}件（先頭10件）:")
        for e in p.errors[:10]:
            print(f"  {e}")
        print("\n同じコマンドをもう一度打つと、取れなかった月だけ取り直します。")
    return p
