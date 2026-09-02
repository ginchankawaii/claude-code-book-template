#!/usr/bin/env python3
"""TOPIX のエンドポイントを特定する。

前回の probe で候補8個すべてが 403 だった。ただし明らかに雑な "/indices" まで
403 を返しているので、**このAPIは存在しないパスにも 403 を返す**とみられる。
つまり 403 は「権限が無い」を意味していない可能性が高く、
パスかパラメータのどちらが違うのかを切り分ける必要がある。

そこで:
  1. エラー応答の本文をそのまま出す（メッセージで理由が分かることが多い）
  2. パス x パラメータ形状の総当たりを試す
     TOPIX は銘柄が1本なので、date ではなく from/to を要求する可能性がある

    docker compose run --rm probe python probe_topix.py
    または
    python probe_topix.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.jquants.com/v2"

PATHS = [
    "/indices/bars/daily-topix",     # /equities/bars/daily に倣った形。最有力
    "/indices/bars/topix/daily",
    "/indices/bars/daily",
    "/indices/bars/topix",
    "/indices/daily-topix",
    "/indices/topix",
    "/indices/topix/bars/daily",
    "/idx/bars/daily-topix",
]

PARAM_SHAPES = [
    ("date のみ",      {"date": "20250602"}),
    ("from/to",        {"from": "20250602", "to": "20250606"}),
    ("パラメータ無し",  {}),
    ("code=0000",      {"code": "0000", "date": "20250602"}),
]

out: list[str] = []


def say(line: str = "") -> None:
    print(line)
    out.append(line)


def call(path: str, params: dict) -> tuple[int, str]:
    url = f"{BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "x-api-key": API_KEY, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode("utf-8")
        except Exception:
            return e.code, ""
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"


API_KEY = os.environ.get("JQUANTS_API_KEY", "").strip()
if not API_KEY:
    print("JQUANTS_API_KEY が設定されていません。")
    sys.exit(1)

say("=" * 70)
say("TOPIX エンドポイントの特定")
say("=" * 70)
say()
say("まず、確実に存在するパスと存在しないパスのエラー本文を比べる。")
say("両者が同じ 403 なら、403 では権限とパス違いを区別できないと分かる。")
say()

for label, path, params in (
    ("実在するパス      ", "/equities/bars/daily", {"date": "20250602"}),
    ("でたらめなパス    ", "/this/does/not/exist", {"date": "20250602"}),
    ("実在パス・引数不正", "/equities/bars/daily", {"date": "not-a-date"}),
):
    code, body = call(path, params)
    say(f"  {label}  {path}")
    say(f"    HTTP {code}: {body[:300]}")
    say()
    time.sleep(0.3)

say("=" * 70)
say("パス x パラメータ の総当たり")
say("=" * 70)

hits = []
for path in PATHS:
    say()
    say(f"### {path}")
    for label, params in PARAM_SHAPES:
        code, body = call(path, params)
        snippet = body[:200].replace("\n", " ")
        say(f"  {code}  {label:14s}  {snippet}")
        if code == 200:
            hits.append((path, label, params, body))
        time.sleep(0.3)

say()
say("=" * 70)
say("結果")
say("=" * 70)
if hits:
    for path, label, params, body in hits:
        say(f"  当たり: {path}  ({label})")
        try:
            data = json.loads(body)
            for key, value in data.items():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    say(f"    列名: {list(value[0].keys())}")
                    say(f"    先頭1件: {json.dumps(value[0], ensure_ascii=False)[:300]}")
        except Exception:
            say(f"    本文: {body[:400]}")
else:
    say("  当たりなし。")
    say("  ダッシュボードの [API Documents] で指数データのページを開き、")
    say("  エンドポイント名の部分をスクリーンショットしてください。")

with open("probe_topix_result.txt", "w", encoding="utf-8") as fh:
    fh.write("\n".join(out))
say()
say("probe_topix_result.txt に書き出しました。")
