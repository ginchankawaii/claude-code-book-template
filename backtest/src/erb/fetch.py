"""J-Quants API V2 からのデータ取得。

V2 は API キー方式（x-api-key ヘッダ）。V1 のリフレッシュトークン方式は廃止。
エンドポイントのパスと列名は config.yaml に置き、`erb probe` で実データと
突き合わせてから本番を回す（推測したまま回さない）。
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any, Iterator

import pandas as pd
import requests

from .config import Config


class JQuantsClient:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.base = cfg["api"]["base_url"].rstrip("/")
        self.sleep = float(cfg["api"].get("rate_limit_sleep_sec", 0.2))
        self.session = requests.Session()
        self.session.headers.update({
            "x-api-key": cfg.api_key,
            "Accept": "application/json",
        })

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        url = f"{self.base}{path}"
        resp = self.session.get(url, params=params or {}, timeout=60)
        if resp.status_code == 401:
            raise RuntimeError("認証に失敗しました。JQUANTS_API_KEY を確認してください。")
        if resp.status_code == 403:
            raise RuntimeError(
                f"アクセスが拒否されました({path})。契約プランでこのデータが使えるか確認してください。"
            )
        resp.raise_for_status()
        return resp.json()

    def paginate(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict]:
        """pagination_key 方式のページ送り。"""
        p = dict(params or {})
        seen = 0
        while True:
            body = self.get(path, p)
            yield body
            key = body.get("pagination_key")
            if not key:
                return
            p["pagination_key"] = key
            seen += 1
            if seen > 10_000:
                raise RuntimeError(f"ページ送りが終わりません({path})。パラメータを確認してください。")
            time.sleep(self.sleep)

    def collect(self, path: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        """レスポンスの中でリストになっているキーを本体とみなして連結する。"""
        chunks: list[pd.DataFrame] = []
        for body in self.paginate(path, params):
            payload = _extract_records(body)
            if payload:
                chunks.append(pd.DataFrame(payload))
        if not chunks:
            return pd.DataFrame()
        return pd.concat(chunks, ignore_index=True)


def probe(cfg: Config, out_path: Path) -> str:
    """実データの1ページだけ取って、実際の列名と設定の食い違いを報告する。

    設計書の「実装前に確認する項目」をここで潰す。
    """
    client = JQuantsClient(cfg)
    lines = ["# probe: 実データと設定の突き合わせ\n"]
    endpoints = cfg["api"]["endpoints"]

    for table, path in endpoints.items():
        lines.append(f"## {table}  `{path}`\n")
        try:
            body = client.get(path, _probe_params(table))
        except Exception as exc:  # noqa: BLE001 - 何が起きたかそのまま出す
            lines.append(f"取得失敗: {type(exc).__name__}: {exc}\n")
            continue

        records = _extract_records(body)
        if not records:
            lines.append(f"レコードが空でした。レスポンスのキー: {sorted(body.keys())}\n")
            continue

        actual = list(records[0].keys())
        expected = cfg.rename_map(table) if table in cfg["columns"] else {}
        missing = [k for k in expected if k not in actual]
        extra = [k for k in actual if k not in expected]

        lines.append("```")
        lines.append(f"実データの列 ({len(actual)}): {actual}")
        if missing:
            lines.append(f"設定にあるが実データに無い: {missing}   <- config.yaml を直すこと")
        if extra:
            lines.append(f"実データにあるが設定に無い: {extra}")
        if not missing:
            lines.append("設定した列はすべて実データに存在します。")
        lines.append("```\n")

        lines.append("先頭1件:\n")
        lines.append("```json")
        lines.append(json.dumps(records[0], ensure_ascii=False, indent=1)[:2000])
        lines.append("```\n")

        if table == "summary":
            values = sorted({str(r.get("DocType")) for r in records if r.get("DocType")})
            lines.append(f"このページに現れた DocType: {values}\n")
        if table == "daily":
            has_mktcap = "MktCap" in actual and records[0].get("MktCap") not in (None, "")
            lines.append(f"MktCap に値が入っているか: {has_mktcap}"
                         "（入っていなければ (発行済株式数-自己株)x終値 で代替する）\n")
        time.sleep(client.sleep)

    lines.append(_delisting_check(client))

    lines.append("## 公式資料で確定済み\n")
    lines.append(
        "- ベースURL: https://api.jquants.com/v2\n"
        "- 認証: リクエストヘッダ x-api-key\n"
        "- 日足エンドポイント: /equities/bars/daily\n"
        "- 日付パラメータ: 区切りなしの YYYYMMDD（例 20230324）\n"
        "- 銘柄コード: 5桁（例 86970）\n"
    )

    lines.append("## 残りの確認項目（このプローブでは判定できない）\n")
    lines.append(
        "- 寄らずの日の始値が null か前日終値か: 出来高0の日を抽出して確認する。\n"
        "- AdjFactor の適用方向: 分割のあった銘柄で調整前後の系列を比較する。\n"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines)
    out_path.write_text(text, encoding="utf-8")
    return text


#: 日付パラメータの書式。J-Quants 公式のサンプルコードは
#: params={"code": "86970", "date": "20230324"} と、区切りなしの YYYYMMDD。
#: 銘柄コードも5桁（"86970"）で渡す。
DATE_FORMAT = "%Y%m%d"


def fmt_date(d: date | str) -> str:
    """API に渡す日付文字列。"""
    if isinstance(d, str):
        return d.replace("-", "")
    return d.strftime(DATE_FORMAT)


#: 生存バイアスの確認に使う銘柄。
#: ネットワンシステムズ(7518) は SCSK による TOB を経て 2025-03-18 に上場廃止。
#: 最終売買日は 2025-03-17。この銘柄の日足が残っていれば、上場廃止銘柄が
#: 過去データとして保持されていることの証拠になる。
DELISTED_PROBE_CODE = "75180"
DELISTED_PROBE_LAST_TRADING_DAY = "2025-03-17"


def _delisting_check(client: "JQuantsClient") -> str:
    """上場廃止銘柄が過去データに残っているかを確かめる。

    これは設計上いちばん重要な未確認事項。残っていなければ生存バイアスが
    不可避で、バックテストの結果は実際より良く出る。
    Free プランの収録期間（直近12週を除く2年分）にも 2025-03-17 は入るので、
    課金する前にこの1点だけは確かめられる。
    """
    lines = ["## 生存バイアスの確認（最重要）\n"]
    path = "/equities/bars/daily"
    try:
        body = client.get(path, {"code": DELISTED_PROBE_CODE,
                                 "date": fmt_date(DELISTED_PROBE_LAST_TRADING_DAY)})
        records = _extract_records(body)
    except Exception as exc:  # noqa: BLE001
        lines.append(f"確認できませんでした: {type(exc).__name__}: {exc}\n")
        return "\n".join(lines)

    lines.append("```")
    lines.append(f"銘柄: {DELISTED_PROBE_CODE}（ネットワンシステムズ / 2025-03-18 上場廃止）")
    lines.append(f"照会日: {DELISTED_PROBE_LAST_TRADING_DAY}（最終売買日）")
    if records:
        lines.append(f"結果: {len(records)} 件のデータあり")
        lines.append("")
        lines.append("=> 上場廃止銘柄が過去データとして残っている。生存バイアスは回避できる。")
    else:
        lines.append("結果: データなし")
        lines.append("")
        lines.append("=> 上場廃止銘柄が残っていない可能性が高い。")
        lines.append("   この場合、バックテストからは『5年間ずっと上場していた銘柄』しか")
        lines.append("   拾えず、結果は実際より良く出る（生存バイアス）。")
        lines.append("   別の日付でも再確認し、それでも空なら方針を見直すこと。")
    lines.append("```\n")
    return "\n".join(lines)


def _probe_params(table: str) -> dict[str, Any]:
    """1ページだけ取るための最小パラメータ。"""
    if table in {"daily", "topix", "master"}:
        return {"date": fmt_date("2025-06-02")}
    if table == "summary":
        return {"date": fmt_date("2025-05-15")}
    if table == "calendar":
        return {"from": fmt_date("2025-06-01"), "to": fmt_date("2025-06-30")}
    return {}


def _extract_records(body: dict) -> list[dict]:
    """レスポンス本体のリストを取り出す。キー名は種別ごとに違う。"""
    for key, value in body.items():
        if key == "pagination_key":
            continue
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
    return []
