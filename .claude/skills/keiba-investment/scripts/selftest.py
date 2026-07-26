#!/usr/bin/env python3
"""取得層のセルフテスト。ネットワーク不要。

スクレイピングのコードは、相手のサイトに繋がらない環境では動作確認ができない。
そこで、実際のnetkeibaのHTML構造を模したフィクスチャに対してパーサを走らせ、
「構造さえ想定通りなら正しく動く」ところまでは保証しておく。

これで潰せるのはロジックの誤りであって、構造の想定違いは潰せない。
実サイトに繋がる環境で一度 `fetch.py card` を通すまで、パーサは
「未検証」の扱いを外さないこと。

  python3 scripts/selftest.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch  # noqa: E402

PASS, FAIL = [], []


def check(name, fn):
    try:
        fn()
        PASS.append(name)
        print(f"  OK   {name}")
    except AssertionError as e:
        FAIL.append((name, str(e)))
        print(f"  NG   {name}: {e}")
    except Exception as e:
        FAIL.append((name, f"{type(e).__name__}: {e}"))
        print(f"  NG   {name}: {type(e).__name__}: {e}")


# ---------------------------------------------------------------- 素材

def shutuba_html(n=13):
    """netkeibaの出馬表テーブルを模したHTML。
    列: 枠, 馬番, 印, 馬名, 性齢, 斤量, 騎手, 厩舎 ..."""
    rows = []
    for i in range(1, n + 1):
        waku = min(8, (i + 1) // 2)
        rows.append(f"""
        <tr class="HorseList">
          <td class="Waku{waku}">{waku}</td>
          <td class="Umaban{waku}">{i}</td>
          <td class="Mark"></td>
          <td class="HorseInfo">
            <span class="HorseName"><a href="/horse/2021104{i:03d}/">テストウマ{i}ゴウ</a></span>
          </td>
          <td class="Barei">牡{3 + i % 3}</td>
          <td class="Txt_C">5{i % 3}.0</td>
          <td class="Jockey"><a href="/jockey/result/recent/0123{i:02d}/">騎手{i}</a></td>
          <td class="Trainer"><a href="/trainer/result/recent/0145{i:02d}/">厩舎{i}</a></td>
        </tr>""")
    return ("<html><head><title>テストステークス | 2026年7月26日 札幌11R</title></head>"
            "<body><table class=\"Shutuba_Table RaceTable01\">"
            "<tr><th>枠</th><th>馬番</th><th>印</th><th>馬名</th></tr>"
            + "".join(rows) + "</table></body></html>")


REAL_ODDS = {1: 19.1, 2: 2.5, 3: 4.0, 4: 19.9, 5: 11.3, 6: 56.1, 7: 23.5,
             8: 6.6, 9: 64.2, 10: 33.2, 11: 10.7, 12: 40.9, 13: 22.8}


def odds_json(odds=None):
    odds = odds or REAL_ODDS
    return json.dumps({"status": "OK", "data": {"odds": {
        "1": {str(k): [f"{v:.1f}", "1", str(i + 1)] for i, (k, v) in enumerate(odds.items())}
    }}})


# ---------------------------------------------------------------- 検証ロジック

def t_odds_valid():
    to = fetch.validate_odds(REAL_ODDS)
    assert 0.20 <= to <= 0.21, f"控除率 {to}"


def t_odds_missing_horses():
    """出走馬が欠けた入力は必ず弾かれること。黙って通ると資金を溶かす。"""
    try:
        fetch.validate_odds({1: 2.5, 2: 4.0, 3: 6.6})
    except fetch.ParseError:
        return
    raise AssertionError("頭数不足が検出されなかった")


def t_odds_partial_field():
    """馬番は連続しているが上位人気だけ、というケース（控除率が負になる）。"""
    partial = {i: REAL_ODDS[i] for i in (1, 2, 3, 4, 5, 6)}
    try:
        fetch.validate_odds(partial)
    except fetch.ParseError as e:
        assert "控除率" in str(e), f"想定と違う理由で弾かれた: {e}"
        return
    raise AssertionError("部分入力が検出されなかった")


def t_odds_noncontiguous():
    d = dict(REAL_ODDS)
    d[99] = d.pop(13)
    try:
        fetch.validate_odds(d)
    except fetch.ParseError:
        return
    raise AssertionError("馬番の欠番が検出されなかった")


def t_place_odds_mistaken_as_win():
    """複勝オッズを単勝と取り違えた場合。Σ(1/o)が大きくなるので弾けるはず。"""
    place = {k: max(1.1, v / 4.0) for k, v in REAL_ODDS.items()}
    try:
        fetch.validate_odds(place)
    except fetch.ParseError:
        return
    raise AssertionError("券種の取り違えが検出されなかった")


# ---------------------------------------------------------------- パーサ

def t_odds_api_parse():
    body = odds_json()
    data = json.loads(body)
    block = (data.get("data") or data).get("odds", {}).get("1")
    got = {int(k): float(v[0]) for k, v in block.items()}
    assert got == REAL_ODDS, f"オッズが一致しない: {got}"
    fetch.validate_odds(got)


def t_shutuba_parse():
    p = fetch.TableParser("Shutuba_Table")
    p.feed(shutuba_html(13))
    assert len(p.rows) == 14, f"行数 {len(p.rows)}（ヘッダ1＋13頭のはず）"
    horses = []
    for cells, hrefs in p.rows:
        nums = [c for c in cells[:3] if c.isdigit()]
        if len(nums) < 2:
            continue
        import re
        horses.append({
            "umaban": int(nums[1]), "waku": int(nums[0]),
            "name": next((c for c in cells if re.search(r"[ァ-ヴー]{2,}", c)), ""),
            "horse_id": next((m.group(1) for h in hrefs
                              if (m := re.search(r"/horse/(\d+)", h))), None),
        })
    assert len(horses) == 13, f"抽出頭数 {len(horses)}"
    assert horses[0]["umaban"] == 1 and horses[-1]["umaban"] == 13
    assert horses[4]["name"] == "テストウマ5ゴウ", f"馬名 {horses[4]['name']}"
    assert horses[4]["horse_id"] == "2021104005", f"horse_id {horses[4]['horse_id']}"


def t_card_validation_rejects_gap():
    bad = {"horses": [{"umaban": i, "name": f"ウマ{i}"} for i in [1, 2, 3, 4, 6]]}
    try:
        fetch.validate_card(bad)
    except fetch.ParseError:
        return
    raise AssertionError("馬番の飛びが検出されなかった")


def t_build_race_json():
    p = fetch.TableParser("Shutuba_Table")
    p.feed(shutuba_html(13))
    import re
    horses = []
    for cells, hrefs in p.rows:
        nums = [c for c in cells[:3] if c.isdigit()]
        if len(nums) < 2:
            continue
        horses.append({"umaban": int(nums[1]), "waku": int(nums[0]),
                       "name": next((c for c in cells if re.search(r"[ァ-ヴー]{2,}", c)), ""),
                       "horse_id": None, "sexage": "", "raw": cells})
    card = {"race_id": "202601020811", "venue": "札幌", "race_no": 11,
            "title": "テストステークス", "horses": horses}
    race = fetch.build_race_json("202601020811", card, REAL_ODDS, 100000)
    assert len(race["candidates"]) == 13
    assert all(c["p"] is None for c in race["candidates"]), \
        "p が自動で埋まっている。オッズ由来の確率は期待値を必ず払戻率に固定してしまう"
    assert 0.20 <= race["takeout"] <= 0.21, f"控除率 {race['takeout']}"
    assert race["candidates"][1]["odds"] == 2.5


PAYOUT_HTML = """<html><body><table class="Payout_Detail_Table">
<tr class="Tansho"><th>単勝</th><td class="Result"><div><span>8</span></div></td>
  <td class="Payout"><span>660円</span></td><td class="Ninki"><span>3人気</span></td></tr>
<tr class="Fukusho"><th>複勝</th>
  <td class="Result"><div><span>8</span></div><div><span>2</span></div><div><span>13</span></div></td>
  <td class="Payout"><span>210円</span><br><span>130円</span><br><span>1,180円</span></td>
  <td class="Ninki"><span>3人気</span><br><span>1人気</span><br><span>9人気</span></td></tr>
<tr class="Wakuren"><th>枠連</th><td class="Result"><div><span>1</span>-<span>5</span></div></td>
  <td class="Payout"><span>1,240円</span></td><td class="Ninki"><span>4人気</span></td></tr>
<tr class="Umaren"><th>馬連</th><td class="Result"><div><span>2</span>-<span>8</span></div></td>
  <td class="Payout"><span>1,850円</span></td><td class="Ninki"><span>5人気</span></td></tr>
<tr class="Sanrentan"><th>3連単</th>
  <td class="Result"><div><span>8</span>-<span>2</span>-<span>13</span></div></td>
  <td class="Payout"><span>48,320円</span></td><td class="Ninki"><span>112人気</span></td></tr>
</table></body></html>"""


def t_payout_tansho():
    got = fetch._parse_payouts(PAYOUT_HTML)
    assert got["単勝"] == {8: 660}, got["単勝"]


def t_payout_fukusho_multi():
    """複勝は1セルに複数頭が入る。div境界で区切らないと "8213" に潰れる。"""
    got = fetch._parse_payouts(PAYOUT_HTML)
    assert got["複勝"] == {8: 210, 2: 130, 13: 1180}, got["複勝"]


def t_payout_no_crosstalk():
    """拾わない券種（枠連・馬連・3連単）の数字が混入しないこと。"""
    got = fetch._parse_payouts(PAYOUT_HTML)
    assert 48320 not in got["単勝"].values(), "3連単の払戻が単勝に混入"
    assert 1240 not in got["複勝"].values(), "枠連の払戻が複勝に混入"
    assert set(got) == {"単勝", "複勝"}, got.keys()


def t_settlement_amount():
    """決済額は 賭け金/100 × 払戻金。購入時オッズではない。"""
    got = fetch._parse_payouts(PAYOUT_HTML)
    yen = got["単勝"][8]
    assert int(1500 / 100 * yen) == 9900, "1500円 × 660円/100円 = 9,900円"
    assert int(100 / 100 * yen) == 660


def t_empty_shutuba_is_error():
    p = fetch.TableParser("Shutuba_Table")
    p.feed("<html><body><table class='Other_Table'><tr><td>1</td></tr></table></body></html>")
    assert p.rows == [], "無関係のテーブルを拾っている"


# ---------------------------------------------------------------- 実行

def main():
    print("取得層セルフテスト（ネットワーク不要）")
    print("=" * 56)
    print("[検証ロジック] 不正データを確実に弾けるか")
    check("正常な単勝オッズを受理する", t_odds_valid)
    check("頭数不足を弾く", t_odds_missing_horses)
    check("上位人気のみの部分入力を弾く", t_odds_partial_field)
    check("馬番の欠番を弾く", t_odds_noncontiguous)
    check("複勝オッズの取り違えを弾く", t_place_odds_mistaken_as_win)
    check("出馬表の馬番の飛びを弾く", t_card_validation_rejects_gap)

    print("[パーサ] 想定構造から正しく抽出できるか")
    check("オッズAPIのJSONを解釈する", t_odds_api_parse)
    check("出馬表テーブルから馬番・馬名・horse_idを取る", t_shutuba_parse)
    check("無関係なテーブルを拾わない", t_empty_shutuba_is_error)
    check("レースJSONを組み立てる（pは空のまま）", t_build_race_json)

    print("[決済] 払戻の読み取りと金額計算")
    check("単勝の払戻を取る", t_payout_tansho)
    check("複勝の複数頭を分離して取る", t_payout_fukusho_multi)
    check("他券種の払戻が混入しない", t_payout_no_crosstalk)
    check("決済額 = 賭け金/100 × 払戻金", t_settlement_amount)

    print("=" * 56)
    print(f"成功 {len(PASS)} / 失敗 {len(FAIL)}")
    if FAIL:
        for n, e in FAIL:
            print(f"  - {n}: {e}")
        return 1
    print("\nロジックは想定通り。ただし実サイトのHTML構造が想定と一致するかは")
    print("このテストでは検証できない。ネットワークの通る環境で一度")
    print("`fetch.py card --race-id ...` を通すまで、パーサは未検証扱いのこと。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
