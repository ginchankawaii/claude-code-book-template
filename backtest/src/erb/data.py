"""CSV/Parquet の読み込みと列名の正規化。

J-Quants V2 の列名は V1 と異なり、実データで確認するまで確定させない。
config.yaml の columns セクションで対応表を持ち、欠けている列は
「無いものとして」扱い、依存する処理側で明示的に落とす。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import Config
from .constants import normalize_code

#: 各テーブルで最低限必要な内部列名。
REQUIRED = {
    "summary": ["disc_date", "code", "doc_type"],
    "daily": ["date", "code", "open", "close", "adj_open", "adj_close"],
    "master": ["date", "code"],
    "calendar": ["date", "holiday_div"],
    "topix": ["date", "open", "close"],
}

DATE_COLS = {"date", "disc_date", "cur_fy_start", "cur_fy_end"}
NUMERIC_HINTS = (
    "open", "high", "low", "close", "volume", "turnover", "mkt_cap",
    "adj_factor", "op_actual", "fop", "nxfop", "fop_2q",
    "shares_out", "treasury_shares",
)


def load_table(cfg: Config, table: str, path: Path | str) -> pd.DataFrame:
    """1テーブルを読み込み、内部の正準列名に直す。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"{table} のデータがありません: {p}")
    df = _read_any(p)
    df = normalize(cfg, table, df)
    missing = [c for c in REQUIRED.get(table, []) if c not in df.columns]
    if missing:
        raise KeyError(
            f"{table} に必須列がありません: {missing}\n"
            f"読み込めた列: {sorted(df.columns)}\n"
            f"config.yaml の columns.{table} を実データに合わせてください（erb probe が対応表を出します）。"
        )
    return df


def normalize(cfg: Config, table: str, df: pd.DataFrame) -> pd.DataFrame:
    """列名の変換と型付け。元の DataFrame は変更しない。"""
    rename = cfg.rename_map(table)
    out = df.rename(columns=rename).copy()
    # 変換後に重複した列（V2 と内部名が衝突した場合）は先勝ちで落とす
    out = out.loc[:, ~out.columns.duplicated()]

    for col in out.columns:
        if col in DATE_COLS:
            out[col] = pd.to_datetime(out[col], errors="coerce").dt.date
        elif col in NUMERIC_HINTS:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    if table == "daily" and "mkt_cap" in out.columns:
        # MktCap は百万円単位で返る。円に揃えないと時価総額フィルタが効かない。
        multiplier = float(cfg.get("units", {}).get("mkt_cap_multiplier", 1))
        out["mkt_cap"] = pd.to_numeric(out["mkt_cap"], errors="coerce") * multiplier

    if "code" in out.columns:
        out["code"] = out["code"].map(normalize_code)
    if "disc_time" in out.columns:
        out["disc_time"] = out["disc_time"].astype("string")
    for flag in ("upper_limit", "lower_limit"):
        if flag in out.columns:
            out[flag] = _to_flag(out[flag])
    return out


def _to_flag(s: pd.Series) -> pd.Series:
    """ストップ高/安フラグを bool に。'0'/'1'/'*'/'' など表記が揺れる。"""
    as_str = s.astype("string").str.strip().fillna("")
    return ~as_str.isin(["", "0", "0.0", "nan", "None", "false", "False"])


def _read_any(p: Path) -> pd.DataFrame:
    suffix = p.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(p)
    if suffix in {".csv", ".gz", ".txt"}:
        return pd.read_csv(p, compression="infer", dtype={"Code": "string"})
    if suffix in {".json", ".jsonl"}:
        return pd.read_json(p, lines=(suffix == ".jsonl"))
    raise ValueError(f"未対応の拡張子です: {p}")


def daily_with_turnover_average(df: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """銘柄ごとに直近 lookback 営業日の平均売買代金を付ける。

    当日を含めない（当日の売買代金は寄付の時点では未確定なため）。
    """
    if "turnover" not in df.columns:
        out = df.copy()
        out["turnover_avg"] = pd.NA
        return out
    out = df.sort_values(["code", "date"]).copy()
    out["turnover_avg"] = (
        out.groupby("code", observed=True)["turnover"]
        .transform(lambda s: s.shift(1).rolling(lookback, min_periods=max(5, lookback // 2)).mean())
    )
    return out
