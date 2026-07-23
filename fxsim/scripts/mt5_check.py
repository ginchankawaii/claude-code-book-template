"""MT5 connection diagnostic — pinpoint why initialize() fails.

Run on Windows with the MT5 terminal open + logged in:
    python -m scripts.mt5_check
"""
from __future__ import annotations

import os


def main() -> None:
    try:
        import MetaTrader5 as mt5
    except Exception as exc:
        print("MetaTrader5 import FAILED:", exc); return
    print("MetaTrader5 package version:", getattr(mt5, "__version__", "?"))
    print("author/version tuple:", mt5.__author__ if hasattr(mt5, "__author__") else "")

    path = os.getenv("MT5_PATH") or None
    print(f"\n--- attempt A: initialize() with NO path (attach to running terminal) ---")
    ok = mt5.initialize(timeout=60000)
    print("initialize ->", ok, "| last_error:", mt5.last_error())
    if not ok and path:
        mt5.shutdown()
        print(f"\n--- attempt B: initialize(path={path!r}) ---")
        ok = mt5.initialize(path=path, timeout=60000)
        print("initialize ->", ok, "| last_error:", mt5.last_error())

    if ok:
        ti = mt5.terminal_info()
        ai = mt5.account_info()
        print("\nCONNECTED ✅")
        print("terminal connected:", getattr(ti, "connected", "?"),
              "| trade_allowed:", getattr(ti, "trade_allowed", "?"),
              "| build:", getattr(mt5.version(), "__getitem__", lambda *_: '?'))
        print("terminal version():", mt5.version())
        print("terminal data path:", getattr(ti, "data_path", "?"))
        print("account:", getattr(ai, "login", "?"), "balance:", getattr(ai, "balance", "?"),
              "server:", getattr(ai, "server", "?"))
        for sym in ("USDJPY", "USDJPY.sml"):
            si = mt5.symbol_info(sym)
            print(f"symbol {sym}:", "FOUND" if si else "not found")
        mt5.shutdown()
    else:
        print("\nSTILL FAILING ❌  — share this whole output.")


if __name__ == "__main__":
    main()
