# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import miniyaml

RULES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rules.yaml")


class MiniYamlTest(unittest.TestCase):
    def test_rules_yaml_matches_pyyaml(self):
        """本番の rules.yaml がPyYAMLと同じ結果になること(最重要テスト)。"""
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML未導入のため比較スキップ")
        with open(RULES_PATH, encoding="utf-8-sig") as f:
            text = f.read()
        self.assertEqual(miniyaml.load(text), yaml.safe_load(text))

    def test_nested_map_and_lists(self):
        text = (
            "a:\n"
            "  b: 1\n"
            "  c:\n"
            "    - x\n"
            "    - y\n"
            "d: [p, q, 2]\n"
        )
        self.assertEqual(
            miniyaml.load(text),
            {"a": {"b": 1, "c": ["x", "y"]}, "d": ["p", "q", 2]})

    def test_list_of_maps(self):
        text = (
            "- id: A\n"
            "  vals:\n"
            "    - 1\n"
            "- id: B\n"
        )
        self.assertEqual(
            miniyaml.load(text),
            [{"id": "A", "vals": [1]}, {"id": "B"}])

    def test_comments_and_quotes(self):
        text = (
            "# 全行コメント\n"
            "a: \"値に # を含む\"  # 末尾コメント\n"
            "b: 'single'\n"
        )
        self.assertEqual(miniyaml.load(text), {"a": "値に # を含む", "b": "single"})

    def test_scalars(self):
        text = "i: 3\nf: 1.5\nt: true\nn: null\ns: hello world\nempty: []\n"
        self.assertEqual(
            miniyaml.load(text),
            {"i": 3, "f": 1.5, "t": True, "n": None, "s": "hello world",
             "empty": []})

    def test_tab_indent_error(self):
        with self.assertRaises(miniyaml.MiniYamlError):
            miniyaml.load("a:\n\tb: 1\n")

    def test_multiline_scalar_error(self):
        with self.assertRaises(miniyaml.MiniYamlError):
            miniyaml.load("a: |\n  x\n")

    def test_duplicate_key_error(self):
        with self.assertRaises(miniyaml.MiniYamlError):
            miniyaml.load("a: 1\na: 2\n")


if __name__ == "__main__":
    unittest.main()
