#!/usr/bin/env python3
"""レースデータの取得層。標準ライブラリのみ。

設計上の最重要方針は「黙って間違えないこと」。
スクレイピングは相手のHTML構造の変更で簡単に壊れるが、壊れ方が
「例外で止まる」ではなく「それらしい別の数字を返す」場合がある。
馬券の期待値計算にとって、これは無害な不具合ではなく資金を溶かす嘘になる。

そのため、取得したデータは必ず境界で検証してから返す（validate_* 群）。
検証に落ちたら、推測で埋めずに例外で止める。

  fetch.py doctor                       この環境からどこに出られるかを診断
  fetch.py racelist --date 20260726     その日のrace_id一覧
  fetch.py card --race-id 202601020811  出馬表＋単勝オッズ（レースJSONを書き出す）
  fetch.py odds --race-id ...           単勝オッズのみ（直前の再取得用）
  fetch.py result --race-id ...         確定結果
  fetch.py import --file x.csv          手元のCSVを同じ形式に変換（スクレイピング不要）
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(ROOT, "data", "cache")
RACES = os.path.join(ROOT, "data", "races")

BASE = "https://race.netkeiba.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 相手のサーバに負荷をかけないための最小間隔（秒）。
# 短くしたくなったら、遮断されて自分のデータ基盤ごと止まることを思い出すこと。
MIN_INTERVAL = 2.0
_last_request = [0.0]

# 場コード（race_idの5〜6桁目）
VENUES = {"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
          "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}


class Blocked(Exception):
    """ネットワークポリシー等で到達できない。回避せず報告する。"""


class ParseError(Exception):
    """取得はできたが、期待した構造ではなかった。推測で埋めない。"""


# ---------------------------------------------------------------- HTTP

def _cache_path(url, ext):
    key = hashlib.sha1(url.encode()).hexdigest()[:20]
    return os.path.join(CACHE, f"{key}{ext}")


_robots = {}


def _robots_allows(url):
    """robots.txt を尊重する。

    禁止されている場合に無理やり取りに行く選択肢は用意していない。
    公式に認められた経路（JRA-VAN DataLab）が別に存在する以上、
    規約を踏み越えてまでスクレイピングする理由がないため。
    """
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(origin + "/robots.txt")
        try:
            rp.read()
        except Exception:
            # robots.txt が読めない場合は判断材料が無いので、通す側に倒さない
            _robots[origin] = None
            return None
        _robots[origin] = rp
    rp = _robots[origin]
    if rp is None:
        return None
    return rp.can_fetch(UA, url)


def http_get(url, ttl=3600, use_cache=True):
    """レート制限・キャッシュ・robots尊重つきのGET。"""
    os.makedirs(CACHE, exist_ok=True)
    path = _cache_path(url, ".body")
    if use_cache and os.path.exists(path) and (time.time() - os.path.getmtime(path)) < ttl:
        with open(path, encoding="utf-8") as f:
            return f.read()

    allowed = _robots_allows(url)
    if allowed is False:
        raise Blocked(
            f"robots.txt がこのURLの取得を許可していません: {url}\n"
            "  公式データを使う経路（JRA-VAN DataLab）に切り替えるか、\n"
            "  `fetch.py import` で手元のデータを取り込んでください。")

    wait = MIN_INTERVAL - (time.time() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    _last_request[0] = time.time()

    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "ja,en;q=0.8",
        "Referer": BASE + "/",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            raw = res.read()
    except urllib.error.HTTPError as e:
        if e.code in (403, 407):
            raise Blocked(f"{url} は 403/407 で拒否されました（ポリシー拒否の可能性）") from e
        raise
    except urllib.error.URLError as e:
        raise Blocked(f"{url} に到達できません: {e.reason}\n"
                      "  `fetch.py doctor` で疎通状況を確認してください。") from e

    body = raw.decode("euc_jp", errors="replace") if b"euc-jp" in raw[:2000].lower() \
        else raw.decode("utf-8", errors="replace")
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return body


# ---------------------------------------------------------------- HTML

_SEPARATORS = {"br", "div", "li", "p", "tr", "dd", "dt"}


class TableParser(HTMLParser):
    """指定クラスのtableから、行ごとに (セルのテキスト列, セル内のhref列) を集める。

    位置ではなくクラス名で表を特定し、抽出後に検証する方針にしている。
    正規表現でHTMLを直接叩くより、構造変更時に「壊れたと分かる形」で壊れやすい。
    """

    def __init__(self, table_class):
        super().__init__(convert_charrefs=True)
        self.want = table_class
        self.rows = []
        self._depth = 0
        self._row = None
        self._cell = None
        self._hrefs = None

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "table":
            cls = d.get("class", "")
            self._depth = 1 if self.want in cls else 0
        elif self._depth and tag == "tr":
            self._row, self._hrefs = [], []
        elif self._depth and tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif self._depth and tag == "a" and self._hrefs is not None and d.get("href"):
            self._hrefs.append(d["href"])
        if self._cell is not None and tag in _SEPARATORS:
            # ブロック要素の境界に区切りを入れる。入れないと
            # <div>8</div><div>2</div><div>13</div> が "8213" に潰れ、
            # 複勝の馬番が1頭の巨大な番号になってしまう
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag == "table":
            self._depth = 0
        elif self._depth and tag in ("td", "th") and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif self._depth and tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append((self._row, self._hrefs))
            self._row, self._hrefs = None, None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


# ---------------------------------------------------------------- 検証

def validate_odds(odds_map):
    """単勝オッズの妥当性を、控除率という物理法則で検証する。

    Σ(1/オッズ) は払戻率の逆数（単勝80%なら1.25）付近に必ず落ちる。
    ここから外れるのは、頭数の取りこぼしか、券種の取り違えか、
    パースの失敗のいずれか。どれであっても使ってはいけないデータ。
    """
    if len(odds_map) < 5:
        raise ParseError(f"頭数が {len(odds_map)} 頭しかありません。取得に失敗しています")
    bad = [k for k, v in odds_map.items() if not (1.0 <= v <= 10000)]
    if bad:
        raise ParseError(f"オッズの値域が不正です: 馬番 {bad}")
    nums = sorted(odds_map)
    if nums != list(range(1, len(nums) + 1)):
        raise ParseError(f"馬番が 1..{len(nums)} で連続していません: {nums}")
    book = sum(1.0 / v for v in odds_map.values())
    takeout = 1.0 - 1.0 / book
    if not (0.15 <= takeout <= 0.32):
        raise ParseError(
            f"オッズから逆算した控除率が {takeout*100:.1f}% で異常です"
            f"（正常なら15〜32%）。出走馬の取りこぼしかパース失敗が疑われます")
    return takeout


def validate_card(card):
    horses = card.get("horses", [])
    if len(horses) < 5:
        raise ParseError(f"出走馬が {len(horses)} 頭しか取れていません")
    for h in horses:
        if not h.get("name") or not h.get("umaban"):
            raise ParseError(f"馬番または馬名が欠けた行があります: {h}")
    nums = sorted(h["umaban"] for h in horses)
    if nums != list(range(1, len(nums) + 1)):
        raise ParseError(f"馬番が連続していません: {nums}")
    return card


# ---------------------------------------------------------------- 取得

def fetch_racelist(date_str, ttl=1800):
    """開催日の race_id 一覧。

    race_list.html はJS描画なので、素のHTTPで中身が入っている
    race_list_sub.html の方を叩く。
    """
    url = f"{BASE}/top/race_list_sub.html?kaisai_date={date_str}"
    html = http_get(url, ttl=ttl)
    ids = sorted(set(re.findall(r"race_id=(\d{12})", html)))
    if not ids:
        raise ParseError(
            f"{date_str} のrace_idが1件も取れませんでした。\n"
            "  開催が無い日か、ページ構造が変わった可能性があります。")
    return ids


def fetch_win_odds(race_id, ttl=120):
    """単勝オッズ。netkeibaのJSON APIを使う（HTMLパースより壊れにくい）。

    レスポンスは data['odds']['1'] に {馬番: [オッズ, ...]} の形で入る。
    オッズは直前まで動くので、TTLは既定120秒と短くしている。
    """
    url = f"{BASE}/api/api_get_jra_odds.html?race_id={race_id}&type=1&action=init"
    body = http_get(url, ttl=ttl)
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise ParseError(f"オッズAPIがJSONを返しませんでした（構造変更の可能性）: {e}") from e

    block = (data.get("data") or data).get("odds", {}).get("1")
    if not block:
        raise ParseError(f"オッズAPIの応答に単勝データがありません: keys={list(data)[:8]}")

    odds = {}
    for k, v in block.items():
        if not str(k).isdigit():
            continue
        val = v[0] if isinstance(v, (list, tuple)) else v
        try:
            odds[int(k)] = float(val)
        except (TypeError, ValueError):
            continue
    validate_odds(odds)
    return odds


def fetch_card(race_id, ttl=21600):
    """出馬表。列の並びはページ構造に依存するので、位置ではなく内容で拾う。"""
    url = f"{BASE}/race/shutuba.html?race_id={race_id}"
    html = http_get(url, ttl=ttl)

    p = TableParser("Shutuba_Table")
    p.feed(html)
    if not p.rows:
        raise ParseError(
            "出馬表のテーブルが見つかりませんでした。\n"
            "  netkeibaの構造変更か、レース前でまだ確定していない可能性があります。")

    horses = []
    for cells, hrefs in p.rows:
        nums = [c for c in cells[:3] if c.isdigit()]
        if len(nums) < 2:
            continue  # ヘッダ行など
        umaban = int(nums[1])
        horse_id = next((m.group(1) for h in hrefs
                         if (m := re.search(r"/horse/(\d+)", h))), None)
        name = next((c for c in cells if re.search(r"[ァ-ヴー]{2,}", c)), "")
        sexage = next((c for c in cells if re.fullmatch(r"[牡牝セ]\d+", c)), "")
        horses.append({
            "umaban": umaban, "waku": int(nums[0]), "name": name,
            "horse_id": horse_id, "sexage": sexage,
            "raw": cells,   # 検証・デバッグ用に元の行を残す
        })

    title = re.search(r'<title>([^<]+)</title>', html)
    card = {
        "race_id": race_id,
        "venue": VENUES.get(race_id[4:6], race_id[4:6]),
        "race_no": int(race_id[10:12]),
        "title": (title.group(1).strip() if title else ""),
        "horses": sorted(horses, key=lambda h: h["umaban"]),
    }
    return validate_card(card)


def fetch_result(race_id, ttl=86400):
    url = f"{BASE}/race/result.html?race_id={race_id}"
    html = http_get(url, ttl=ttl)
    p = TableParser("ResultTableWrap")
    p.feed(html)
    if not p.rows:
        p = TableParser("RaceTable01")
        p.feed(html)
    if not p.rows:
        raise ParseError("結果テーブルが見つかりませんでした（未確定の可能性）")
    order = []
    for cells, _ in p.rows:
        if len(cells) >= 3 and cells[0].isdigit() and cells[2].isdigit():
            order.append({"chakujun": int(cells[0]), "umaban": int(cells[2]),
                          "raw": cells})
    if not order:
        raise ParseError("着順を1件も抽出できませんでした")
    return {"race_id": race_id, "order": order,
            "payouts": _parse_payouts(html)}


def _parse_payouts(html):
    """払戻表から単勝・複勝を取り出す。

    決済は「賭け金 × オッズ」ではなく、必ず公式の払戻金から計算する。
    購入時のオッズと確定オッズは違うので、前者で決済すると台帳が
    実際の資金と静かにずれていく。
    """
    p = TableParser("Payout_Detail_Table")
    p.feed(html)
    out = {"単勝": {}, "複勝": {}}
    # 拾わない券種の行に入ったら kind を切る。切らないと、直前の券種の
    # 払戻を後続の券種の数字で上書きしてしまう
    ALL_KINDS = {"単勝", "複勝", "枠連", "馬連", "ワイド", "馬単",
                 "3連複", "三連複", "3連単", "三連単", "WIN5"}
    kind = None
    for cells, _ in p.rows:
        if not cells:
            continue
        if cells[0] in out:
            kind = cells[0]
            body = cells[1:]
        elif cells[0] in ALL_KINDS:
            kind = None
            continue
        elif kind:
            body = cells
        else:
            continue
        # 「馬番」「払戻金(円区切りあり)」が並ぶ。複勝は複数行ぶんが1セルに入る
        if len(body) < 2:
            continue
        umabans = re.findall(r"\d+", body[0])
        yens = [int(x.replace(",", "")) for x in re.findall(r"[\d,]{3,}", body[1])]
        for u, y in zip(umabans, yens):
            out[kind][int(u)] = y
    return out


# ---------------------------------------------------------------- 出力

def build_race_json(race_id, card, odds, bankroll=None):
    """ev.py plan がそのまま食える形に組み立てる。

    確率 p は意図的に null にしてある。ここを機械的に埋めないのが要点で、
    オッズから作った確率で期待値を出すと、定義上どの馬も払戻率ちょうどになり、
    必ず負ける。p を入れるのは、オッズ以外の情報を見た人間／モデルの仕事。
    """
    takeout = 1.0 - 1.0 / sum(1.0 / v for v in odds.values())
    cands = []
    for h in card["horses"]:
        o = odds.get(h["umaban"])
        if o is None:
            raise ParseError(f"馬番 {h['umaban']} のオッズがありません")
        cands.append({
            "label": f"{h['umaban']} {h['name']}",
            "odds": o, "p": None, "why": "",
        })
    return {
        "race": f"{card['venue']}{card['race_no']}R {card['title']}",
        "race_id": race_id,
        "bet_type": "単勝",
        "takeout": round(takeout, 4),
        "bankroll": bankroll,
        "kelly_fraction": 0.25,
        "max_race_exposure": 0.05,
        "min_ev": 1.10,
        "exclusive": True,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "candidates": cands,
    }


def save_race(race):
    os.makedirs(RACES, exist_ok=True)
    path = os.path.join(RACES, f"{race['race_id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(race, f, ensure_ascii=False, indent=2)
    return path


# ---------------------------------------------------------------- コマンド

def cmd_doctor(args):
    """この環境から自走できるかを判定する。

    「取れるはず」で組み立てて失敗するより、最初に白黒つけた方が速い。
    """
    print("疎通診断")
    print("-" * 56)
    targets = [("race.netkeiba.com", f"{BASE}/top/"),
               ("www.netkeiba.com", "https://www.netkeiba.com/"),
               ("jra-van.jp", "https://jra-van.jp/"),
               ("pypi.org (対照)", "https://pypi.org/")]
    ok = []
    for name, url in targets:
        try:
            http_get(url, ttl=0, use_cache=False)
            print(f"  {name:<24} 到達可")
            ok.append(name)
        except Blocked as e:
            print(f"  {name:<24} 到達不可 — {str(e).splitlines()[0]}")
        except Exception as e:
            print(f"  {name:<24} エラー — {type(e).__name__}: {e}")
    print("-" * 56)
    if "race.netkeiba.com" in ok:
        print("自走可能: `run.py scan --date YYYYMMDD` が使えます。")
    else:
        print("自走不可: この環境からレースデータを取得できません。")
        print("  対処は references/autonomy.md の「遮断されている場合」を参照。")
        print("  当面は `fetch.py import` か、オッズの手貼りで運用してください。")
    return 0 if "race.netkeiba.com" in ok else 3


def cmd_racelist(args):
    ids = fetch_racelist(args.date)
    for rid in ids:
        print(f"{rid}  {VENUES.get(rid[4:6], '??')}{int(rid[10:12])}R")
    print(f"\n{len(ids)}件")


def cmd_card(args):
    card = fetch_card(args.race_id)
    odds = fetch_win_odds(args.race_id)
    race = build_race_json(args.race_id, card, odds, args.bankroll)
    path = save_race(race)
    print(f"{race['race']}  {len(race['candidates'])}頭  "
          f"控除率 {race['takeout']*100:.1f}%")
    print(f"書き出し: {path}")
    print("※ 各馬の p は null のままです。オッズ以外の情報を見て埋めてください")


def cmd_odds(args):
    odds = fetch_win_odds(args.race_id, ttl=0)
    for k in sorted(odds):
        print(f"{k:>3}  {odds[k]:>7.1f}")


def cmd_result(args):
    r = fetch_result(args.race_id)
    for o in r["order"][:5]:
        print(f"{o['chakujun']:>2}着  馬番{o['umaban']}")


def cmd_import(args):
    """スクレイピングを使わずに、手元のCSVから同じ形式を作る。

    列は umaban,name,odds （ヘッダ必須）。JRA-VAN からの書き出しや、
    画面を手で写した場合の受け口。取得経路が塞がっても運用を止めないための逃げ道。
    """
    horses, odds = [], {}
    with open(args.file, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            n = int(row["umaban"])
            horses.append({"umaban": n, "waku": 0, "name": row["name"].strip(),
                           "horse_id": None, "sexage": "", "raw": []})
            odds[n] = float(row["odds"])
    validate_odds(odds)
    card = validate_card({"race_id": args.race_id, "venue": args.venue,
                          "race_no": args.race_no, "title": args.title,
                          "horses": sorted(horses, key=lambda h: h["umaban"])})
    race = build_race_json(args.race_id, card, odds, args.bankroll)
    print(f"書き出し: {save_race(race)}")


def main():
    ap = argparse.ArgumentParser(description="レースデータ取得層")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="この環境から自走できるか診断する")
    d.set_defaults(func=cmd_doctor)

    r = sub.add_parser("racelist", help="開催日のrace_id一覧")
    r.add_argument("--date", required=True, help="YYYYMMDD")
    r.set_defaults(func=cmd_racelist)

    c = sub.add_parser("card", help="出馬表＋単勝オッズを取得しレースJSONを書く")
    c.add_argument("--race-id", required=True)
    c.add_argument("--bankroll", type=float, default=None)
    c.set_defaults(func=cmd_card)

    o = sub.add_parser("odds", help="単勝オッズのみ再取得")
    o.add_argument("--race-id", required=True)
    o.set_defaults(func=cmd_odds)

    s = sub.add_parser("result", help="確定結果")
    s.add_argument("--race-id", required=True)
    s.set_defaults(func=cmd_result)

    i = sub.add_parser("import", help="CSVからレースJSONを作る（取得経路が無い時）")
    i.add_argument("--file", required=True, help="umaban,name,odds のCSV")
    i.add_argument("--race-id", required=True)
    i.add_argument("--venue", default="")
    i.add_argument("--race-no", type=int, default=0)
    i.add_argument("--title", default="")
    i.add_argument("--bankroll", type=float, default=None)
    i.set_defaults(func=cmd_import)

    args = ap.parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    try:
        main()
    except Blocked as e:
        print(f"\n[到達不可] {e}", file=sys.stderr)
        sys.exit(3)
    except ParseError as e:
        print(f"\n[データ不正] {e}\n"
              "  推測で補完はしません。このデータは使わないでください。", file=sys.stderr)
        sys.exit(4)
    except BrokenPipeError:
        sys.exit(0)
