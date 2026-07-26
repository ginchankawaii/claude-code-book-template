#!/usr/bin/env python3
"""期待値・ケリー基準による賭け金計算。標準ライブラリのみ。

サブコマンド:
  market  オッズ列 -> 控除率を除去した市場の暗黙確率
  quick   単発の期待値とケリー賭け金
  plan    レース定義JSON -> 買い目ごとの期待値と推奨賭け金

オッズは日本式の「元返し込み」小数オッズ（単勝4.5倍なら100円が450円になる）を前提とする。
"""

import argparse
import json
import sys
import unicodedata

UNIT = 100  # JRAの最小購入単位（円）


def width(s):
    """端末上の表示幅。日本語は全角で2文字分を占めるため、len()では桁が揃わない。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s, n, right=False):
    """表示幅ベースで揃える。"""
    s = str(s)
    fill = " " * max(0, n - width(s))
    return fill + s if right else s + fill


# ---------------------------------------------------------------- 市場確率

def implied_probs(odds, takeout=None, tau=1.0):
    """オッズ列から市場の暗黙確率を求める。

    生の 1/odds の総和は 1/(1-控除率) 付近になる（テラ銭の分だけ1を超える）。
    総和で割って正規化することで控除率を取り除く。

    tau は本命-大穴バイアス補正の指数。p ∝ (1/odds)^tau として再正規化する。
    tau>1 は人気薄の確率を割り引く方向。ただし日本の市場でこのバイアスが
    有意に存在するかは議論があるため、既定は 1.0（＝補正なし）。
    自分のデータで検証できるまで、安易に動かさないこと。
    """
    raw = [(1.0 / o) ** tau for o in odds]
    s = sum(raw)
    if s <= 0:
        raise ValueError("オッズが不正です")
    probs = [r / s for r in raw]
    booksum = sum(1.0 / o for o in odds)
    実効控除率 = 1.0 - 1.0 / booksum if booksum > 0 else None
    return probs, 実効控除率


# ---------------------------------------------------------------- ケリー

def kelly_single(p, o):
    """独立した1点賭けのケリー比率。b=o-1 として f=(p*b-(1-p))/b。"""
    b = o - 1.0
    if b <= 0:
        return 0.0
    f = (p * o - 1.0) / b
    return max(0.0, f)


def kelly_exclusive(cands):
    """同時に1つしか的中しない買い目群（同一レースの単勝など）の同時ケリー配分。

    Smoczynski & Tomkins (2010) の解法。期待収益率 p*o の高い順に候補を並べ、
    採用集合 S_t に対する閾値
        b_t = (1 - Σ_{i∈S_t} p_i) / (1 - Σ_{i∈S_t} 1/o_i)
    を計算し、p_t*o_t > b_t を満たす最大の t を採用集合とする。
    そのとき最適比率は f_i = p_i - b_k/o_i。

    独立ケリーを各馬に個別適用すると、同一レースで同時に外れる相関を無視して
    過剰に賭けることになるため、単勝の複数点買いでは必ずこちらを使う。

    cands: [{"p":..., "odds":...}, ...] （並び順は問わない）
    戻り値: 元の順序に対応する比率リスト
    """
    idx = sorted(range(len(cands)), key=lambda i: cands[i]["p"] * cands[i]["odds"], reverse=True)
    cum_p = 0.0
    cum_inv = 0.0
    best_k = 0
    best_b = None
    for t, i in enumerate(idx, start=1):
        c = cands[i]
        cum_p += c["p"]
        cum_inv += 1.0 / c["odds"]
        denom = 1.0 - cum_inv
        if denom <= 1e-12:
            break  # これ以上採用すると閾値が定義できない
        b_t = (1.0 - cum_p) / denom
        if c["p"] * c["odds"] > b_t:
            best_k = t
            best_b = b_t
        else:
            break

    fractions = [0.0] * len(cands)
    if best_k == 0 or best_b is None:
        return fractions
    for t, i in enumerate(idx, start=1):
        if t > best_k:
            break
        c = cands[i]
        fractions[i] = max(0.0, c["p"] - best_b / c["odds"])
    return fractions


# ---------------------------------------------------------------- プラン

def build_plan(cfg):
    bankroll = float(cfg["bankroll"])
    frac = float(cfg.get("kelly_fraction", 0.25))
    max_exp = float(cfg.get("max_race_exposure", 0.05))
    min_ev = float(cfg.get("min_ev", 1.10))
    exclusive = bool(cfg.get("exclusive", True))
    takeout = cfg.get("takeout")
    cands = cfg["candidates"]

    for c in cands:
        c["odds"] = float(c["odds"])
        c["p"] = float(c["p"])
        c["ev"] = c["p"] * c["odds"]

    # 市場の暗黙確率（参考値）。全出走馬のオッズが揃っている時のみ意味を持つ
    market, 実効控除率 = implied_probs([c["odds"] for c in cands])
    for c, m in zip(cands, market):
        c["market_p"] = m

    p_sum = sum(c["p"] for c in cands)

    # 期待値閾値でふるいにかける（見積もり誤差のバッファ）
    live = [c for c in cands if c["ev"] >= min_ev]

    if not live:
        fractions = {id(c): 0.0 for c in cands}
    elif exclusive:
        fr = kelly_exclusive([{"p": c["p"], "odds": c["odds"]} for c in live])
        fractions = {id(c): f for c, f in zip(live, fr)}
    else:
        fractions = {id(c): kelly_single(c["p"], c["odds"]) for c in live}

    # フラクショナル・ケリー
    for c in cands:
        c["kelly_raw"] = fractions.get(id(c), 0.0)
        c["kelly"] = c["kelly_raw"] * frac

    # レース単位の投下上限で頭打ち（超過分は比例縮小）
    total = sum(c["kelly"] for c in cands)
    capped = False
    if total > max_exp and total > 0:
        scale = max_exp / total
        for c in cands:
            c["kelly"] *= scale
        capped = True

    # 100円単位に切り捨て
    for c in cands:
        raw_stake = c["kelly"] * bankroll
        c["stake"] = int(raw_stake // UNIT) * UNIT

    return {
        "race": cfg.get("race", ""),
        "bet_type": cfg.get("bet_type", ""),
        "bankroll": bankroll,
        "kelly_fraction": frac,
        "min_ev": min_ev,
        "exclusive": exclusive,
        "candidates": cands,
        "takeout_declared": takeout,
        "takeout_implied": 実効控除率,
        "prob_sum": p_sum,
        "capped": capped,
        "total_stake": sum(c["stake"] for c in cands),
    }


def render_plan(plan):
    out = []
    a = out.append
    a(f"レース : {plan['race']}   券種: {plan['bet_type']}")
    a(f"資金   : {plan['bankroll']:,.0f}円   ケリー係数: {plan['kelly_fraction']}   EV閾値: {plan['min_ev']:.2f}")
    if plan["takeout_implied"] is not None:
        a(f"オッズから逆算した実効控除率: {plan['takeout_implied']*100:.1f}%")
    a("")
    a(pad("買い目", 24) + pad("オッズ", 8, True) + pad("自確率", 8, True)
      + pad("市場", 8, True) + pad("EV", 8, True) + pad("ケリー", 9, True)
      + pad("賭け金", 11, True))
    a("-" * 76)
    for c in plan["candidates"]:
        mark = "  <=" if c["stake"] > 0 else ""
        a(pad(c.get("label", "?"), 24)
          + pad(f"{c['odds']:.1f}", 8, True)
          + pad(f"{c['p']*100:.1f}%", 8, True)
          + pad(f"{c['market_p']*100:.1f}%", 8, True)
          + pad(f"{c['ev']:.2f}", 8, True)
          + pad(f"{c['kelly']*100:.2f}%", 9, True)
          + pad(f"{c['stake']:,d}円", 11, True) + mark)
    a("-" * 76)
    a(f"合計投下: {plan['total_stake']:,}円 "
      f"（資金の {plan['total_stake']/plan['bankroll']*100:.2f}%）")

    a("")
    warn = []
    ps = plan["prob_sum"]
    if abs(ps - 1.0) > 0.02 and plan["exclusive"]:
        warn.append(f"自分の確率の合計が {ps:.3f} です。排他的な買い目では1.0に正規化してください"
                    "（そうでないと期待値が全部ずれます）")
    if plan["capped"]:
        warn.append("ケリーの示す額がレース上限を超えたため縮小しました。"
                    "確率見積もりが楽観的すぎないか点検してください")
    if plan["total_stake"] == 0:
        warn.append("賭ける根拠がありません。見送りが正しい結論です")
    for c in plan["candidates"]:
        if c["stake"] > 0 and c["p"] > 0.6:
            warn.append(f"{c.get('label')} の確率 {c['p']*100:.0f}% は非常に強い主張です。"
                        "根拠を再確認してください")
    if warn:
        a("【注意】")
        for w in warn:
            a(f"  - {w}")
    return "\n".join(out)


# ---------------------------------------------------------------- CLI

def cmd_market(args):
    probs, to = implied_probs(args.odds, tau=args.tau)
    print(f"{'オッズ':>8}{'市場確率':>10}")
    print("-" * 18)
    for o, p in zip(args.odds, probs):
        print(f"{o:>8.1f}{p*100:>9.1f}%")
    print("-" * 18)
    if to is not None:
        print(f"オッズから逆算した実効控除率: {to*100:.1f}%")
    if args.takeout is not None and to is not None:
        if abs(to - args.takeout) > 0.03:
            print(f"※ 指定控除率 {args.takeout*100:.1f}% と乖離しています。"
                  "オッズが全出走馬分そろっているか確認してください")


def cmd_threshold(args):
    """各馬について「賭けるために必要な確信の水準」を出す。

    オッズしか手元に無い段階で唯一できる、意味のある作業がこれ。
    自分の確率を市場から作ることはできない（それでは期待値が控除率の分だけ
    必ずマイナスになる）が、「どこまで強気になれば買えるか」という
    判断の敷居は、オッズだけから確定的に決まる。

    必要確率 = min_ev / オッズ。
    これを市場の暗黙確率と比べた倍率は
        必要確率 / 市場確率 = min_ev × Σ(1/オッズ)
    となり、実は全馬で同じ値になる。控除率と要求期待値だけで決まるためで、
    「どの馬を選ぶか」以前に、市場よりどれだけ強気である必要があるかが
    この一つの数字に集約される。
    """
    odds = args.odds
    labels = args.labels or [f"{i+1}" for i in range(len(odds))]
    if len(labels) != len(odds):
        raise ValueError("--labels の数が --odds と一致しません")
    market, to = implied_probs(odds)
    booksum = sum(1.0 / o for o in odds)
    ratio = args.min_ev * booksum

    print(f"要求期待値 {args.min_ev*100:.0f}%  /  実効控除率 {to*100:.1f}%")
    print(f"→ どの馬でも、市場の見立ての {ratio:.2f}倍 の勝率を確信できなければ買えない")
    print()
    print(pad("馬", 22) + pad("オッズ", 8, True) + pad("市場確率", 10, True)
          + pad("必要確率", 10, True))
    print("-" * 50)
    order = sorted(range(len(odds)), key=lambda i: odds[i])
    for i in order:
        need = args.min_ev / odds[i]
        print(pad(labels[i], 22) + pad(f"{odds[i]:.1f}", 8, True)
              + pad(f"{market[i]*100:.1f}%", 10, True)
              + pad(f"{need*100:.1f}%", 10, True))
    print("-" * 50)
    print("※ 必要確率は「賭けてよい下限」であって、予測値ではない。")
    print("  市場を見ずに出した自分の確率がこれを超えた馬だけが買い目になる。")


def cmd_quick(args):
    ev = args.p * args.odds
    f = kelly_single(args.p, args.odds) * args.fraction
    stake = int((f * args.bankroll) // UNIT) * UNIT
    print(f"期待値（回収率換算）: {ev*100:.1f}%   エッジ: {(ev-1)*100:+.1f}%")
    print(f"フルケリー: {kelly_single(args.p, args.odds)*100:.2f}%  "
          f"-> {args.fraction}ケリー: {f*100:.2f}%")
    print(f"推奨賭け金: {stake:,}円（資金 {args.bankroll:,.0f}円）")
    if ev < 1.10:
        print("※ 期待値が110%未満です。見積もり誤差に飲まれる領域なので、原則見送り")


def cmd_plan(args):
    with open(args.file, encoding="utf-8") as f:
        cfg = json.load(f)
    plan = build_plan(cfg)
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2, default=str))
    else:
        print(render_plan(plan))


def main():
    ap = argparse.ArgumentParser(description="競馬の期待値・ケリー計算")
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("market", help="オッズから市場の暗黙確率を出す")
    m.add_argument("--odds", type=float, nargs="+", required=True)
    m.add_argument("--takeout", type=float, default=None, help="想定控除率（検算用・例 0.20）")
    m.add_argument("--tau", type=float, default=1.0, help="本命-大穴バイアス補正指数（既定1.0=補正なし）")
    m.set_defaults(func=cmd_market)

    t = sub.add_parser("threshold", help="各馬を買うために必要な確率の下限を出す")
    t.add_argument("--odds", type=float, nargs="+", required=True)
    t.add_argument("--labels", nargs="+", default=None)
    t.add_argument("--min-ev", dest="min_ev", type=float, default=1.10)
    t.set_defaults(func=cmd_threshold)

    q = sub.add_parser("quick", help="単発の期待値とケリー")
    q.add_argument("--p", type=float, required=True, help="自分の的中確率（0〜1）")
    q.add_argument("--odds", type=float, required=True)
    q.add_argument("--bankroll", type=float, required=True)
    q.add_argument("--fraction", type=float, default=0.25)
    q.set_defaults(func=cmd_quick)

    p = sub.add_parser("plan", help="レース定義JSONから買い目プランを作る")
    p.add_argument("--file", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_plan)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, FileNotFoundError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)
    except BrokenPipeError:
        # `| head` などで出力を打ち切られた場合。異常ではない
        try:
            sys.stdout.close()
        finally:
            sys.exit(0)
