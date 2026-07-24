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

    def test_qty_with_units_extracts_number(self):
        """「約20」「2台」のような表記は数値を抽出する(min_qtyルールの検出漏れ防止)。"""
        path = self._write(
            "Part Number,Quantity\nC9120AXI-Q,約20\nAIR-CT3504-K9,2台\n")
        rows, warnings, _ = checker.read_bom(path)
        self.assertEqual([r["qty"] for r in rows], [20, 2])
        self.assertEqual(len(warnings), 2)

    def test_digitless_qty_defaults_to_one(self):
        path = self._write("Part Number,Quantity\nC9120AXI-Q,数量未定\n")
        rows, warnings, _ = checker.read_bom(path)
        self.assertEqual(rows[0]["qty"], 1)
        self.assertTrue(warnings)

    def test_utf16_tab_separated(self):
        """Excel「Unicodeテキスト」保存(UTF-16タブ区切り)も文字化けせず読めること。"""
        path = self._write(
            "Part Number\tDescription\tQuantity\n"
            "ASA5516-FPWR-K9\tASA\t2\nL-ASA5516-TAMC=\tLic\t1\n",
            encoding="utf-16")
        report, has_findings = checker.run_check(path, RULES)
        self.assertTrue(has_findings)
        self.assertIn("ASA-001", report)

    def test_exit_code_2_on_bad_out_dir(self):
        """実行エラーは「指摘あり(1)」ではなく必ず2で終わること。"""
        rc = checker.main([os.path.join(SAMPLES, "bom_clean.csv"),
                           "--out", "/nonexistent_dir_xyz/report.md"])
        self.assertEqual(rc, 2)

    def test_exit_code_2_on_broken_rules(self):
        fd, bad = tempfile.mkstemp(suffix=".yaml")
        os.close(fd)
        self.addCleanup(os.remove, bad)
        with open(bad, "w", encoding="utf-8") as f:
            f.write("patterns:\n  foo: [unclosed\nrules: []\n")
        rc = checker.main([os.path.join(SAMPLES, "bom_clean.csv"),
                           "--rules", bad])
        self.assertEqual(rc, 2)

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

    def test_sku_pattern_matrix(self):
        """実在SKUに対するグループ判定の回帰テスト(検証レビューで発覚した誤判定の再発防止)。"""
        compiled, _ = checker.load_rules(RULES)

        def groups_of(part):
            part = part.upper()
            return {g for g, regs in compiled.items()
                    if any(r.search(part) for r in regs)}

        # WLC本体はスイッチと誤認しない
        for sku in ("C9800-40-K9", "C9800-80-K9", "C9800-L-F-K9", "C9800-CL-K9"):
            self.assertIn("wlc_models", groups_of(sku), sku)
            self.assertNotIn("switch_models", groups_of(sku), sku)
        # 現行世代スイッチ・シャーシを見逃さない
        for sku in ("C9300X-24Y-A", "C9500X-28C8D-A", "C9200CX-12P-2X2G",
                    "C9404R", "C9300-48P-E", "C9200L-24T-4G-E",
                    "WS-C2960X-48TS-L"):
            self.assertIn("switch_models", groups_of(sku), sku)
        # 部材・ライセンス・モジュールを本体として数えない
        for sku in ("ASA5506-PWR-AC=", "AIR-CT5508-RMNT", "AIR-AP-BRACKET-2=",
                    "C9300-NM-8X", "C9300-DNA-E-48-3Y", "C9800-AC-750W"):
            self.assertEqual(
                groups_of(sku) & {"ap_models", "wlc_models", "asa_hardware",
                                  "switch_models", "hardware_any"},
                set(), sku)
        # 本体・ライセンスの正マッチ
        self.assertIn("asa_hardware", groups_of("ASA5516-FPWR-K9"))
        self.assertIn("asa_hardware", groups_of("ASA5585-S10-K9"))
        self.assertIn("wlc_models", groups_of("AIR-CT3504-K9"))
        self.assertIn("wlc_ap_licenses", groups_of("AIR-DNA-A-3Y"))
        self.assertIn("wlc_ap_licenses", groups_of("LIC-CT3504-1A"))
        for sku in ("C9120AXI-Q", "C9130AXI-B", "CW9163E-MR", "AIR-AP1852I-B-K9"):
            self.assertIn("ap_models", groups_of(sku), sku)


if __name__ == "__main__":
    unittest.main()
