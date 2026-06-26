"""当日運用(半自動): 学習済みモデルで「まだ走っていないレース」を採点し買い目を出す。

バックテスト(backtest.py)が過去で検証するのに対し、本モジュールは
「全履歴で学習 → 直近の確定レースで較正/ブレンド重み → 出馬表(未確定レース)を予測」
という推論経路。出力は各レースの勝率ランキングと、現在オッズに対する期待値(EV)・買い目。

未確定レース = finish_pos が NaN の行(出馬表は着順未確定)。これらは学習から除外し、
PiT 特徴量は各馬の過去走(履歴)から計算される(履歴と出馬表を結合して build_features)。

⚠️ これは検証前モデルのペーパートレード。控除率を超える保証は無い。記録・観察用。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .blend import benter_blend, fit_blend_weight, market_implied_prob
from .calibration import Calibrator, race_normalize
from .model import KeibaModel, ModelConfig


@dataclass
class PredictConfig:
    valid_days: int = 60          # 較正/ブレンド重みに使う直近の確定レース期間
    calibration: str = "isotonic"
    odds_col: str = "final_odds"  # 出馬表時点の現在オッズ(ingest が O1 速報→final_odds に格納)
    ev_threshold: float = 1.15    # 買い目とみなす EV 下限
    edge_ratio: float = 1.25      # モデル確率 / 市場確率 の下限
    max_odds: float = 30.0
    min_model_prob: float = 0.03


class Predictor:
    def __init__(self, model: KeibaModel, calibrator: Calibrator, blend_w: float,
                 config: PredictConfig):
        self.model = model
        self.cal = calibrator
        self.blend_w = blend_w
        self.cfg = config


def fit_predictor(feat: pd.DataFrame, model_config: ModelConfig | None = None,
                  config: PredictConfig | None = None) -> Predictor:
    """確定済みレース(finish_pos あり)で学習し、直近で較正・ブレンド重みを決める。"""
    cfg = config or PredictConfig()
    labeled = feat[feat["finish_pos"].notna()].copy()
    if labeled.empty:
        raise ValueError("確定済みレースが無く学習できません")

    dmax = int(labeled["race_date"].max())
    valid_lo = dmax - cfg.valid_days
    train = labeled[labeled["race_date"] < valid_lo]
    valid = labeled[labeled["race_date"] >= valid_lo]
    if train.empty or valid.empty:
        # 期間が短い場合は時間順 85/15 分割で代替
        cut = labeled["race_date"].quantile(0.85)
        train = labeled[labeled["race_date"] < cut]
        valid = labeled[labeled["race_date"] >= cut]
    if train.empty:
        train = labeled
        valid = labeled

    model = KeibaModel(model_config or ModelConfig()).fit(train, valid)
    pv = model.predict_proba(valid)
    cal = Calibrator(cfg.calibration).fit(pv, valid["is_win"].to_numpy())
    pv_cal = race_normalize(valid, cal.transform(pv))
    qv = market_implied_prob(valid, cfg.odds_col)
    blend_w, _ = fit_blend_weight(valid, pv_cal, qv, valid["is_win"].to_numpy())
    return Predictor(model, cal, blend_w, cfg)


def predict_upcoming(predictor: Predictor, feat_all: pd.DataFrame) -> pd.DataFrame:
    """feat_all(履歴+出馬表を結合して build_features 済み)から、未確定レースの
    各馬の勝率・EV・買い目判定を返す。"""
    cfg = predictor.cfg
    upcoming = feat_all[feat_all["finish_pos"].isna()].copy()
    if upcoming.empty:
        return _empty_pred()

    p = predictor.model.predict_proba(upcoming)
    p_cal = race_normalize(upcoming, predictor.cal.transform(p))
    q = market_implied_prob(upcoming, cfg.odds_col)
    p_blend = benter_blend(upcoming, p_cal, q, predictor.blend_w)

    odds = upcoming[cfg.odds_col].to_numpy(dtype=float)
    ev = p_blend * odds
    with np.errstate(invalid="ignore", divide="ignore"):
        edge = p_blend / np.clip(q, 1e-9, None)

    out = pd.DataFrame({
        "race_id": upcoming["race_id"].to_numpy(),
        "post_position": upcoming.get("post_position", pd.Series(np.nan, index=upcoming.index)).to_numpy(),
        "win_prob": p_blend,
        "market_prob": q,
        "odds": odds,
        "ev": ev,
        "edge": edge,
    })
    out["bet"] = (
        (out["ev"] > cfg.ev_threshold)
        & (out["edge"] >= cfg.edge_ratio)
        & (out["odds"] <= cfg.max_odds)
        & (out["win_prob"] >= cfg.min_model_prob)
    )
    # レース内で勝率降順 → 予想順位
    out = out.sort_values(["race_id", "win_prob"], ascending=[True, False]).reset_index(drop=True)
    out["rank"] = out.groupby("race_id").cumcount() + 1
    return out


def format_predictions(pred: pd.DataFrame, top_n: int = 5) -> str:
    """レースごとに上位 top_n 頭と買い目を整形する。"""
    if pred is None or pred.empty:
        return "未確定レース(出馬表)が見つかりませんでした。"
    lines = []
    for rid, g in pred.groupby("race_id", sort=False):
        lines.append(f"\n── レース {rid} ──")
        lines.append(f"{'予':>2} {'馬番':>3} {'勝率':>6} {'オッズ':>7} {'EV':>5}  買い目")
        for _, r in g.head(top_n).iterrows():
            mark = "◎買" if r["bet"] else ""
            post = "-" if pd.isna(r["post_position"]) else f"{int(r['post_position'])}"
            odds = "-" if pd.isna(r["odds"]) else f"{r['odds']:.1f}"
            lines.append(f"{int(r['rank']):>2} {post:>3} {r['win_prob']*100:>5.1f}% {odds:>7} "
                         f"{r['ev']:>5.2f}  {mark}")
    bets = pred[pred["bet"]]
    lines.append(f"\n=== 買い目(単勝・EV閾値超え): {len(bets)} 点 ===")
    for _, r in bets.iterrows():
        post = "-" if pd.isna(r["post_position"]) else f"{int(r['post_position'])}"
        lines.append(f"  レース{r['race_id']} 馬番{post}  勝率{r['win_prob']*100:.1f}% "
                     f"オッズ{r['odds']:.1f} EV{r['ev']:.2f}")
    lines.append("\n⚠ 検証前モデルのペーパートレード。お金を賭ける根拠にはしないこと。")
    return "\n".join(lines)


def _empty_pred() -> pd.DataFrame:
    return pd.DataFrame(columns=["race_id", "post_position", "win_prob", "market_prob",
                                 "odds", "ev", "edge", "bet", "rank"])


def main(argv: list[str] | None = None) -> int:
    import argparse

    from .features import build_features
    from .ingest import IngestBackend, validate_runners

    p = argparse.ArgumentParser(prog="keiba.predict",
                                description="出馬表(未確定レース)を予測して買い目を出す(当日運用)")
    p.add_argument("--db", required=True, help="JV-Data DB(jrvltsql の keiba.db 等)")
    p.add_argument("--db-kind", choices=["sqlite", "duckdb"], default="sqlite")
    p.add_argument("--objective", choices=["binary", "lambdarank"], default="binary")
    p.add_argument("--ev", type=float, default=1.15, help="買い目とみなす EV 下限")
    p.add_argument("--top", type=int, default=5, help="各レースの表示頭数")
    args = p.parse_args(argv)

    runners, _ = IngestBackend(args.db, kind=args.db_kind).load()
    n_up = int(runners["finish_pos"].isna().sum()) if "finish_pos" in runners else 0
    print(f"取り込み: {len(runners)} 出走 / {runners['race_id'].nunique()} レース"
          f"(うち未確定={n_up} 出走)")
    issues = validate_runners(runners)
    if issues:
        print("⚠ バリデーション警告:", *issues, sep="\n  - ")
    if n_up == 0:
        print("未確定レース(出馬表)がDBにありません。今週の出馬表を取得してから再実行してください。")
        return 1

    feat = build_features(runners)
    predictor = fit_predictor(feat, ModelConfig(objective=args.objective),
                              PredictConfig(ev_threshold=args.ev))
    pred = predict_upcoming(predictor, feat)
    print(format_predictions(pred, top_n=args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
