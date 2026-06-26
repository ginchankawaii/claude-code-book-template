"""当日予想 + 2026バックテストの Web ビューア(ブラウザ版)。

  python -m keiba.web --db /data/keiba.db --port 8000

構成:
  * モデルは「評価年(既定=データ最新年=2026)より前」で学習(アウトオブタイム)。
    → 今日のライブ予想も2026バックテストも、同じ blind なモデルで公正に評価。
  * ナビ: 日付 → 会場 → レース(過去の2026開催日も今日も同じ導線)。
  * 各レース: 勝率予想 + 買い方提案(根拠コメント・各券種の的中確率/妙味目安・単勝EV)
    + 確定済みなら着順を色分けして「予想 vs 結果」。
  * /summary: 2026通算の本命的中率・単勝回収率・月別推移など。
  * 今日(最新日)は一定間隔で自動更新。

⚠ 検証前モデルのペーパートレード。お金を賭ける根拠にはしないこと。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import threading
import time

import numpy as np
import pandas as pd
from flask import Flask, redirect, render_template_string, url_for

from .betadvice import advise_race
from .features import build_features
from .ingest import IngestBackend, validate_runners
from .model import ModelConfig
from .predict import PredictConfig, fit_predictor, predict_range

app = Flask(__name__)

JYO = {"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
       "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}
WD = "月火水木金土日"

STATE = {"db": None, "kind": "sqlite", "predictor": None, "pred": None,
         "updated": None, "issues": [], "building": False, "error": None,
         "objective": "binary", "ev": 1.15, "refresh_sec": 90, "cutoff": None,
         "today": None}
_LOCK = threading.Lock()


def _venue(race_id) -> str:
    return JYO.get(str(race_id).zfill(12)[4:6], "?")


def _racenum(race_id) -> int:
    try:
        return int(str(race_id).zfill(12)[10:12])
    except ValueError:
        return 0


def _date_label(ordinal) -> str:
    try:
        d = _dt.date.fromordinal(int(ordinal))
        return f"{d.month}/{d.day}({WD[d.weekday()]})"
    except Exception:
        return str(ordinal)


def rebuild(retrain: bool = False) -> None:
    with _LOCK:
        if STATE["building"]:
            return
        STATE["building"] = True
    try:
        runners, _ = IngestBackend(STATE["db"], kind=STATE["kind"],
                                   include_realtime=True).load()
        issues = validate_runners(runners)
        feat = build_features(runners)
        # 評価年(最新年)の元旦を学習カットオフに(アウトオブタイム)
        max_ord = int(feat["race_date"].max())
        year = _dt.date.fromordinal(max_ord).year
        cutoff = _dt.date(year, 1, 1).toordinal()
        if retrain or STATE["predictor"] is None:
            STATE["predictor"] = fit_predictor(
                feat, ModelConfig(objective=STATE["objective"]),
                PredictConfig(ev_threshold=STATE["ev"]), eval_date=cutoff)
        pred = predict_range(STATE["predictor"], feat, cutoff, max_ord + 1)
        with _LOCK:
            STATE["pred"] = pred
            STATE["issues"] = issues
            STATE["cutoff"] = cutoff
            STATE["today"] = max_ord
            STATE["updated"] = _dt.datetime.now().strftime("%H:%M:%S")
            STATE["error"] = None
    except Exception as exc:  # pragma: no cover
        with _LOCK:
            STATE["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        with _LOCK:
            STATE["building"] = False


# ---------------------------------------------------------------------------
# ビュー構築
# ---------------------------------------------------------------------------

def _nav_days(pred: pd.DataFrame):
    """日付→会場 のナビ構造。新しい日付が先頭。"""
    days = []
    for od, g in sorted(pred.groupby("race_date"), key=lambda kv: kv[0], reverse=True):
        venues = sorted({_venue(r) for r in g["race_id"].unique()})
        days.append({"ord": int(od), "label": _date_label(od), "venues": venues})
    return days


def _row_view(h) -> dict:
    fp = h["finish_pos"]
    return {
        "rank": int(h["rank"]),
        "post": "-" if h["post_position"] != h["post_position"] else str(int(h["post_position"])),
        "win": float(h["win_prob"]),
        "odds": "-" if h["odds"] != h["odds"] else f"{h['odds']:.1f}",
        "ev": "-" if h["ev"] != h["ev"] else f"{h['ev']:.2f}",
        "ev_hi": (h["ev"] == h["ev"]) and float(h["ev"]) >= 1.0,
        "bet": bool(h["bet"]),
        "fin": None if fp != fp else int(fp),
        "pick": int(h["rank"]) == 1,
    }


def _day_view(pred: pd.DataFrame, day_ord: int) -> dict:
    sub = pred[pred["race_date"] == day_ord]
    venues = {}
    for rid, g in sub.groupby("race_id", sort=False):
        g = g.sort_values("rank")
        finished = bool(g["race_finished"].iloc[0])
        pick = g.iloc[0]
        status = "発走前"
        if finished:
            fp = pick["finish_pos"]
            pf = None if fp != fp else int(fp)
            status = "的中" if pf == 1 else ("複勝圏" if (pf is not None and pf <= 3) else "外")
        adv = advise_race(g)
        race = {"race_id": rid, "num": _racenum(rid), "label": f"{_venue(rid)} {_racenum(rid)}R",
                "finished": finished, "status": status,
                "rows": [_row_view(h) for _, h in g.head(8).iterrows()],
                "advice": adv}
        venues.setdefault(_venue(rid), []).append(race)
    for v in venues:
        venues[v].sort(key=lambda r: r["num"])
    ordered = [{"venue": v, "races": venues[v]} for v in sorted(venues)]
    return {"day_ord": day_ord, "day_label": _date_label(day_ord), "venues": ordered,
            "is_today": day_ord == STATE["today"]}


def _summary_view(pred: pd.DataFrame) -> dict:
    fin = pred[pred["race_finished"]]
    out = {"n_races": int(pred["race_id"].nunique()),
           "n_finished": int(fin["race_id"].nunique()), "months": []}
    if fin.empty:
        return out
    picks = fin[fin["rank"] == 1].copy()
    picks["won"] = (picks["finish_pos"] == 1)
    picks["top3"] = picks["finish_pos"] <= 3
    picks["ret"] = np.where(picks["won"], picks["odds"].fillna(0.0), 0.0)
    n = len(picks)
    out["honmei_win"] = float(picks["won"].mean())
    out["honmei_top3"] = float(picks["top3"].mean())
    staked = picks["odds"].notna().sum()
    out["honmei_roi"] = float(picks.loc[picks["odds"].notna(), "ret"].sum() / staked) if staked else None
    # EVフィルタ買い目(単勝)の回収率
    out["ev_n"], out["ev_roi"], out["ev_hit"] = 0, None, None
    bets = fin[fin["bet"]]
    if len(bets):
        bret = (bets["finish_pos"] == 1).astype(float) * bets["odds"].fillna(0.0)
        out["ev_n"] = int(len(bets))
        out["ev_roi"] = float(bret.sum() / len(bets))
        out["ev_hit"] = float((bets["finish_pos"] == 1).mean())
    # 月別
    picks["month"] = picks["race_date"].map(lambda o: _dt.date.fromordinal(int(o)).month)
    for m, g in picks.groupby("month"):
        st = g["odds"].notna().sum()
        out["months"].append({
            "month": int(m), "n": int(len(g)),
            "win": float(g["won"].mean()),
            "roi": float(g.loc[g["odds"].notna(), "ret"].sum() / st) if st else None,
        })
    return out


# ---------------------------------------------------------------------------
# テンプレート
# ---------------------------------------------------------------------------

BASE_CSS = """
 :root{--bg:#0f1115;--card:#171a21;--line:#2a2f3a;--mut:#9aa4b2;--accent:#2a6df4}
 *{box-sizing:border-box} body{font-family:system-ui,'Segoe UI',sans-serif;margin:0;background:var(--bg);color:#e6e6e6}
 a{color:#7fb0ff;text-decoration:none} a:hover{text-decoration:underline}
 header{position:sticky;top:0;background:#141821;padding:10px 16px;border-bottom:1px solid var(--line);z-index:9}
 h1{font-size:16px;margin:0} .sub{font-size:12px;color:var(--mut)}
 .wrap{max-width:1120px;margin:0 auto;padding:12px 16px 56px}
 .nav{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}
 .nav a{background:#222733;padding:5px 10px;border-radius:999px;font-size:12px;color:#cdd6e3}
 .nav a.on{background:var(--accent);color:#fff}
 .nav a .v{color:var(--mut);font-size:11px}
 .warn{background:#3a2a12;color:#ffce8a;padding:8px 12px;border-radius:8px;font-size:12px;margin:8px 0}
 .vsec{margin-top:14px} .vsec h2{font-size:15px;margin:0 0 6px;color:#cdd6e3;border-left:3px solid var(--accent);padding-left:8px}
 .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}
 .race{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
 .race h3{font-size:14px;margin:0 0 6px;display:flex;justify-content:space-between;align-items:center}
 .badge{font-size:11px;padding:2px 8px;border-radius:999px;font-weight:700}
 .b-pre{background:#222733;color:#9aa4b2} .b-win{background:#10391f;color:#5ee08a}
 .b-top3{background:#3a3413;color:#ffe08a} .b-miss{background:#3a1b1b;color:#ff9a9a}
 table{width:100%;border-collapse:collapse;font-size:13px} th,td{padding:3px 6px;text-align:right}
 th{color:#8a93a3;font-weight:600;border-bottom:1px solid var(--line)} td.l,th.l{text-align:left}
 tr.pick{box-shadow:inset 3px 0 0 var(--accent)} tr.bet{background:#13301c} .mk{color:#5ee08a;font-weight:700}
 .ev-hi{color:#5ee08a} .ev-lo{color:var(--mut)}
 .barwrap{display:inline-block;width:46px;height:7px;background:#222733;border-radius:4px;vertical-align:middle;margin-right:5px;overflow:hidden}
 .bar{height:100%;background:var(--accent)}
 .fin{display:inline-block;min-width:18px;text-align:center;border-radius:5px;font-weight:700;font-size:12px}
 .f1{background:#caa700;color:#1a1a1a} .f2{background:#9fb0c2;color:#1a1a1a} .f3{background:#b08552;color:#1a1a1a} .fx{color:var(--mut)}
 .adv{margin-top:6px;font-size:12px;background:#10141b;border:1px solid var(--line);border-radius:8px;padding:6px 8px;line-height:1.6}
 .adv .ty{color:#ffd479;font-weight:700} .adv .ex{color:var(--mut)} .adv .ex b{color:#cdd6e3}
 .panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:10px 0}
 .sum{display:flex;gap:18px;flex-wrap:wrap;font-size:13px} .sum b{font-size:18px;color:#fff}
 a.btn{display:inline-block;background:var(--accent);color:#fff;padding:6px 12px;border-radius:8px;font-size:13px}
 .foot{color:var(--mut);font-size:11px;margin-top:18px;line-height:1.7}
"""

LAYOUT = """
<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{% if auto and refresh_sec %}<meta http-equiv="refresh" content="{{refresh_sec}}">{% endif %}
<title>keiba 予想</title><style>{{css}}</style></head><body>
<header>
  <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
    <div><h1>🐴 keiba 予想 <span class="sub">(ペーパートレード)</span></h1>
      <div class="sub">更新 {{updated or '—'}}{% if building %} ・<b style="color:#ffce8a">更新中…</b>{% endif %}
        ・<a href="{{url_for('summary')}}">2026通算成績</a></div></div>
    <a class="btn" href="{{url_for('refresh')}}">今すぐ更新</a>
  </div>
  <div class="nav">
    {% for d in days %}<a class="{{'on' if d.ord==cur_ord else ''}}" href="{{url_for('day', ordinal=d.ord)}}">{{d.label}} <span class="v">{{d.venues|join('・')}}</span></a>{% endfor %}
  </div>
</header>
<div class="wrap">
  {% if error %}<div class="warn">エラー: {{error}}</div>{% endif %}
  {% if issues %}<div class="warn">注意: {{issues|join(' / ')}}</div>{% endif %}
  {{ body|safe }}
  <div class="foot">⚠ 検証前モデルの紙上テスト。回収率が控除率を超える保証は無い。お金を賭ける根拠にはしないこと。<br>
    連系(馬連〜三連単)は的中確率と「妙味目安(◯倍以上で買い)」を表示。実オッズ(O2〜O6)接続後に実EVへ差し替え予定。<br>
    着順を出すには取得層で結果速報も回す: <code>jltsql realtime start --specs 0B12,0B15,0B30</code></div>
</div></body></html>
"""

DAY_BODY = """
{% macro race_card(r) %}
  <div class="race">
    <h3><span>{{r.label}}</span>
      <span class="badge {{'b-win' if r.status=='的中' else 'b-top3' if r.status=='複勝圏' else 'b-miss' if r.status=='外' else 'b-pre'}}">{{r.status}}</span></h3>
    <table><tr><th>予</th><th class="l">馬番</th><th>勝率</th><th>オッズ</th><th>EV</th>{% if r.finished %}<th>着</th>{% endif %}</tr>
    {% for h in r.rows %}
      <tr class="{{'pick ' if h.pick else ''}}{{'bet' if h.bet else ''}}">
        <td>{{h.rank}}</td><td class="l">{{h.post}}{% if h.bet %} <span class="mk">◎</span>{% endif %}</td>
        <td><span class="barwrap"><span class="bar" style="width:{{(h.win*100)|round(0,'floor')}}%"></span></span>{{'%.1f'|format(h.win*100)}}%</td>
        <td>{{h.odds}}</td><td class="{{'ev-hi' if h.ev_hi else 'ev-lo'}}">{{h.ev}}</td>
        {% if r.finished %}<td>{% if h.fin %}<span class="fin {{'f1' if h.fin==1 else 'f2' if h.fin==2 else 'f3' if h.fin==3 else 'fx'}}">{{h.fin}}</span>{% else %}<span class="fx">-</span>{% endif %}</td>{% endif %}
      </tr>
    {% endfor %}
    </table>
    <div class="adv"><span class="ty">{{r.advice.type}}</span> {{r.advice.comment}}
      <div class="ex" style="margin-top:4px">
        {% for e in r.advice.exotic %}<b>{{e.kind}}</b> {{e.sel}} 的中{{'%.1f'|format(e.prob*100)}}% <span style="color:#7fb0ff">妙味{{'%.0f'|format(e.fair)}}倍↑</span>　{% endfor %}
      </div>
    </div>
  </div>
{% endmacro %}
<h2 style="margin:6px 0">{{view.day_label}} {% if view.is_today %}<span class="sub">(本日・自動更新)</span>{% endif %}</h2>
{% for v in view.venues %}
  <div class="vsec"><h2>{{v.venue}}</h2><div class="cards">
    {% for r in v.races %}{{ race_card(r) }}{% endfor %}
  </div></div>
{% endfor %}
"""

SUMMARY_BODY = """
<h2>2026 通算成績(アウトオブタイム・紙上)</h2>
{% if s.n_finished %}
<div class="panel sum">
  <div>対象 <b>{{s.n_finished}}</b> / {{s.n_races}} レース(確定)</div>
  <div>本命的中 <b>{{'%.1f'|format(s.honmei_win*100)}}%</b></div>
  <div>本命複勝圏 <b>{{'%.1f'|format(s.honmei_top3*100)}}%</b></div>
  {% if s.honmei_roi is not none %}<div>本命 単勝回収率 <b>{{'%.0f'|format(s.honmei_roi*100)}}%</b></div>{% endif %}
  {% if s.ev_roi is not none %}<div>EV買い目 回収率 <b>{{'%.0f'|format(s.ev_roi*100)}}%</b> <span class="sub">({{s.ev_n}}点/的中{{'%.0f'|format(s.ev_hit*100)}}%)</span></div>{% endif %}
</div>
<div class="panel">
  <div style="font-weight:700;margin-bottom:6px">月別(本命単勝)</div>
  <table style="max-width:520px"><tr><th class="l">月</th><th>レース</th><th>的中率</th><th>回収率</th></tr>
  {% for m in s.months %}<tr><td class="l">{{m.month}}月</td><td>{{m.n}}</td><td>{{'%.1f'|format(m.win*100)}}%</td><td>{% if m.roi is not none %}{{'%.0f'|format(m.roi*100)}}%{% else %}-{% endif %}</td></tr>{% endfor %}
  </table>
</div>
<div class="sub">※ 本命=モデル予想1位を単勝で1点買いし続けた紙上成績。回収率100%が損益分岐。控除率20%の壁を越えるのは構造的に難しい(リサーチ参照)。</div>
{% else %}
<div class="sub">確定済みの2026レースがまだありません(結果速報の取り込み後に集計されます)。</div>
{% endif %}
"""


def _render(body_html, cur_ord, auto=False):
    with _LOCK:
        pred = STATE["pred"]
        ctx = {k: STATE[k] for k in ("updated", "building", "error", "issues", "refresh_sec")}
    days = _nav_days(pred) if pred is not None and len(pred) else []
    return render_template_string(LAYOUT, css=BASE_CSS, body=body_html, days=days,
                                  cur_ord=cur_ord, auto=auto, url_for=url_for, **ctx)


@app.route("/")
def index():
    with _LOCK:
        today = STATE["today"]
    if today is None:
        return _render("<div class='sub'>準備中…</div>", None)
    return redirect(url_for("day", ordinal=today))


@app.route("/day/<int:ordinal>")
def day(ordinal: int):
    with _LOCK:
        pred = STATE["pred"]; today = STATE["today"]
    if pred is None or len(pred) == 0:
        return _render("<div class='sub'>準備中…</div>", ordinal)
    view = _day_view(pred, ordinal)
    body = render_template_string(DAY_BODY, view=view)
    return _render(body, ordinal, auto=(ordinal == today))


@app.route("/summary")
def summary():
    with _LOCK:
        pred = STATE["pred"]
    s = _summary_view(pred) if pred is not None and len(pred) else {"n_finished": 0, "n_races": 0}
    body = render_template_string(SUMMARY_BODY, s=s)
    return _render(body, None)


@app.route("/refresh")
def refresh():
    rebuild(retrain=False)
    return redirect(url_for("index"))


def _auto_refresh_loop(interval: int):
    while True:
        time.sleep(interval)
        rebuild(retrain=False)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="keiba.web", description="当日予想+2026バックテストの Web ビューア")
    p.add_argument("--db", required=True)
    p.add_argument("--db-kind", choices=["sqlite", "duckdb"], default="sqlite")
    p.add_argument("--objective", choices=["binary", "lambdarank"], default="binary")
    p.add_argument("--ev", type=float, default=1.15)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--refresh", type=int, default=90)
    p.add_argument("--reingest", type=int, default=240)
    args = p.parse_args(argv)
    STATE.update(db=args.db, kind=args.db_kind, objective=args.objective,
                 ev=args.ev, refresh_sec=args.refresh)
    print("初回の学習中…(2026を除外して学習・数分)", flush=True)
    rebuild(retrain=True)
    print(f"準備完了。ブラウザで http://localhost:{args.port} を開いてください。", flush=True)
    threading.Thread(target=_auto_refresh_loop, args=(args.reingest,), daemon=True).start()
    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
