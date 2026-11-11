"""PDCA health check — is the live FX run tracking the backtest?

Reads the live run from SQLite (+ the live H1 bar feed if the EA bridge is up),
runs the validated strategy on the same recent bars to get the CURRENT call,
and prints a health report flagging drawdown breach / overtrading / execution
drift / insufficient data.

  py -3.12 -m scripts.run_monitor              # latest FX run
  py -3.12 -m scripts.run_monitor --run-id 7   # a specific run
  py -3.12 -m scripts.run_monitor --kind stocks

Run it whenever you review the system (the heart of the PDCA loop).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from app import bridge, db, monitor
from scripts.run_ai_bridge import LOCK_WAIT_LOG_EVERY_S, LOCK_WAIT_TICK_S
from app.config import Settings
from app.indicators import candles_to_df, enrich
from app.providers.csv import load_csv_file
from app.strategies.trend import TrendRegimeStrategy


def _timed_actions(run_id: int) -> list[tuple[str, str]]:
    """(time, action) of the decision log, oldest first, blocked rows skipped."""
    out = []
    for s in db.load_signals(run_id):
        if s.get("source") != "combined":
            continue
        try:
            comp = json.loads(s["components"]) if s.get("components") else {}
        except (json.JSONDecodeError, TypeError):
            comp = {}
        if comp.get("trigger") == "blocked-on-lock":
            continue
        out.append((str(s.get("time")), str(comp.get("action", "FLAT"))))
    return out


def _actions(run_id: int) -> list[str]:
    """The decision log, oldest first. A brain blocked on the lock writes
    'FLAT' blocked-on-lock rows while the book may still be LONG; they are not
    decisions (as in _last_decision_age_s), and counting them added two fake
    position changes to 取引頻度 per blocked spell (Round-9)."""
    out = []
    for s in db.load_signals(run_id):
        if s.get("source") != "combined":
            continue
        comp = {}
        try:
            comp = json.loads(s["components"]) if s.get("components") else {}
        except (json.JSONDecodeError, TypeError):
            comp = {}
        if comp.get("trigger") == "blocked-on-lock":
            continue
        out.append(str(comp.get("action", "FLAT")))
    return out


def _bars_age_h(candles) -> float | None:
    if not candles:
        return None
    t = candles[-1].time
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600.0


def _current_strategy_signal(cfg: Settings, instrument: str, history_csv: str) -> str | None:
    """What the trend filter says RIGHT NOW, from the live bar feed (or CSV)."""
    need = cfg.trend_sma + 5
    candles = bridge.read_bars(instrument, cfg.granularity)
    if len(candles) < need:
        # No silent fallback to the bundled CSV (round-6): a "trend basis"
        # computed from frozen data would explain a dead feed as an AI veto.
        print(f"[monitor] bar feed unavailable/short ({len(candles)} bars < {need}) — "
              f"trend basis not computed; is the EA exporting?")
        return None
    age = _bars_age_h(candles)
    limit = bridge.max_bar_age_h(candles[-1].time)
    if age is not None and age > limit:
        # The brain refuses these bars and goes blind; a trend basis from them
        # would describe a feed the system itself is not trading on (round-6f).
        print(f"[monitor] bars are {age:.0f}h old (> {limit:.0f}h): the brain "
              f"is blind on this feed — trend basis not computed")
        return None
    # The EA's last row is the still-forming bar; the brain decides on closed
    # bars only (Round-9), so the basis must too — else 執行一致 blames a dead
    # brain on every intrabar crossing.
    df = enrich(candles_to_df(candles[:-1]))
    sig = TrendRegimeStrategy(sma=cfg.trend_sma).generate(instrument, df)
    return "LONG" if sig.direction > 0 else "FLAT"


def _last_ai_binding(rid: int) -> bool | None:
    """Did the AI actually BIND the last decision? Only then may a trend/decision
    gap be attributed to an Opus veto (round-6: in shadow authority the note
    'Opus等でFLAT判断' was true in zero reachable cases)."""
    for s in reversed(db.load_signals(rid)):
        if s.get("source") != "combined":
            continue
        try:
            comp = json.loads(s["components"]) if s.get("components") else {}
        except (json.JSONDecodeError, TypeError):
            return None
        return bool(comp.get("ai_binding")) if "ai_binding" in comp else None
    return None


def _ea_build() -> str | None:
    """EA build tag from the status file: None = status unreadable (skip the
    check), "" = readable but no build column (an old EA -> RED)."""
    try:
        s = bridge.read_status()
    except Exception:
        return None
    if not s:
        return None
    return str(s.get("build") or "")


def _bridge_liveness() -> dict:
    """What the status file says about the EA being ALIVE, not just present.
    run_monitor read only position_lots/build and printed 🟢 執行一致 from a
    file the EA had stopped writing a day earlier (round-6f)."""
    out = {"missing": False, "age_s": None, "legacy": False}
    try:
        st = bridge.read_status()
    except Exception:
        st = None
    if not st:
        out["missing"] = True
        return out
    now = datetime.now(timezone.utc).timestamp()
    if st.get("ea_time") is not None:
        out["age_s"] = now - float(st["ea_time"])
    else:
        out["legacy"] = True
        try:
            out["age_s"] = now - (bridge.common_files_dir() / bridge.STATUS_FILE).stat().st_mtime
        except OSError:
            out["age_s"] = None
    return out


def _brain_liveness() -> dict:
    """The brain's own heartbeat, read the way the EA's is: from the file it
    writes. Nothing read this before round-7 — the only brain signal was the
    age of the newest DB row, and a brain wedged before the resident loop
    writes no rows at all, so a 68-hour outage looked like a quiet market."""
    out = {"signal_age_s": None, "expired": None}
    try:
        path = bridge.common_files_dir() / bridge.SIGNAL_FILE
        out["signal_age_s"] = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
        sig = bridge.read_signal()
        if sig and sig.get("expires_at"):
            out["expired"] = datetime.now(timezone.utc).timestamp() > float(sig["expires_at"])
    except OSError:
        pass
    return out


def _last_decision_age_s(rid: int) -> float | None:
    """Age of the newest real decision. A brain that is up but blocked writes
    only blocked-on-lock rows; those must not read as a decision."""
    for s in reversed(db.load_signals(rid)):
        if s.get("source") != "combined":
            continue
        try:
            comp = json.loads(s["components"]) if s.get("components") else {}
        except (json.JSONDecodeError, TypeError):
            comp = {}
        if comp.get("trigger") == "blocked-on-lock":
            continue
        try:
            t = datetime.fromisoformat(str(s.get("time")))
        except ValueError:
            return None
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds()
    return None


# A waiting brain writes a blocked-on-lock row every LOCK_WAIT_LOG_EVERY_S. An
# older one means the wait has ENDED (a takeover writes nothing until its next
# decision, up to the 20 h daily slot): it read 🔴「取引していません」 for hours
# while the brain traded, and the remedy it named could not clear it (Round-9
# second review). A brain that died while waiting is caught by its heartbeat.
BLOCKED_FRESH_S = 2 * LOCK_WAIT_LOG_EVERY_S + 2 * LOCK_WAIT_TICK_S


def _blocked_on_lock(rid: int, now: datetime | None = None) -> str | None:
    """The newest row's reason, if the brain is reporting itself blocked NOW."""
    now = now or datetime.now(timezone.utc)
    for s in reversed(db.load_signals(rid)):
        if s.get("source") != "combined":
            continue
        try:
            comp = json.loads(s["components"]) if s.get("components") else {}
        except (json.JSONDecodeError, TypeError):
            return None
        if comp.get("trigger") != "blocked-on-lock":
            return None
        try:
            t = datetime.fromisoformat(str(s.get("time")))
        except ValueError:
            return None
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if (now - t).total_seconds() > BLOCKED_FRESH_S:
            return None                     # the wait is over
        return str(s.get("reason") or "")
    return None


def _closed_bar_segment(rid: int, equity: list[dict]) -> dict:
    """The part of the run the envelope checks judge: from the first decision
    of the closed-bar brain (Round-9) on. The run that began in June mixes the
    forming-bar brain, which the envelopes exclude by design."""
    since = None
    for s in db.load_signals(rid):
        if s.get("source") != "combined":
            continue
        try:
            comp = json.loads(s["components"]) if s.get("components") else {}
        except (json.JSONDecodeError, TypeError):
            continue
        if comp.get("cadence") == "closed-bar":
            since = str(s.get("time"))
            break
    if since is None:
        return {"pending": True}
    eq = [e for e in equity if str(e["time"]) >= since]
    acts = [a for t, a in _timed_actions(rid) if t >= since]
    if len(eq) < 2:
        return {"pending": "one-row"}
    return {"equity_values": [e["equity"] for e in eq], "actions": acts, "since": since,
            "span_days": monitor.span_days_between(eq[0]["time"], eq[-1]["time"])}


def _live_position() -> str | None:
    try:
        s = bridge.read_status()
    except Exception:
        s = None
    if not s:
        return None
    lots = s.get("position_lots", 0.0) or 0.0
    return "LONG" if lots > 1e-9 else "FLAT"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", type=int, default=None)
    ap.add_argument("--kind", default="fx", choices=["fx", "stocks"])
    ap.add_argument("--instrument", default="USD_JPY")
    ap.add_argument("--granularity", default="H1")
    ap.add_argument("--sma", type=int, default=2400)
    ap.add_argument("--history", default="data/USD_JPY_H1.csv")
    args = ap.parse_args()

    db.init_db()
    rid = args.run_id or db.latest_live_run_id(args.kind)   # never a backtest row (round-6)
    if not rid:
        print(f"[monitor] {args.kind} のライブrunがまだありません。"); return
    run = db.get_run(rid)
    print(f"[monitor] run #{rid} mode={run.get('mode')} gran={run.get('granularity')} "
          f"started={str(run.get('started_at'))[:16]}")
    equity = db.load_equity(rid)
    if len(equity) < 2:
        print(f"[monitor] run #{rid}: エクイティ記録が少なすぎます（判断にはもう少し稼働が必要）。"); return

    eq_vals = [e["equity"] for e in equity]
    span = monitor.span_days_between(equity[0]["time"], equity[-1]["time"])
    staleness = monitor.span_days_between(equity[-1]["time"], datetime.now(timezone.utc))
    actions = _actions(rid)

    trend_basis = live_pos = None
    liveness = {"missing": False, "age_s": None, "legacy": False}
    brain = {"signal_age_s": None, "expired": None}
    bars_age = bars_count = bars_need = bars_limit = None
    if args.kind == "fx":
        cfg = Settings(granularity=args.granularity, trend_sma=args.sma)
        trend_basis = _current_strategy_signal(cfg, args.instrument, args.history)
        live_pos = _live_position()
        liveness = _bridge_liveness()
        brain = _brain_liveness()
        _bars = bridge.read_bars(args.instrument, args.granularity)
        bars_age = _bars_age_h(_bars)
        bars_limit = bridge.max_bar_age_h(_bars[-1].time) if _bars else None
        bars_count, bars_need = len(_bars), args.sma + 5

    rep = monitor.build_report(
        initial_balance=run["initial_balance"], equity_values=eq_vals,
        span_days=span, actions=actions, live_position=live_pos,
        trend_basis=trend_basis, staleness_days=staleness,
        last_ai_binding=_last_ai_binding(rid), ea_build=_ea_build(),
        status_missing=liveness["missing"], ea_status_age_s=liveness["age_s"],
        bars_age_h=bars_age, bars_count=bars_count, bars_need=bars_need,
        bars_limit_h=bars_limit,
        brain_signal_age_s=brain["signal_age_s"], signal_expired=brain["expired"],
        last_decision_age_s=_last_decision_age_s(rid), blocked_on_lock=_blocked_on_lock(rid),
        kind=args.kind,
        segment=_closed_bar_segment(rid, equity) if args.kind == "fx" else None)

    bal0 = rep["initial_balance"]; eq = rep["current_equity"]; s = rep["stats"]
    print("=" * 60)
    print(f" PDCA健康診断  run #{rid} · {run['instrument']} {run['granularity']}")
    print("=" * 60)
    print(f" 稼働 {span:.0f}日 ｜ 初期 ¥{bal0:,.0f} → 現在 ¥{eq:,.0f} ({s['return_pct']:+.1f}%)")
    print(f" 現在DD {s['cur_dd_pct']:.1f}% ｜ 期間中最大DD {s['max_dd_pct']:.1f}%")
    tpy = rep["trades_per_year"]                          # annualised only from 365 days
    print(f" 建玉変化（全期間） {rep['n_position_changes']}回／{span:.0f}日"
          + (f"（年率 {tpy:.0f}回）" if tpy is not None else ""))
    print("-" * 60)
    if args.kind == "fx":
        print(" 基準（バックテスト H1 2015-26/SMA2400/線形ランプ5x・スワップ別）: "
              f"年+{monitor.BT_CAGR_PCT:.0f}% / 最大DD {monitor.BT_MAXDD_PCT:.0f}%（警告線{monitor.EXP_MAXDD_PCT:.0f}%）/ "
              f"建玉変化 約{monitor.BT_CHANGES_PER_YEAR:.0f}回/年")
        print("   ※ 取引頻度・リターンは確定足方式（2026-11修正）の判断以降の区間だけを、同じ長さの期間の"
              "バックテスト／確定足リプレイと比較。円安が続いた好条件の11年なので、相場次第で下回りうる")
    print("-" * 60)
    for c in rep["checks"]:
        print(f"  {c['flag']} {c['name']:<6} {c['msg']}")
    print("-" * 60)
    print(f" 総合判定： {rep['verdict']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
