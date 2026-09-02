"""落としたデータの検品。

グリッドを回す前に、データそのものが壊れていないかを確かめる。
ここを飛ばすと、結果の数字が何を意味しているのか分からなくなる。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .calendar import BUSINESS_DAY_DIVISIONS
from .config import Config
from .constants import is_excluded

#: 生存バイアスの確認に使う。2025-03-18 上場廃止。
DELISTED_CHECK_CODE = "75180"
DELISTED_LAST_DAY = date(2025, 3, 17)


def verify(cfg: Config, bundle: dict, events: pd.DataFrame, diagnostics: dict) -> str:
    lines: list[str] = ["# データ検品\n"]
    daily = bundle["daily"]
    summary = bundle["summary"]
    topix = bundle.get("topix")
    calendar = bundle["calendar"]

    lines += _section_coverage(daily, summary, topix, calendar)
    lines += _section_daily(daily, calendar)
    lines += _section_summary(summary)
    lines += _section_survivorship(daily)
    lines += _section_events(events, diagnostics)
    lines += _section_topix(topix, calendar)
    return "\n".join(lines)


def _fmt_range(s: pd.Series) -> str:
    v = s.dropna()
    return f"{min(v)} 〜 {max(v)}" if len(v) else "（空）"


def _section_coverage(daily, summary, topix, calendar) -> list[str]:
    out = ["## 1. 収録範囲\n", "```"]
    out.append(f"営業日(カレンダー) : {len(calendar.days):>9,}日  {calendar.days[0]} 〜 {calendar.days[-1]}")
    out.append(f"日足               : {len(daily):>9,}行  {_fmt_range(daily['date'])}")
    out.append(f"財務サマリー       : {len(summary):>9,}行  {_fmt_range(summary['disc_date'])}")
    if topix is not None and len(topix):
        out.append(f"TOPIX              : {len(topix):>9,}行  {_fmt_range(topix['date'])}")
    else:
        out.append("TOPIX              : なし  ← 超過リターンで判定できません")
    out.append("```\n")
    return out


def _section_daily(daily, calendar) -> list[str]:
    out = ["## 2. 日足の穴\n"]
    have = set(daily["date"].dropna().unique())
    want = set(calendar.days)
    missing = sorted(want - have)
    extra = sorted(have - want)

    out.append("```")
    out.append(f"営業日のうち日足がある日: {len(want & have):,} / {len(want):,}")
    if missing:
        out.append(f"日足が無い営業日: {len(missing)}日")
        for d in missing[:10]:
            out.append(f"  {d}")
        if len(missing) > 10:
            out.append(f"  ...他 {len(missing) - 10}日")
    else:
        out.append("日足が無い営業日: なし")
    if extra:
        out.append(f"カレンダー外の日付: {len(extra)}日（{extra[:3]}...）")
    out.append("```\n")

    # 銘柄数の推移。急に減っていたら取得漏れ
    per_day = daily.groupby("date", observed=True).size()
    yearly = per_day.groupby([d.year for d in per_day.index]).agg(["min", "median", "max", "count"])
    out.append("年ごとの1日あたり銘柄数\n")
    out.append("```")
    out.append(f"{'年':<6}{'最小':>8}{'中央':>8}{'最大':>8}{'日数':>8}")
    for year, row in yearly.iterrows():
        out.append(f"{year:<6}{int(row['min']):>8,}{int(row['median']):>8,}"
                   f"{int(row['max']):>8,}{int(row['count']):>8,}")
    out.append("```\n")

    # 重要列の欠損率
    out.append("主要列の欠損率\n```")
    for col in ("open", "close", "adj_open", "adj_close", "volume", "turnover", "mkt_cap"):
        if col in daily.columns:
            rate = daily[col].isna().mean()
            flag = "  ←要確認" if rate > 0.10 else ""
            out.append(f"{col:<12}{rate:>8.2%}{flag}")
    out.append("```\n")

    if "mkt_cap" in daily.columns:
        mc = daily["mkt_cap"].dropna()
        if len(mc):
            out.append("時価総額（円に換算済みか確認）\n```")
            out.append(f"中央値: {mc.median()/1e8:>12,.0f} 億円")
            out.append(f"最大  : {mc.max()/1e8:>12,.0f} 億円")
            ok = 1e9 < mc.median() < 1e13
            out.append(f"判定  : {'妥当' if ok else '★おかしい（単位を確認）'}")
            out.append("```\n")
    return out


def _section_summary(summary) -> list[str]:
    out = ["## 3. 開示の内訳\n```"]
    if "doc_type" in summary.columns:
        counts = summary["doc_type"].astype(str).value_counts()
        for name, n in counts.items():
            out.append(f"{n:>8,}  {name}")
    out.append("```\n")

    per_year = summary.groupby([d.year for d in summary["disc_date"]]).size()
    out.append("年ごとの開示件数\n```")
    for year, n in per_year.items():
        out.append(f"{year}: {n:>8,}")
    out.append("```\n")
    return out


def _section_survivorship(daily) -> list[str]:
    out = ["## 4. 生存バイアス\n```"]
    codes = daily["code"].astype(str)
    hit = daily[codes.isin({DELISTED_CHECK_CODE, "7518"})]
    if len(hit):
        last = max(hit["date"])
        out.append(f"7518（2025-03-18 上場廃止）: {len(hit):,}行  最終日 {last}")
        out.append("=> 上場廃止銘柄が含まれている。生存バイアスは回避できている。")
    else:
        out.append("7518 が見つかりません。")
        out.append("=> ★上場廃止銘柄が落ちている可能性。結果は実際より甘く出ます。")

    # 途中でデータが途切れた銘柄の数 = 上場廃止・統合の目安
    last_seen = daily.groupby("code", observed=True)["date"].max()
    overall_last = daily["date"].max()
    gone = (last_seen < overall_last).sum()
    out.append("")
    out.append(f"最終日まで残っていない銘柄: {gone:,} / {len(last_seen):,}")
    out.append("（上場廃止・経営統合・コード変更の合計。0 なら生存バイアスを疑う）")

    excluded = sorted({c for c in daily["code"].unique() if is_excluded(c)})
    out.append("")
    out.append(f"仕様の除外銘柄がデータ内に存在: {excluded}")
    out.append("```\n")
    return out


def _section_events(events, diagnostics) -> list[str]:
    out = ["## 5. イベントの構築\n```"]
    for k, v in diagnostics.items():
        out.append(f"{k}: {v:,}" if isinstance(v, int) else f"{k}: {v}")
    out.append("```\n")

    if events.empty:
        out.append("★イベントが1件も作れていません。\n")
        return out

    r = events["revision_rate"]
    out.append("```")
    out.append(f"イベント総数            : {len(events):>8,}")
    out.append(f"修正率が計算できたもの  : {r.notna().sum():>8,}")
    out.append(f"  うち上方              : {(r > 0).sum():>8,}")
    out.append(f"  うち下方              : {(r < 0).sum():>8,}")
    out.append(f"初回予想（修正ではない）: {events['is_initial_forecast'].sum():>8,}")
    out.append(f"引け後の開示            : {events['after_close'].sum():>8,}")
    out.append(f"場中の開示              : {(~events['after_close']).sum():>8,}")
    out.append(f"常習（3年で4回以上）    : {events['habitual'].sum():>8,}")
    out.append(f"エントリー日が付いたもの: {events['entry_date'].notna().sum():>8,}")
    out.append("```\n")

    per_year = events.groupby([d.year for d in events["disc_date"]]).size()
    out.append("年ごとのイベント数\n```")
    for year, n in per_year.items():
        out.append(f"{year}: {n:>8,}")
    out.append("```\n")
    return out


def _section_topix(topix, calendar) -> list[str]:
    out = ["## 6. TOPIX\n```"]
    if topix is None or not len(topix):
        out.append("★TOPIX がありません。超過リターンで判定できません。")
        out.append("  erb fetch --tables topix を実行してください。")
        out.append("```\n")
        return out
    have = set(topix["date"].dropna().unique())
    want = set(calendar.days)
    missing = sorted(want - have)
    out.append(f"営業日のうち TOPIX がある日: {len(want & have):,} / {len(want):,}")
    if missing:
        out.append(f"欠けている日: {len(missing)}日（{[str(d) for d in missing[:5]]}...）")
    for col in ("open", "close"):
        if col in topix.columns:
            v = pd.to_numeric(topix[col], errors="coerce").dropna()
            if len(v):
                out.append(f"{col}: {v.min():,.1f} 〜 {v.max():,.1f}")
    out.append("```\n")
    return out
