"""M3: 期待値フィルタ・分数ケリー資金配分・モンテカルロ破産確率。

回収率で勝つための選定/資金管理層(research第6章)。
  * EV = 較正済み勝率 × 購入時オッズ。EV>1+α のみ購入。
  * 分数ケリー(既定1/4)で賭け金配分。1点/1日上限を併設。
  * オッズ滑り(中間→確定でオッズ低下)を下方補正してから判定。
  * モンテカルロでバンクロール推移・最大DD・破産確率を推定。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BettingConfig:
    ev_threshold: float = 1.12     # EV>1.12 のみ購入
    edge_ratio: float = 1.25       # モデル確率が市場確率の何倍以上で買うか(長shot ノイズ除け)
    max_odds: float = 20.0         # これ以上の高オッズは買わない(変動と自己インパクト回避)
    min_model_prob: float = 0.03   # これ未満の低確率は買わない(較正ノイズ除け)
    kelly_fraction: float = 0.25   # 分数ケリー(1/4)
    max_stake_per_bet: float = 0.04  # 1点あたり資金比率上限
    odds_slip_factor: float = 0.95  # 確定オッズへの下方補正(購入時オッズ×係数)
    min_odds: float = 1.0


def expected_value(prob: np.ndarray, odds: np.ndarray) -> np.ndarray:
    return np.asarray(prob, float) * np.asarray(odds, float)


def kelly_fraction(prob: np.ndarray, odds: np.ndarray) -> np.ndarray:
    """単勝の最適ケリー比率 f=(p*odds-1)/(odds-1)。負はベットしない=0。"""
    p = np.asarray(prob, float)
    o = np.asarray(odds, float)
    b = np.clip(o - 1.0, 1e-9, None)
    f = (p * o - 1.0) / b
    return np.clip(f, 0.0, 1.0)


def select_bets(df: pd.DataFrame, prob: np.ndarray,
                bet_odds_col: str = "intermediate_odds",
                settle_odds_col: str = "final_odds",
                market_prob: np.ndarray | None = None,
                config: BettingConfig | None = None) -> pd.DataFrame:
    """EV + エッジ + 規律フィルタ → 分数ケリーで購入対象と賭け金比率を返す。

    EV/ケリーは「購入時に見えるオッズ(bet_odds_col)× odds_slip_factor」で
    判定(確定オッズは賭け時点で未確定。滑りを保守的に織り込む)。
    決済は確定オッズ(settle_odds_col)。

    規律(長shot のノイズ採用を防ぎ変動を抑える):
      * EV > ev_threshold
      * モデル確率 / 市場確率 >= edge_ratio(市場に対する明確な上振れ)
      * 賭けオッズ <= max_odds(高オッズの自己インパクト/変動回避)
      * モデル確率 >= min_model_prob(較正ノイズ除け)
    """
    cfg = config or BettingConfig()
    bet_odds = np.clip(df[bet_odds_col].to_numpy(float) * cfg.odds_slip_factor, cfg.min_odds, None)
    prob = np.asarray(prob, float)

    ev = expected_value(prob, bet_odds)
    f_full = kelly_fraction(prob, bet_odds)
    stake = np.clip(f_full * cfg.kelly_fraction, 0.0, cfg.max_stake_per_bet)

    mask = (ev > cfg.ev_threshold) & (stake > 0)
    mask &= bet_odds <= cfg.max_odds
    mask &= prob >= cfg.min_model_prob
    if market_prob is not None:
        mkt = np.clip(np.asarray(market_prob, float), 1e-9, None)
        mask &= (prob / mkt) >= cfg.edge_ratio

    out = df.loc[mask, ["race_id", "race_date", settle_odds_col, "is_win"]].copy()
    out = out.rename(columns={settle_odds_col: "final_odds"})
    out["model_prob"] = prob[mask]
    out["ev"] = ev[mask]
    out["stake_frac"] = stake[mask]
    out["bet_odds"] = bet_odds[mask]
    if market_prob is not None:
        out["market_prob"] = np.asarray(market_prob, float)[mask]
    return out.reset_index(drop=True)


def settle_flat(bets: pd.DataFrame, odds_col: str = "final_odds") -> dict:
    """等額(フラット)ベットの回収率会計。確定オッズで決済する。"""
    if len(bets) == 0:
        return _empty_result()
    ret = (bets["is_win"].to_numpy() * bets[odds_col].to_numpy()).sum()
    n = len(bets)
    return {
        "n_bets": int(n),
        "hit_rate": float(bets["is_win"].mean()),
        "roi": float(ret / n),
        "staked": float(n),
        "returned": float(ret),
    }


def settle_kelly(bets: pd.DataFrame, odds_col: str = "final_odds",
                 bankroll0: float = 1.0, compound: bool = True) -> dict:
    """分数ケリーで時系列に決済しバンクロール推移を返す。

    決済単位は「レース(決定点)」。同一レース内の複数ベットは賭け時点で互いの
    結果が未知なので、レース開始時のバンクロールから全点を一括サイズし、レース内
    払戻を合算してからバンクロールを更新する(順序依存・相互排他の不整合を回避)。
    """
    if len(bets) == 0:
        return {**_empty_result(), "bankroll_curve": np.array([bankroll0]),
                "final_bankroll": bankroll0, "max_drawdown": 0.0}
    bankroll = bankroll0
    curve = [bankroll]
    staked_total = 0.0
    returned_total = 0.0
    # レース(決定点)単位、時系列順に決済
    for _, race in bets.sort_values(["race_date", "race_id"]).groupby(
        ["race_date", "race_id"], sort=False
    ):
        base = bankroll if compound else bankroll0
        stakes = race["stake_frac"].to_numpy() * base
        payoff = (race["is_win"].to_numpy() * race[odds_col].to_numpy() * stakes).sum()
        staked_total += stakes.sum()
        returned_total += payoff
        bankroll += payoff - stakes.sum()
        curve.append(bankroll)
    curve = np.array(curve)
    peak = np.maximum.accumulate(curve)
    dd = (peak - curve) / np.where(peak > 0, peak, 1.0)
    return {
        "n_bets": int(len(bets)),
        "hit_rate": float(bets["is_win"].mean()),
        "roi": float(returned_total / staked_total) if staked_total > 0 else 0.0,
        "staked": float(staked_total),
        "returned": float(returned_total),
        "bankroll_curve": curve,
        "final_bankroll": float(bankroll),
        "max_drawdown": float(dd.max()),
    }


def monte_carlo_ruin(bets: pd.DataFrame, odds_col: str = "final_odds",
                     bankroll0: float = 1.0, ruin_level: float = 0.3,
                     n_sims: int = 500, seed: int = 0) -> dict:
    """レース(決定点)をブロック・ブートストラップしてバンクロール推移を多数生成し、
    破産確率(bankroll が ruin_level を下回る割合)と最終資金分布・最大DDを推定する。

    各レースは「実際の決済結果(is_win × オッズ)」をブロックとして扱う。これにより
    同一レース内の単勝が相互排他(高々1頭的中)であることが自動的に保たれ、独立
    ベルヌーイ再サンプルが生む非現実的な余剰的中(=破産確率の過小評価)を避ける。
    レース単位の復元抽出で順序と組成の不確実性を表現する(実現エッジ前提の保守的推定)。
    """
    if len(bets) == 0:
        return {"ruin_prob": 0.0, "median_final": bankroll0, "p05_final": bankroll0,
                "median_max_dd": 0.0}
    rng = np.random.default_rng(seed)
    # レース単位のブロック (stake_fracs, is_win*odds=純払戻倍率) に集約
    blocks = [
        (race["stake_frac"].to_numpy(),
         race["is_win"].to_numpy() * race[odds_col].to_numpy())
        for _, race in bets.groupby("race_id", sort=False)
    ]
    n_blocks = len(blocks)
    finals = np.empty(n_sims)
    max_dds = np.empty(n_sims)
    ruined = 0
    for s in range(n_sims):
        pick = rng.integers(0, n_blocks, n_blocks)  # レースを復元抽出
        bankroll = bankroll0
        peak = bankroll
        max_dd = 0.0
        hit_ruin = False
        for b in pick:
            fracs, mult = blocks[b]
            stakes = fracs * bankroll
            bankroll += (mult * stakes).sum() - stakes.sum()
            peak = max(peak, bankroll)
            if peak > 0:
                max_dd = max(max_dd, (peak - bankroll) / peak)
            if bankroll <= ruin_level * bankroll0:
                hit_ruin = True
        finals[s] = bankroll
        max_dds[s] = max_dd
        ruined += int(hit_ruin)
    return {
        "ruin_prob": float(ruined / n_sims),
        "median_final": float(np.median(finals)),
        "p05_final": float(np.percentile(finals, 5)),
        "median_max_dd": float(np.median(max_dds)),
    }


def _empty_result() -> dict:
    return {"n_bets": 0, "hit_rate": 0.0, "roi": 0.0, "staked": 0.0, "returned": 0.0}
