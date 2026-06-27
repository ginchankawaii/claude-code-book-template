"""M3: walk-forward(時系列分割)回収率バックテスト。

過去→未来の順序を厳守して、各テスト区間ごとに
  train(過去) → valid(較正・ブレンド重み) → test(賭け・決済)
を回し、確定オッズで決済する。ランダム分割は禁止(リーク・楽観バイアス)。

評価は的中率ではなく回収率(ROI)・バンクロール推移・最大DD・破産確率を主とし、
モデル/市場/ブレンドの確率品質(Brier/log-loss/ECE)も併記する(research第6章)。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .blend import benter_blend, fit_blend_weight, market_implied_prob
from .betting import (
    BettingConfig,
    monte_carlo_ruin,
    select_bets,
    settle_flat,
    settle_kelly,
)
from .exotic import ExoticConfig, select_exotic_bets, summarize_exotic
from .calibration import (
    Calibrator,
    brier_score,
    expected_calibration_error,
    log_loss,
    race_normalize,
)
from .model import KeibaModel, ModelConfig


@dataclass
class WalkForwardConfig:
    train_min_days: int = 180   # 最初のtrainに最低必要な日数
    valid_days: int = 60        # 較正・ブレンド重み用の検証区間
    test_days: int = 45         # 1フォールドのテスト区間
    step_days: int | None = None  # フォールドの進み幅(既定=test_days)
    market_odds_col: str = "intermediate_odds"  # ブレンド用市場確率の元(発走前)
    bet_odds_col: str = "intermediate_odds"     # 賭け判定オッズ(発走前)
    settle_odds_col: str = "final_odds"         # 決済オッズ(確定)
    calibration: str = "isotonic"


def walk_forward(feat: pd.DataFrame, model_config: ModelConfig | None = None,
                 betting_config: BettingConfig | None = None,
                 wf_config: WalkForwardConfig | None = None,
                 exotic_config: ExoticConfig | None = None,
                 verbose: bool = False) -> dict:
    """walk-forward バックテストを実行して結果dictを返す。

    exotic_config を渡すと連系券種(馬連/ワイド/三連複)の EV ベットも評価する
    (None ならスキップ)。
    """

    wf = wf_config or WalkForwardConfig()
    mcfg = model_config or ModelConfig()
    bcfg = betting_config or BettingConfig()
    step = wf.step_days or wf.test_days

    if step < wf.test_days:
        # test 窓が重複するとレース/ベットが pooled 集計に二重計上される。
        raise ValueError(
            f"step_days({step}) は test_days({wf.test_days}) 以上にしてください"
            "(テスト窓の重複=二重計上を防ぐため)"
        )

    dmin, dmax = int(feat.race_date.min()), int(feat.race_date.max())
    fold_start = dmin + wf.train_min_days + wf.valid_days

    folds = []
    all_bets = []
    all_exotic = []
    test_pred_frames = []
    t0 = fold_start
    while t0 + wf.test_days <= dmax + 1:
        test_lo, test_hi = t0, t0 + wf.test_days
        valid_lo, valid_hi = test_lo - wf.valid_days, test_lo
        train = feat[feat.race_date < valid_lo]
        valid = feat[(feat.race_date >= valid_lo) & (feat.race_date < valid_hi)]
        test = feat[(feat.race_date >= test_lo) & (feat.race_date < test_hi)]
        if len(train) == 0 or len(valid) == 0 or len(test) == 0:
            t0 += step
            continue

        fold_res, bets, test_pred, exotic = _run_fold(
            train, valid, test, mcfg, bcfg, wf, exotic_config
        )
        fold_res["fold"] = len(folds) + 1
        fold_res["test_range"] = (test_lo, test_hi)
        folds.append(fold_res)
        if len(bets):
            all_bets.append(bets)
        if exotic is not None and len(exotic):
            all_exotic.append(exotic)
        test_pred_frames.append(test_pred)
        if verbose:
            print(f"fold {fold_res['fold']:>2} [{test_lo}-{test_hi}) "
                  f"w={fold_res['blend_w']:.2f} bets={fold_res['n_bets']:>4} "
                  f"flatROI={fold_res['flat_roi']:.3f}")
        t0 += step

    bets_df = pd.concat(all_bets, ignore_index=True) if all_bets else _empty_bets()
    preds_df = pd.concat(test_pred_frames, ignore_index=True)
    exotic_df = pd.concat(all_exotic, ignore_index=True) if all_exotic else None

    result = _aggregate(folds, bets_df, preds_df, bcfg)
    result["exotic"] = summarize_exotic(exotic_df) if exotic_df is not None else {}
    result["exotic_bets"] = exotic_df
    return result


def _run_fold(train, valid, test, mcfg, bcfg, wf, exotic_config=None):
    # 1) 学習
    model = KeibaModel(mcfg).fit(train, valid)
    # 2) 検証で較正 + ブレンド重み
    pv_model = model.predict_proba(valid)
    cal = Calibrator(wf.calibration).fit(pv_model, valid.is_win.to_numpy())
    pv_cal = race_normalize(valid, cal.transform(pv_model))
    qv = market_implied_prob(valid, wf.market_odds_col)
    blend_w, _ = fit_blend_weight(valid, pv_cal, qv, valid.is_win.to_numpy())
    # 3) テストで予測 → 較正 → ブレンド
    pt_model = model.predict_proba(test)
    pt_cal = race_normalize(test, cal.transform(pt_model))
    qt = market_implied_prob(test, wf.market_odds_col)
    pt_blend = benter_blend(test, pt_cal, qt, blend_w)
    # 4) 賭け選定 → 決済(確定オッズ)。市場確率に対するエッジで規律フィルタ。
    bets = select_bets(test, pt_blend, wf.bet_odds_col, wf.settle_odds_col,
                       market_prob=qt, config=bcfg)
    flat = settle_flat(bets)
    y = test.is_win.to_numpy()
    res = {
        "blend_w": blend_w,
        "n_bets": flat["n_bets"],
        "flat_roi": flat["roi"],
        "hit_rate": flat["hit_rate"],
        "model_brier": brier_score(pt_cal, y),
        "market_brier": brier_score(qt, y),
        "blend_brier": brier_score(pt_blend, y),
        "model_logloss": log_loss(pt_cal, y),
        "market_logloss": log_loss(qt, y),
        "blend_logloss": log_loss(pt_blend, y),
        "blend_ece": expected_calibration_error(pt_blend, y),
    }
    test_pred = pd.DataFrame({
        "race_id": test.race_id.to_numpy(),
        "race_date": test.race_date.to_numpy(),
        "is_win": y,
        "p_model": pt_cal,
        "p_market": qt,
        "p_blend": pt_blend,
        "final_odds": test[wf.settle_odds_col].to_numpy(),
        # C2: 寄りつき→直近のオッズの動き(賢い金)。蓄積時系列があるレースのみ非NaN。
        "odds_drift": (test["odds_drift"].to_numpy() if "odds_drift" in test.columns
                       else np.nan),
    })

    # 5) 連系券種(任意): ブレンド確率と市場確率からレース単位で EV ベット
    exotic = None
    if exotic_config is not None:
        tt = test.reset_index(drop=True)
        pb = pd.Series(pt_blend).reset_index(drop=True)
        qm = pd.Series(qt).reset_index(drop=True)
        frames = []
        for rid, idx in tt.groupby("race_id", sort=False).groups.items():
            sub = tt.loc[idx]
            eb = select_exotic_bets(sub, pb.loc[idx].to_numpy(), qm.loc[idx].to_numpy(),
                                    exotic_config)
            if len(eb):
                frames.append(eb)
        exotic = pd.concat(frames, ignore_index=True) if frames else None

    return res, bets, test_pred, exotic


def _aggregate(folds, bets_df, preds_df, bcfg) -> dict:
    flat = settle_flat(bets_df)
    kelly = settle_kelly(bets_df)
    ruin = monte_carlo_ruin(bets_df)

    y = preds_df.is_win.to_numpy()
    quality = {
        "model_brier": brier_score(preds_df.p_model, y),
        "market_brier": brier_score(preds_df.p_market, y),
        "blend_brier": brier_score(preds_df.p_blend, y),
        "model_logloss": log_loss(preds_df.p_model, y),
        "market_logloss": log_loss(preds_df.p_market, y),
        "blend_logloss": log_loss(preds_df.p_blend, y),
        "blend_ece": expected_calibration_error(preds_df.p_blend, y),
    }
    return {
        "n_folds": len(folds),
        "flat": flat,
        "kelly": kelly,
        "ruin": ruin,
        "quality": quality,
        "avg_blend_w": float(np.mean([f["blend_w"] for f in folds])) if folds else float("nan"),
        "per_fold": pd.DataFrame(folds),
        "bets": bets_df,
        "preds": preds_df,
        "betting_config": bcfg,
    }


def _empty_bets() -> pd.DataFrame:
    return pd.DataFrame(columns=["race_id", "race_date", "final_odds", "is_win",
                                 "model_prob", "ev", "stake_frac", "bet_odds"])
