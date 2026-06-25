"""M0: JV-Data 風の合成データ生成器。

目的は「分析層パイプライン(特徴量→学習→較正→walk-forward回収率→EV/ケリー)
を実データ無しで一気通貫に完成・検証する」こと。現実の競馬を当てる器では
なく、配管(リーク防止・較正・ROI会計)の正しさを示すための環境である。

設計上の肝(ここが後段の "学べる小さなエッジ" を生む):
  * 各馬は持続的な latent ability を持つ。
  * 各馬は AR(1) 的な「調子(form_state)」を持ち、これは過去の着順に現れる。
  * 市場(オッズ)は ability/騎手/枠はほぼ正しく織り込むが、form_state を
    *過小評価* する(係数を下げる)。→ 過去走から form を復元できるモデルは
    市場が取りこぼした残差を突いて正のEVを得られる(Benter流の構図)。
  * オッズは控除率(takeout)分のオーバーラウンドを持ち、何も予想能力が
    無ければ期待回収率は (1-控除率) に収束する。

すべて乱数シードで再現可能。truth 列(true_win_prob 等)は診断専用で、
特徴量・学習には絶対に使わない(リーク防止の検証対象)。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class SyntheticConfig:
    n_horses: int = 1200
    n_jockeys: int = 90
    n_sires: int = 60
    n_days: int = 540          # 約1.5年分
    races_per_day: int = 6
    min_field: int = 8
    max_field: int = 16
    seed: int = 7

    # 強さの構成係数
    w_ability: float = 1.0
    w_jockey: float = 0.45
    w_sire_fit: float = 0.35
    w_form: float = 0.55       # 真の強さに対する調子の寄与
    pl_temperature: float = 0.80  # Plackett-Luce(Gumbel)温度。大きいほど波乱
    race_noise: float = 0.80   # = pl_temperature の別名(後方互換)

    # 市場の効率性。
    #  market_form_weight: form への系統的な重み(1.0=不偏)。<1で過小評価。
    #  market_myopia: 市場の form 読みのノイズ(大きいほど近視眼的=モデルに勝機)。
    #                 0 なら市場は form を完璧に読み、モデルは原理的に勝てない。
    #  この2つで「効率的だが form に近視眼的な市場」を表現する。
    #  myopia を上げるほどモデル/ブレンドのエッジ(回収率)が増える。
    market_form_weight: float = 1.0
    market_myopia: float = 0.7
    market_noise: float = 0.07
    takeout: float = 0.20      # 単勝控除率
    odds_slip: float = 0.06    # 朝→確定オッズの平均的な滑り幅

    # 馬体重ランダムウォーク
    base_horse_weight: float = 470.0
    horse_weight_sd: float = 8.0


def generate_dataset(config: SyntheticConfig | None = None):
    """合成データセットを生成して返す。

    Returns:
        runners: pd.DataFrame  1行=1出走馬。schema.all_columns() 準拠 + truth列。
        races:   pd.DataFrame  1行=1レース(race_id, race_date, surface, distance, ...).
    """

    cfg = config or SyntheticConfig()
    rng = np.random.default_rng(cfg.seed)

    # --- マスタ(持続的潜在変数) ---
    horse_ability = rng.normal(0.0, 1.0, cfg.n_horses)
    jockey_skill = rng.normal(0.0, 1.0, cfg.n_jockeys)
    sire_dist_pref = rng.uniform(1200, 2400, cfg.n_sires)   # 種牡馬の得意距離
    sire_surface_pref = rng.integers(0, 2, cfg.n_sires)     # 0=芝得意,1=ダ得意
    sire_ability = rng.normal(0.0, 0.4, cfg.n_sires)

    horse_sire = rng.integers(0, cfg.n_sires, cfg.n_horses)
    horse_sex = rng.integers(0, 3, cfg.n_horses)
    # 馬ごとの状態(時間発展)
    horse_age_days = rng.integers(2 * 365, 5 * 365, cfg.n_horses).astype(float)
    horse_form = rng.normal(0.0, 1.0, cfg.n_horses)         # AR(1) 調子
    horse_hweight = rng.normal(cfg.base_horse_weight, 18.0, cfg.n_horses)
    horse_last_date = np.full(cfg.n_horses, -9999, dtype=float)
    horse_starts = np.zeros(cfg.n_horses, dtype=int)

    rows: list[dict] = []
    race_rows: list[dict] = []
    race_counter = 0

    for day in range(cfg.n_days):
        for _ in range(cfg.races_per_day):
            race_counter += 1
            race_id = race_counter
            surface = int(rng.integers(0, 2))
            distance = int(rng.choice([1200, 1400, 1600, 1800, 2000, 2400]))
            class_level = int(rng.integers(1, 6))
            field_size = int(rng.integers(cfg.min_field, cfg.max_field + 1))

            # 出走馬を抽選(置換なし)。出走確率はクラス近接で軽く重み付け。
            entrants = rng.choice(cfg.n_horses, size=field_size, replace=False)
            posts = rng.permutation(field_size) + 1  # 馬番1..field

            # 調子を AR(1) で更新(出走馬のみ、レースをまたいで持続)。
            # 持続性が高いほど過去走から復元可能 = モデルが取れる残差になる。
            horse_form[entrants] = (
                0.90 * horse_form[entrants]
                + rng.normal(0.0, 0.45, field_size)
            )
            # 馬体重ランダムウォーク
            new_hw = horse_hweight[entrants] + rng.normal(0.0, cfg.horse_weight_sd, field_size)
            weight_diff = new_hw - horse_hweight[entrants]
            horse_hweight[entrants] = new_hw

            # 各構成要素
            ability = horse_ability[entrants]
            sire = horse_sire[entrants]
            jock = rng.integers(0, cfg.n_jockeys, field_size)
            jk = jockey_skill[jock]

            # 種牡馬の距離・馬場適性
            dist_fit = -((sire_dist_pref[sire] - distance) / 600.0) ** 2
            surf_fit = np.where(sire_surface_pref[sire] == surface, 0.25, -0.25)
            sire_fit = sire_ability[sire] + 0.3 * dist_fit + surf_fit

            # 枠順バイアス(内枠やや有利、コース距離で符号が変わる体)
            rel = (posts - 1) / max(field_size - 1, 1)
            draw_bias = (0.5 - rel) * (0.30 if surface == 0 else 0.18)

            carried_weight = 55.0 + rng.normal(0.0, 1.2, field_size) + 0.3 * (class_level - 3)
            weight_effect = -0.04 * (carried_weight - 55.0)

            form_state = horse_form[entrants]

            # 真の強さ
            true_strength = (
                cfg.w_ability * ability
                + cfg.w_jockey * jk
                + cfg.w_sire_fit * sire_fit
                + cfg.w_form * form_state
                + draw_bias
                + weight_effect
            )
            beta = cfg.pl_temperature
            # 着順は Plackett-Luce(Gumbel-max トリック)で決定。
            # これにより P(1着) = softmax(strength/beta) が *厳密に* 成立し、
            # 効率的市場は人気馬を正しく評価できる(Bolton-Chapman/Benterの枠組み)。
            gumbel = rng.gumbel(0.0, 1.0, field_size)
            score = true_strength / beta + gumbel
            order = np.argsort(-score)          # 速い順(=PLサンプリング順)
            finish_pos = np.empty(field_size, dtype=int)
            finish_pos[order] = np.arange(1, field_size + 1)

            # 真の勝率(Gumbel ノイズ下で厳密)
            true_wp = _softmax(true_strength / beta)

            # 市場の織り込み。ability/騎手/枠/斤量は正しく評価するが、form は
            # 近視眼的(ノイズ込み)にしか読めない。過去走を集計するモデルは
            # この form 読みを上回りうる → 市場が取りこぼす残差(Benterの構図)。
            market_form_read = form_state + rng.normal(0.0, cfg.market_myopia, field_size)
            market_strength = (
                cfg.w_ability * ability
                + cfg.w_jockey * jk
                + cfg.w_sire_fit * sire_fit
                + cfg.market_form_weight * cfg.w_form * market_form_read
                + draw_bias
                + weight_effect
                + rng.normal(0.0, cfg.market_noise, field_size)
            )
            market_prob = _softmax(market_strength / beta)
            # 控除率込みオッズ: sum(1/odds)=1/(1-takeout) になるよう設定
            final_odds = (1.0 - cfg.takeout) / np.clip(market_prob, 1e-6, None)
            final_odds = np.clip(final_odds, 1.0, 999.0)
            # 朝・中間オッズは情報が少なく、確定へ向けて滑る
            slip = rng.normal(0.0, cfg.odds_slip, field_size)
            morning_odds = np.clip(final_odds * (1.0 + 0.5 * cfg.odds_slip + slip), 1.0, 999.0)
            intermediate_odds = np.clip(final_odds * (1.0 + slip * 0.5), 1.0, 999.0)
            final_pop = _rank_desc(market_prob)  # 人気(1=1番人気)

            # 走破タイム・上がり・通過順(確定後情報)。着順と整合する向きに生成。
            base_time = distance / 16.0          # ざっくり基準秒
            rank_eff = (field_size - finish_pos) / max(field_size - 1, 1)  # 1着=1.0
            finish_time = base_time - 1.2 * rank_eff + rng.normal(0, 0.2, field_size)
            last_3f = 35.5 - 1.0 * rank_eff + rng.normal(0, 0.3, field_size)
            passing_rank = np.clip(finish_pos + rng.normal(0, 1.5, field_size), 1, field_size)

            # 馬齢・間隔
            age_years = horse_age_days[entrants] / 365.0
            dsl = np.where(
                horse_last_date[entrants] < 0,
                rng.integers(28, 84, field_size),
                day - horse_last_date[entrants],
            ).astype(float)
            is_first = (horse_starts[entrants] == 0).astype(int)

            for k in range(field_size):
                h = entrants[k]
                rows.append(
                    {
                        "race_id": race_id,
                        "race_date": day,
                        "horse_id": int(h),
                        "jockey_id": int(jock[k]),
                        "trainer_id": int(h) % 200,
                        "sire_id": int(sire[k]),
                        "post_position": int(posts[k]),
                        "field_size": field_size,
                        "draw_bias": float(draw_bias[k]),
                        "carried_weight": float(carried_weight[k]),
                        "horse_weight": float(new_hw[k]),
                        "weight_diff": float(weight_diff[k]),
                        "age": float(age_years[k]),
                        "sex": int(horse_sex[h]),
                        "days_since_last": float(dsl[k]),
                        "class_level": class_level,
                        "surface": surface,
                        "distance": distance,
                        "is_first_start": int(is_first[k]),
                        # 発走前の市場情報
                        "morning_odds": float(morning_odds[k]),
                        "intermediate_odds": float(intermediate_odds[k]),
                        # 確定後情報(当該レースの特徴量に入れたらリーク)
                        "finish_pos": int(finish_pos[k]),
                        "finish_time": float(finish_time[k]),
                        "last_3f": float(last_3f[k]),
                        "passing_rank": float(passing_rank[k]),
                        "is_win": int(finish_pos[k] == 1),
                        "is_top3": int(finish_pos[k] <= 3),
                        "final_odds": float(final_odds[k]),
                        "final_popularity": int(final_pop[k]),
                        "payout_win": float(final_odds[k] * 100.0 if finish_pos[k] == 1 else 0.0),
                        # truth(診断専用・絶対に特徴量化しない)
                        "true_win_prob": float(true_wp[k]),
                        "true_strength": float(true_strength[k]),
                    }
                )

            # 状態更新
            horse_last_date[entrants] = day
            horse_starts[entrants] += 1
            horse_age_days[entrants] += 0  # 簡略化(年齢は日でなく走破で扱わない)

            race_rows.append(
                {
                    "race_id": race_id,
                    "race_date": day,
                    "surface": surface,
                    "distance": distance,
                    "class_level": class_level,
                    "field_size": field_size,
                }
            )

    runners = pd.DataFrame(rows)
    races = pd.DataFrame(race_rows)
    return runners, races


def _softmax(x: np.ndarray) -> np.ndarray:
    x = x - np.max(x)
    e = np.exp(x)
    return e / e.sum()


def _rank_desc(values: np.ndarray) -> np.ndarray:
    """大きい値ほど順位1。タイは安定順。"""
    order = np.argsort(-values, kind="stable")
    ranks = np.empty(len(values), dtype=int)
    ranks[order] = np.arange(1, len(values) + 1)
    return ranks
