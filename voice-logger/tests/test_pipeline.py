"""パイプラインの耐障害性（再試行・冪等性・台帳・監視ループ）のテスト。

faster-whisper / Ollama は読み込まない。文字起こしと LLM 分析は差し替える。

実行: cd voice-logger && python -m pytest tests/ -q
"""

from __future__ import annotations

import http.server
import json
import logging
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from voice_logger import analyze as analyze_mod
from voice_logger import cli, fsutil, obsidian, pipeline, transcribe as transcribe_mod, watch
from voice_logger.analyze import Analysis
from voice_logger.config import (
    Config, OllamaConfig, PathsConfig, WatchConfig, WhisperConfig,
)
from voice_logger.errors import ServiceUnavailable
from voice_logger.fsutil import FileLock
from voice_logger.ingest import canonical_name, time_payload
from voice_logger.obsidian import append_to_daily_note, upsert_section_block
from voice_logger.pipeline import (
    FailureLog, Manifest, build_markdown_block, file_sha256, iter_audio_files, process_file,
)
from voice_logger.timeparse import parse_start_time
from voice_logger.transcribe import Segment, Transcript

logging.getLogger("voice_logger").setLevel(logging.CRITICAL)

HEADING = "## 🎙️ 会話ログ（自動生成）"
NAME = "20260827_091500.wav"
DAY = datetime(2026, 8, 27).date()


def make_cfg(tmp: Path, **watch_kwargs) -> Config:
    cfg = Config(
        paths=PathsConfig(inbox=tmp / "inbox", archive=tmp / "archive",
                          state=tmp / "state", obsidian_vault=tmp / "vault"),
        watch=WatchConfig(**watch_kwargs),
    )
    cfg.paths.inbox.mkdir(parents=True, exist_ok=True)
    return cfg


def fake_transcript(text: str = "おはようございます") -> Transcript:
    return Transcript(segments=[Segment(0.0, 2.0, text)], language="ja", duration=60.0)


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)
        self.cfg = make_cfg(self.tmp)

    def put(self, name: str = NAME, data: bytes = b"audio-1", age_sec: float = 3600) -> Path:
        path = self.cfg.paths.inbox / name
        path.write_bytes(data)
        old = time.time() - age_sec
        os.utime(path, (old, old))
        return path

    def note(self) -> Path:
        return obsidian.daily_note_path(self.cfg, DAY)

    def patch_stages(self, transcript=None, analysis=None, analyze_error=None):
        """transcribe / analyze を差し替え、(transcribe の mock, analyze の mock) を返す。"""
        t = mock.patch.object(pipeline, "transcribe",
                              return_value=transcript or fake_transcript())
        a = mock.patch.object(pipeline, "analyze", side_effect=analyze_error,
                              return_value=analysis or Analysis(summary="朝の挨拶。"))
        mocks = t.start(), a.start()
        self.addCleanup(t.stop)
        self.addCleanup(a.stop)
        return mocks


# --------------------------------------------------------------------------- ノート


class TestSectionBoundaries(unittest.TestCase):
    def test_hash_comment_in_code_fence_is_not_a_heading(self):
        content = (f"{HEADING}\n\nブロックA\n\n```python\n# これはコメント\nprint(1)\n```\n\n"
                   "## 次のセクション\n\n別の内容\n")
        result = upsert_section_block(content, HEADING, "ブロックB")
        self.assertLess(result.index("```\n\n"), result.index("ブロックB"))
        self.assertLess(result.index("ブロックB"), result.index("## 次のセクション"))
        self.assertEqual(result.count("```"), 2)

    def test_tilde_fence_and_longer_closing_fence(self):
        content = f"{HEADING}\n\n~~~\n# x\n```\n## y\n~~~~\n\n# 次\n"
        result = upsert_section_block(content, HEADING, "ブロックB")
        self.assertLess(result.index("~~~~"), result.index("ブロックB"))
        self.assertLess(result.index("ブロックB"), result.index("# 次"))

    def test_section_heading_inside_fence_is_not_the_section(self):
        content = f"```\n{HEADING}\n```\n\n本文\n"
        result = upsert_section_block(content, HEADING, "ブロックB")
        self.assertEqual(result.count(HEADING), 2)        # フェンスの外に新しく作る
        self.assertTrue(result.rstrip().endswith("ブロックB"))

    def test_hashtag_line_is_not_a_heading(self):
        content = f"{HEADING}\n\nブロックA\n#タグ だけの行\n#######7個は見出しではない\n"
        result = upsert_section_block(content, HEADING, "ブロックB")
        self.assertTrue(result.rstrip().endswith("ブロックB"))

    def test_unclosed_fence_runs_to_the_end(self):
        content = f"{HEADING}\n\n```\n# コメント\n## これも中身\n"
        result = upsert_section_block(content, HEADING, "ブロックB")
        self.assertTrue(result.rstrip().endswith("ブロックB"))


class TestBlockRendering(unittest.TestCase):
    def test_llm_text_cannot_start_a_line(self):
        analysis = Analysis(
            summary="一行目\n# 見出しのふり\n```\nコードのふり",
            todos=["資料を送る\n## 偽見出し", "  "],
            topics=["予定\n---"],
            reflection="良い日\n<!-- vl:000000000000 -->",
        )
        transcript = fake_transcript("こんにちは\n# 発話中の改行")
        block = build_markdown_block("a.wav", datetime(2026, 8, 27, 9, 15), transcript,
                                     analysis, "ab" * 32)
        for line in block.split("\n")[1:]:
            self.assertFalse(line.startswith(("#", "```", "---")), line)
        self.assertEqual(len(obsidian.MARKER_RE.findall(block)), 1)   # 偽の目印は無害化
        self.assertEqual(block.count("- [ ]"), 1)

    def test_marker_is_a_standalone_html_comment_after_the_heading(self):
        block = build_markdown_block("a.wav", datetime(2026, 8, 27, 9, 15), fake_transcript(),
                                     Analysis(summary="s"), "0123456789abcdef" * 4)
        lines = block.split("\n")
        self.assertTrue(lines[0].startswith("### 🎧 09:15–09:16"))
        self.assertEqual(lines[1], "<!-- vl:0123456789ab -->")


class TestDailyNoteWrite(TempDirTest):
    BLOCK = "### 🎧 09:15\n<!-- vl:0123456789ab -->\n本文"

    def leftovers(self) -> list[str]:
        return sorted(p.name for p in self.note().parent.iterdir() if p != self.note())

    def test_write_is_atomic_and_leaves_no_temp_file(self):
        self.note().parent.mkdir(parents=True)
        self.note().write_text("# 手書き\n\n大事なメモ\n", encoding="utf-8")
        append_to_daily_note(self.cfg, DAY, self.BLOCK)
        text = self.note().read_text(encoding="utf-8")
        self.assertIn("大事なメモ", text)
        self.assertIn("本文", text)
        self.assertEqual(self.leftovers(), [])

    def test_same_marker_is_appended_only_once(self):
        append_to_daily_note(self.cfg, DAY, self.BLOCK)
        before = self.note().read_text(encoding="utf-8")
        append_to_daily_note(self.cfg, DAY, self.BLOCK.replace("本文", "別の要約"))
        self.assertEqual(self.note().read_text(encoding="utf-8"), before)

    def test_replace_is_retried_while_the_note_is_held_open(self):
        real, calls = os.replace, []

        def flaky(src, dst):
            calls.append(dst)
            if len(calls) < 3:
                raise PermissionError(13, "sharing violation")
            real(src, dst)

        with mock.patch.object(fsutil.os, "replace", flaky), \
                mock.patch.object(fsutil.time, "sleep"):
            append_to_daily_note(self.cfg, DAY, self.BLOCK)
        self.assertEqual(len(calls), 3)
        self.assertIn("本文", self.note().read_text(encoding="utf-8"))

    def test_gives_up_with_an_error_and_keeps_the_note_intact(self):
        self.note().parent.mkdir(parents=True)
        self.note().write_text("大事なメモ\n", encoding="utf-8")
        with mock.patch.object(fsutil.os, "replace",
                               side_effect=PermissionError(13, "locked")), \
                mock.patch.object(fsutil.time, "sleep"):
            with self.assertRaises(PermissionError):
                append_to_daily_note(self.cfg, DAY, self.BLOCK)
        self.assertEqual(self.note().read_text(encoding="utf-8"), "大事なメモ\n")
        self.assertEqual(self.leftovers(), [])

    def test_edit_made_while_writing_is_not_lost(self):
        self.note().parent.mkdir(parents=True)
        self.note().write_text("メモ1\n", encoding="utf-8")
        real = obsidian.write_synced
        edited = []

        def write_then_user_edits(tmp, text):
            real(tmp, text)
            if not edited:   # 一時ファイルを書いている最中に利用者が保存した、を再現
                edited.append(True)
                self.note().write_text("メモ1\nメモ2\n", encoding="utf-8")

        with mock.patch.object(obsidian, "write_synced", write_then_user_edits):
            append_to_daily_note(self.cfg, DAY, self.BLOCK)
        text = self.note().read_text(encoding="utf-8")
        self.assertIn("メモ2", text)
        self.assertIn("本文", text)


# --------------------------------------------------------------------------- 1件の処理


class TestProcessFileIdempotency(TempDirTest):
    def test_crash_at_archive_twice_leaves_exactly_one_block(self):
        path = self.put()
        transcribe, _ = self.patch_stages()
        manifest = Manifest(self.cfg.paths.state)
        with mock.patch.object(pipeline, "archive_audio", side_effect=OSError("disk full")):
            for _ in range(2):
                with self.assertRaises(OSError):
                    process_file(self.cfg, path, manifest)
        self.assertTrue(process_file(self.cfg, path, manifest))

        text = self.note().read_text(encoding="utf-8")
        self.assertEqual(text.count("### 🎧"), 1)
        self.assertEqual(len(obsidian.MARKER_RE.findall(text)), 1)
        self.assertEqual(transcribe.call_count, 1)        # 2回目以降はキャッシュ
        self.assertFalse(path.exists())
        self.assertTrue(manifest.seen(file_sha256(next(self.cfg.paths.archive.rglob("*.wav")))))

    def test_transcript_is_cached_before_the_llm_step(self):
        path = self.put()
        transcribe, analyze = self.patch_stages(analyze_error=RuntimeError("LLM が壊れたJSONを返した"))
        manifest = Manifest(self.cfg.paths.state)
        with self.assertRaises(RuntimeError):
            process_file(self.cfg, path, manifest)
        cache = list((self.cfg.paths.state / "transcript_cache").glob("*.json"))
        self.assertEqual(len(cache), 1)

        analyze.side_effect = None
        self.assertTrue(process_file(self.cfg, path, manifest))
        self.assertEqual(transcribe.call_count, 1)
        self.assertEqual(list((self.cfg.paths.state / "transcript_cache").glob("*.json")), [])

    def test_cache_is_not_reused_after_changing_the_whisper_model(self):
        path = self.put()
        transcribe, _ = self.patch_stages(analyze_error=RuntimeError("x"))
        manifest = Manifest(self.cfg.paths.state)
        with self.assertRaises(RuntimeError):
            process_file(self.cfg, path, manifest)
        self.cfg.whisper.model = "small"
        with self.assertRaises(RuntimeError):
            process_file(self.cfg, path, manifest)
        self.assertEqual(transcribe.call_count, 2)

    def test_dry_run_writes_nothing(self):
        path = self.put()
        self.patch_stages()
        with mock.patch("builtins.print"):
            process_file(self.cfg, path, Manifest(self.cfg.paths.state), dry_run=True)
        self.assertTrue(path.exists())
        self.assertFalse((self.cfg.paths.state / "transcript_cache").exists())
        self.assertFalse(self.note().exists())

    def test_unwritable_vault_is_not_blamed_on_the_file(self):
        path = self.put()
        self.patch_stages()
        with mock.patch.object(pipeline, "append_to_daily_note",
                               side_effect=PermissionError(13, "locked")):
            with self.assertRaises(ServiceUnavailable):
                process_file(self.cfg, path, Manifest(self.cfg.paths.state))
        self.assertTrue(path.exists())


class TestIterAudioFiles(TempDirTest):
    def test_sidecars_dotfiles_and_hidden_dirs_are_ignored(self):
        inbox = self.cfg.paths.inbox
        (inbox / ".stversions").mkdir()
        for name in ("a.wav", "._a.wav", ".hidden.m4a", ".syncthing.b.wav.tmp",
                     ".stversions/old.wav", "sub/c.MP3", "notes.txt"):
            target = inbox / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x")
        found = [p.relative_to(inbox).as_posix() for p in iter_audio_files(inbox)]
        self.assertEqual(found, ["a.wav", "sub/c.MP3"])
        self.assertEqual(iter_audio_files(inbox / "._a.wav"), [])


# --------------------------------------------------------------------------- 台帳


class TestManifest(TempDirTest):
    def test_corrupt_manifest_is_set_aside_and_processing_continues(self):
        state = self.cfg.paths.state
        state.mkdir(parents=True)
        (state / "manifest.json").write_text('{"abc": {"source": "x"', encoding="utf-8")
        with self.assertLogs("voice_logger", level="ERROR"):
            manifest = Manifest(state)
        self.assertFalse(manifest.seen("abc"))
        self.assertEqual(len(list(state.glob("manifest.json.corrupt-*"))), 1)
        manifest.record("def", {"source": "y"})
        self.assertEqual(json.loads((state / "manifest.json").read_text(encoding="utf-8")),
                         {"def": {"source": "y"}})

    def test_two_processes_do_not_clobber_each_other(self):
        state = self.cfg.paths.state
        watch_side, process_side = Manifest(state), Manifest(state)   # 別プロセスに相当
        watch_side.record("aaa", {"source": "a"})
        process_side.record("bbb", {"source": "b"})
        watch_side.record("ccc", {"source": "c"})
        on_disk = json.loads((state / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(on_disk), ["aaa", "bbb", "ccc"])
        self.assertTrue(watch_side.seen("bbb"))     # 相手の記録も見える
        self.assertTrue(process_side.seen("ccc"))
        self.assertEqual([p.name for p in state.iterdir()], ["manifest.json"])

    def test_record_waits_for_the_lock_and_breaks_a_stale_one(self):
        state = self.cfg.paths.state
        manifest = Manifest(state)
        lock = state / "manifest.json.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("999999")
        manifest._lock = FileLock(lock, timeout_sec=0.2, stale_sec=30)
        with self.assertRaises(TimeoutError):       # 生きているロックは奪わない
            manifest.record("aaa", {})
        old = time.time() - 120
        os.utime(lock, (old, old))                  # 持ち主が落ちて残ったロック
        manifest.record("aaa", {})
        self.assertTrue(manifest.seen("aaa"))
        self.assertFalse(lock.exists())


class TestFailureLog(TempDirTest):
    def test_backoff_doubles_and_survives_restart(self):
        wc = WatchConfig(retry_base_sec=60, retry_max_sec=200)
        log = FailureLog(self.cfg.paths.state, wc)
        self.assertTrue(log.due("sha", 1000.0))
        self.assertEqual(log.record("sha", "a.wav", "boom", 1000.0), 1)
        self.assertFalse(log.due("sha", 1059.0))
        self.assertTrue(log.due("sha", 1060.0))
        self.assertEqual(log.record("sha", "a.wav", "boom", 1060.0), 2)
        self.assertEqual(log.next_retry("sha"), 1180.0)

        reloaded = FailureLog(self.cfg.paths.state, wc)
        self.assertEqual(reloaded.count("sha"), 2)
        self.assertEqual(reloaded.record("sha", "a.wav", "boom", 2000.0), 3)
        self.assertEqual(reloaded.next_retry("sha"), 2200.0)     # 上限で頭打ち
        reloaded.clear("sha")
        self.assertEqual(FailureLog(self.cfg.paths.state, wc).count("sha"), 0)


# --------------------------------------------------------------------------- 監視ループ


class TestStableFiles(TempDirTest):
    def scan(self, pending, now, min_age=60.0):
        return [p.name for p in watch.stable_files(self.cfg.paths.inbox, pending, min_age, now)]

    def test_needs_two_unchanged_scans_and_a_minimum_age(self):
        now = time.time()
        path = self.put(age_sec=10)
        pending = {}
        self.assertEqual(self.scan(pending, now), [])            # 初見
        self.assertEqual(self.scan(pending, now + 30), [])       # 不変だがまだ新しい (40秒)
        self.assertEqual(self.scan(pending, now + 60), [NAME])   # 70秒たった
        self.assertEqual(path.read_bytes(), b"audio-1")

    def test_same_size_but_newer_mtime_is_not_stable(self):
        """領域を先に確保して書き進めるコピー: サイズは同じでも mtime が動く。"""
        now = time.time()
        path = self.put(age_sec=3600)
        pending = {}
        self.scan(pending, now)
        os.utime(path, (now - 1800, now - 1800))
        self.assertEqual(self.scan(pending, now + 30), [])
        self.assertEqual(self.scan(pending, now + 60), [NAME])

    def test_mtime_in_the_future_does_not_wait_forever(self):
        now = time.time()
        self.put(age_sec=-86400)                                  # 送り元の時計が1日進んでいる
        pending = {}
        self.assertEqual(self.scan(pending, now), [])
        self.assertEqual(self.scan(pending, now + 30), [])
        self.assertEqual(self.scan(pending, now + 61), [NAME])

    def test_file_that_vanishes_during_the_scan_is_skipped(self):
        self.put("20260827_091501.wav")
        ghost = self.cfg.paths.inbox / "ghost.wav"
        listed = [ghost, self.cfg.paths.inbox / "20260827_091501.wav"]
        with mock.patch.object(watch, "iter_audio_files", return_value=listed):
            pending = {}
            self.scan(pending, time.time())
            self.assertEqual(self.scan(pending, time.time()), ["20260827_091501.wav"])
        self.assertNotIn(ghost, pending)

    def test_unreadable_file_is_skipped(self):
        self.put()
        pending = {}
        self.scan(pending, time.time())
        with mock.patch.object(watch, "_readable_now", return_value=False):
            self.assertEqual(self.scan(pending, time.time()), [])
        self.assertEqual(self.scan(pending, time.time()), [NAME])


class WatcherTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.cfg.watch = WatchConfig(max_failures=3, retry_base_sec=60, retry_max_sec=3600,
                                     min_age_sec=0)
        self.now = time.time()
        self.watcher = watch.Watcher(self.cfg, Manifest(self.cfg.paths.state), interval=30)
        self.watcher.clock = lambda: self.now

    def scan(self, advance: float = 0.0) -> None:
        self.now += advance
        self.watcher.scan_once()

    def inbox_names(self) -> list[str]:
        return sorted(p.name for p in self.cfg.paths.inbox.iterdir())


class TestWatcherRetries(WatcherTest):
    def test_broken_file_backs_off_and_is_quarantined(self):
        self.put()
        good = self.put("20260827_101500.wav", b"audio-2")
        transcribe, _ = self.patch_stages()
        transcribe.side_effect = lambda path, cfg: (
            fake_transcript() if path == good else (_ for _ in ()).throw(ValueError("壊れた音声")))

        self.scan()                       # 初見（安定判定のため1回見送る）
        self.scan(30)                     # 失敗1回目。もう1本は普通に処理される
        self.assertEqual(self.inbox_names(), [NAME])
        calls = transcribe.call_count
        self.scan(30)                     # 60秒たっていないので触らない
        self.assertEqual(transcribe.call_count, calls)
        self.scan(60)                     # 失敗2回目（次は120秒後）
        self.scan(60)
        self.assertEqual(transcribe.call_count, calls + 1)
        with self.assertLogs("voice_logger", level="ERROR") as logs:
            self.scan(120)                # 失敗3回目 = max_failures → 隔離
        self.assertEqual(self.inbox_names(), [])
        failed = self.cfg.paths.quarantine_dir()
        self.assertEqual(failed, self.tmp / "failed")
        self.assertEqual([p.name for p in failed.iterdir()], [NAME])
        self.assertIn("隔離", "\n".join(logs.output))
        self.assertEqual(self.watcher.failures.count(file_sha256(failed / NAME)), 0)

    def test_failure_count_survives_restart(self):
        path = self.put()
        transcribe, _ = self.patch_stages()
        transcribe.side_effect = ValueError("壊れた音声")
        self.scan()
        self.scan(30)
        restarted = watch.Watcher(self.cfg, Manifest(self.cfg.paths.state), interval=30)
        restarted.clock = lambda: self.now
        restarted.scan_once()
        restarted.scan_once()             # 再起動直後でも再試行時刻までは触らない
        self.assertEqual(transcribe.call_count, 1)
        self.assertEqual(restarted.failures.count(file_sha256(path)), 1)

    def test_service_outage_is_not_counted_against_files(self):
        path = self.put()
        self.put("20260827_101500.wav", b"audio-2")
        transcribe, analyze = self.patch_stages(
            analyze_error=ServiceUnavailable("Ollama にモデルがありません。ollama pull ..."))
        self.scan()
        with self.assertLogs("voice_logger", level="ERROR") as logs:
            self.scan(30)
        self.assertIn("ollama pull", "\n".join(logs.output))
        self.assertEqual(analyze.call_count, 1)           # 2本目は試さずに待つ
        self.scan(10)                                     # 待機中は何もしない
        self.assertEqual(analyze.call_count, 1)
        for _ in range(20):                               # 何度落ちていても隔離されない
            self.scan(700)
        self.assertEqual(len(self.inbox_names()), 2)
        self.assertEqual(self.watcher.failures.count(file_sha256(path)), 0)
        self.assertFalse(self.cfg.paths.quarantine_dir().exists())

        analyze.side_effect = None                        # モデルを pull した
        self.scan(700)
        self.assertEqual(self.inbox_names(), [])
        self.assertEqual(transcribe.call_count, 2)        # 文字起こしは1本1回だけ

    def test_file_removed_during_processing_is_not_a_failure(self):
        path = self.put()
        transcribe, _ = self.patch_stages()

        def vanish(p, cfg):
            p.unlink()
            raise FileNotFoundError(str(p))

        transcribe.side_effect = vanish
        self.scan()
        self.scan(30)
        self.assertEqual(self.watcher.failures._data, {})
        self.assertFalse(path.exists())


class TestWatcherDuplicates(WatcherTest):
    def process_once(self) -> Path:
        self.put()
        self.patch_stages()
        self.scan()
        self.scan(30)
        return next(self.cfg.paths.archive.rglob("*.wav"))

    def test_identical_copy_of_archived_audio_is_deleted(self):
        archived = self.process_once()
        self.put("copy of recording.wav")          # 同じ内容が別名でまた同期されてきた
        self.scan(30)
        with mock.patch.object(watch, "file_sha256", wraps=file_sha256) as hashing:
            self.scan(30)
            self.scan(30)
        self.assertEqual(self.inbox_names(), [])
        self.assertEqual(hashing.call_count, 1)    # 退かすので、以後のスキャンで読み直さない
        self.assertEqual([p.name for p in self.cfg.paths.archive.rglob("*.wav")],
                         [archived.name])
        self.assertEqual(self.note().read_text(encoding="utf-8").count("### 🎧"), 1)

    def test_copy_is_archived_when_the_archived_audio_is_gone(self):
        archived = self.process_once()
        archived.unlink()
        self.put("copy.wav")
        self.scan(30)
        self.scan(30)
        self.assertEqual(self.inbox_names(), [])
        self.assertEqual([p.name for p in self.cfg.paths.archive.rglob("*.wav")], ["copy.wav"])


class TestServeStartupErrors(TempDirTest):
    def test_missing_pki_files_exit_with_a_clear_error(self):
        config = self.tmp / "config.toml"
        config.write_text(
            f'[paths]\ninbox = "{self.tmp.as_posix()}/inbox"\nstate = "{self.tmp.as_posix()}/state"\n'
            f'[ingest]\nport = 0\ntls_cert = "{self.tmp.as_posix()}/pki/server.crt"\n'
            f'tls_key = "{self.tmp.as_posix()}/pki/server.key"\n'
            f'client_ca = "{self.tmp.as_posix()}/pki/ca.crt"\n'
            f'hmac_key_file = "{self.tmp.as_posix()}/pki/hmac.key"\n', encoding="utf-8")
        with self.assertLogs("voice_logger", level="ERROR") as logs:
            code = cli.main(["--config", str(config), "serve"])
        self.assertEqual(code, 2)
        self.assertIn("hmac.key", "\n".join(logs.output))


# --------------------------------------------------------------------------- 外部通信


class _FakeOllama(http.server.BaseHTTPRequestHandler):
    status = 200
    requests: list[dict] = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append(body)
        if self.status == 200:
            content = json.dumps({"summary": "要約", "todos": [], "topics": [], "reflection": ""})
            payload = {"message": {"content": content}}
        else:
            payload = {"error": f"model '{body['model']}' not found"}
        data = json.dumps(payload).encode("utf-8")
        self.send_response(self.status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class TestOllamaClient(unittest.TestCase):
    def setUp(self):
        try:
            import requests  # noqa: F401
        except ImportError:
            self.skipTest("requests が必要")
        _FakeOllama.status, _FakeOllama.requests = 200, []
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllama)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def analyze(self, **kwargs) -> Analysis:
        cfg = OllamaConfig(url=self.url, model="qwen3:4b", timeout_sec=10, **kwargs)
        return analyze_mod.analyze(fake_transcript(), datetime(2026, 8, 27, 9, 15), cfg)

    def test_proxy_environment_is_ignored(self):
        """HTTP_PROXY が設定されたマシンでも、文字起こしをプロキシへ送らない。"""
        dead_proxy = "http://127.0.0.1:9"
        env = {"HTTP_PROXY": dead_proxy, "http_proxy": dead_proxy,
               "ALL_PROXY": dead_proxy, "all_proxy": dead_proxy, "NO_PROXY": "", "no_proxy": ""}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(self.analyze().summary, "要約")
        self.assertFalse(analyze_mod._http().trust_env)

    def test_context_size_and_think_come_from_config(self):
        self.analyze(num_ctx=8192, think=False)
        self.analyze()
        first, second = _FakeOllama.requests
        self.assertEqual(first["options"]["num_ctx"], 8192)
        self.assertIs(first["think"], False)
        self.assertNotIn("think", second)

    def test_missing_model_tells_how_to_pull_it(self):
        _FakeOllama.status = 404
        with self.assertRaises(ServiceUnavailable) as caught:
            self.analyze()
        self.assertIn("ollama pull qwen3:4b", str(caught.exception))

    def test_unreachable_ollama_is_a_service_outage(self):
        self.url = "http://127.0.0.1:9"
        with self.assertRaises(ServiceUnavailable):
            self.analyze()


class TestWhisperOffline(unittest.TestCase):
    """モデルがキャッシュにあれば huggingface.co へ問い合わせない。"""

    def setUp(self):
        self.calls: list[bool] = []
        self.cached = True
        test = self

        class FakeWhisperModel:
            def __init__(self, model, device, compute_type, local_files_only):
                test.calls.append(local_files_only)
                if local_files_only and not test.cached:
                    raise FileNotFoundError("Cannot find an appropriate cached snapshot")

        fake = types.ModuleType("faster_whisper")
        fake.WhisperModel = FakeWhisperModel
        for patcher in (mock.patch.dict(sys.modules, {"faster_whisper": fake}),
                        mock.patch.dict(transcribe_mod._model_cache, clear=True),
                        mock.patch.dict(os.environ)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("HF_HUB_OFFLINE", None)

    def load(self, offline):
        return transcribe_mod._get_model(WhisperConfig(model="tiny", offline=offline))

    def test_cached_model_loads_without_network(self):
        self.load("auto")
        self.assertEqual(self.calls, [True])
        self.assertEqual(os.environ["HF_HUB_DISABLE_TELEMETRY"], "1")

    def test_first_run_falls_back_to_download(self):
        self.cached = False
        self.load("auto")
        self.assertEqual(self.calls, [True, False])

    def test_offline_true_never_downloads(self):
        self.cached = False
        with self.assertRaises(ServiceUnavailable):
            self.load(True)
        self.assertEqual(self.calls, [True])
        self.assertEqual(os.environ["HF_HUB_OFFLINE"], "1")

    def test_offline_false_keeps_the_old_behaviour(self):
        self.load(False)
        self.assertEqual(self.calls, [False])


# --------------------------------------------------------------------------- タイムゾーン


@unittest.skipUnless(hasattr(time, "tzset") and Path("/usr/share/zoneinfo/Asia/Tokyo").exists(),
                     "tzset と tzdata が必要")
class TestTimezone(unittest.TestCase):
    """TZ 環境変数（compose が渡す）が、時刻を使う箇所すべてに効くこと。"""

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"TZ": "Asia/Tokyo"})
        patcher.start()
        time.tzset()
        self.addCleanup(time.tzset)      # 後から登録したものが先に走る: 環境を戻してから tzset
        self.addCleanup(patcher.stop)

    def test_device_gets_jst_offset(self):
        payload = time_payload()
        self.assertEqual(payload["tz_offset_min"], 540)
        self.assertTrue(payload["iso"].endswith("+09:00"))

    def test_early_morning_recording_lands_on_the_local_day(self):
        epoch = 1787787300                                  # 2026-08-26 23:35:00 UTC
        self.assertEqual(canonical_name(datetime.fromtimestamp(epoch)), "20260827_083500.wav")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "recording.wav"
            path.write_bytes(b"x")
            os.utime(path, (epoch, epoch))
            start, source = parse_start_time(path)
        self.assertEqual((source, start.date()), ("mtime", DAY))


if __name__ == "__main__":
    unittest.main()
