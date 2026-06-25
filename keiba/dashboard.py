"""可視化ダッシュボード。

分析層の結果を図にする:
  1. 信頼性曲線(reliability): model / market / blend の較正の良さ。
  2. バンクロール推移(分数ケリー)。
  3. 回収率の分布(複数シード): 単点でなく分布で見ることで、選択バイアス+
     少フォールド分散による上振れを正直に提示する(誇張防止)。
  4. 特徴量重要度。

ラベルは文字化け回避のため英語。matplotlib(Aggバックエンド)で PNG 出力。

使い方:
    python -m keiba.dashboard --out plots --days 540 --seeds 6
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .backtest import WalkForwardConfig, walk_forward
from .betting import BettingConfig
from .calibration import reliability_curve
from .features import FEATURE_COLUMNS, build_features
from .model import KeibaModel, ModelConfig
from .reader import SyntheticBackend
from .synth import SyntheticConfig


def plot_reliability(preds, path: Path) -> Path:
    y = preds.is_win.to_numpy()
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="perfect")
    for col, name, color in [("p_market", "market", "tab:gray"),
                             ("p_model", "model", "tab:blue"),
                             ("p_blend", "blend", "tab:red")]:
        rc = reliability_curve(preds[col].to_numpy(), y, n_bins=12)
        ax.plot(rc["mean_pred"], rc["observed"], "o-", color=color, label=name, ms=4)
    ax.set_xlabel("predicted win probability")
    ax.set_ylabel("observed win frequency")
    ax.set_title("Reliability (calibration) curve")
    ax.legend()
    ax.set_xlim(0, max(0.3, preds[["p_model", "p_blend"]].max().max()))
    ax.set_ylim(0, ax.get_xlim()[1])
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def plot_bankroll(kelly: dict, path: Path) -> Path:
    curve = kelly.get("bankroll_curve")
    fig, ax = plt.subplots(figsize=(7, 4))
    if curve is not None and len(curve) > 1:
        ax.plot(curve, color="tab:green")
        ax.axhline(1.0, color="k", ls="--", lw=1)
        ax.set_yscale("log")
    ax.set_xlabel("settled race (decision point)")
    ax.set_ylabel("bankroll (×, log scale)")
    ax.set_title(f"Fractional-Kelly bankroll  (final={kelly.get('final_bankroll', 0):.2f}x, "
                 f"maxDD={kelly.get('max_drawdown', 0)*100:.0f}%)")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def plot_roi_distribution(rois, path: Path) -> Path:
    rois = np.asarray(rois, float)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(rois, bins=max(5, len(rois)), color="tab:orange", edgecolor="k", alpha=0.8)
    ax.axvline(1.0, color="k", ls="--", lw=1.5, label="break-even (100%)")
    ax.axvline(rois.mean(), color="tab:red", lw=1.5, label=f"mean={rois.mean()*100:.0f}%")
    ax.set_xlabel("flat ROI across seeds")
    ax.set_ylabel("count")
    ax.set_title(f"ROI distribution over {len(rois)} seeds "
                 f"(mean={rois.mean()*100:.0f}%, sd={rois.std()*100:.0f}%)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def plot_feature_importance(model: KeibaModel, path: Path) -> Path:
    imp = model.booster.feature_importance(importance_type="gain")
    feats = model.features
    order = np.argsort(imp)[::-1][:18]
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.barh([feats[i] for i in order][::-1], [imp[i] for i in order][::-1], color="tab:purple")
    ax.set_xlabel("gain importance")
    ax.set_title("LightGBM feature importance (top 18)")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def roi_distribution(n_seeds: int = 6, days: int = 360, myopia: float = 0.7) -> list[float]:
    """複数シードで walk-forward を回し、フラットROIの分布を返す(正直な提示用)。"""
    rois = []
    for seed in range(n_seeds):
        runners, _ = SyntheticBackend(
            SyntheticConfig(n_days=days, seed=seed, market_myopia=myopia)
        ).load()
        feat = build_features(runners)
        bt = walk_forward(feat, ModelConfig(num_boost_round=250),
                          BettingConfig(), WalkForwardConfig())
        rois.append(bt["flat"]["roi"])
    return rois


def build_dashboard(outdir: str | Path = "plots", days: int = 540,
                    seeds: int = 6, myopia: float = 0.7) -> list[Path]:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    runners, _ = SyntheticBackend(SyntheticConfig(n_days=days, market_myopia=myopia)).load()
    feat = build_features(runners)
    bt = walk_forward(feat, ModelConfig(), BettingConfig(), WalkForwardConfig())

    # 全データで重要度用のモデルを1つ学習(可視化目的)
    cut = int(feat.race_date.quantile(0.8))
    imp_model = KeibaModel(ModelConfig()).fit(feat[feat.race_date < cut],
                                              feat[feat.race_date >= cut])

    paths = []
    paths.append(plot_reliability(bt["preds"], outdir / "reliability.png"))
    paths.append(plot_bankroll(bt["kelly"], outdir / "bankroll.png"))
    paths.append(plot_feature_importance(imp_model, outdir / "feature_importance.png"))
    rois = roi_distribution(n_seeds=seeds, days=min(days, 360), myopia=myopia)
    paths.append(plot_roi_distribution(rois, outdir / "roi_distribution.png"))
    return paths


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="keiba.dashboard", description="分析層の可視化ダッシュボード")
    p.add_argument("--out", default="plots", help="PNG 出力ディレクトリ")
    p.add_argument("--days", type=int, default=540)
    p.add_argument("--seeds", type=int, default=6, help="ROI分布のシード数")
    p.add_argument("--myopia", type=float, default=0.7)
    args = p.parse_args(argv)
    paths = build_dashboard(args.out, args.days, args.seeds, args.myopia)
    for pth in paths:
        print(f"wrote {pth}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
