#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
案C の高さスタック比較図 (option_c_stackup.svg) を生成する。

数値は option_c_socket_height.py が筐体CADを実行して得た値と同一。
実行: python3 hardware/pcb/option_c_stackup.py
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

# 日本語ラベルを出すため IPAGothic を使う (Debian: fonts-ipafont-gothic)
for _f in ("IPAGothic", "IPAPGothic", "Noto Sans CJK JP", "DejaVu Sans"):
    if _f in {f.name for f in matplotlib.font_manager.fontManager.ttflist}:
        matplotlib.rcParams["font.family"] = _f
        break
matplotlib.rcParams["axes.unicode_minus"] = False

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "option_c_stackup.svg")

WALL = 1.6
LID_T = 1.8

# (層名, 厚み, 色) を床(内側)から上へ
COLS = {
    "floor": "#8d99ae", "pcb": "#2a9d8f", "conn": "#e76f51",
    "xiao": "#264653", "air": "#e9ecef", "lid": "#adb5bd",
}

STACKS = [
    ("v1 現行\n(直はんだ)", [
        ("裏面はんだ逃げ 1.4", 1.4, "conn"),
        ("XIAO スタック 7.5", 7.5, "xiao"),
        ("リッド余裕 2.3", 2.3, "air"),
    ], 14.6, "はんだ11点 / 交換不可"),
    ("C-a'\n標準ピンヘッダ\n+ 低メス", [
        ("台座 0.6", 0.6, "floor"),
        ("キャリア基板 1.0", 1.0, "pcb"),
        ("ヘッダ2.5\n+ソケット3.6\n=6.1", 6.1, "conn"),
        ("XIAO スタック 7.5", 7.5, "xiao"),
        ("リッド余裕 0.6", 0.6, "air"),
    ], 19.2, "現実解。+4.6mm"),
    ("C-b\n細ピンヘッダ\n+ 丸ピン", [
        ("台座 0.6", 0.6, "floor"),
        ("キャリア基板 1.0", 1.0, "pcb"),
        ("ヘッダ2.0\n+ソケット3.0\n=5.0", 5.0, "conn"),
        ("XIAO スタック 7.5", 7.5, "xiao"),
        ("リッド余裕 0.6", 0.6, "air"),
    ], 18.1, "ソケット高さ assumption"),
    ("C-d\n裸ピン (上級者)\n案Cの理論下限", [
        ("台座 0.3", 0.3, "floor"),
        ("キャリア基板 0.8", 0.8, "pcb"),
        ("裸ピン\n+ソケット3.6\n=3.9", 3.9, "conn"),
        ("XIAO スタック 7.5", 7.5, "xiao"),
        ("リッド余裕 0.6", 0.6, "air"),
    ], 16.5, "初心者には非現実的。+1.9mm"),
]


def main():
    fig, ax = plt.subplots(figsize=(11.5, 6.2))
    x = 0.0
    bw = 1.6
    gap = 1.15
    for title, layers, outer, note in STACKS:
        z = 0.0
        # 背面壁
        ax.add_patch(Rectangle((x, -WALL), bw, WALL, fc="#ced4da", ec="k", lw=0.6))
        for name, t, key in layers:
            ax.add_patch(Rectangle((x, z), bw, t, fc=COLS[key], ec="k", lw=0.6,
                                   alpha=0.95))
            if t >= 0.55:
                ax.text(x + bw / 2, z + t / 2, name, ha="center", va="center",
                        fontsize=6.6, linespacing=1.15,
                        color="white" if key in ("xiao", "conn", "pcb") else "black")
            z += t
        # リッド板
        ax.add_patch(Rectangle((x, z), bw, LID_T, fc=COLS["lid"], ec="k", lw=0.6))
        z += LID_T
        ax.plot([x - 0.12, x + bw + 0.12], [z, z], color="k", lw=1.1)
        ax.annotate("", xy=(x + bw + 0.30, -WALL), xytext=(x + bw + 0.30, z),
                    arrowprops=dict(arrowstyle="<->", lw=1.0))
        ax.text(x + bw + 0.40, (z - WALL) / 2, f"外形 {outer:.1f} mm",
                rotation=90, va="center", ha="left", fontsize=9,
                fontweight="bold")
        ax.text(x + bw / 2, -3.0, title, ha="center", va="top", fontsize=9,
                fontweight="bold")
        ax.text(x + bw / 2, -6.2, note, ha="center", va="top", fontsize=7.5,
                color="#6c757d")
        x += bw + gap

    ax.axhline(0, color="k", lw=0.4, ls=":")
    ax.set_xlim(-0.6, x + 0.4)
    ax.set_ylim(-8.5, 21.0)
    ax.set_ylabel("筐体内の z (奥行き) 方向 [mm]   z=0 が内側床面")
    ax.set_xticks([])
    ax.set_title("案C: XIAO をピンソケットで着脱可能にしたときの奥行き方向スタック\n"
                 "(数値は hardware/cad/mindclip_case.py を実行して確認。allday バリアント)",
                 fontsize=11)
    ax.spines[["top", "right", "bottom"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT, format="svg", bbox_inches="tight")
    print(f"[render] {OUT}")


if __name__ == "__main__":
    main()
