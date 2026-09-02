#!/usr/bin/env python3
"""J-Quants API V2 の疎通確認（単体で動く版）。

Docker を組む前に、これだけ先に流せます。必要なのは requests だけ。

    pip install requests
    set JQUANTS_API_KEY=<ダッシュボードで発行したキー>     # Windows
    export JQUANTS_API_KEY=<キー>                          # macOS / Linux
    python probe_standalone.py

確認するのは4点。

  1. エンドポイントのパス（推定のものは候補を順に試して当たりを探す）
  2. 実際の列名（config.yaml と突き合わせるための一覧を出す）
  3. DocType の実際の値（業績予想修正・配当予想修正・決算短信の区別）
  4. 上場廃止銘柄が過去データに残っているか   ← 最重要

4 は Free プラン（直近12週を除く2年分）でも判定できます。
結果を probe_result.txt に書き出すので、そのまま貼ってください。
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

# 公式サンプルで確定しているのは daily のみ。他は候補を順に試す。
CANDIDATES = {
    "daily":    ["/equities/bars/daily"],
    "master":   ["/equities/master", "/equities/list", "/listed/info"],
    "summary":  ["/fins/summary", "/fins/statements"],
    "calendar": ["/markets/calendar", "/markets/trading_calendar"],
    "topix":    ["/indices/daily-topix", "/indices/topix", "/indices/daily_topix",
                 "/indices/bars/daily", "/indices/bars/topix", "/indices/topix/daily",
                 "/idx/daily-topix", "/indices"],
}

#: 403 が返っても候補を試し続ける表。パスが違うのか権限が無いのかを切り分けるため。
KEEP_TRYING_ON_403 = {"topix"}

# 日付は区切りなしの YYYYMMDD、銘柄コードは5桁（公式サンプルに準拠）
PARAMS = {
    "daily":    {"date": "20250602"},
    "master":   {"date": "20250602"},
    "summary":  {"date": "20250515"},
    "calendar": {"from": "20250601", "to": "20250630"},
    "topix":    {"date": "20250602"},
}

# ネットワンシステムズ(7518)。SCSK による TOB を経て 2025-03-18 上場廃止。
# 最終売買日 2025-03-17 の日足が残っていれば、上場廃止銘柄は保持されている。
DELISTED_CODE = "75180"
DELISTED_LAST_DAY = "20250317"

out: list[str] = []


def say(line: str = "") -> None:
    print(line)
    out.append(line)


def get(path: str, params: dict) -> tuple[int, dict | str]:
    url = f"{BASE}{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "x-api-key": API_KEY,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")[:300]
        except Exception:
            body = ""
        return e.code, body
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"


def records(body) -> list[dict]:
    """レスポンス本体のリストを取り出す。キー名は種別ごとに違う。"""
    if not isinstance(body, dict):
        return []
    for key, value in body.items():
        if key == "pagination_key":
            continue
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
    return []


API_KEY = os.environ.get("JQUANTS_API_KEY", "").strip()
if not API_KEY:
    print("JQUANTS_API_KEY が設定されていません。")
    print("ダッシュボードの [API Keys] で発行したキーを環境変数に入れてください。")
    sys.exit(1)

say("=" * 60)
say("J-Quants API V2 疎通確認")
say("=" * 60)

found: dict[str, str] = {}

for table, paths in CANDIDATES.items():
    say()
    say(f"### {table}")
    hit = None
    for path in paths:
        code, body = get(path, PARAMS[table])
        if code == 200:
            hit = path
            say(f"  OK   {path}")
            break
        if code == 403:
            say(f"  403  {path}  （権限が無い、またはパスが違う）")
            if table not in KEEP_TRYING_ON_403:
                hit = "PLAN"
                break
            hit = "PLAN"
            time.sleep(0.3)
            continue
        if code == 404:
            say(f"  404  {path}  （このパスは存在しない）")
        else:
            say(f"  {code}  {path}  {str(body)[:120]}")
        time.sleep(0.3)

    if hit in (None, "PLAN"):
        if hit is None:
            say("  => 候補が全滅。API Documents でパスを確認してください。")
        continue

    found[table] = hit
    recs = records(body)
    if not recs:
        say(f"  レコードが空です。レスポンスのキー: {sorted(body.keys()) if isinstance(body, dict) else body}")
        continue

    say(f"  件数: {len(recs)}")
    say(f"  列名: {list(recs[0].keys())}")
    say("  先頭1件:")
    say("    " + json.dumps(recs[0], ensure_ascii=False)[:600])

    if table == "summary":
        doctypes = sorted({str(r.get("DocType")) for r in recs if r.get("DocType")})
        say(f"  このページに出た DocType: {doctypes}")
    if table == "daily":
        mc = recs[0].get("MktCap")
        say(f"  MktCap の値: {mc!r}  （空なら発行済株式数x終値で代替する）")
    time.sleep(0.3)

say()
say("=" * 60)
say("### 契約プランの反映確認")
say("=" * 60)
say("Free は直近12週を除く2年分、Light は過去5年分。")
say("古い日付が取れるかどうかで、契約が反映されているか分かる。")
say()
if "daily" in found:
    for label, day in (("3か月前  ", "20260601"),
                       ("1年前    ", "20250901"),
                       ("2年半前  ", "20240301"),
                       ("4年前    ", "20220901"),
                       ("5年ほど前", "20211001")):
        code, body = get(found["daily"], {"date": day})
        n = len(records(body)) if code == 200 else 0
        mark = "OK  " if n > 0 else "なし"
        say(f"  {label} {day}: HTTP {code}  {n:>5}件  {mark}")
        time.sleep(0.3)
    say()
    say("  4年前・5年前が0件なら、Light がまだ反映されていません。")
    say("  ダッシュボードの [Subscription] で Light になっているか確認してください。")
    say("  プラン変更後は [API Keys] でキーを再発行すると通ることがあります。")
else:
    say("  daily のパスが特定できず確認できませんでした。")

say()
say("=" * 60)
say("### 生存バイアスの確認（最重要）")
say("=" * 60)
if "daily" in found:
    code, body = get(found["daily"], {"code": DELISTED_CODE, "date": DELISTED_LAST_DAY})
    recs = records(body) if code == 200 else []
    say(f"  銘柄 {DELISTED_CODE}（ネットワンシステムズ / 2025-03-18 上場廃止）")
    say(f"  照会日 {DELISTED_LAST_DAY}（最終売買日）  HTTP {code}")
    if recs:
        say(f"  結果: データあり（{len(recs)}件）")
        say("    " + json.dumps(recs[0], ensure_ascii=False)[:400])
        say()
        say("  => 上場廃止銘柄が過去データに残っている。生存バイアスは回避できる。")
        say("     Light に進んでよい。")
    else:
        say("  結果: データなし")
        say()
        say("  => 上場廃止銘柄が拾えない可能性が高い。この場合、検証からは")
        say("     『ずっと上場していた銘柄』しか拾えず、結果は必ず甘く出る。")
        say("     Light を契約する前に方針を相談すること。")
        if code != 200:
            say(f"     （HTTP {code} なので、収録期間外や権限の可能性もある）")
else:
    say("  daily のパスが特定できなかったため確認できませんでした。")

say()
say("=" * 60)
say("### まとめ")
say("=" * 60)
for table in CANDIDATES:
    say(f"  {table:9s} -> {found.get(table, '未確定')}")

with open("probe_result.txt", "w", encoding="utf-8") as fh:
    fh.write("\n".join(out))
say()
say("probe_result.txt に書き出しました。これをそのまま貼ってください。")
