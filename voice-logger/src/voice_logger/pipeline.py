"""パイプライン本体：音声ファイル1件を 文字起こし → 分析 → Daily Note 追記 まで処理する。

途中で落ちても同じファイルをもう一度流せば同じ結果に収束するようにしてある:

  * 文字起こしは LLM 分析の前に `state/transcript_cache/<sha256>.json` へ保存し、
    再試行ではそれを使う（一番重い工程をやり直さない）
  * ノートのブロックには音源の目印が入り、同じ目印があれば追記しない（obsidian.py）
  * 台帳は書くたびにディスクから読み直して合流する（`process` と `watch` の同時実行）
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from .analyze import Analysis, analyze
from .config import Config, WatchConfig, WhisperConfig
from .errors import ServiceUnavailable
from .fsutil import FileLock, atomic_write_text
from .obsidian import append_to_daily_note, block_marker
from .timeparse import parse_start_time
from .transcribe import Segment, Transcript, transcribe

logger = logging.getLogger("voice_logger")

AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".webm"}
# 失敗記録を残しておく期間（inbox から手で消されたファイルの記録が溜まり続けないように）
FAILURE_RETENTION_SEC = 30 * 24 * 3600


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _unique_dest(dest_dir: Path, name: str) -> Path:
    dest = dest_dir / name
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 1
    while dest.exists():
        dest = dest_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    return dest


class Manifest:
    """処理済みファイルの台帳（sha256ベースなのでリネーム・再コピーでも重複処理しない）。

    `watch` の常駐中に `process` を別プロセスで走らせても互いの記録を消さないよう、
    ディスク上のファイルを正とする: 参照のたびに更新を検知して読み直し、記録は
    ロックファイルの下で「読み直す → 1件足す → アトミックに書き戻す」。
    """

    def __init__(self, state_dir: Path):
        self.path = state_dir / "manifest.json"
        self._lock = FileLock(state_dir / "manifest.json.lock")
        self._data: dict[str, dict] = {}
        self._signature: tuple[int, int] | None = None
        self._reload()

    def _disk_signature(self) -> tuple[int, int] | None:
        try:
            st = self.path.stat()
        except OSError:
            return None
        return st.st_mtime_ns, st.st_size

    def _set_aside_corrupt(self) -> None:
        aside = self.path.with_name(
            f"{self.path.name}.corrupt-{datetime.now():%Y%m%d-%H%M%S}")
        try:
            self.path.replace(aside)
        except OSError:  # 別プロセスが先に退避した
            return
        logger.error(
            "処理済み台帳が壊れていたため %s に退避し、空の台帳で続行します。"
            "過去に処理した音声を inbox に戻すと再処理されます（ノートのブロックは"
            "目印で重複しません）", aside)

    def _reload(self) -> None:
        signature = self._disk_signature()
        if signature is None:
            self._data, self._signature = {}, None
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("台帳のトップレベルがオブジェクトではありません")
        except OSError:
            return  # 置き換えの瞬間に読めなかっただけ。手元の内容のまま次回また確認する
        except ValueError:  # JSONDecodeError / UnicodeDecodeError を含む
            self._set_aside_corrupt()
            self._data, self._signature = {}, None
            return
        self._data, self._signature = data, signature

    def _refresh(self) -> None:
        if self._disk_signature() != self._signature:
            self._reload()

    def get(self, digest: str) -> dict | None:
        self._refresh()
        return self._data.get(digest)

    def seen(self, digest: str) -> bool:
        return self.get(digest) is not None

    def record(self, digest: str, entry: dict) -> None:
        with self._lock:
            self._reload()
            self._data[digest] = entry
            atomic_write_text(
                self.path, json.dumps(self._data, ensure_ascii=False, indent=1))
            self._signature = self._disk_signature()


class FailureLog:
    """ファイル（sha256）ごとの失敗回数と次回再試行時刻。再起動しても引き継ぐ。

    これが無いと、壊れた音声1本を 30 秒ごとに永遠に文字起こしし続ける。
    """

    def __init__(self, state_dir: Path, wc: WatchConfig):
        self.path = state_dir / "failures.json"
        self.wc = wc
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            logger.warning("失敗記録が読めないので作り直します: %s", self.path)
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self) -> None:
        atomic_write_text(self.path, json.dumps(self._data, ensure_ascii=False, indent=1))

    def _prune(self, now: float) -> None:
        stale = [d for d, e in self._data.items()
                 if now - e.get("last_failed", now) > FAILURE_RETENTION_SEC]
        for digest in stale:
            del self._data[digest]

    def count(self, digest: str) -> int:
        return int(self._data.get(digest, {}).get("count", 0))

    def next_retry(self, digest: str) -> float:
        return float(self._data.get(digest, {}).get("next_retry", 0.0))

    def due(self, digest: str, now: float) -> bool:
        return now >= self.next_retry(digest)

    def record(self, digest: str, source: str, error: str, now: float) -> int:
        """失敗を1回数え、数えた後の回数を返す。"""
        count = self.count(digest) + 1
        delay = min(self.wc.retry_base_sec * 2 ** (count - 1), self.wc.retry_max_sec)
        self._prune(now)
        self._data[digest] = {
            "source": source, "count": count, "last_error": error[:500],
            "last_failed": now, "next_retry": now + delay,
        }
        self._save()
        return count

    def clear(self, digest: str) -> None:
        if self._data.pop(digest, None) is not None:
            self._save()


def _one_line(text: str) -> str:
    """LLM・文字起こし由来の文字列を、ブロックの1行に安全に埋められる形にする。

    改行を残すと続きの行が行頭から始まり、`# ` や ``` で始まっていればノートの
    見出し・コードフェンスとして解釈されてしまう（以降のセクション境界が狂う）。
    `<!--` はブロックの目印や Obsidian の表示を壊さないよう無害化する。
    """
    return " ".join(str(text).split()).replace("<!--", "&lt;!--")


def build_markdown_block(
    source_name: str,
    start: datetime,
    transcript: Transcript,
    analysis: Analysis,
    digest: str = "",
) -> str:
    end = start + timedelta(seconds=transcript.duration)
    lines: list[str] = []
    lines.append(f"### 🎧 {start:%H:%M}–{end:%H:%M}（{_one_line(source_name)}）")
    if digest:
        # 見出しの直後に単独行で置く（HTMLコメントは Obsidian のプレビューに出ない）
        lines.append(block_marker(digest))
    if analysis.summary:
        lines.append(f"**サマリー**: {_one_line(analysis.summary)}")
    topics = [t for t in map(_one_line, analysis.topics) if t]
    if topics:
        lines.append(f"**トピック**: {'、'.join(topics)}")
    if analysis.reflection:
        lines.append(f"**振り返り**: {_one_line(analysis.reflection)}")
    todos = [t for t in map(_one_line, analysis.todos) if t]
    if todos:
        lines.append("")
        lines.append("**ToDo / 約束**")
        for todo in todos:
            lines.append(f"- [ ] {todo}")
    lines.append("")
    lines.append("> [!note]- 全文文字起こし")
    for seg in transcript.segments:
        clock = (start + timedelta(seconds=seg.start)).strftime("%H:%M")
        lines.append(f"> - {clock} {_one_line(seg.text)}")
    return "\n".join(lines)


# ---- 文字起こしキャッシュ（LLM 分析以降で失敗しても、文字起こしをやり直さない）


def _transcript_cache_path(cfg: Config, digest: str) -> Path:
    return cfg.paths.state / "transcript_cache" / f"{digest}.json"


def _whisper_key(wc: WhisperConfig) -> dict:
    # モデルや言語を変えたら古い文字起こしを使い回さない
    return {"model": wc.model, "language": wc.language}


def load_cached_transcript(cfg: Config, digest: str) -> Transcript | None:
    try:
        raw = json.loads(_transcript_cache_path(cfg, digest).read_text(encoding="utf-8"))
        if raw["whisper"] != _whisper_key(cfg.whisper):
            return None
        return Transcript(
            segments=[Segment(**seg) for seg in raw["segments"]],
            language=raw["language"], duration=raw["duration"],
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None  # 無い・壊れている → 文字起こしからやり直すだけ


def save_cached_transcript(cfg: Config, digest: str, transcript: Transcript) -> None:
    atomic_write_text(
        _transcript_cache_path(cfg, digest),
        json.dumps({
            "whisper": _whisper_key(cfg.whisper),
            "language": transcript.language,
            "duration": transcript.duration,
            "segments": [asdict(s) for s in transcript.segments],
        }, ensure_ascii=False),
    )


def drop_cached_transcript(cfg: Config, digest: str) -> None:
    try:
        _transcript_cache_path(cfg, digest).unlink()
    except OSError:
        pass


def _transcript_for(cfg: Config, path: Path, digest: str, use_cache_dir: bool) -> Transcript:
    cached = load_cached_transcript(cfg, digest)
    if cached is not None:
        logger.info("文字起こしはキャッシュを使用: %s", path.name)
        return cached
    logger.info("文字起こし開始: %s", path.name)
    transcript = transcribe(path, cfg.whisper)
    if use_cache_dir:
        save_cached_transcript(cfg, digest, transcript)
    return transcript


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
    atomic_write_text(
        out,
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
    )
    return out


def archive_audio(cfg: Config, path: Path, start: datetime) -> Path:
    dest_dir = cfg.paths.archive / f"{start:%Y-%m}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = _unique_dest(dest_dir, path.name)
    shutil.move(str(path), str(dest))
    return dest


def quarantine_audio(cfg: Config, path: Path) -> Path:
    """処理できない音声を inbox の外へ隔離する（削除はしない。戻せば再処理される）。"""
    dest_dir = cfg.paths.quarantine_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = _unique_dest(dest_dir, path.name)
    shutil.move(str(path), str(dest))
    return dest


def _same_content_archived(path: Path, digest: str, entry: dict) -> bool:
    recorded = entry.get("archived_audio")
    if not recorded:
        return False
    archived = Path(recorded)
    try:
        if archived.resolve() == path.resolve():
            return False
        return (archived.is_file() and archived.stat().st_size == path.stat().st_size
                and file_sha256(archived) == digest)
    except OSError:
        return False


def retire_duplicate(cfg: Config, path: Path, digest: str, entry: dict) -> None:
    """処理済みと同じ内容の音声を inbox から退かす。

    置いたままだと毎スキャンで全体を読み直して sha256 を計算することになる。
    同じ内容が archive に残っていれば削除、無ければ（手で消された等）archive へ移す。
    """
    if _same_content_archived(path, digest, entry):
        path.unlink()
        logger.info("処理済みと同一内容のため削除: %s（保管済み: %s）",
                    path.name, entry.get("archived_audio"))
        return
    try:
        start = datetime.fromisoformat(entry["start"])
    except (KeyError, TypeError, ValueError):
        start = parse_start_time(path)[0]
    logger.info("処理済みのためアーカイブへ移動: %s → %s",
                path.name, archive_audio(cfg, path, start))


def _append_note(cfg: Config, start: datetime, block: str) -> Path:
    try:
        return append_to_daily_note(cfg, start.date(), block)
    except OSError as exc:
        # vault が見えない・ノートを掴まれている、は録音のせいではない
        raise ServiceUnavailable(
            f"Daily Note に書き込めません（vault のマウントと、Obsidian / 同期ソフトが"
            f"ノートを掴んでいないかを確認してください）: {exc}") from exc


def process_file(
    cfg: Config,
    path: Path,
    manifest: Manifest,
    dry_run: bool = False,
    digest: str | None = None,
    retire_duplicates: bool = False,
) -> bool:
    """1ファイルを処理。処理した場合 True、スキップした場合 False を返す。

    `digest` は呼び出し側が計算済みの sha256（大きな音声を二度読まないため）。
    `retire_duplicates` は処理済みファイルを inbox から退かすか（`watch` 用。
    `process` で利用者が指した場所のファイルは勝手に消さない）。
    """
    digest = digest or file_sha256(path)
    entry = manifest.get(digest)
    if entry is not None:
        logger.info("スキップ（処理済み）: %s", path.name)
        if retire_duplicates and not dry_run:
            retire_duplicate(cfg, path, digest, entry)
        return False

    transcript = _transcript_for(cfg, path, digest, use_cache_dir=not dry_run)
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

    block = build_markdown_block(path.name, start, transcript, analysis, digest)

    if dry_run:
        print(block)
        return True

    if not transcript.is_empty():
        note = _append_note(cfg, start, block)
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
    drop_cached_transcript(cfg, digest)
    logger.info("完了: %s → %s", path.name, archived)
    return True


def _is_hidden(path: Path, root: Path) -> bool:
    """ドットで始まる名前（自身または root までの途中のディレクトリ）か。

    macOS の `._*`（AppleDouble: 拡張子は音声でも中身はメタデータ）、Syncthing の
    `.stversions/` や転送中の `.syncthing.*.tmp`、受信APIの `.ingest-*.part` を拾わない。
    """
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def iter_audio_files(root: Path) -> list[Path]:
    if root.is_file():
        ok = root.suffix.lower() in AUDIO_EXTENSIONS and not root.name.startswith(".")
        return [root] if ok else []
    return sorted(
        p for p in root.rglob("*")
        if p.suffix.lower() in AUDIO_EXTENSIONS and not _is_hidden(p, root) and p.is_file()
    )
