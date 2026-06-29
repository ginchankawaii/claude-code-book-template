"""keiba: 可視化ダッシュボードのスモークテスト(学習不要の安価な部分)。"""

import numpy as np
import pandas as pd

from keiba.dashboard import plot_bankroll, plot_reliability, plot_roi_distribution


def test_plot_reliability(tmp_path):
    n = 200
    rng = np.random.default_rng(0)
    preds = pd.DataFrame({
        "is_win": rng.integers(0, 2, n),
        "p_model": rng.random(n) * 0.3,
        "p_market": rng.random(n) * 0.3,
        "p_blend": rng.random(n) * 0.3,
    })
    p = plot_reliability(preds, tmp_path / "rel.png")
    assert p.exists() and p.stat().st_size > 0


def test_plot_bankroll(tmp_path):
    kelly = {"bankroll_curve": np.cumprod(1 + np.full(20, 0.01)),
             "final_bankroll": 1.2, "max_drawdown": 0.1}
    p = plot_bankroll(kelly, tmp_path / "bank.png")
    assert p.exists() and p.stat().st_size > 0


def test_plot_roi_distribution(tmp_path):
    p = plot_roi_distribution([0.8, 1.0, 1.2, 1.4, 0.95, 1.1], tmp_path / "roi.png")
    assert p.exists() and p.stat().st_size > 0
