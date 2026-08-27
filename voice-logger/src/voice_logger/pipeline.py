"""パイプライン本体：音声ファイル1件を 文字起こし → 分析 → Daily Note 追記 まで処理する。"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from .analyze import Analysis, analyze
from .config import Config
from .obsidian import append_to_daily_note
from .timeparse import parse_start_time
from .transcribe import Transcript, transcribe

logger = logging.getLogger("voice_logger")

AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".webm"}


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Manifest:
    """処理済みファイルの台帳（sha256ベースなのでリネーム・再コピーでも重複処理しない）。"""

    def __init__(self, state_dir: Path):
        self.path = state_dir / "manifest.json"
        self._data: dict[str, dict] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def seen(self, digest: str) -> bool:
        return digest in self._data

    def record(self, digest: str, entry: dict) -> None:
        self._data[digest] = entry
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        tmp.replace(self.path)


def build_markdown_block(
    source_name: str,
    start: datetime,
    transcript: Transcript,
    analysis: Analysis,
) -> str:
    end = start + timedelta(seconds=transcript.duration)
    lines: list[str] = []
    lines.append(f"### 🎧 {start:%H:%M}–{end:%H:%M}（{source_name}）")
    if analysis.summary:
        lines.append(f"**サマリー**: {analysis.summary}")
    if analysis.topics:
        lines.append(f"**トピック**: {'、'.join(analysis.topics)}")
    if analysis.reflection:
        lines.append(f"**振り返り**: {analysis.reflection}")
    if analysis.todos:
        lines.append("")
        lines.append("**ToDo / 約束**")
        for todo in analysis.todos:
            lines.append(f"- [ ] {todo}")
    lines.append("")
    lines.append("> [!note]- 全文文字起こし")
    for seg in transcript.segments:
        clock = (start + timedelta(seconds=seg.start)).strftime("%H:%M")
        lines.append(f"> - {clock} {seg.text}")
    return "\n".join(lines)


def save_transcript_json(
    cfg: Config,
    digest: str,
    source: Path,
    start: datetime,
    transcript: Transcript,
    analysis: Analysis,
) -> Path:
    out_dir = cfg.paths.state / "transcripts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{start:%Y-%m-%d_%H%M%S}_{source.stem}.json"
    out.write_text(
        json.dumps(
            {
                "source": source.name,
                "sha256": digest,
                "start": start.isoformat(),
                "duration_sec": transcript.duration,
                "language": transcript.language,
                "segments": [asdict(s) for s in transcript.segments],
                "analysis": asdict(analysis),
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return out


def archive_audio(cfg: Config, path: Path, start: datetime) -> Path:
    dest_dir = cfg.paths.archive / f"{start:%Y-%m}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    counter = 1
    while dest.exists():
        dest = dest_dir / f"{path.stem}_{counter}{path.suffix}"
        counter += 1
    shutil.move(str(path), str(dest))
    return dest


def process_file(cfg: Config, path: Path, manifest: Manifest, dry_run: bool = False) -> bool:
    """1ファイルを処理。処理した場合 True、スキップした場合 False を返す。"""
    digest = file_sha256(path)
    if manifest.seen(digest):
        logger.info("スキップ（処理済み）: %s", path.name)
        return False

    logger.info("文字起こし開始: %s", path.name)
    transcript = transcribe(path, cfg.whisper)
    start, start_source = parse_start_time(path, transcript.duration)
    logger.info(
        "文字起こし完了: %d セグメント / %.0f 秒（開始時刻 %s, 推定元=%s）",
        len(transcript.segments), transcript.duration, start, start_source,
    )

    if transcript.is_empty():
        logger.info("発話なしのためノート追記なし: %s", path.name)
        analysis = Analysis()
    else:
        logger.info("LLM分析開始 (%s)", cfg.ollama.model)
        analysis = analyze(transcript, start, cfg.ollama)

    block = build_markdown_block(path.name, start, transcript, analysis)

    if dry_run:
        print(block)
        return True

    if not transcript.is_empty():
        note = append_to_daily_note(cfg, start.date(), block)
        logger.info("Daily Note 追記: %s", note)
    else:
        note = None

    transcript_path = save_transcript_json(cfg, digest, path, start, transcript, analysis)
    archived = archive_audio(cfg, path, start)
    manifest.record(
        digest,
        {
            "source": path.name,
            "processed_at": datetime.now().isoformat(timespec="seconds"),
            "start": start.isoformat(),
            "note": str(note) if note else None,
            "transcript": str(transcript_path),
            "archived_audio": str(archived),
        },
    )
    logger.info("完了: %s → %s", path.name, archived)
    return True


def iter_audio_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix.lower() in AUDIO_EXTENSIONS else []
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
    )
