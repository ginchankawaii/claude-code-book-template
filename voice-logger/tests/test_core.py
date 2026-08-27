"""重量級依存（faster-whisper / Ollama）なしで動くコアロジックのテスト。

実行: cd voice-logger && PYTHONPATH=src python -m unittest discover tests -v
"""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from voice_logger.obsidian import upsert_section_block
from voice_logger.timeparse import parse_start_time

HEADING = "## 🎙️ 会話ログ（自動生成）"


class TestUpsertSectionBlock(unittest.TestCase):
    def test_empty_note(self):
        result = upsert_section_block("", HEADING, "### 🎧 09:00\nテスト")
        self.assertEqual(result, f"{HEADING}\n\n### 🎧 09:00\nテスト\n")

    def test_note_without_section(self):
        content = "# 2026-08-27\n\n今日の出来事。\n"
        result = upsert_section_block(content, HEADING, "ブロックA")
        self.assertIn("今日の出来事。", result)
        self.assertTrue(result.rstrip().endswith("ブロックA"))
        self.assertIn(HEADING, result)

    def test_append_to_existing_section_at_end(self):
        content = f"# メモ\n\n{HEADING}\n\nブロックA\n"
        result = upsert_section_block(content, HEADING, "ブロックB")
        self.assertEqual(result.count(HEADING), 1)
        self.assertLess(result.index("ブロックA"), result.index("ブロックB"))

    def test_insert_before_next_section(self):
        content = f"# メモ\n\n{HEADING}\n\nブロックA\n\n## 次のセクション\n\n別の内容\n"
        result = upsert_section_block(content, HEADING, "ブロックB")
        self.assertLess(result.index("ブロックA"), result.index("ブロックB"))
        self.assertLess(result.index("ブロックB"), result.index("## 次のセクション"))
        self.assertIn("別の内容", result)

    def test_h3_inside_section_is_not_a_boundary(self):
        content = f"{HEADING}\n\n### 🎧 09:00\n内容A\n"
        result = upsert_section_block(content, HEADING, "### 🎧 13:00\n内容B")
        self.assertLess(result.index("内容A"), result.index("内容B"))


class TestParseStartTime(unittest.TestCase):
    def _touch(self, tmpdir: str, name: str) -> Path:
        p = Path(tmpdir) / name
        p.write_bytes(b"x")
        return p

    def test_full_datetime_patterns(self):
        cases = {
            "20260827_091500.wav": datetime(2026, 8, 27, 9, 15, 0),
            "2026-08-27_09-15-00.m4a": datetime(2026, 8, 27, 9, 15, 0),
            "2026-08-27 09.15.00.mp3": datetime(2026, 8, 27, 9, 15, 0),
            "REC_2026-08-27_09-15.wav": datetime(2026, 8, 27, 9, 15),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            for name, expected in cases.items():
                path = self._touch(tmpdir, name)
                dt, source = parse_start_time(path)
                self.assertEqual(dt, expected, name)
                self.assertEqual(source, "filename", name)

    def test_date_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._touch(tmpdir, "20260827.wav")
            dt, source = parse_start_time(path)
            self.assertEqual(dt, datetime(2026, 8, 27))
            self.assertEqual(source, "filename")

    def test_fallback_to_mtime_minus_duration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._touch(tmpdir, "recording.wav")
            dt, source = parse_start_time(path, duration_sec=3600)
            self.assertEqual(source, "mtime")
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            self.assertAlmostEqual((mtime - dt).total_seconds(), 3600, delta=1)

    def test_garbage_digits_do_not_crash(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._touch(tmpdir, "99999999_998877.wav")
            dt, source = parse_start_time(path)
            self.assertEqual(source, "mtime")


if __name__ == "__main__":
    unittest.main()
