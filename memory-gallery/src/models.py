"""共通データモデルと定数。全モジュールはここの契約に従う（変更は全体合意が必要）。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# --- Notion ID（CLAUDE.md 2章が正） ---
PARENT_PAGE_ID = "3a3ba892-b37d-812d-829b-f32725be6fb1"   # 記憶ギャラリー（非共有）
CARDS_DB_ID = "4d62923f-dc2e-40ec-b0a9-143209b87fe7"      # 記憶カード
CARDS_DS_ID = "acc739a1-17a1-4c95-903b-25d155561b0b"
ANCHORS_DB_ID = "02b9bf24-889a-4f15-9314-3b2dda7466f6"    # アンカー台帳
ANCHORS_DS_ID = "3a7752e4-3d1c-4ced-8d81-68720b7e1a09"

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"
NOTION_RPS = 3  # レート制限 3 req/sec

STATE_AWAITING_COMMENT = "一言待ち"  # 連想鎖モード: 3案書き込み後。「自分の一言」は絶対に自動化しない
STATE_ACTIVE = "運用中"              # mindmapモード: 画像添付後（ギャラリー閲覧で運用）

MAX_IMAGES_PER_CARD = 3
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 1枚あたり上限
NOTION_RICH_TEXT_LIMIT = 2000      # rich_text 1要素の文字数上限


def anthropic_model() -> str:
    return os.environ.get("MEMORY_GALLERY_MODEL", "claude-opus-4-8")


@dataclass
class Anchor:
    """アンカー台帳の1行。台帳の正は Notion DB（実行時に読む。コードにハードコード禁止）。"""
    page_id: str
    name: str                                       # アンカー（title）
    kinds: list[str] = field(default_factory=list)  # 種別: 属性/人物/感情/数字
    body: str = ""                                  # 中身
    emotion: str = ""                               # 感情: 報酬/嫌悪/罪悪/痛み/屈辱
    connection: str = ""                            # 接続先
    strength: str = ""                              # 強度: 弱/中/強
    status: str = ""                                # 状態: 候補/採用
    used_by: list[str] = field(default_factory=list)  # 使用済み項目（記憶カードのURL/ID）


@dataclass
class CardImage:
    mime: str      # 例: image/png
    data_b64: str  # base64エンコード済みバイト列


@dataclass
class MemoryCard:
    """記憶カードの1行（連想鎖が空＝未処理のものを拾う）。"""
    page_id: str
    title: str                                       # 項目
    domain: str = ""                                 # 分野
    return_to: str = ""                              # 戻り先
    state: str = ""                                  # 状態
    combo_before: float | None = None                # コンボ前
    images: list[CardImage] = field(default_factory=list)


@dataclass
class ChainProposal:
    """連想鎖の1案。3案生成し、選択と「自分の一言」は人間が行う。"""
    fact: str                # 覚えたい事実（1〜2文の検証可能な断定）
    anchors: list[str]       # 使用アンカー名（台帳の title と完全一致であること）
    chain: str               # 連想鎖（「 → 」区切り、最後は fact に戻る）
    rationale: str = ""      # なぜこの鎖が fact に戻るか


@dataclass
class GateResult:
    """事実照合ゲートの結果。ok=False のカードには書き込まない（何も作らないほうがマシ）。

    ok=True でも誤りのある案は kept_indices から除外される（無傷の案だけ書き込む）。
    """
    ok: bool
    issues: list[str] = field(default_factory=list)
    needs_human: bool = True  # 画像入力時は常に True（入口の誤読はハルシネーション経路）
    kept_indices: list[int] = field(default_factory=list)  # 書き込んでよい案のインデックス
