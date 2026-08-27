"""Obsidian Daily Note への追記。

指定セクション見出しの配下（次の同レベル以上の見出しの直前）にブロックを
挿入する。見出しが無ければノート末尾にセクションごと追加する。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .config import Config


def _heading_level(line: str) -> int:
    stripped = line.lstrip()
    if not stripped.startswith("#"):
        return 0
    return len(stripped) - len(stripped.lstrip("#"))


def upsert_section_block(content: str, heading: str, block: str) -> str:
    """content 内の heading セクション末尾に block を挿入した新しい文字列を返す。"""
    block = block.strip("\n")
    if not content.strip():
        return f"{heading}\n\n{block}\n"

    lines = content.split("\n")
    target_level = _heading_level(heading)
    heading_idx = None
    for i, line in enumerate(lines):
        if line.strip() == heading.strip():
            heading_idx = i
            break

    if heading_idx is None:
        return content.rstrip("\n") + f"\n\n{heading}\n\n{block}\n"

    # セクション終端 = heading より後で最初に現れる同レベル以上の見出し
    end_idx = len(lines)
    for i in range(heading_idx + 1, len(lines)):
        level = _heading_level(lines[i])
        if 0 < level <= target_level:
            end_idx = i
            break

    before = "\n".join(lines[:end_idx]).rstrip("\n")
    after = "\n".join(lines[end_idx:])
    result = before + f"\n\n{block}\n"
    if after.strip():
        result += "\n" + after.lstrip("\n")
    return result


def daily_note_path(cfg: Config, day: date) -> Path:
    filename = day.strftime(cfg.diary.date_format) + ".md"
    return cfg.paths.obsidian_vault / cfg.paths.daily_notes_dir / filename


def append_to_daily_note(cfg: Config, day: date, block: str) -> Path:
    path = daily_note_path(cfg, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(
        upsert_section_block(content, cfg.diary.section_heading, block),
        encoding="utf-8",
    )
    return path
