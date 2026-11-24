"""Fetch historical FX candles from stooq.com and save as data/<INSTRUMENT>.csv.

stooq serves free daily OHLC history as a one-shot CSV download, e.g.
    https://stooq.com/q/d/l/?s=usdjpy&i=d
This requires the environment's network allowlist to include stooq.com
(Custom network access). It is reachable only from a session started AFTER the
allowlist change — not the session in which the change was made.

Usage:
    python -m scripts.fetch_stooq                # USD_JPY daily -> data/USD_JPY.csv
    python -m scripts.fetch_stooq --instrument EUR_USD
    python -m scripts.fetch_stooq --interval d   # d=daily (free & reliable for FX)

The saved file is picked up by the CSV provider (FXSIM_PROVIDER=csv).
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def stooq_symbol(instrument: str) -> str:
    """USD_JPY -> usdjpy (stooq FX symbol convention)."""
    return instrument.replace("_", "").lower()


def fetch(instrument: str, interval: str) -> str:
    sym = stooq_symbol(instrument)
    url = f"https://stooq.com/q/d/l/?s={sym}&i={interval}"
    req = urllib.request.Request(url, headers={"User-Agent": "fxsim/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default="USD_JPY")
    ap.add_argument("--interval", default="d", help="d=daily (recommended)")
    args = ap.parse_args()

    try:
        text = fetch(args.instrument, args.interval)
    except Exception as exc:  # network / allowlist problems
        print(f"[fetch] download failed: {exc}", file=sys.stderr)
        return 2

    head = text.lstrip()[:60].lower()
    if "host not in allowlist" in head:
        print("[fetch] BLOCKED: add 'stooq.com' to the environment's Custom "
              "network allowlist, then start a NEW session and retry.", file=sys.stderr)
        return 3
    if not head.startswith("date") or "exceeded" in head:
        print(f"[fetch] unexpected response (rate-limited or empty?):\n{text[:200]}",
              file=sys.stderr)
        return 4

    rows = [ln for ln in text.splitlines() if ln.strip()]
    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / f"{args.instrument}.csv"
    out.write_text(text, encoding="utf-8")
    first = rows[1].split(",")[0] if len(rows) > 1 else "?"
    last = rows[-1].split(",")[0] if len(rows) > 1 else "?"
    print(f"[fetch] saved {len(rows)-1} {args.interval}-bars to {out}")
    print(f"[fetch] range: {first} -> {last}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
