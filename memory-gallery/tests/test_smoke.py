"""スモークテスト（stdlib unittest のみ・ネットワーク/API/実名データ不使用）。

実行: cd memory-gallery && python3 -m unittest discover -s tests
"""
from __future__ import annotations

import unittest

from src import gate, skeleton
from src.chain import _parse_proposals
from src.models import Anchor, ChainProposal
from src.notion import _parse_anchor, _parse_card


def _proposal(anchors: list[str], chain: str, fact: str = "事実F") -> ChainProposal:
    return ChainProposal(fact=fact, anchors=anchors, chain=chain, rationale="根拠")


def _ledger() -> list[Anchor]:
    """ダミー台帳（実名・実エピソードは使わない）。"""
    return [
        Anchor(page_id="p1", name="アンカーA", kinds=["属性"], status="採用"),
        Anchor(page_id="p2", name="アンカーB", kinds=["感情"], status="採用"),
        Anchor(page_id="p3", name="アンカーD", kinds=["属性"], status="採用"),
        Anchor(page_id="p4", name="アンカーE", kinds=["感情"], status="採用"),
        Anchor(page_id="p5", name="使用済みC", kinds=["属性"], status="採用", used_by=["card-x"]),
        Anchor(page_id="p6", name="両属AB", kinds=["属性", "感情"], status="採用"),
    ]


def _ok_proposals() -> list[ChainProposal]:
    return [
        _proposal(["アンカーA", "アンカーB"], "アンカーA → アンカーB → 事実F"),
        _proposal(["アンカーD", "アンカーB"], "アンカーD → アンカーB → 事実F"),
        _proposal(["アンカーA", "アンカーE"], "アンカーA → アンカーE → 事実F"),
    ]


class TestSkeleton(unittest.TestCase):
    def test_deterministic(self):
        p = _proposal(["アンカーA"], "アンカーA → 連想 → 事実F")
        self.assertEqual(skeleton.to_mermaid(p), skeleton.to_mermaid(p))

    def test_structure_and_arrows(self):
        p = _proposal(["アンカーA"], "アンカーA → 連想 -> 事実F")
        mermaid = skeleton.to_mermaid(p)
        self.assertTrue(mermaid.startswith("flowchart LR"))
        self.assertIn('n0["アンカーA"]', mermaid)
        self.assertIn("n0 --> n1", mermaid)
        self.assertIn("n1 --> n2", mermaid)
        self.assertIn("style n2", mermaid)

    def test_double_quote_escaped(self):
        p = _proposal(["アンカーA"], 'アンカーA → "引用" → 事実F')
        self.assertNotIn('""', skeleton.to_mermaid(p).replace('["', "").replace('"]', ""))
        self.assertIn("'引用'", skeleton.to_mermaid(p))

    def test_empty_chain_survives(self):
        p = _proposal(["アンカーA"], "", fact="事実F")
        mermaid = skeleton.to_mermaid(p)
        self.assertIn("事実F", mermaid)


class TestGateStaticChecks(unittest.TestCase):
    def test_ok_case_returns_empty(self):
        self.assertEqual(gate.static_checks("事実F", _ok_proposals(), _ledger()), [])

    def test_unknown_anchor_rule1(self):
        proposals = _ok_proposals()
        proposals[0] = _proposal(["謎アンカー", "アンカーB"], "謎アンカー → アンカーB → 事実F")
        issues = gate.static_checks("事実F", proposals, _ledger())
        self.assertTrue(any("台帳にない" in i for i in issues))

    def test_used_anchor_rule3(self):
        proposals = _ok_proposals()
        proposals[0] = _proposal(["使用済みC", "アンカーB"], "使用済みC → アンカーB → 事実F")
        issues = gate.static_checks("事実F", proposals, _ledger())
        self.assertTrue(any("使い回し" in i for i in issues))

    def test_missing_emotion_rule4(self):
        proposals = _ok_proposals()
        proposals[0] = _proposal(["アンカーA", "アンカーD"], "アンカーA → アンカーD → 事実F")
        issues = gate.static_checks("事実F", proposals, _ledger())
        self.assertTrue(any("感情アンカー" in i for i in issues))

    def test_dual_kind_anchor_satisfies_rule4(self):
        proposals = _ok_proposals()
        proposals[0] = _proposal(["両属AB"], "両属AB → 事実F")
        self.assertEqual(gate.static_checks("事実F", proposals, _ledger()), [])

    def test_identical_anchor_sets_flagged(self):
        p = _proposal(["アンカーA", "アンカーB"], "アンカーA → アンカーB → 事実F")
        issues = gate.static_checks("事実F", [p, p, p], _ledger())
        self.assertTrue(any("同一" in i for i in issues))

    def test_wrong_count_flagged(self):
        issues = gate.static_checks("事実F", _ok_proposals()[:2], _ledger())
        self.assertTrue(any("3件ではありません" in i for i in issues))

    def test_anchor_missing_from_chain_text(self):
        proposals = _ok_proposals()
        proposals[0] = _proposal(["アンカーA", "アンカーB"], "何か → 事実F")
        issues = gate.static_checks("事実F", proposals, _ledger())
        self.assertTrue(any("文中に現れません" in i for i in issues))

    def test_anchor_short_form_accepted(self):
        # 台帳名「アンカーG（犬）」に対し、鎖では短縮形「アンカーG」でも一致とみなす
        ledger = _ledger() + [
            Anchor(page_id="p7", name="アンカーG（犬）", kinds=["属性", "感情"], status="採用")
        ]
        proposals = _ok_proposals()
        proposals[0] = _proposal(["アンカーG（犬）"], "アンカーG → 吠える → 事実F")
        self.assertEqual(gate.static_checks("事実F", proposals, ledger), [])


class TestGateVerifyFiltering(unittest.TestCase):
    """LLM照合の案別フィルタリング（llm_fact_check をモックしてネットワークなしで検証）。"""

    def _with_mock(self, mock_issues):
        original = gate.llm_fact_check
        gate.llm_fact_check = lambda fact, proposals: mock_issues
        try:
            return gate.verify("事実F", _ok_proposals(), _ledger(), has_images=False)
        finally:
            gate.llm_fact_check = original

    def test_clean_pass_keeps_all(self):
        result = self._with_mock([])
        self.assertTrue(result.ok)
        self.assertEqual(result.kept_indices, [0, 1, 2])
        self.assertFalse(result.needs_human)

    def test_bad_proposal_dropped_others_kept(self):
        result = self._with_mock([(2, "案2の技術的誤り")])
        self.assertTrue(result.ok)
        self.assertEqual(result.kept_indices, [0, 2])
        self.assertTrue(result.needs_human)  # 指摘があるので要目視

    def test_fact_level_issue_blocks_all(self):
        result = self._with_mock([(None, "覚えたい事実そのものが誤り")])
        self.assertFalse(result.ok)
        self.assertEqual(result.kept_indices, [])

    def test_all_proposals_bad_blocks_all(self):
        result = self._with_mock([(1, "誤り"), (2, "誤り"), (3, "誤り")])
        self.assertFalse(result.ok)
        self.assertEqual(result.kept_indices, [])


class TestChainParseProposals(unittest.TestCase):
    _JSON = (
        '{"proposals": ['
        '{"anchors": ["アンカーA"], "chain": "アンカーA → 事実F", "rationale": "r1"},'
        '{"anchors": ["アンカーB"], "chain": "アンカーB → 事実F", "rationale": "r2"},'
        '{"anchors": ["アンカーD"], "chain": "アンカーD → 事実F", "rationale": "r3"}'
        "]}"
    )

    def test_fenced_json(self):
        text = f"生成しました。\n```json\n{self._JSON}\n```\n以上です。"
        proposals = _parse_proposals(text, "事実F")
        self.assertEqual(len(proposals), 3)
        self.assertEqual(proposals[0].fact, "事実F")
        self.assertEqual(proposals[0].anchors, ["アンカーA"])

    def test_bare_json(self):
        proposals = _parse_proposals(self._JSON, "事実F")
        self.assertEqual(len(proposals), 3)

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            _parse_proposals("JSONはありません", "事実F")

    def test_too_few_raises(self):
        text = '{"proposals": [{"anchors": ["アンカーA"], "chain": "アンカーA → 事実F"}]}'
        with self.assertRaises(ValueError):
            _parse_proposals(text, "事実F")


class TestMindmap(unittest.TestCase):
    _MAP = {
        "center": "OSPF LSAタイプ一覧",
        "theme": "ルータ",
        "branches": [
            {"label": "タイプ1 (ルータリンク)", "emoji": "🔴",
             "children": [{"label": "生成: 全ルータ"}, {"label": "コード: O"}]},
            {"label": "タイプ5 (AS外部リンク)", "emoji": "🌍",
             "children": [{"label": "生成: ASBR"}]},
        ],
    }

    def test_mermaid_deterministic_and_sanitized(self):
        from src.mindmap import to_mermaid_mindmap
        first = to_mermaid_mindmap(self._MAP)
        self.assertEqual(first, to_mermaid_mindmap(self._MAP))
        self.assertTrue(first.startswith("mindmap"))
        self.assertIn("root((OSPF LSAタイプ一覧))", first)
        self.assertIn("タイプ1 （ルータリンク）", first)  # 半角括弧は全角へ
        self.assertIn("生成: 全ルータ", first)

    def test_image_prompt_contains_all_labels_verbatim(self):
        from src.render import build_image_prompt
        prompt = build_image_prompt(self._MAP)
        for text in ["OSPF LSAタイプ一覧", "タイプ1 (ルータリンク)", "生成: 全ルータ",
                     "コード: O", "タイプ5 (AS外部リンク)", "生成: ASBR"]:
            self.assertIn(text, prompt)
        self.assertIn("禁止", prompt)  # 事実の描き足し禁止が明記されている

    def test_summary_line_lists_branches(self):
        from src.mindmap import summary_line
        line = summary_line(self._MAP)
        self.assertIn("mindmap生成済み", line)
        self.assertIn("タイプ1", line)


class TestGraphLinks(unittest.TestCase):
    _MAP = {
        "center": "テーマX",
        "branches": [{"label": "枝A"}, {"label": "枝B"}],
    }

    def _ledger(self):
        return [
            Anchor(page_id="g1", name="番号キャラ", kinds=["属性"], status="採用",
                   used_by=["old-card"]),  # 属性は使用済みでも再利用可
            Anchor(page_id="g2", name="激痛の記憶", kinds=["感情"], status="採用",
                   used_by=["old-card"]),  # 感情は専有＝使用済みなら不可
            Anchor(page_id="g3", name="新しい怒り", kinds=["感情"], status="採用"),
            Anchor(page_id="g4", name="タロウ", kinds=["人物"], status="採用"),
            Anchor(page_id="g5", name="ポチ（柴）", kinds=["属性"], status="採用"),
        ]

    def _cards(self):
        from src.models import MemoryCard
        return [
            MemoryCard(page_id="c1", title="既習カードZ"),
            MemoryCard(page_id="c2", title="タロウ"),  # 個人語タイトルの既習カード
        ]

    def _check(self, links):
        from src.graph import static_check_links
        return static_check_links(links, self._MAP, self._ledger(), self._cards())

    def test_valid_attribute_reuse_allowed(self):
        valid, issues = self._check([
            {"node": "枝A", "anchor": "番号キャラ", "reason": "r", "visual": "図鑑風キャラ"},
        ])
        self.assertEqual(len(valid), 1)
        self.assertEqual(issues, [])

    def test_used_emotion_anchor_rejected(self):
        valid, issues = self._check([
            {"node": "枝A", "anchor": "激痛の記憶", "reason": "r", "visual": "転ぶ人"},
        ])
        self.assertEqual(valid, [])
        self.assertTrue(any("専有" in i for i in issues))

    def test_unused_emotion_anchor_allowed(self):
        valid, _ = self._check([
            {"node": "枝A", "anchor": "新しい怒り", "reason": "r", "visual": "怒りの炎"},
        ])
        self.assertEqual(len(valid), 1)

    def test_unknown_node_rejected(self):
        valid, issues = self._check([
            {"node": "存在しない枝", "anchor": "番号キャラ", "reason": "r", "visual": "x"},
        ])
        self.assertEqual(valid, [])
        self.assertTrue(any("存在しません" in i for i in issues))

    def test_personal_name_in_visual_rejected(self):
        valid, issues = self._check([
            {"node": "枝A", "anchor": "新しい怒り", "reason": "r",
             "visual": "タロウが怒っている絵"},
        ])
        self.assertEqual(valid, [])
        self.assertTrue(any("個人的な名前" in i for i in issues))

    def test_related_card_must_exist(self):
        valid, issues = self._check([
            {"node": "枝B", "related_card": "無いカード", "reason": "r", "visual": "道標"},
        ])
        self.assertEqual(valid, [])
        valid2, _ = self._check([
            {"node": "枝B", "related_card": "既習カードZ", "reason": "r", "visual": "道標"},
        ])
        self.assertEqual(len(valid2), 1)

    def test_image_prompt_includes_link_visuals(self):
        from src.render import build_image_prompt
        links = [{"node": "枝A", "anchor": "新しい怒り", "reason": "r",
                  "visual": "燃える炎の挿絵", "related_card": "既習カードZ"}]
        prompt = build_image_prompt(self._MAP, links)
        self.assertIn("燃える炎の挿絵", prompt)
        self.assertIn("関連: 既習カードZ", prompt)
        self.assertNotIn("新しい怒り", prompt)  # アンカー名は絵のプロンプトに出さない

    def test_attribute_pet_name_in_visual_rejected(self):
        # 属性アンカーの名前（ペット名等）も禁止語。visual に混入したら除外する
        valid, issues = self._check([
            {"node": "枝A", "anchor": "ポチ（柴）", "reason": "r",
             "visual": "ポチが走っている絵"},
        ])
        self.assertEqual(valid, [])
        self.assertTrue(any("個人的な名前" in i for i in issues))

    def test_personal_card_title_signpost_suppressed(self):
        # 個人語タイトルの既習カード: 結線は保持しつつ、絵の道標だけ抑止する
        from src.render import build_image_prompt
        valid, issues = self._check([
            {"node": "枝B", "related_card": "タロウ", "reason": "r", "visual": "道標"},
        ])
        self.assertEqual(len(valid), 1)
        self.assertTrue(valid[0].get("suppress_signpost"))
        self.assertTrue(any("道標抑止" in i for i in issues))
        prompt = build_image_prompt(self._MAP, valid)
        self.assertNotIn("タロウ", prompt)  # カード名（個人語）は画像プロンプトに出さない


class TestNotionParsers(unittest.TestCase):
    def test_parse_anchor_minimal(self):
        page = {
            "id": "page-anchor-1",
            "properties": {
                "アンカー": {"title": [{"plain_text": "アンカーA"}]},
                "種別": {"multi_select": [{"name": "属性"}, {"name": "感情"}]},
                "中身": {"rich_text": [{"plain_text": "中身X"}]},
                "感情": {"select": {"name": "報酬"}},
                "接続先": {"rich_text": [{"plain_text": "接続先Y"}]},
                "強度": {"select": {"name": "強"}},
                "状態": {"select": {"name": "採用"}},
                "使用済み項目": {"relation": [{"id": "card-1"}]},
            },
        }
        anchor = _parse_anchor(page)
        self.assertEqual(anchor.page_id, "page-anchor-1")
        self.assertEqual(anchor.name, "アンカーA")
        self.assertEqual(anchor.kinds, ["属性", "感情"])
        self.assertEqual(anchor.body, "中身X")
        self.assertEqual(anchor.emotion, "報酬")
        self.assertEqual(anchor.connection, "接続先Y")
        self.assertEqual(anchor.strength, "強")
        self.assertEqual(anchor.status, "採用")
        self.assertEqual(anchor.used_by, ["card-1"])

    def test_parse_anchor_missing_properties_defaults(self):
        anchor = _parse_anchor({"id": "page-anchor-2", "properties": {}})
        self.assertEqual(anchor.name, "")
        self.assertEqual(anchor.kinds, [])
        self.assertEqual(anchor.used_by, [])

    def test_parse_card_minimal(self):
        page = {
            "id": "page-card-1",
            "properties": {
                "項目": {"title": [{"plain_text": "項目X"}]},
                "分野": {"select": {"name": "分野Y"}},
                "戻り先": {"rich_text": [{"plain_text": "戻り先Z"}]},
                "状態": {"select": None},
                "コンボ前": {"number": 77},
            },
        }
        card = _parse_card(page)
        self.assertEqual(card.page_id, "page-card-1")
        self.assertEqual(card.title, "項目X")
        self.assertEqual(card.domain, "分野Y")
        self.assertEqual(card.return_to, "戻り先Z")
        self.assertEqual(card.state, "")
        self.assertEqual(card.combo_before, 77)
        self.assertEqual(card.images, [])

    def test_parse_card_missing_properties_defaults(self):
        card = _parse_card({"id": "page-card-2", "properties": {}})
        self.assertEqual(card.title, "")
        self.assertIsNone(card.combo_before)


class TestNotionWrites(unittest.TestCase):
    """_request をモックして、relation の追記マージと素材テキスト取得を検証する。"""

    def _client(self):
        from src.notion import NotionClient
        return NotionClient(token="dummy-token")

    def test_mark_anchors_used_merges_remote_and_updates_memory(self):
        from src.models import MemoryCard
        client = self._client()
        calls = []

        def fake_request(method, path, json_body=None, params=None, version=None):
            calls.append((method, path, json_body))
            if method == "GET":
                # Notion 上には（同一バッチの前カード分など）既存の使用記録がある
                return {"properties": {"使用済み項目": {"relation": [{"id": "card-old"}]}}}
            return {}

        client._request = fake_request
        anchor = Anchor(page_id="a1", name="感情A", kinds=["感情"], status="採用")
        card = MemoryCard(page_id="card-new", title="カードN")
        client.mark_anchors_used(["感情A"], card, [anchor])

        # in-memory 反映（同一実行内の専有チェックが効く）
        self.assertIn("card-new", anchor.used_by)
        self.assertIn("card-old", anchor.used_by)
        # PATCH は既存＋新規の和集合（既存を上書きしない）
        patch = next(c for c in calls if c[0] == "PATCH")
        ids = [r["id"] for r in patch[2]["properties"]["使用済み項目"]["relation"]]
        self.assertEqual(set(ids), {"card-old", "card-new"})

    def test_mark_anchors_used_skips_patch_when_already_recorded(self):
        from src.models import MemoryCard
        client = self._client()
        calls = []

        def fake_request(method, path, json_body=None, params=None, version=None):
            calls.append((method, path, json_body))
            return {"properties": {"使用済み項目": {"relation": [{"id": "card-new"}]}}}

        client._request = fake_request
        anchor = Anchor(page_id="a1", name="感情A", kinds=["感情"], status="採用")
        client.mark_anchors_used(["感情A"], MemoryCard(page_id="card-new", title="t"), [anchor])
        self.assertEqual([c[0] for c in calls], ["GET"])  # PATCH なし
        self.assertEqual(anchor.used_by, ["card-new"])

    def test_set_related_cards_unions_existing_relation(self):
        client = self._client()
        calls = []

        def fake_request(method, path, json_body=None, params=None, version=None):
            calls.append((method, path, json_body))
            if method == "GET":
                return {"properties": {"関連カード": {"relation": [{"id": "rel-old"}]}}}
            return {}

        client._request = fake_request
        client.set_related_cards("page-1", ["rel-new", "rel-old"])
        patch = next(c for c in calls if c[0] == "PATCH")
        ids = [r["id"] for r in patch[2]["properties"]["関連カード"]["relation"]]
        self.assertEqual(set(ids), {"rel-old", "rel-new"})  # 既存 rel-old を消さない

    def test_fetch_card_text_reads_paragraphs_and_tables(self):
        client = self._client()

        def fake_request(method, path, json_body=None, params=None, version=None):
            if path == "/blocks/page-1/children":
                return {"results": [
                    {"type": "paragraph",
                     "paragraph": {"rich_text": [{"plain_text": "本文の素材1"}]}},
                    {"type": "image", "image": {}},
                    {"id": "tbl-1", "type": "table", "table": {}},
                ], "has_more": False}
            if path == "/blocks/tbl-1/children":
                return {"results": [
                    {"type": "table_row", "table_row": {"cells": [
                        [{"plain_text": "タイプ1"}], [{"plain_text": "全ルータ"}],
                    ]}},
                ], "has_more": False}
            return {}

        client._request = fake_request
        text = client.fetch_card_text("page-1")
        self.assertIn("本文の素材1", text)
        self.assertIn("タイプ1 | 全ルータ", text)


if __name__ == "__main__":
    unittest.main()
