# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import checker

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(BASE, "rules.yaml")
SAMPLES = os.path.join(BASE, "samples")


class CheckerSampleTest(unittest.TestCase):
    """3つのサンプルBOM = 過去の失敗2件+クリーン構成のキラーデモ検証。"""

    def test_wlc_incident_detected(self):
        report, has_findings = checker.run_check(
            os.path.join(SAMPLES, "bom_wlc_incident.csv"), RULES)
        self.assertTrue(has_findings)
        self.assertIn("WLC-001", report)
        self.assertIn("既存WLC", report)
        self.assertNotIn("ASA-001", report)
        # 部材(ブラケット)はAPとして数えないこと
        self.assertNotIn("AIR-AP-BRACKET", report.split("パターン照合")[0])

    def test_asa_incident_detected(self):
        report, has_findings = checker.run_check(
            os.path.join(SAMPLES, "bom_asa_incident.csv"), RULES)
        self.assertTrue(has_findings)
        self.assertIn("ASA-001", report)
        self.assertIn("ASA本体 2 台", report)
        self.assertIn("1 本しかありません", report)
        self.assertNotIn("WLC-001", report)

    def test_clean_bom_passes(self):
        report, has_findings = checker.run_check(
            os.path.join(SAMPLES, "bom_clean.csv"), RULES)
        self.assertFalse(has_findings)
        self.assertIn("指摘なし", report)
        self.assertNotIn("[DRAFT]", report)


class CheckerIoTest(unittest.TestCase):
    def _write(self, content, encoding="utf-8"):
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        self.addCleanup(os.remove, path)
        with open(path, "w", encoding=encoding, newline="") as f:
            f.write(content)
        return path

    def test_cp932_japanese_headers(self):
        """Excel(Shift-JIS)保存 + 日本語ヘッダーのCSVも読めること。"""
        path = self._write(
            "型番,説明,数量\nASA5516-FPWR-K9,ASA本体,2\nL-ASA5516-TAMC=,ライセンス,1\n",
            encoding="cp932")
        report, has_findings = checker.run_check(path, RULES)
        self.assertTrue(has_findings)
        self.assertIn("ASA-001", report)
        self.assertIn("cp932", report)

    def test_qty_with_comma(self):
        path = self._write(
            "Part Number,Description,Quantity\n"
            "C9120AXI-Q,AP,\"1,000\"\n")
        rows, warnings, _ = checker.read_bom(path)
        self.assertEqual(rows[0]["qty"], 1000)
        self.assertEqual(warnings, [])

    def test_unparsable_qty_defaults_to_one(self):
        path = self._write(
            "Part Number,Quantity\nC9120AXI-Q,約20\n")
        rows, warnings, _ = checker.read_bom(path)
        self.assertEqual(rows[0]["qty"], 1)
        self.assertTrue(warnings)

    def test_no_header_mode(self):
        path = self._write("ASA5516-FPWR-K9,ASA,2\nL-ASA5516-TAMC=,Lic,1\n")
        rows, _, _ = checker.read_bom(path, no_header=True)
        self.assertEqual([r["qty"] for r in rows], [2, 1])

    def test_missing_header_raises(self):
        path = self._write("foo,bar\nbaz,1\n")
        with self.assertRaises(checker.CheckerError):
            checker.read_bom(path)

    def test_fullwidth_normalization(self):
        """全角の型番・数量(Excelあるある)も正規化して読めること。"""
        path = self._write(
            "型番,数量\nＡＳＡ５５１６－ＦＰＷＲ－Ｋ９,２\nL-ASA5516-TAMC=,1\n")
        rows, _, _ = checker.read_bom(path)
        self.assertEqual(rows[0]["part"], "ASA5516-FPWR-K9")
        self.assertEqual(rows[0]["qty"], 2)


class CheckerRulesTest(unittest.TestCase):
    def test_rules_file_valid(self):
        compiled, rules = checker.load_rules(RULES)
        ids = [r["id"] for r in rules]
        self.assertIn("WLC-001", ids)
        self.assertIn("ASA-001", ids)
        confirmed = [r for r in rules
                     if (r.get("status") or "confirmed") != "draft"]
        self.assertEqual(len(confirmed), 2)


if __name__ == "__main__":
    unittest.main()
