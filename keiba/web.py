"""当日予想の Web ビューア(ブラウザで見る版)。

学習済みモデルで当日カードを採点し、レースごとの勝率・オッズ・EV・買い目を
HTML で表示する。Docker でポート公開して http://localhost:8000 で開く。

  python -m keiba.web --db /data/keiba.db --port 8000

起動時に一度だけ学習(数分)。`更新`ボタンで最新オッズ/カードを再取り込みして
再採点する(モデルは再学習しない=速い)。

⚠ 検証前モデルのペーパートレード。お金を賭ける根拠にはしないこと。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import threading

from flask import Flask, redirect, render_template_string

from .features import build_features
from .ingest import IngestBackend, validate_runners
from .model import ModelConfig
from .predict import PredictConfig, fit_predictor, predict_upcoming, upcoming_rows

app = Flask(__name__)

# 競馬場コード → 名称
JYO = {"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
       "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}

STATE = {"db": None, "kind": "sqlite", "predictor": None, "pred": None,
         "updated": None, "issues": [], "n_races": 0, "n_runners": 0,
         "building": False, "error": None, "objective": "binary", "ev": 1.15}
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
    """DB を取り込み直し、(必要なら学習し、)当日カードを再採点する。"""
    with _LOCK:
        STATE["building"] = True
        STATE["error"] = None
    try:
        runners, _ = IngestBackend(STATE["db"], kind=STATE["kind"],
                                   include_realtime=True).load()
        issues = validate_runners(runners)
        feat = build_features(runners)
        card = upcoming_rows(feat)
        if retrain or STATE["predictor"] is None:
            STATE["predictor"] = fit_predictor(
                feat, ModelConfig(objective=STATE["objective"]),
                PredictConfig(ev_threshold=STATE["ev"]))
        pred = predict_upcoming(STATE["predictor"], feat)
        with _LOCK:
            STATE["pred"] = pred
            STATE["issues"] = issues
            STATE["n_races"] = int(card["race_id"].nunique())
            STATE["n_runners"] = int(len(card))
            STATE["updated"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            STATE["error"] = None
    except Exception as exc:  # pragma: no cover
        with _LOCK:
            STATE["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        with _LOCK:
            STATE["building"] = False


PAGE = """
<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>keiba 当日予想</title>
<style>
 body{font-family:system-ui,'Segoe UI',sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
 header{position:sticky;top:0;background:#171a21;padding:12px 16px;border-bottom:1px solid #2a2f3a;z-index:5}
 h1{font-size:18px;margin:0 0 4px} .sub{font-size:12px;color:#9aa4b2}
 .wrap{max-width:1000px;margin:0 auto;padding:12px 16px 48px}
 .warn{background:#3a2a12;color:#ffce8a;padding:8px 12px;border-radius:8px;font-size:12px;margin:8px 0}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
 .race{background:#171a21;border:1px solid #2a2f3a;border-radius:12px;padding:10px 12px}
 .race h2{font-size:14px;margin:0 0 6px;color:#cdd6e3}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th,td{padding:4px 6px;text-align:right} th{color:#8a93a3;font-weight:600;border-bottom:1px solid #2a2f3a}
 td.l,th.l{text-align:left}
 tr.bet{background:#13301c} .mk{color:#5ee08a;font-weight:700}
 .ev-hi{color:#5ee08a} .ev-lo{color:#9aa4b2}
 a.btn{display:inline-block;background:#2a6df4;color:#fff;text-decoration:none;padding:6px 12px;border-radius:8px;font-size:13px}
 .buys{background:#13301c;border:1px solid #245034;border-radius:10px;padding:8px 12px;margin:8px 0;font-size:13px}
 .foot{color:#9aa4b2;font-size:11px;margin-top:16px;line-height:1.6}
</style></head><body>
<header>
  <h1>🐴 keiba 当日予想 <span class="sub">(ペーパートレード)</span></h1>
  <div class="sub">
    更新: {{updated or '—'}} ／ 当日カード {{n_races}}レース {{n_runners}}頭
    {% if building %}・<b style="color:#ffce8a">更新中…</b>{% endif %}
    &nbsp; <a class="btn" href="/refresh">最新オッズで更新</a>
  </div>
</header>
<div class="wrap">
  {% if error %}<div class="warn">エラー: {{error}}</div>{% endif %}
  {% if issues %}<div class="warn">注意: {{issues|join(' / ')}}</div>{% endif %}
  {% if buys %}
    <div class="buys"><b>◎ 買い目(単勝 EV超え): {{buys|length}}点</b>
      {% for b in buys %}<span style="margin-right:10px">{{b.label}} {{b.post}}番 ({{'%.1f'|format(b.win*100)}}% / {{'%.1f'|format(b.odds)}}倍 / EV{{'%.2f'|format(b.ev)}})</span>{% endfor %}
    </div>
  {% else %}
    <div class="sub">EV閾値を超える買い目は今のところ無し(市場が効率的＝正直な結果)。勝率ランキングは下記。</div>
  {% endif %}
  <div class="grid">
  {% for r in races %}
    <div class="race"><h2>{{r.label}} <span class="sub">#{{r.race_id}}</span></h2>
      <table><tr><th>予</th><th class="l">馬番</th><th>勝率</th><th>オッズ</th><th>EV</th><th></th></tr>
      {% for h in r.rows %}
        <tr class="{{'bet' if h.bet else ''}}">
          <td>{{h.rank}}</td><td class="l">{{h.post}}</td>
          <td>{{'%.1f'|format(h.win*100)}}%</td>
          <td>{{h.odds}}</td>
          <td class="{{'ev-hi' if h.ev_num and h.ev_num>=1 else 'ev-lo'}}">{{h.ev}}</td>
          <td class="mk">{{'◎' if h.bet else ''}}</td>
        </tr>
      {% endfor %}
      </table>
    </div>
  {% endfor %}
  </div>
  <div class="foot">
    ⚠ これは検証前モデルの紙上テスト。回収率が控除率(単勝20%)を超える保証は無い。お金を賭ける根拠にはしないこと。<br>
    オッズは取り込み時点のスナップショット。発走が近づいたら「最新オッズで更新」を押す(取得層で realtime を回し DB を更新後)。
  </div>
</div></body></html>
"""


@app.route("/")
def index():
    with _LOCK:
        pred = STATE["pred"]
        ctx = {k: STATE[k] for k in ("updated", "n_races", "n_runners", "building", "error", "issues")}
    races, buys = [], []
    if pred is not None and len(pred):
        for rid, g in pred.groupby("race_id", sort=False):
            rows = []
            for _, h in g.head(8).iterrows():
                post = "-" if h["post_position"] != h["post_position"] else str(int(h["post_position"]))
                odds = "-" if h["odds"] != h["odds"] else f"{h['odds']:.1f}"
                ev = "-" if h["ev"] != h["ev"] else f"{h['ev']:.2f}"
                rows.append({"rank": int(h["rank"]), "post": post, "win": float(h["win_prob"]),
                             "odds": odds, "ev": ev, "ev_num": (None if h["ev"] != h["ev"] else float(h["ev"])),
                             "bet": bool(h["bet"])})
            races.append({"race_id": rid, "label": _race_label(rid), "rows": rows})
        for _, h in pred[pred["bet"]].iterrows():
            buys.append({"label": _race_label(h["race_id"]),
                         "post": "-" if h["post_position"] != h["post_position"] else str(int(h["post_position"])),
                         "win": float(h["win_prob"]), "odds": float(h["odds"]), "ev": float(h["ev"])})
    return render_template_string(PAGE, races=races, buys=buys, **ctx)


@app.route("/refresh")
def refresh():
    rebuild(retrain=False)
    return redirect("/")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="keiba.web", description="当日予想の Web ビューア")
    p.add_argument("--db", required=True)
    p.add_argument("--db-kind", choices=["sqlite", "duckdb"], default="sqlite")
    p.add_argument("--objective", choices=["binary", "lambdarank"], default="binary")
    p.add_argument("--ev", type=float, default=1.15)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)

    STATE.update(db=args.db, kind=args.db_kind, objective=args.objective, ev=args.ev)
    print("初回の学習中…(数分かかります)")
    rebuild(retrain=True)
    print(f"準備完了。ブラウザで http://localhost:{args.port} を開いてください。")
    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
