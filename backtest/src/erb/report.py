"""結果の Markdown 出力。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import grid as grid_mod
from .config import Config


def write_results(result: grid_mod.GridResult, cfg: Config, out_dir: Path,
                  diagnostics: dict, generated_at: str) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []

    cells = result.cells
    csv_path = out_dir / "grid.csv"
    cells.to_csv(csv_path, index=False)
    written.append(csv_path)

    md = [f"# バックテスト結果\n", f"生成: {generated_at}\n"]

    md.append("## 1. 判定（主条件・事前登録セル）\n")
    primary = grid_mod.primary_cell(cells, cfg)
    if primary.empty:
        md.append("主条件に一致するセルがありません。config.yaml の judgement.primary_cell を確認してください。\n")
    else:
        md.append(_table(primary[[
            "holding_days", "revision_threshold", "slippage_pct", "trades",
            "gross_pct", "excess_topix_pct", "net_edge_pct",
            "t_stat", "cluster_ci_low_pct", "cluster_ci_high_pct",
            "required_n", "verdict", "decision",
        ]]))
        md.append("")
        md.append("判定基準: 純エッジ = TOPIX超過の粗エッジ − スリッページ − 金利\n")
        md.append("```\n< 0.05%        打ち切り\n0.05 〜 0.35%  ペーパートレード3か月\n> 0.35%        少額実弾\n```\n")

    md.append("## 2. 安定性（全条件でプラスか）\n")
    stab = grid_mod.stability_check(cells)
    md.append("```")
    for k, v in stab.items():
        md.append(f"{k}: {v}")
    md.append("```")
    md.append("対照群を除く全セルで純エッジがプラスでなければ採用しない。\n")

    md.append("## 3. 対照群\n")
    md.append("上方修正だけが優位でなければ、拾っているのは市場ベータであってイベントのエッジではない。\n")
    ctrl = cells[cells["is_control"] & (cells["timing"] == "all")]
    if not ctrl.empty:
        md.append(_table(ctrl[[
            "holding_days", "revision_threshold", "slippage_pct", "trades",
            "gross_pct", "excess_topix_pct", "net_edge_pct", "verdict",
        ]].head(40)))
    md.append("")

    md.append("## 4. 元金別の損益とリスク\n")
    eq_cols = [c for c in cells.columns if c.startswith("eq")]
    if eq_cols:
        keep = ["holding_days", "revision_threshold", "slippage_pct", "trades",
                "taken", "skipped_no_slot"] + eq_cols
        sub = cells[(cells["timing"] == "all") & (~cells["is_control"])][keep]
        md.append(_table(sub.head(40)))
        md.append("")
        md.append("margin_call_days は維持率20%を割った日数。0 でなければその元金は使えない。\n")

    md.append("## 5. タイミング内訳（引け後 / 場中）\n")
    tm = cells[(cells["timing"] != "all") & (~cells["is_control"])]
    if not tm.empty:
        md.append(_table(tm[[
            "holding_days", "timing", "revision_threshold", "slippage_pct",
            "trades", "gross_pct", "net_edge_pct", "verdict",
        ]].head(60)))
    md.append("")

    md.append("## 6. 約定できなかった件数\n")
    md.append("```")
    for n, counts in sorted(result.skip_summary.items()):
        md.append(f"N={n}: {counts}")
    md.append("```")
    md.append("lot_too_large は生の株価で単元100株が建玉に収まらなかったもの。")
    md.append("no_open は寄らず。excluded_limit_up はストップ高で寄った日の除外。\n")

    md.append("## 7. イベント構築の診断\n")
    md.append("```")
    for k, v in diagnostics.items():
        md.append(f"{k}: {v}")
    md.append("```\n")

    md.append("## 8. この結果を読むときの注意\n")
    md.append(
        "- 単純な t 値は決算集中期の相関で有意性を過大評価する。"
        "クラスター・ブートストラップの信頼区間下限が 0 を上回っているかで見ること。\n"
        "- 増担保規制はバックテストで再現できない。急騰した小型株は実際には"
        "建玉が組めないことがある。ペーパートレードで実測すること。\n"
        "- 上場廃止銘柄がデータに残っているかは probe の結果を確認すること。"
        "残っていなければ生存バイアスが結果を押し上げている。\n"
    )

    md_path = out_dir / "results.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    written.append(md_path)
    return written


def write_histogram(trades: pd.DataFrame, out_dir: Path) -> Path:
    """修正率の分布。閾値を決める前に必ず見る。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    r = trades["revision_rate"].dropna()
    lines = ["# 修正率の分布\n"]
    lines.append(
        "東証の適時開示基準では、営業利益の業績予想修正は原則 ±30% を超えないと"
        "開示義務が生じない（売上高は ±10%）。固定の 5%/10%/20% では母集団が"
        "ほぼ同じになりうるため、実データの分位点から閾値を決める。\n"
    )
    if r.empty:
        lines.append("修正率が計算できたイベントがありません。\n")
    else:
        up = r[r > 0]
        lines.append("```")
        lines.append(f"全体件数: {len(r)}  上方: {len(up)}  下方: {int((r < 0).sum())}")
        if not up.empty:
            for q in (0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99):
                lines.append(f"上方修正 {int(q*100):>2}%点: {up.quantile(q):+.1%}")
            lines.append(f"上方修正のうち +30% 超: {int((up > 0.30).sum())} 件 "
                         f"({(up > 0.30).mean():.1%})")
        lines.append("```\n")
        bins = [-10, -1.0, -0.5, -0.3, -0.1, 0, 0.1, 0.3, 0.5, 1.0, 2.0, 10]
        cut = pd.cut(r, bins=bins)
        lines.append("```")
        for interval, count in cut.value_counts().sort_index().items():
            lines.append(f"{str(interval):>18}: {count}")
        lines.append("```\n")
    p = out_dir / "histogram.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def _table(df: pd.DataFrame) -> str:
    if df.empty:
        return "(該当なし)"
    d = df.copy()
    for c in d.columns:
        if d[c].dtype.kind == "f":
            d[c] = d[c].map(lambda v: "" if pd.isna(v) else f"{v:.3f}")
    header = "| " + " | ".join(str(c) for c in d.columns) + " |"
    sep = "|" + "|".join(["---"] * len(d.columns)) + "|"
    body = ["| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |"
            for row in d.itertuples(index=False)]
    return "\n".join([header, sep] + body)
