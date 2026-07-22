"""L2 構造層: 連想鎖を決定論的に Mermaid 化する（検証用の正）。LLM・乱数・時刻は使わない。"""
from __future__ import annotations

import re

from .models import ChainProposal

_ARROW = re.compile(r"\s*(?:→|->)\s*")


def _label(text: str) -> str:
    """Mermaid ノードラベル用に正規化。改行・連続空白を潰し、二重引用符を単引用符へ。"""
    t = " ".join(text.split())
    return t.replace('"', "'")


def to_mermaid(p: ChainProposal) -> str:
    """連想鎖テキスト（「 → 」区切り）を flowchart LR に変換する。同じ入力なら常に同じ出力。"""
    steps = [s.strip() for s in _ARROW.split(p.chain) if s.strip()]
    if not steps:
        steps = [p.fact or "(空)"]
    lines = ["flowchart LR"]
    for i, step in enumerate(steps):
        lines.append(f'    n{i}["{_label(step)}"]')
    for i in range(len(steps) - 1):
        lines.append(f"    n{i} --> n{i + 1}")
    last = len(steps) - 1
    lines.append(f"    style n{last} fill:#ffe08a,stroke:#b8860b,stroke-width:2px")
    return "\n".join(lines)
