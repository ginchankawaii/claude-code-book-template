"""Notion REST クライアント（素の REST API / requests）。

読み: アンカー台帳・記憶カード・ページ本文の画像添付。
書き: 連想鎖3案の書き戻し（状態=一言待ち）、アンカーの使用済み relation 追記。

注意:
- レート制限 3 req/sec（models.NOTION_RPS）を全リクエスト共通のスロットラーで守る。
- 429 は Retry-After を尊重して最大3回、5xx は指数バックオフで最大3回リトライ。
- 個人情報（アンカー名・エピソード等）はログ・例外メッセージに出さない。
"""
from __future__ import annotations

import base64
import os
import time

from .models import (
    ANCHORS_DB_ID,
    ANCHORS_DS_ID,
    Anchor,
    CARDS_DB_ID,
    CARDS_DS_ID,
    CardImage,
    ChainProposal,
    GateResult,
    MAX_IMAGE_BYTES,
    MAX_IMAGES_PER_CARD,
    MemoryCard,
    NOTION_API_BASE,
    NOTION_RICH_TEXT_LIMIT,
    NOTION_RPS,
    NOTION_VERSION,
    STATE_AWAITING_COMMENT,
)

_MAX_RETRIES = 3            # 429/5xx それぞれの最大リトライ回数
_BLOCK_APPEND_CHUNK = 100   # blocks children 追記の1リクエスト上限
_ANCHOR_STATUS_ADOPTED = "採用"


class NotionAPIError(RuntimeError):
    """Notion API がエラー status を返したとき。個人情報は含めない（APIのエラーメッセージのみ）。"""

    def __init__(self, status: int, path: str, code: str = "", message: str = ""):
        self.status = status
        self.path = path
        self.code = code
        self.message = message
        detail = f" | {message}" if message else ""
        super().__init__(f"Notion API error {status} ({code or 'unknown'}) at {path}{detail}")


# ---------------------------------------------------------------------------
# 純関数（テスト用に公開）
# ---------------------------------------------------------------------------

def _plain_text(rich_text: list | None) -> str:
    """rich_text 配列を plain_text 連結で1本の文字列にする。"""
    if not rich_text:
        return ""
    parts = []
    for item in rich_text:
        if isinstance(item, dict):
            parts.append(item.get("plain_text") or item.get("text", {}).get("content", "") or "")
    return "".join(parts)


def _prop(page_json: dict, name: str) -> dict:
    return (page_json.get("properties") or {}).get(name) or {}


def _parse_anchor(page_json: dict) -> Anchor:
    """アンカー台帳のページ JSON → Anchor。プロパティ欠落に強いこと。"""
    title = _plain_text(_prop(page_json, "アンカー").get("title"))
    kinds = [
        t.get("name", "")
        for t in (_prop(page_json, "種別").get("multi_select") or [])
        if isinstance(t, dict)
    ]
    body = _plain_text(_prop(page_json, "中身").get("rich_text"))
    emotion = (_prop(page_json, "感情").get("select") or {}).get("name", "") or ""
    connection = _plain_text(_prop(page_json, "接続先").get("rich_text"))
    strength = (_prop(page_json, "強度").get("select") or {}).get("name", "") or ""
    status = (_prop(page_json, "状態").get("select") or {}).get("name", "") or ""
    used_by = [
        r.get("id", "")
        for r in (_prop(page_json, "使用済み項目").get("relation") or [])
        if isinstance(r, dict) and r.get("id")
    ]
    return Anchor(
        page_id=page_json.get("id", ""),
        name=title,
        kinds=kinds,
        body=body,
        emotion=emotion,
        connection=connection,
        strength=strength,
        status=status,
        used_by=used_by,
    )


def _parse_card(page_json: dict) -> MemoryCard:
    """記憶カードのページ JSON → MemoryCard。プロパティ欠落に強いこと。"""
    title = _plain_text(_prop(page_json, "項目").get("title"))
    domain = (_prop(page_json, "分野").get("select") or {}).get("name", "") or ""
    return_to = _plain_text(_prop(page_json, "戻り先").get("rich_text"))
    state = (_prop(page_json, "状態").get("select") or {}).get("name", "") or ""
    combo_before = _prop(page_json, "コンボ前").get("number")
    return MemoryCard(
        page_id=page_json.get("id", ""),
        title=title,
        domain=domain,
        return_to=return_to,
        state=state,
        combo_before=combo_before,
    )


def _split_text(text: str, limit: int = NOTION_RICH_TEXT_LIMIT) -> list[str]:
    """文字列を limit 文字ごとに分割（空文字は1要素の空リスト扱いにしない）。"""
    if not text:
        return []
    return [text[i : i + limit] for i in range(0, len(text), limit)]


def _rich_text(text: str) -> list[dict]:
    """rich_text 配列を NOTION_RICH_TEXT_LIMIT ごとに分割して組み立てる。"""
    return [{"type": "text", "text": {"content": chunk}} for chunk in _split_text(text)]


def _card_chain_is_empty(page_json: dict) -> bool:
    """クライアント側フォールバック用: 「連想鎖」プロパティが空か。"""
    return _plain_text(_prop(page_json, "連想鎖").get("rich_text")).strip() == ""


# ---------------------------------------------------------------------------
# クライアント
# ---------------------------------------------------------------------------

class NotionClient:
    """Notion REST API クライアント。トークンは引数 or 環境変数 NOTION_TOKEN。"""

    def __init__(self, token: str | None = None):
        token = token or os.environ.get("NOTION_TOKEN")
        if not token:
            raise RuntimeError(
                "NOTION_TOKEN が設定されていません。"
                "環境変数 NOTION_TOKEN を設定するか NotionClient(token=...) で渡してください。"
            )
        self._token = token
        self._min_interval = 1.0 / max(NOTION_RPS, 1)
        self._next_allowed = 0.0  # time.monotonic ベース

    # -- 低レベル ---------------------------------------------------------

    def _throttle(self) -> None:
        now = time.monotonic()
        if now < self._next_allowed:
            time.sleep(self._next_allowed - now)
            now = time.monotonic()
        self._next_allowed = now + self._min_interval

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, json_body: dict | None = None,
                 params: dict | None = None) -> dict:
        """Notion API へ1リクエスト。スロットル＋429/5xx リトライ込み。"""
        import requests  # 遅延 import（依存未導入環境への防御）

        url = f"{NOTION_API_BASE}{path}"
        attempts_429 = 0
        attempts_5xx = 0
        while True:
            self._throttle()
            resp = requests.request(
                method, url, headers=self._headers(), json=json_body,
                params=params, timeout=60,
            )
            if resp.status_code == 429:
                attempts_429 += 1
                if attempts_429 > _MAX_RETRIES:
                    raise NotionAPIError(429, path, "rate_limited")
                try:
                    wait = float(resp.headers.get("Retry-After", "1"))
                except (TypeError, ValueError):
                    wait = 1.0
                time.sleep(max(wait, 0.5))
                continue
            if 500 <= resp.status_code < 600:
                attempts_5xx += 1
                if attempts_5xx > _MAX_RETRIES:
                    raise NotionAPIError(resp.status_code, path, "server_error")
                time.sleep(2 ** (attempts_5xx - 1))  # 1s, 2s, 4s
                continue
            if resp.status_code >= 400:
                code = ""
                message = ""
                try:
                    payload = resp.json() or {}
                    code = payload.get("code", "")
                    message = str(payload.get("message", ""))[:300]
                except ValueError:
                    pass
                raise NotionAPIError(resp.status_code, path, code, message)
            try:
                return resp.json()
            except ValueError:
                return {}

    def _query_all(self, ds_id: str, db_id: str, filter_: dict | None = None) -> list[dict]:
        """DBクエリ。data_sources を優先し、404/400 なら databases にフォールバック。
        has_more/next_cursor のページネーションで全件返す。"""
        paths = [f"/data_sources/{ds_id}/query", f"/databases/{db_id}/query"]
        errors: list[NotionAPIError] = []
        for i, path in enumerate(paths):
            results: list[dict] = []
            cursor: str | None = None
            try:
                while True:
                    body: dict = {"page_size": 100}
                    if filter_:
                        body["filter"] = filter_
                    if cursor:
                        body["start_cursor"] = cursor
                    data = self._request("POST", path, json_body=body)
                    results.extend(data.get("results") or [])
                    if not data.get("has_more"):
                        return results
                    cursor = data.get("next_cursor")
                    if not cursor:
                        return results
            except NotionAPIError as e:
                errors.append(e)
                # APIバージョン差異への防御: 404/400 のときのみ次のエンドポイントへ
                if e.status in (400, 404) and i + 1 < len(paths):
                    continue
                raise
        # 両エンドポイントとも失敗。根本原因は最初（data_sources）のエラーの方。
        primary = errors[0] if errors else NotionAPIError(0, paths[0], "unreachable")
        hint = ""
        if any(e.code == "object_not_found" for e in errors):
            hint = (
                "\n→ ヒント: 統合トークンは接続を付与したページしか見えません。"
                "Notion で対象ページ（記憶ギャラリー）を開き、⋯ → 接続 → 作成したコネクトを追加してください。"
            )
        elif any(e.code in ("unauthorized", "restricted_resource") for e in errors):
            hint = "\n→ ヒント: NOTION_TOKEN の値が正しいか確認してください（コピーミス・再生成後の旧トークン等）。"
        details = " / ".join(str(e) for e in errors)
        raise NotionAPIError(
            primary.status, primary.path, primary.code, f"{details}{hint}"
        )

    # -- 読み -------------------------------------------------------------

    def fetch_anchors(self) -> list[Anchor]:
        """アンカー台帳DBを全件取得し、状態=採用のアンカーだけ返す。"""
        pages = self._query_all(ANCHORS_DS_ID, ANCHORS_DB_ID)
        anchors = [_parse_anchor(p) for p in pages]
        return [a for a in anchors if a.status == _ANCHOR_STATUS_ADOPTED]

    def fetch_pending_cards(self) -> list[MemoryCard]:
        """記憶カードDBから「連想鎖」が空の未処理カードを取得する。"""
        filter_ = {"property": "連想鎖", "rich_text": {"is_empty": True}}
        try:
            pages = self._query_all(CARDS_DS_ID, CARDS_DB_ID, filter_=filter_)
        except NotionAPIError:
            # フィルタがAPIエラーになる環境への防御: 全件取得してクライアント側で絞る
            pages = self._query_all(CARDS_DS_ID, CARDS_DB_ID)
            pages = [p for p in pages if _card_chain_is_empty(p)]
        return [_parse_card(p) for p in pages]

    def fetch_card(self, page_id: str) -> MemoryCard:
        """記憶カードを page_id で単体取得する。"""
        data = self._request("GET", f"/pages/{page_id}")
        return _parse_card(data)

    def fetch_card_images(self, page_id: str) -> list[CardImage]:
        """カード本文の image ブロックをダウンロードし base64 で返す（上限あり）。"""
        import requests  # 遅延 import

        images: list[CardImage] = []
        cursor: str | None = None
        while len(images) < MAX_IMAGES_PER_CARD:
            params: dict = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            data = self._request("GET", f"/blocks/{page_id}/children", params=params)
            for block in data.get("results") or []:
                if len(images) >= MAX_IMAGES_PER_CARD:
                    break
                if block.get("type") != "image":
                    continue
                image = block.get("image") or {}
                url = (image.get("file") or {}).get("url") or (image.get("external") or {}).get("url")
                if not url:
                    continue
                try:
                    resp = requests.get(url, timeout=60)
                except requests.RequestException:
                    continue  # 1枚の失敗で全体を落とさない
                if resp.status_code != 200:
                    continue
                content = resp.content
                if not content or len(content) > MAX_IMAGE_BYTES:
                    continue  # サイズ上限超過はスキップ
                content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
                mime = content_type if content_type.startswith("image/") else "image/png"
                images.append(CardImage(mime=mime, data_b64=base64.b64encode(content).decode("ascii")))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            if not cursor:
                break
        return images

    # -- 書き -------------------------------------------------------------

    def write_result(self, card: MemoryCard, fact: str, proposals: list[ChainProposal],
                     mermaids: list[str], gate: GateResult) -> None:
        """カードへ3案を書き戻す（プロパティ更新＋本文追記。状態=一言待ち）。"""
        if not proposals:
            raise ValueError("proposals が空です（書き込むものがありません）")

        first = proposals[0]
        properties = {
            "アンカー": {"rich_text": _rich_text(" / ".join(first.anchors))},
            "連想鎖": {"rich_text": _rich_text(first.chain[:NOTION_RICH_TEXT_LIMIT])},
            "状態": {"select": {"name": STATE_AWAITING_COMMENT}},
        }
        self._request("PATCH", f"/pages/{card.page_id}", json_body={"properties": properties})

        blocks: list[dict] = [
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": _rich_text("連想鎖 3案（自分の一言を書いたら状態を運用中に）")
                },
            },
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": _rich_text(
                        f"覚えたい事実: {fact}"
                        + ("\n⚠️ 事実は要目視確認" if gate.needs_human else "")
                    ),
                    "icon": {"type": "emoji", "emoji": "📌"},
                },
            },
        ]
        for i, proposal in enumerate(proposals):
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": _rich_text(f"案{i + 1}")},
            })
            body_text = proposal.chain
            if proposal.rationale:
                body_text += f"\n{proposal.rationale}"
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": _rich_text(body_text)},
            })
            if i < len(mermaids) and mermaids[i]:
                blocks.append({
                    "object": "block",
                    "type": "code",
                    "code": {
                        "language": "mermaid",
                        "rich_text": _rich_text(mermaids[i]),
                    },
                })
        for issue in gate.issues:
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": _rich_text(issue)},
            })

        for start in range(0, len(blocks), _BLOCK_APPEND_CHUNK):
            self._request(
                "PATCH",
                f"/blocks/{card.page_id}/children",
                json_body={"children": blocks[start : start + _BLOCK_APPEND_CHUNK]},
            )

    def mark_anchors_used(self, anchor_names: list[str], card: MemoryCard,
                          anchors: list[Anchor]) -> None:
        """使用アンカーの「使用済み項目」relation にカードページを追記する（既存は保持）。"""
        by_name = {a.name: a for a in anchors}
        for name in anchor_names:
            anchor = by_name.get(name)
            if anchor is None or not anchor.page_id:
                continue  # 台帳にない名前は黙ってスキップ（ゲート側で検出済みの想定）
            existing = [pid for pid in anchor.used_by if pid]
            if card.page_id in existing:
                continue
            relation = [{"id": pid} for pid in existing] + [{"id": card.page_id}]
            self._request(
                "PATCH",
                f"/pages/{anchor.page_id}",
                json_body={"properties": {"使用済み項目": {"relation": relation}}},
            )
