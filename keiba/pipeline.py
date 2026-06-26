"""分析層の一気通貫オーケストレーション(M0→M4)。

合成データ生成 → PiT特徴量 → リーク監査 → walk-forward(学習・較正・市場
ブレンド・EV/分数ケリー・回収率) を実行し、ダッシュボードを整形して返す。
実データ到着時は reader を差し替えるだけで本関数はそのまま使える。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .backtest import WalkForwardConfig, walk_forward
from .betting import BettingConfig
from .exotic import ExoticConfig
from .features import build_features
from .leakage import (
    assert_no_post_race_features,
    audit_outcome_independence,
    audit_temporal_invariance,
)
from .model import ModelConfig
from .reader import JVLinkReader, SyntheticBackend
from .synth import SyntheticConfig


@dataclass
class PipelineResult:
    backtest: dict
    leak_audit: dict
    n_runners: int
    n_races: int


def run_pipeline(reader: JVLinkReader | None = None,
                 model_config: ModelConfig | None = None,
                 betting_config: BettingConfig | None = None,
                 wf_config: WalkForwardConfig | None = None,
                 exotic_config: ExoticConfig | None = None,
                 run_leak_audit: bool = True,
                 verbose: bool = False) -> PipelineResult:
    reader = reader or SyntheticBackend(SyntheticConfig())
    runners, races = reader.load()

    assert_no_post_race_features()
    if run_leak_audit:
        ti = audit_temporal_invariance(runners, n_sample_races=20)
        oi = audit_outcome_independence(runners, n_sample_races=20)
        leak = {
            "ok": ti["ok"] and oi["ok"],
            "checked": ti["checked"] + oi["checked"],
            "temporal": ti,
            "outcome": oi,
        }
    else:
        leak = {"ok": None}

    feat = build_features(runners)
    bt = walk_forward(feat, model_config, betting_config, wf_config,
                      exotic_config=exotic_config, verbose=verbose)
    return PipelineResult(backtest=bt, leak_audit=leak,
                          n_runners=len(runners), n_races=len(races))


def format_report(result: PipelineResult) -> str:
    bt = result.backtest
    q = bt["quality"]
    flat = bt["flat"]
    kelly = bt["kelly"]
    ruin = bt["ruin"]
    leak = result.leak_audit
    L = []
    L.append("=" * 64)
    L.append(" keiba 分析層パイプライン(M0→M4)")
    L.append("=" * 64)
    L.append(f"データ: {result.n_races} レース / {result.n_runners} 出走")
    if leak.get("ok") is not None:
        status = "OK(リークなし)" if leak["ok"] else "NG リーク検出!"
        L.append(f"リーク監査(時間不変性+結果独立性): {leak['checked']}レース → {status}")
    L.append(f"walk-forward フォールド数: {bt['n_folds']}  平均ブレンド重み(市場): {bt['avg_blend_w']:.2f}")
    L.append("")
    L.append("--- 確率品質(テスト集計, 小さいほど良い) ---")
    L.append(f"  Brier   model={q['model_brier']:.4f}  market={q['market_brier']:.4f}  blend={q['blend_brier']:.4f}")
    L.append(f"  LogLoss model={q['model_logloss']:.4f}  market={q['market_logloss']:.4f}  blend={q['blend_logloss']:.4f}")
    L.append(f"  ブレンドECE={q['blend_ece']:.4f}")
    L.append("")
    L.append("--- 回収率(単勝・確定オッズ決済) ---")
    L.append(f"  EVフィルタ後ベット数: {flat['n_bets']}  的中率: {flat['hit_rate']*100:.1f}%")
    L.append(f"  フラットROI : {flat['roi']*100:.1f}%   (100%が損益分岐)")
    L.append(f"  分数ケリーROI: {kelly['roi']*100:.1f}%  最終資金: {kelly['final_bankroll']:.3f}x  最大DD: {kelly['max_drawdown']*100:.1f}%")
    exotic = bt.get("exotic") or {}
    if exotic:
        L.append("")
        L.append("--- 連系券種(EVフィルタ; 合成オッズ=単勝市場×Harville×控除率) ---")
        names = {"umaren": "馬連", "wide": "ワイド", "sanrenpuku": "三連複"}
        for bt_key in ["umaren", "wide", "sanrenpuku"]:
            if bt_key in exotic:
                e = exotic[bt_key]
                L.append(f"  {names[bt_key]:　<4} 点数={e['n_bets']:>4}  的中率={e['hit_rate']*100:>5.1f}%  ROI={e['roi']*100:>6.1f}%")
    L.append("")
    L.append("--- リスク(モンテカルロ; レース単位ブロック・ブートストラップ) ---")
    L.append(f"  破産確率(≤30%資金): {ruin['ruin_prob']*100:.1f}%  最終資金中央値: {ruin['median_final']:.2f}x  下側5%: {ruin['p05_final']:.2f}x")
    L.append("=" * 64)
    L.append("【重要な但し書き — この回収率を実力値と読まないこと】")
    L.append(" * これは合成データでの配管検証であり、実運用の成果ではない。")
    L.append(f" * 回収率は EVフィルタの選択バイアスと少フォールド({bt['n_folds']}個)分散で")
    L.append("   大きく上振れする。真のエッジが無い設定(--myopia 0 等)でも、較正ノイズ")
    L.append("   への選択だけで100%超が出ることがある(単点でなく分布で見るべき)。")
    L.append(" * 実データでは控除率の壁(単複20%)で回収率は大きく下がるのが現実。")
    L.append("   詳細と検証プロトコルは docs/RESEARCH_JRAVAN.md を参照。")
    L.append("=" * 64)
    return "\n".join(L)
