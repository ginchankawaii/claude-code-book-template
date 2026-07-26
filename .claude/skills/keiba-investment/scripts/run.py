#!/usr/bin/env python3
"""自走ループの司令塔。取得 → 準備 → （判断） → 記帳 → 決済 → 検証。

決定的にできる部分（取得・計算・記帳・決済・集計）はここが全部やる。
唯一自動化していないのが「各馬の勝率をいくつと見るか」で、これは意図的。

オッズから確率を作ると、期待値は定義上どの馬でも払戻率ちょうど（単勝80%）に
なり、必ず負ける。確率はオッズ以外の情報から来なければ意味がなく、そこは
今のところ判断の仕事として残している。つまりこのスクリプトは「Claudeが
考えるべき一点だけを残して、他を全部片付ける」ためのもの。

  run.py scan --date 20260726       その日のレースを取得し、検討対象を絞る
  run.py brief --race-id ...        1レース分の判断材料をまとめて出す
  run.py settle --date 20260726     確定結果で未決済ベットを決済し、レポートを出す
  run.py status                     現在の運用状況
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch  # noqa: E402
import ledger  # noqa: E402
from ev import implied_probs, pad  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _bankroll():
    acc = ledger.load_account()
    r = ledger.analyze(acc, ledger.load_bets())
    return acc, r


# ---------------------------------------------------------------- scan

def cmd_scan(args):
    """開催日の全レースを取得して、レースJSONを揃える。

    ここで買い目は決めない。決めるための材料を、欠けなく・検証済みの状態で
    並べるところまでが仕事。
    """
    acc, r = _bankroll()
    print(f"資金 {r['equity']:,.0f}円 / Phase {r['phase']} / 投下可能 {r['available']:,.0f}円")
    print()

    ids = fetch.fetch_racelist(args.date)
    if args.race_no:
        ids = [i for i in ids if int(i[10:12]) in args.race_no]
    if args.limit:
        ids = ids[:args.limit]
    print(f"{args.date} の対象レース: {len(ids)}件\n")

    done, skipped = [], []
    for rid in ids:
        label = f"{fetch.VENUES.get(rid[4:6], '??')}{int(rid[10:12])}R"
        try:
            card = fetch.fetch_card(rid)
            odds = fetch.fetch_win_odds(rid)
            race = fetch.build_race_json(rid, card, odds, r["available"])
            fetch.save_race(race)
            done.append((rid, race))
            print(f"  取得  {label:<10} {len(race['candidates']):>2}頭  "
                  f"控除率 {race['takeout']*100:.1f}%")
        except (fetch.ParseError, fetch.Blocked) as e:
            skipped.append((label, str(e).splitlines()[0]))
            print(f"  除外  {label:<10} {str(e).splitlines()[0]}")

    print()
    if skipped:
        # 黙って落とすと「全部見た」ように見える。何を見ていないかは必ず出す
        print(f"【取得できなかったレース {len(skipped)}件】判断対象から外れています")
        for label, why in skipped:
            print(f"  - {label}: {why}")
        print()

    print(f"レースJSON: {fetch.RACES}/")
    print("次にやること: 各レースについて `run.py brief --race-id <id>` を読み、")
    print("オッズ以外の情報から各馬の p を埋める。埋まっていないレースは買えない。")
    return 0


# ---------------------------------------------------------------- brief

def cmd_brief(args):
    """1レース分の判断材料を1画面にまとめる。

    「必要確率」を併記しているのは、自分の見立てを書く前に敷居を見せておくと
    アンカリングで甘くなるため……ではなく、逆に見送り判断が速くなるため。
    敷居に届く見込みが最初から無いレースは、分析に時間を使うだけ無駄になる。
    """
    path = os.path.join(fetch.RACES, f"{args.race_id}.json")
    if not os.path.exists(path):
        print(f"レースJSONがありません: {path}\n"
              f"  先に `run.py scan --date ...` か `fetch.py card --race-id {args.race_id}` を実行してください",
              file=sys.stderr)
        return 4
    with open(path, encoding="utf-8") as f:
        race = json.load(f)

    odds = [c["odds"] for c in race["candidates"]]
    market, to = implied_probs(odds)
    booksum = sum(1.0 / o for o in odds)
    ratio = race.get("min_ev", 1.10) * booksum

    print(f"{race['race']}   ({race['race_id']})")
    print(f"取得時刻 {race.get('fetched_at', '?')}   控除率 {to*100:.1f}%   {len(odds)}頭")
    print(f"要求期待値 {race.get('min_ev', 1.10)*100:.0f}% → "
          f"市場の見立ての {ratio:.2f}倍 の勝率を確信できる馬だけが買い目")
    print()
    print(pad("馬", 24) + pad("オッズ", 8, True) + pad("市場", 8, True)
          + pad("必要確率", 10, True) + "   自分の見立て")
    print("-" * 68)
    for c, m in sorted(zip(race["candidates"], market), key=lambda x: x[0]["odds"]):
        need = race.get("min_ev", 1.10) / c["odds"]
        mine = f"{c['p']*100:.1f}%" if c.get("p") is not None else "（未記入）"
        print(pad(c["label"], 24) + pad(f"{c['odds']:.1f}", 8, True)
              + pad(f"{m*100:.1f}%", 8, True) + pad(f"{need*100:.1f}%", 10, True)
              + "   " + mine)
    print("-" * 68)

    unfilled = [c for c in race["candidates"] if c.get("p") is None]
    if unfilled:
        print(f"\np が未記入: {len(unfilled)}/{len(race['candidates'])}頭")
        print("  近走・馬場・展開・枠・調教を見て埋める（references/race-analysis.md）。")
        print("  オッズだけで埋めるのは禁止。期待値が必ず払戻率に固定され、負ける。")
    else:
        print("\np は記入済み。`ev.py plan --file "
              f"{os.path.relpath(path, ROOT)}` で買い目を計算できます。")
    return 0


# ---------------------------------------------------------------- settle

def cmd_settle(args):
    """確定結果を取得して未決済ベットを決済する。

    払戻は公式の払戻金から計算する。購入時オッズで決済すると、台帳と実際の
    資金が静かにずれ、キャリブレーション検証の土台ごと崩れる。
    """
    bets = ledger.load_bets()
    open_bets = [b for b in bets if b["status"] == "open"]
    if args.date:
        open_bets = [b for b in open_bets if b["date"].replace("-", "") == args.date]
    if not open_bets:
        print("決済対象の未決済ベットはありません")
        return 0

    by_race = {}
    for b in open_bets:
        rid = b.get("race_id")
        if not rid:
            print(f"  #{b['id']} は race_id が無いため自動決済できません "
                  f"（`ledger.py settle --id {b['id']} --payout ...` で手動決済）")
            continue
        by_race.setdefault(rid, []).append(b)

    settled = 0
    for rid, group in by_race.items():
        try:
            res = fetch.fetch_result(rid)
        except (fetch.ParseError, fetch.Blocked) as e:
            print(f"  {rid}: 結果を取得できません — {str(e).splitlines()[0]}")
            continue
        pay = res.get("payouts", {})
        for b in group:
            table = pay.get(b["type"], {})
            if not table:
                print(f"  #{b['id']} {b['type']} の払戻が取得できませんでした")
                continue
            yen = table.get(int(b["sel"]), 0)
            payout = int(b["stake"] / 100 * yen)
            subprocess.run([sys.executable, os.path.join(HERE, "ledger.py"),
                            "settle", "--id", str(b["id"]), "--payout", str(payout)],
                           check=True)
            settled += 1

    print(f"\n{settled}件を決済しました\n")
    subprocess.run([sys.executable, os.path.join(HERE, "ledger.py"), "report"], check=True)
    return 0


def cmd_status(args):
    return subprocess.run([sys.executable, os.path.join(HERE, "ledger.py"),
                           "report"]).returncode


def main():
    ap = argparse.ArgumentParser(description="自走ループの司令塔")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="開催日のレースを取得して揃える")
    s.add_argument("--date", required=True, help="YYYYMMDD")
    s.add_argument("--race-no", type=int, nargs="+", default=None,
                   help="対象レース番号を絞る（例: 10 11 12）")
    s.add_argument("--limit", type=int, default=None)
    s.set_defaults(func=cmd_scan)

    b = sub.add_parser("brief", help="1レース分の判断材料を出す")
    b.add_argument("--race-id", required=True)
    b.set_defaults(func=cmd_brief)

    t = sub.add_parser("settle", help="確定結果で未決済ベットを決済する")
    t.add_argument("--date", default=None, help="YYYYMMDD（省略時は全件）")
    t.set_defaults(func=cmd_settle)

    st = sub.add_parser("status", help="現在の運用状況")
    st.set_defaults(func=cmd_status)

    args = ap.parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    try:
        main()
    except fetch.Blocked as e:
        print(f"\n[到達不可] {e}\n"
              "  この環境からは自走できません。`fetch.py doctor` と\n"
              "  references/autonomy.md を確認してください。", file=sys.stderr)
        sys.exit(3)
    except fetch.ParseError as e:
        print(f"\n[データ不正] {e}", file=sys.stderr)
        sys.exit(4)
    except BrokenPipeError:
        sys.exit(0)
