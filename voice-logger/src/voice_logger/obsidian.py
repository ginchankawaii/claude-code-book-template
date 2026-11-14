"""Obsidian Daily Note への追記。

指定セクション見出しの配下（次の同レベル以上の見出しの直前）にブロックを
挿入する。見出しが無ければノート末尾にセクションごと追加する。

ノートは利用者が Obsidian で開いて編集しているファイルなので:

  * 書き込みは「同じディレクトリの一時ファイル → fsync → `os.replace`」で行う
    （その場で切り詰めて書くと、途中で落ちたときに手書きの内容ごと失う）
  * 置き換える直前に読み直し、読んだ後に編集されていたら作り直す
  * ブロックには音源ごとの目印 `<!-- vl:<sha256先頭12桁> -->` が入っており、
    同じ目印が既にノートにあれば何もしない（追記後に落ちて再処理しても増えない）

Obsidian が未保存の編集をメモリに持ったまま後から保存した場合は Obsidian 側が
後勝ちになる。これは外部から書き込む以上なくせない（README「既知の制約」）。
"""

from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path

from .config import Config
from .fsutil import fsync_dir, is_busy_error, replace_with_retry, temp_sibling, write_synced

# ブロックの冪等化マーカー。HTMLコメントなので Obsidian の表示には出ない
MARKER_RE = re.compile(r"<!-- vl:[0-9a-f]{12} -->")
# CommonMark の ATX 見出し: 行頭の空白は3つまで、`#` は1〜6個、その後は空白か行末
_ATX_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]|$)")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
# 書いている間に利用者が編集した・相手がファイルを掴んでいた、の再試行回数
_WRITE_ATTEMPTS = 5


def block_marker(digest: str) -> str:
    return f"<!-- vl:{digest[:12]} -->"


def _heading_level(line: str) -> int:
    m = _ATX_RE.match(line)
    return len(m.group(1)) if m else 0


def _fence_mask(lines: list[str]) -> list[bool]:
    """各行がフェンス付きコードブロック（``` / ~~~）の内側（フェンス行を含む）か。

    コードブロック内の `# コメント` を見出しと取り違えると、ブロックをフェンスの
    内側に挿入してしまう。閉じていないフェンスは CommonMark と同じく文末まで続く。
    """
    mask = []
    fence = ""  # 開いているフェンスの文字列（閉じるには同じ文字で同じ長さ以上が要る）
    for line in lines:
        m = _FENCE_RE.match(line)
        if not fence:
            # バッククォートのフェンスは、情報文字列にバッククォートを含められない
            if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                fence = m.group(1)
            mask.append(bool(fence))
            continue
        mask.append(True)
        if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) \
                and not m.group(2).strip():
            fence = ""
    return mask


def upsert_section_block(content: str, heading: str, block: str) -> str:
    """content 内の heading セクション末尾に block を挿入した新しい文字列を返す。"""
    block = block.strip("\n")
    if not content.strip():
        return f"{heading}\n\n{block}\n"

    lines = content.split("\n")
    in_fence = _fence_mask(lines)
    target_level = _heading_level(heading)
    heading_idx = None
    for i, line in enumerate(lines):
        if not in_fence[i] and line.strip() == heading.strip():
            heading_idx = i
            break

    if heading_idx is None:
        return content.rstrip("\n") + f"\n\n{heading}\n\n{block}\n"

    # セクション終端 = heading より後で最初に現れる同レベル以上の見出し
    end_idx = len(lines)
    for i in range(heading_idx + 1, len(lines)):
        if in_fence[i]:
            continue
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


def _read_note(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _copy_mode(src: Path, dst: Path) -> None:
    try:
        shutil.copymode(src, dst)
    except OSError:  # 無い・Windows のバインドマウント等で chmod できない場合は既定のまま
        pass


def _already_present(content: str, block: str) -> bool:
    marker = MARKER_RE.search(block)
    return bool(marker) and marker.group(0) in content


def append_to_daily_note(cfg: Config, day: date, block: str) -> Path:
    """Daily Note にブロックを1回だけ追記する。書けなければ OSError を上げる。"""
    path = daily_note_path(cfg, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = temp_sibling(path)
    try:
        for attempt in range(_WRITE_ATTEMPTS):
            content = _read_note(path)
            if _already_present(content, block):
                return path
            write_synced(tmp, upsert_section_block(content, cfg.diary.section_heading, block))
            _copy_mode(path, tmp)
            # 一時ファイルを書いている間に利用者が保存していたら、その内容で作り直す
            if _read_note(path) != content:
                continue
            try:
                replace_with_retry(tmp, path)
            except OSError as exc:
                if not is_busy_error(exc):
                    raise
                raise PermissionError(
                    exc.errno, "Daily Note を置き換えられません（Obsidian や同期ソフトが"
                               "ファイルを掴んでいる可能性があります）", str(path)) from exc
            fsync_dir(path.parent)
            return path
        raise OSError(f"Daily Note が編集され続けているため追記を見送りました: {path}")
    finally:
        tmp.unlink(missing_ok=True)  # 成功時は rename 済みなので何もしない
