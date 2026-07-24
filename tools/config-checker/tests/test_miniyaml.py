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

    def test_plain_scalar_with_apostrophe_and_comment(self):
        """語中のアポストロフィを引用符と誤認してコメントを取り込まないこと。"""
        self.assertEqual(
            miniyaml.load("note: Bob's rule # comment"),
            {"note": "Bob's rule"})

    def test_flow_list_with_quoted_comma(self):
        self.assertEqual(
            miniyaml.load('tags: ["a,b", c]'), {"tags": ["a,b", "c"]})

    def test_document_markers(self):
        self.assertEqual(miniyaml.load("---\na: 1\n...\n"), {"a": 1})

    def test_yaml11_booleans(self):
        self.assertEqual(
            miniyaml.load("a: yes\nb: off\n"), {"a": True, "b": False})

    def test_unsupported_constructs_raise(self):
        """非対応構文は黙って誤解釈せず、明確なエラーになること。"""
        docs = (
            "m: {a: 1}",            # フローマップ
            "a: &x v",              # アンカー
            "a: *x",                # エイリアス
            's: "a\\nb"',           # エスケープシーケンス
            "l: [[1], 2]",          # ネストしたフロー形式
            "v: 'a' and 'b'",       # 引用符の後に余分な文字
            "d1: 1\n---\nd2: 2\n",  # 複数ドキュメント
        )
        for doc in docs:
            with self.assertRaises(miniyaml.MiniYamlError):
                miniyaml.load(doc)


if __name__ == "__main__":
    unittest.main()
