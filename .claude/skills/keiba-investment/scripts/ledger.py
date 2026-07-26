#!/usr/bin/env python3
"""馬券投資の資金台帳。記帳・決済・検証。標準ライブラリのみ。

台帳は運用の記憶そのもの。ここに残っていないベットは、後から検証できないので
運用実績としては存在しなかったのと同じになる。だから必ず賭ける前に記帳する。

保存先:
  portfolio/bankroll.json  口座の状態（初期資金・フェーズ）
  portfolio/bets.jsonl     1行1ベットの追記ログ
"""

import argparse
import json
import os
import random
import statistics
import sys
import unicodedata
from datetime import date


def width(s):
    """端末上の表示幅。日本語は全角で2文字分を占めるため、len()では桁が揃わない。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(s))


def pad(s, n, right=False):
    s = str(s)
    fill = " " * max(0, n - width(s))
    return fill + s if right else s + fill

HERE = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO = os.path.join(os.path.dirname(HERE), "portfolio")
ACCOUNT = os.path.join(PORTFOLIO, "bankroll.json")
BETS = os.path.join(PORTFOLIO, "bets.jsonl")


# ---------------------------------------------------------------- 入出力

def load_account():
    if not os.path.exists(ACCOUNT):
        raise SystemExit("口座が未初期化です。まず `ledger.py init --bankroll 100000` を実行してください")
    with open(ACCOUNT, encoding="utf-8") as f:
        return json.load(f)


def save_account(acc):
    os.makedirs(PORTFOLIO, exist_ok=True)
    with open(ACCOUNT, "w", encoding="utf-8") as f:
        json.dump(acc, f, ensure_ascii=False, indent=2)


def load_bets():
    if not os.path.exists(BETS):
        return []
    out = []
    with open(BETS, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write_bets(bets):
    os.makedirs(PORTFOLIO, exist_ok=True)
    tmp = BETS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for b in bets:
            f.write(json.dumps(b, ensure_ascii=False) + "\n")
    os.replace(tmp, BETS)


def append_bet(bet):
    os.makedirs(PORTFOLIO, exist_ok=True)
    with open(BETS, "a", encoding="utf-8") as f:
        f.write(json.dumps(bet, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- 分析

def bootstrap_roi_ci(settled, iters=5000, seed=42):
    """回収率の95%信頼区間をブートストラップで求める。

    単純な平均回収率だけを見ると、たまたま高配当を1本引いただけで
    「勝てている」と錯覚する。区間の下限が1.0を超えて初めて、
    運と区別のついた実力だと言える。
    """
    if len(settled) < 20:
        return None
    rng = random.Random(seed)
    n = len(settled)
    rois = []
    for _ in range(iters):
        sample = [settled[rng.randrange(n)] for _ in range(n)]
        stake = sum(b["stake"] for b in sample)
        payout = sum(b.get("payout") or 0 for b in sample)
        if stake > 0:
            rois.append(payout / stake)
    if not rois:
        return None
    rois.sort()
    lo = rois[int(0.025 * len(rois))]
    hi = rois[int(0.975 * len(rois)) - 1]
    return lo, hi


def max_drawdown(settled, initial):
    """資金曲線のピークからの最大下落率。"""
    equity = initial
    peak = initial
    worst = 0.0
    for b in settled:
        equity += (b.get("payout") or 0) - b["stake"]
        peak = max(peak, equity)
        if peak > 0:
            worst = max(worst, (peak - equity) / peak)
    return worst, equity


CAL_BINS = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.20),
            (0.20, 0.35), (0.35, 0.50), (0.50, 1.01)]


def calibration(settled):
    """見積もり確率のビンごとに、平均予測確率と実際の的中率を並べる。

    ここが運用の健康診断。回収率は運で大きく揺れるが、キャリブレーションのズレは
    モデルの構造的な欠陥を直接示す。「30%と言った馬が15%しか来ていない」なら、
    今の回収率がプラスでもその運用は破綻に向かっている。
    """
    rows = []
    for lo, hi in CAL_BINS:
        grp = [b for b in settled if b.get("p") is not None and lo <= b["p"] < hi]
        if not grp:
            continue
        hits = sum(1 for b in grp if (b.get("payout") or 0) > 0)
        rows.append({
            "range": f"{lo*100:.0f}-{hi*100:.0f}%",
            "n": len(grp),
            "pred": statistics.mean(b["p"] for b in grp),
            "actual": hits / len(grp),
        })
    return rows


def analyze(acc, bets):
    settled = [b for b in bets if b["status"] == "settled"]
    open_bets = [b for b in bets if b["status"] == "open"]
    initial = acc["initial"]

    stake = sum(b["stake"] for b in settled)
    payout = sum(b.get("payout") or 0 for b in settled)
    hits = sum(1 for b in settled if (b.get("payout") or 0) > 0)
    dd, equity = max_drawdown(settled, initial)
    pending = sum(b["stake"] for b in open_bets)

    return {
        "initial": initial,
        "phase": acc.get("phase", 0),
        "n_settled": len(settled),
        "n_open": len(open_bets),
        "stake": stake,
        "payout": payout,
        "pnl": payout - stake,
        "roi": (payout / stake) if stake else None,
        "hit_rate": (hits / len(settled)) if settled else None,
        "avg_odds": statistics.mean([b["odds"] for b in settled]) if settled else None,
        "equity": equity,
        "available": equity - pending,
        "pending": pending,
        "max_drawdown": dd,
        "roi_ci": bootstrap_roi_ci(settled),
        "calibration": calibration(settled),
    }


def discipline_check(r):
    """運用憲法への抵触チェック。数字で切るためのもの。"""
    issues = []
    if r["max_drawdown"] >= 0.30:
        issues.append(f"【キルスイッチ】最大ドローダウンが {r['max_drawdown']*100:.1f}% に達しています。"
                      "運用を停止し、キャリブレーションから再検証してください")
    elif r["max_drawdown"] >= 0.20:
        issues.append(f"最大ドローダウン {r['max_drawdown']*100:.1f}%。30%で停止規定に抵触します")

    if r["n_settled"] >= 200 and r["roi"] is not None and r["roi"] < 0.95:
        issues.append(f"200ベット以上で回収率 {r['roi']*100:.1f}%。この戦略は棄却対象です")

    for row in r["calibration"]:
        if row["n"] >= 20 and row["pred"] - row["actual"] > 0.10:
            issues.append(f"確率{row['range']}帯で予測 {row['pred']*100:.0f}% に対し実績 "
                          f"{row['actual']*100:.0f}%。この帯の見積もりが構造的に楽観的です")

    ci = r["roi_ci"]
    if r["n_settled"] >= 100 and ci and ci[0] >= 0.90 and r["phase"] == 0:
        issues.append("Phase 1（小資金実運用）への移行条件を満たしています")
    return issues


# ---------------------------------------------------------------- 表示

def render(r, issues):
    L = []
    a = L.append
    a("=" * 62)
    a(f"  馬券投資 運用レポート        Phase {r['phase']}")
    a("=" * 62)
    a(f"初期資金       : {r['initial']:>12,.0f} 円")
    a(f"現在資金       : {r['equity']:>12,.0f} 円  ({(r['equity']/r['initial']-1)*100:+.1f}%)")
    if r["pending"]:
        a(f"  うち未決済拘束: {r['pending']:>12,.0f} 円（{r['n_open']}件）")
        a(f"  投下可能資金  : {r['available']:>12,.0f} 円")
    a("")
    a(f"決済済ベット数 : {r['n_settled']:>12,d} 件")
    if r["n_settled"]:
        a(f"総投下         : {r['stake']:>12,.0f} 円")
        a(f"総払戻         : {r['payout']:>12,.0f} 円")
        a(f"収支           : {r['pnl']:>+12,.0f} 円")
        a(f"回収率         : {r['roi']*100:>11.1f} %")
        a(f"的中率         : {r['hit_rate']*100:>11.1f} %")
        a(f"平均オッズ     : {r['avg_odds']:>11.1f} 倍")
        a(f"最大DD         : {r['max_drawdown']*100:>11.1f} %")

    a("")
    ci = r["roi_ci"]
    if ci:
        a(f"回収率の95%信頼区間: {ci[0]*100:.1f}% 〜 {ci[1]*100:.1f}%")
        if ci[0] > 1.0:
            a("  -> 下限が100%を超えています。運では説明しづらい水準です")
        elif ci[1] < 1.0:
            a("  -> 上限が100%未満。負けていることが統計的に示されています")
        else:
            a("  -> 区間が100%をまたいでいます。まだ運と区別がつきません（判断保留）")
    else:
        a(f"回収率の信頼区間: サンプル不足（20件以上必要 / 現在 {r['n_settled']}件）")

    a("")
    a("【キャリブレーション】自分の見積もりは正直か")
    if r["calibration"]:
        a("  " + pad("確率帯", 10) + pad("件数", 6, True) + pad("予測", 9, True)
          + pad("実績", 9, True) + pad("乖離", 10, True))
        for row in r["calibration"]:
            gap = row["actual"] - row["pred"]
            a("  " + pad(row["range"], 10) + pad(row["n"], 6, True)
              + pad(f"{row['pred']*100:.1f}%", 9, True)
              + pad(f"{row['actual']*100:.1f}%", 9, True)
              + pad(f"{gap*100:+.1f}pt", 10, True))
    else:
        a("  データなし（記帳時に --p を必ず入れてください）")

    a("")
    if issues:
        a("【規律チェック】")
        for i in issues:
            a(f"  - {i}")
    else:
        a("【規律チェック】抵触なし")
    a("=" * 62)
    return "\n".join(L)


# ---------------------------------------------------------------- コマンド

def cmd_init(args):
    if os.path.exists(ACCOUNT) and not args.force:
        raise SystemExit("すでに初期化済みです。上書きするなら --force")
    save_account({
        "initial": args.bankroll,
        "phase": args.phase,
        "created": args.date or date.today().isoformat(),
        "currency": "JPY",
    })
    if not os.path.exists(BETS):
        open(BETS, "a", encoding="utf-8").close()
    print(f"初期化しました: 資金 {args.bankroll:,.0f}円 / Phase {args.phase}")
    print(f"  {ACCOUNT}")
    print(f"  {BETS}")


def cmd_bet(args):
    acc = load_account()
    bets = load_bets()
    r = analyze(acc, bets)

    if args.stake > r["available"]:
        raise SystemExit(f"投下可能資金 {r['available']:,.0f}円 を超えています（要求 {args.stake:,.0f}円）")

    stake = int(round(args.stake))
    ratio = stake / r["equity"] if r["equity"] > 0 else 1.0
    bet = {
        "id": (max((b["id"] for b in bets), default=0) + 1),
        "date": args.date or date.today().isoformat(),
        "race": args.race,
        "race_id": args.race_id,   # あると run.py settle が自動決済できる
        "type": args.type,
        "sel": args.sel,
        "odds": args.odds,
        "stake": stake,
        "p": args.p,
        "ev": (args.p * args.odds) if args.p is not None else None,
        "why": args.why,
        "status": "open",
        "payout": None,
    }
    append_bet(bet)
    print(f"#{bet['id']} 記帳: {bet['race']} {bet['type']} {bet['sel']} "
          f"@{bet['odds']} / {bet['stake']:,}円（資金の {ratio*100:.2f}%）")
    if bet["ev"] is not None:
        print(f"  期待値 {bet['ev']*100:.1f}%")
        if bet["ev"] < 1.10:
            print("  ※ 期待値110%未満。運用方針では見送り対象です")
    if ratio > 0.05:
        print("  ※ 1レース5%上限を超えています")
    if stake % 100 != 0:
        print("  ※ 100円単位になっていません（実際には購入できない金額です）")
    if not args.why:
        print("  ※ エッジの根拠(--why)が未記入です。"
              "後で検証できないベットは学習データになりません")


def cmd_settle(args):
    bets = load_bets()
    target = next((b for b in bets if b["id"] == args.id), None)
    if target is None:
        raise SystemExit(f"ID {args.id} が見つかりません")
    if target["status"] == "settled" and not args.force:
        raise SystemExit(f"ID {args.id} は決済済みです（上書きは --force）")
    payout = int(round(args.payout))
    target["payout"] = payout
    target["status"] = "settled"
    write_bets(bets)
    pnl = payout - target["stake"]
    mark = "的中" if payout > 0 else "不的中"
    print(f"#{args.id} {mark}: 払戻 {payout:,}円 / 収支 {pnl:+,}円")


def cmd_open(args):
    bets = [b for b in load_bets() if b["status"] == "open"]
    if not bets:
        print("未決済のベットはありません")
        return
    print(pad("ID", 4, True) + "  " + pad("日付", 12) + pad("レース", 22)
          + pad("買い目", 16) + pad("オッズ", 8, True) + pad("賭け金", 11, True))
    print("-" * 74)
    for b in bets:
        print(pad(b["id"], 4, True) + "  " + pad(b["date"], 12) + pad(b["race"], 22)
              + pad(f"{b['type']} {b['sel']}", 16)
              + pad(f"{b['odds']:.1f}", 8, True)
              + pad(f"{int(b['stake']):,d}円", 11, True))


def cmd_report(args):
    acc = load_account()
    bets = load_bets()
    r = analyze(acc, bets)
    issues = discipline_check(r)
    if args.json:
        print(json.dumps({"summary": r, "issues": issues}, ensure_ascii=False, indent=2))
    else:
        print(render(r, issues))


def cmd_phase(args):
    acc = load_account()
    old = acc.get("phase", 0)
    acc["phase"] = args.set
    save_account(acc)
    print(f"Phase {old} -> {args.set}")
    print("※ フェーズ変更の理由を portfolio/POLICY.md に必ず追記してください")


def main():
    ap = argparse.ArgumentParser(description="馬券投資の資金台帳")
    sub = ap.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("init", help="口座を初期化する")
    i.add_argument("--bankroll", type=float, required=True)
    i.add_argument("--phase", type=int, default=0)
    i.add_argument("--date", default=None)
    i.add_argument("--force", action="store_true")
    i.set_defaults(func=cmd_init)

    b = sub.add_parser("bet", help="ベットを記帳する（購入前に実行）")
    b.add_argument("--race", required=True)
    b.add_argument("--race-id", default=None,
                   help="netkeibaのrace_id。入れておくと run.py settle が自動決済する")
    b.add_argument("--type", required=True, help="単勝 / 複勝 / 馬連 など")
    b.add_argument("--sel", required=True, help="買い目（馬番など）")
    b.add_argument("--odds", type=float, required=True)
    b.add_argument("--stake", type=float, required=True)
    b.add_argument("--p", type=float, default=None, help="自分の的中確率（0〜1）※検証の要")
    b.add_argument("--why", default="", help="市場が見落としていると考える理由")
    b.add_argument("--date", default=None)
    b.set_defaults(func=cmd_bet)

    s = sub.add_parser("settle", help="結果を反映する")
    s.add_argument("--id", type=int, required=True)
    s.add_argument("--payout", type=float, required=True, help="払戻総額（外れは0）")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_settle)

    o = sub.add_parser("open", help="未決済ベット一覧")
    o.set_defaults(func=cmd_open)

    r = sub.add_parser("report", help="運用レポート")
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_report)

    p = sub.add_parser("phase", help="運用フェーズを変更する")
    p.add_argument("--set", type=int, required=True)
    p.set_defaults(func=cmd_phase)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)
