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

# fetch_card_text が素材として拾う rich_text 持ちブロック種別
_TEXT_BLOCK_TYPES = (
    "paragraph", "heading_1", "heading_2", "heading_3",
    "bulleted_list_item", "numbered_list_item", "quote", "callout",
    "toggle", "code",
)


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
        # APIバージョンは env で上書き可。クエリ成功時に「通ったバージョン」を自動採用する。
        self._version = os.environ.get("NOTION_VERSION") or NOTION_VERSION
        self._min_interval = 1.0 / max(NOTION_RPS, 1)
        self._next_allowed = 0.0  # time.monotonic ベース

    # -- 低レベル ---------------------------------------------------------

    def _throttle(self) -> None:
        now = time.monotonic()
        if now < self._next_allowed:
            time.sleep(self._next_allowed - now)
            now = time.monotonic()
        self._next_allowed = now + self._min_interval

    def _headers(self, version: str | None = None) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": version or self._version,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, json_body: dict | None = None,
                 params: dict | None = None, version: str | None = None) -> dict:
        """Notion API へ1リクエスト。スロットル＋429/5xx リトライ込み。"""
        import requests  # 遅延 import（依存未導入環境への防御）

        url = f"{NOTION_API_BASE}{path}"
        attempts_429 = 0
        attempts_5xx = 0
        while True:
            self._throttle()
            resp = requests.request(
                method, url, headers=self._headers(version), json=json_body,
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
        # APIバージョン×エンドポイントの候補を順に試し、通った組を self._version に採用する。
        # 2025-09-03 以降: /data_sources/{id}/query ／ それ以前: /databases/{id}/query
        ds_path = f"/data_sources/{ds_id}/query"
        db_path = f"/databases/{db_id}/query"
        attempts: list[tuple[str, str]] = []
        for version in (self._version, "2025-09-03"):
            if (version, ds_path) not in attempts:
                attempts.append((version, ds_path))
        for version in (self._version, "2022-06-28"):
            if (version, db_path) not in attempts:
                attempts.append((version, db_path))

        errors: list[tuple[str, NotionAPIError]] = []
        for version, path in attempts:
            results: list[dict] = []
            cursor: str | None = None
            try:
                while True:
                    body: dict = {"page_size": 100}
                    if filter_:
                        body["filter"] = filter_
                    if cursor:
                        body["start_cursor"] = cursor
                    data = self._request("POST", path, json_body=body, version=version)
                    self._version = version  # 通ったバージョンを以後の全リクエストで使う
                    results.extend(data.get("results") or [])
                    if not data.get("has_more"):
                        return results
                    cursor = data.get("next_cursor")
                    if not cursor:
                        return results
            except NotionAPIError as e:
                errors.append((version, e))
                # 400/404 は次の候補へ。最後の候補でも raise せず、下の統合エラーに到達させる。
                if e.status in (400, 404):
                    continue
                raise
        # 全候補が失敗。根本原因（最初のエラー）を先頭に、全試行を並べて報告する。
        primary = errors[0][1] if errors else NotionAPIError(0, ds_path, "unreachable")
        codes = {e.code for _, e in errors}
        hint = ""
        if "object_not_found" in codes:
            hint = (
                "\n→ ヒント: 統合トークンは接続を付与したページしか見えません。"
                "Notion で対象ページ（記憶ギャラリー）を開き、⋯ → 接続 → 作成したコネクトを追加してください。"
            )
        elif codes & {"unauthorized", "restricted_resource"}:
            hint = "\n→ ヒント: NOTION_TOKEN の値が正しいか確認してください（コピーミス・再生成後の旧トークン等）。"
        elif codes == {"invalid_request_url"}:
            hint = (
                "\n→ ヒント: どのAPIバージョンでもエンドポイントが見つかりません。"
                " .env に NOTION_VERSION=2025-09-03 を追加して再実行してみてください。"
            )
        details = " / ".join(f"[{v}] {e}" for v, e in errors)
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

    def fetch_all_cards(self) -> list[MemoryCard]:
        """記憶カードDBの全カード（処理済み含む）を取得する。結線エンジンの既習カード一覧用。"""
        pages = self._query_all(CARDS_DS_ID, CARDS_DB_ID)
        return [_parse_card(p) for p in pages]

    def set_related_cards(self, page_id: str, related_page_ids: list[str]) -> None:
        """「関連カード」relation に追記する（ナレッジグラフの網）。

        全置換ではなく既存 relation との和集合で PATCH する（mark_anchors_used と同じ方針）。
        再処理（--card 指定・失敗後の再実行）や本人が手で足したリンクを消さないため。
        """
        if not related_page_ids:
            return
        existing: list[str] = []
        try:
            page = self._request("GET", f"/pages/{page_id}")
            existing = [
                r.get("id", "")
                for r in (_prop(page, "関連カード").get("relation") or [])
                if isinstance(r, dict) and r.get("id")
            ]
        except NotionAPIError:
            pass  # 取得失敗時は追記分のみで続行（消すよりマシだが、原則ここには来ない）
        merged = list(dict.fromkeys(existing + [pid for pid in related_page_ids if pid]))
        if set(merged) == set(existing):
            return  # 追加分なし
        self._request("PATCH", f"/pages/{page_id}", json_body={
            "properties": {"関連カード": {
                "relation": [{"id": pid} for pid in merged],
            }},
        })

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

    def fetch_card_text(self, page_id: str) -> str:
        """カード本文のテキスト系ブロック（段落・見出し・リスト・表・コード等）を素材テキストとして返す。

        v2 の「素材＝テキスト」の入口。build_mindmap / verify_mindmap には
        ここで取得した同一の素材を渡すこと（画像は fetch_card_images が担う）。
        """
        lines: list[str] = []
        cursor: str | None = None
        while True:
            params: dict = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            data = self._request("GET", f"/blocks/{page_id}/children", params=params)
            for block in data.get("results") or []:
                btype = block.get("type")
                if btype in _TEXT_BLOCK_TYPES:
                    text = _plain_text((block.get(btype) or {}).get("rich_text"))
                    if text.strip():
                        lines.append(text)
                elif btype == "table":
                    try:
                        lines.extend(self._fetch_table_rows(block.get("id", "")))
                    except NotionAPIError:
                        continue  # 1つの表の失敗で全体を落とさない
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            if not cursor:
                break
        return "\n".join(lines)

    def _fetch_table_rows(self, table_block_id: str) -> list[str]:
        """table ブロックの子（table_row）を「セル | セル | …」の行テキストにして返す。"""
        if not table_block_id:
            return []
        rows: list[str] = []
        cursor: str | None = None
        while True:
            params: dict = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            data = self._request(
                "GET", f"/blocks/{table_block_id}/children", params=params
            )
            for row in data.get("results") or []:
                if row.get("type") != "table_row":
                    continue
                cells = (row.get("table_row") or {}).get("cells") or []
                rows.append(" | ".join(_plain_text(c) for c in cells))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            if not cursor:
                break
        return rows

    # -- 書き -------------------------------------------------------------

    def create_anchor(self, name: str, kinds: list[str], body: str,
                      emotion: str, connection: str, status: str = "採用") -> str:
        """アンカー台帳に1行追加し、作成ページの id を返す（v3.1 インタビュー用）。

        parent は data_source_id（2025-09-03 以降）→ database_id（旧）の順で
        フォールバックする（_query_all のバージョンラダーと同じ方針）。
        感情 select は台帳の既存選択肢（報酬/嫌悪/罪悪/痛み/屈辱）だけを渡すこと
        （interview._parse_interview_anchor が検証済み。未知の値は新選択肢を作ってしまう）。
        """
        properties: dict = {
            "アンカー": {"title": _rich_text(name)},
            "種別": {"multi_select": [{"name": k} for k in kinds if k]},
            "中身": {"rich_text": _rich_text(body)},
            "接続先": {"rich_text": _rich_text(connection)},
            "状態": {"select": {"name": status}},
        }
        if emotion:
            properties["感情"] = {"select": {"name": emotion}}
        parents = [
            {"type": "data_source_id", "data_source_id": ANCHORS_DS_ID},
            {"type": "database_id", "database_id": ANCHORS_DB_ID},
        ]
        last: NotionAPIError | None = None
        for parent in parents:
            try:
                data = self._request(
                    "POST", "/pages",
                    json_body={"parent": parent, "properties": properties},
                )
                page_id = data.get("id", "")
                if not page_id:
                    raise NotionAPIError(0, "/pages", "no_id", "作成ページの id が返りません")
                return page_id
            except NotionAPIError as e:
                last = e
                if e.status in (400, 404):
                    continue
                raise
        raise last if last else NotionAPIError(0, "/pages", "unreachable")

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
                    "rich_text": _rich_text(
                        f"連想鎖 {len(proposals)}案（自分の一言を書いたら状態を運用中に）"
                    )
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

    def upload_file(self, filename: str, content: bytes,
                    content_type: str = "image/png") -> str:
        """File Upload API で画像等をアップロードし file_upload id を返す（20MB single_part）。"""
        import requests  # 遅延 import

        meta = self._request(
            "POST", "/file_uploads",
            json_body={"mode": "single_part", "filename": filename,
                       "content_type": content_type},
        )
        upload_id = meta.get("id")
        if not upload_id:
            raise NotionAPIError(0, "/file_uploads", "no_id", "file_upload id が返りません")
        upload_url = meta.get("upload_url") or f"{NOTION_API_BASE}/file_uploads/{upload_id}/send"
        self._throttle()
        resp = requests.post(
            upload_url,
            headers={"Authorization": f"Bearer {self._token}",
                     "Notion-Version": self._version},
            files={"file": (filename, content, content_type)},
            timeout=120,
        )
        if resp.status_code >= 400:
            raise NotionAPIError(resp.status_code, "/file_uploads/send", "upload_failed",
                                 resp.text[:300])
        return upload_id

    def set_cover(self, page_id: str, file_upload_id: str) -> None:
        """アップロード済みファイルをページカバーに設定する（ギャラリービュー用）。"""
        self._request("PATCH", f"/pages/{page_id}", json_body={
            "cover": {"type": "file_upload", "file_upload": {"id": file_upload_id}},
        })

    def append_image(self, page_id: str, file_upload_id: str, caption: str = "") -> None:
        """アップロード済みファイルを本文に画像ブロックとして追記する。"""
        image: dict = {"type": "file_upload", "file_upload": {"id": file_upload_id}}
        if caption:
            image["caption"] = _rich_text(caption)
        self._request("PATCH", f"/blocks/{page_id}/children", json_body={
            "children": [{"object": "block", "type": "image", "image": image}],
        })

    def write_mindmap_result(self, card: MemoryCard, mermaid: str, summary: str,
                             issues: list[str], state: str) -> None:
        """v2: 処理済みマーカーと Mermaid（検証用の正）を書き戻す。"""
        properties = {
            "連想鎖": {"rich_text": _rich_text(summary[:NOTION_RICH_TEXT_LIMIT])},
            "状態": {"select": {"name": state}},
        }
        self._request("PATCH", f"/pages/{card.page_id}", json_body={"properties": properties})
        blocks: list[dict] = [
            {"object": "block", "type": "heading_2",
             "heading_2": {"rich_text": _rich_text("マインドマップ（検証用の正）")}},
            {"object": "block", "type": "code",
             "code": {"language": "mermaid", "rich_text": _rich_text(mermaid)}},
        ]
        for issue in issues:
            blocks.append({"object": "block", "type": "bulleted_list_item",
                           "bulleted_list_item": {"rich_text": _rich_text(issue)}})
        self._request("PATCH", f"/blocks/{card.page_id}/children",
                      json_body={"children": blocks})

    def mark_anchors_used(self, anchor_names: list[str], card: MemoryCard,
                          anchors: list[Anchor]) -> None:
        """使用アンカーの「使用済み項目」relation にカードページを追記する（既存は保持）。

        stale 対策（バッチ内で複数カードを処理するケース）:
        - PATCH 直前に該当アンカーページを GET し、Notion 上の最新 relation とマージする
          （起動時スナップショットで relation を丸ごと置換すると他カードの使用記録が消えるため）。
        - 書き込み後は in-memory の anchor.used_by にも反映する。これで同一実行内の後続カードでも
          感情アンカーの1項目専有チェック（propose_links / static_check_links / gate.static_checks /
          chain._candidate_anchors）が正しく効く（ルール#3）。
        """
        by_name = {a.name: a for a in anchors}
        for name in anchor_names:
            anchor = by_name.get(name)
            if anchor is None or not anchor.page_id:
                continue  # 台帳にない名前は黙ってスキップ（ゲート側で検出済みの想定）
            current = [pid for pid in anchor.used_by if pid]
            try:
                page = self._request("GET", f"/pages/{anchor.page_id}")
                remote = [
                    r.get("id", "")
                    for r in (_prop(page, "使用済み項目").get("relation") or [])
                    if isinstance(r, dict) and r.get("id")
                ]
                current = list(dict.fromkeys(remote + current))
            except NotionAPIError:
                pass  # 取得失敗時は手元のスナップショット＋実行中の追記分で続行
            if card.page_id not in current:
                merged = current + [card.page_id]
                self._request(
                    "PATCH",
                    f"/pages/{anchor.page_id}",
                    json_body={"properties": {"使用済み項目": {
                        "relation": [{"id": pid} for pid in merged],
                    }}},
                )
                current = merged
            anchor.used_by = current  # in-memory 反映（同一バッチ内の専有チェック用）
