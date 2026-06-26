"""当日予想の Web ビューア(ブラウザ版)。

  python -m keiba.web --db /data/keiba.db --port 8000

機能:
  * 当日全レースの勝率予想(本命=モデル1位)を一画面表示
  * 買い目提案(本命 + EV妙味馬)
  * 予想 vs 当日結果の比較(確定レースは着順を色付け、本命の的中/複勝圏を判定)
  * 一定間隔の自動更新(ページ自動リロード + 裏で最新オッズ/結果を再取り込み)

起動時に一度だけ学習(当日は学習から除外=リーク防止)。以後は再学習せず再採点。

⚠ 検証前モデルのペーパートレード。お金を賭ける根拠にはしないこと。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import threading
import time

import numpy as np
import pandas as pd
from flask import Flask, redirect, render_template_string

from .features import build_features
from .ingest import IngestBackend, validate_runners
from .model import ModelConfig
from .predict import PredictConfig, fit_predictor, predict_day

app = Flask(__name__)

JYO = {"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
       "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}

STATE = {"db": None, "kind": "sqlite", "predictor": None, "pred": None,
         "updated": None, "issues": [], "building": False, "error": None,
         "objective": "binary", "ev": 1.15, "refresh_sec": 90}
_LOCK = threading.Lock()


def _race_label(race_id) -> str:
    s = str(race_id).zfill(12)
    venue = JYO.get(s[4:6], s[4:6])
    try:
        rn = int(s[10:12])
    except ValueError:
        rn = s[10:12]
    return f"{venue} {rn}R"


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
        if retrain or STATE["predictor"] is None:
            STATE["predictor"] = fit_predictor(
                feat, ModelConfig(objective=STATE["objective"]),
                PredictConfig(ev_threshold=STATE["ev"]))
        pred = predict_day(STATE["predictor"], feat)
        with _LOCK:
            STATE["pred"] = pred
            STATE["issues"] = issues
            STATE["updated"] = _dt.datetime.now().strftime("%H:%M:%S")
            STATE["error"] = None
    except Exception as exc:  # pragma: no cover
        with _LOCK:
            STATE["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        with _LOCK:
            STATE["building"] = False


def _build_view(pred: pd.DataFrame) -> dict:
    """pred(predict_day の出力)から表示用の構造を組む。"""
    races, suggestions = [], []
    fin = win = top3 = 0
    roi_stake = roi_ret = 0.0
    for rid, g in pred.groupby("race_id", sort=False):
        g = g.sort_values("rank")
        finished = bool(g["race_finished"].iloc[0])
        pick = g.iloc[0]
        status, pick_fin = "発走前", None
        if finished:
            fin += 1
            fp = pick["finish_pos"]
            pick_fin = None if fp != fp else int(fp)
            won = pick_fin == 1
            placed = pick_fin is not None and pick_fin <= 3
            win += int(won); top3 += int(placed)
            if pick["odds"] == pick["odds"]:
                roi_stake += 1.0
                roi_ret += float(pick["odds"]) if won else 0.0
            status = "的中" if won else ("複勝圏" if placed else "外")
        rows = []
        for _, h in g.head(10).iterrows():
            fp = h["finish_pos"]
            rows.append({
                "rank": int(h["rank"]),
                "post": "-" if h["post_position"] != h["post_position"] else str(int(h["post_position"])),
                "win": float(h["win_prob"]),
                "odds": "-" if h["odds"] != h["odds"] else f"{h['odds']:.1f}",
                "ev": "-" if h["ev"] != h["ev"] else f"{h['ev']:.2f}",
                "ev_hi": (h["ev"] == h["ev"]) and float(h["ev"]) >= 1.0,
                "bet": bool(h["bet"]),
                "fin": None if fp != fp else int(fp),
                "pick": int(h["rank"]) == 1,
            })
        races.append({"race_id": rid, "label": _race_label(rid), "finished": finished,
                      "status": status, "pick_post": rows[0]["post"], "rows": rows})
        # 提案: 本命 + EV妙味
        sug = {"label": _race_label(rid), "honmei": rows[0],
               "value": [r for r in rows if r["bet"]]}
        suggestions.append(sug)
    summary = {
        "finished": fin,
        "win_rate": (win / fin) if fin else None,
        "top3_rate": (top3 / fin) if fin else None,
        "honmei_roi": (roi_ret / roi_stake) if roi_stake else None,
        "win": win, "top3": top3,
    }
    return {"races": races, "suggestions": suggestions, "summary": summary}


PAGE = """
<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{% if refresh_sec %}<meta http-equiv="refresh" content="{{refresh_sec}}">{% endif %}
<title>keiba 当日予想</title>
<style>
 :root{--bg:#0f1115;--card:#171a21;--line:#2a2f3a;--mut:#9aa4b2}
 body{font-family:system-ui,'Segoe UI',sans-serif;margin:0;background:var(--bg);color:#e6e6e6}
 header{position:sticky;top:0;background:#141821;padding:10px 16px;border-bottom:1px solid var(--line);z-index:9}
 h1{font-size:17px;margin:0} .sub{font-size:12px;color:var(--mut)}
 .wrap{max-width:1080px;margin:0 auto;padding:12px 16px 56px}
 .warn{background:#3a2a12;color:#ffce8a;padding:8px 12px;border-radius:8px;font-size:12px;margin:8px 0}
 .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;margin-top:12px}
 .race{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
 .race h2{font-size:14px;margin:0 0 6px;color:#cdd6e3;display:flex;justify-content:space-between;align-items:center}
 .badge{font-size:11px;padding:2px 8px;border-radius:999px;font-weight:700}
 .b-pre{background:#222733;color:#9aa4b2} .b-win{background:#10391f;color:#5ee08a}
 .b-top3{background:#3a3413;color:#ffe08a} .b-miss{background:#3a1b1b;color:#ff9a9a}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th,td{padding:4px 6px;text-align:right} th{color:#8a93a3;font-weight:600;border-bottom:1px solid var(--line)}
 td.l,th.l{text-align:left}
 tr.pick td{border-top:1px solid #2f5a3a} tr.pick{box-shadow:inset 3px 0 0 #2a6df4}
 tr.bet{background:#13301c} .mk{color:#5ee08a;font-weight:700}
 .ev-hi{color:#5ee08a} .ev-lo{color:var(--mut)}
 .fin{display:inline-block;min-width:20px;text-align:center;border-radius:5px;font-weight:700}
 .f1{background:#caa700;color:#1a1a1a} .f2{background:#9fb0c2;color:#1a1a1a} .f3{background:#b08552;color:#1a1a1a}
 .fx{color:var(--mut)}
 .barwrap{display:inline-block;width:54px;height:8px;background:#222733;border-radius:4px;vertical-align:middle;margin-right:6px;overflow:hidden}
 .bar{height:100%;background:#2a6df4}
 a.btn{display:inline-block;background:#2a6df4;color:#fff;text-decoration:none;padding:6px 12px;border-radius:8px;font-size:13px}
 .panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:10px 0}
 .sum{display:flex;gap:18px;flex-wrap:wrap;font-size:13px} .sum b{font-size:18px;color:#fff}
 .sug{font-size:13px;line-height:1.9} .sug .v{color:#5ee08a;font-weight:700}
 .foot{color:var(--mut);font-size:11px;margin-top:18px;line-height:1.7}
</style></head><body>
<header>
  <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
    <div><h1>🐴 keiba 当日予想 <span class="sub">(ペーパートレード)</span></h1>
      <div class="sub">更新 {{updated or '—'}}{% if building %} ・<b style="color:#ffce8a">更新中…</b>{% endif %}
        ・{{refresh_sec}}秒ごと自動更新</div></div>
    <a class="btn" href="/refresh">今すぐ更新</a>
  </div>
</header>
<div class="wrap">
  {% if error %}<div class="warn">エラー: {{error}}</div>{% endif %}
  {% if issues %}<div class="warn">注意: {{issues|join(' / ')}}</div>{% endif %}

  {% if summary.finished %}
  <div class="panel sum">
    <div>確定 <b>{{summary.finished}}</b> レース</div>
    <div>本命的中 <b>{{summary.win}}</b> <span class="sub">({{'%.0f'|format(summary.win_rate*100)}}%)</span></div>
    <div>本命 複勝圏 <b>{{summary.top3}}</b> <span class="sub">({{'%.0f'|format(summary.top3_rate*100)}}%)</span></div>
    {% if summary.honmei_roi is not none %}<div>本命 単勝ROI <b>{{'%.0f'|format(summary.honmei_roi*100)}}%</b> <span class="sub">(紙上)</span></div>{% endif %}
  </div>
  {% endif %}

  <div class="panel">
    <div style="font-weight:700;margin-bottom:4px">🎯 買い目提案</div>
    <div class="sug">
    {% for s in suggestions %}
      <div>{{s.label}} ｜ 本命 <b>{{s.honmei.post}}番</b> ({{'%.0f'|format(s.honmei.win*100)}}% / {{s.honmei.odds}}倍)
        {% if s.value %}— <span class="v">妙味 {% for v in s.value %}{{v.post}}番(EV{{v.ev}}) {% endfor %}</span>{% endif %}
      </div>
    {% endfor %}
    </div>
  </div>

  <div class="cards">
  {% for r in races %}
    <div class="race">
      <h2><span>{{r.label}} <span class="sub">#{{r.race_id}}</span></span>
        <span class="badge {{'b-win' if r.status=='的中' else 'b-top3' if r.status=='複勝圏' else 'b-miss' if r.status=='外' else 'b-pre'}}">{{r.status}}</span></h2>
      <table>
        <tr><th>予</th><th class="l">馬番</th><th>勝率</th><th>オッズ</th><th>EV</th>{% if r.finished %}<th>着</th>{% else %}<th></th>{% endif %}</tr>
        {% for h in r.rows %}
        <tr class="{{'pick ' if h.pick else ''}}{{'bet' if h.bet else ''}}">
          <td>{{h.rank}}</td>
          <td class="l">{{h.post}}{% if h.bet %} <span class="mk">◎</span>{% endif %}</td>
          <td><span class="barwrap"><span class="bar" style="width:{{(h.win*100)|round(0,'floor')}}%"></span></span>{{'%.1f'|format(h.win*100)}}%</td>
          <td>{{h.odds}}</td>
          <td class="{{'ev-hi' if h.ev_hi else 'ev-lo'}}">{{h.ev}}</td>
          {% if r.finished %}<td>{% if h.fin %}<span class="fin {{'f1' if h.fin==1 else 'f2' if h.fin==2 else 'f3' if h.fin==3 else 'fx'}}">{{h.fin}}</span>{% else %}<span class="fx">-</span>{% endif %}</td>{% else %}<td></td>{% endif %}
        </tr>
        {% endfor %}
      </table>
    </div>
  {% endfor %}
  </div>

  <div class="foot">
    ⚠ 検証前モデルの紙上テスト。回収率が控除率(単勝20%)を超える保証は無い。お金を賭ける根拠にはしないこと。<br>
    結果(着順)を出すには取得層で結果速報も回す: <code>jltsql realtime start --specs 0B12,0B15,0B30</code> → DBを更新後に自動反映。
  </div>
</div></body></html>
"""


@app.route("/")
def index():
    with _LOCK:
        pred = STATE["pred"]
        ctx = {k: STATE[k] for k in ("updated", "building", "error", "issues", "refresh_sec")}
    if pred is not None and len(pred):
        view = _build_view(pred)
    else:
        view = {"races": [], "suggestions": [], "summary": {"finished": 0}}
    return render_template_string(PAGE, **view, **ctx)


@app.route("/refresh")
def refresh():
    rebuild(retrain=False)
    return redirect("/")


def _auto_refresh_loop(interval: int):
    while True:
        time.sleep(interval)
        rebuild(retrain=False)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="keiba.web", description="当日予想の Web ビューア")
    p.add_argument("--db", required=True)
    p.add_argument("--db-kind", choices=["sqlite", "duckdb"], default="sqlite")
    p.add_argument("--objective", choices=["binary", "lambdarank"], default="binary")
    p.add_argument("--ev", type=float, default=1.15)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--refresh", type=int, default=90, help="自動更新の間隔(秒)")
    p.add_argument("--reingest", type=int, default=240, help="裏での再取り込み間隔(秒)")
    args = p.parse_args(argv)

    STATE.update(db=args.db, kind=args.db_kind, objective=args.objective,
                 ev=args.ev, refresh_sec=args.refresh)
    print("初回の学習中…(数分かかります)", flush=True)
    rebuild(retrain=True)
    print(f"準備完了。ブラウザで http://localhost:{args.port} を開いてください。", flush=True)
    t = threading.Thread(target=_auto_refresh_loop, args=(args.reingest,), daemon=True)
    t.start()
    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
