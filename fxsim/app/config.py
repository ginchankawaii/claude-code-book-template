"""Central configuration.

Values are read from environment variables (see .env.example) so the same
code path works for offline backtests and live OANDA paper trading.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Auto-load fxsim/.env (and cwd .env) so credentials work without manual sourcing
# on Windows. Must run before Settings() reads the environment below.
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
    load_dotenv()
except Exception:
    pass

DEFAULT_DB_PATH = DATA_DIR / "fxsim.db"


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class Settings:
    # --- storage ---
    db_path: str = field(default_factory=lambda: os.getenv("FXSIM_DB", str(DEFAULT_DB_PATH)))

    # --- market data / broker (OANDA v20) ---
    data_provider: str = field(default_factory=lambda: os.getenv("FXSIM_PROVIDER", "sample"))
    oanda_token: str = field(default_factory=lambda: os.getenv("OANDA_API_TOKEN", ""))
    oanda_account: str = field(default_factory=lambda: os.getenv("OANDA_ACCOUNT_ID", ""))
    # "practice" (demo) or "live". We only ever READ prices; fills are simulated.
    oanda_env: str = field(default_factory=lambda: os.getenv("OANDA_ENV", "practice"))

    instruments: list[str] = field(
        default_factory=lambda: _get_list("FXSIM_INSTRUMENTS", ["USD_JPY"])
    )
    # H1 is the OOS-validated aggressive default (docs/RESEARCH.md, research_run8).
    granularity: str = field(default_factory=lambda: os.getenv("FXSIM_GRANULARITY", "H1"))

    # --- account / risk ---
    # Default account = ¥500k. JPY (quote currency for USD_JPY).
    initial_balance: float = field(default_factory=lambda: _get_float("FXSIM_BALANCE", 500_000.0))
    risk_per_trade: float = field(default_factory=lambda: _get_float("FXSIM_RISK", 0.04))
    max_position_units: int = field(
        default_factory=lambda: int(_get_float("FXSIM_MAX_UNITS", 100_000))
    )
    # Hard leverage ceiling: notional (units * price) may never exceed
    # max_leverage * equity, regardless of risk_per_trade or ATR. This is both
    # the "aggression dial" and a safety brake — without it a small ATR (e.g.
    # intraday, or the old fixed-rate era) lets risk-based sizing explode to
    # absurd leverage. Set 0 to disable. docs/RESEARCH.md has the return/DD
    # trade-off across leverage levels.
    max_leverage: float = field(default_factory=lambda: _get_float("FXSIM_MAX_LEVERAGE", 5.0))
    # Conviction-scaled leverage: within the SAME hard max_leverage cap, pull
    # exposure down toward dyn_lev_floor when price drifts back toward the trend
    # SMA (the whipsaw zone), full cap when the trend is well established. Cuts
    # max drawdown ~34%->26% at equal-or-higher CAGR, robust OOS (docs/RESEARCH.md,
    # app/sizing.conviction_leverage). ON by default; set FXSIM_DYN_LEVERAGE=0 for
    # the old flat-cap behaviour. Never raises leverage above max_leverage.
    dyn_leverage: bool = field(
        default_factory=lambda: os.getenv("FXSIM_DYN_LEVERAGE", "1") not in ("0", "false", "")
    )
    # Ramp width: full cap once price is this many ATRs above the SMA (1.5 = the
    # robust central pick from the parameter sweep).
    dyn_lev_atr_mult: float = field(default_factory=lambda: _get_float("FXSIM_DYN_LEV_ATR", 1.5))
    # Floor leverage when price sits right at the SMA (1x = conservative but held).
    dyn_lev_floor: float = field(default_factory=lambda: _get_float("FXSIM_DYN_LEV_FLOOR", 1.0))
    # Ramp shape exponent on strength (2.0 = convex: stay near the floor until the
    # trend is well established, load up late — round-2 winner, docs/RESEARCH.md:
    # Sharpe 0.83->0.89, maxDD 26.7->24.6 at equal CAGR, robust across p 1.3-3.0
    # and 3x costs). 1.0 = the round-1 linear ramp.
    dyn_lev_pow: float = field(default_factory=lambda: _get_float("FXSIM_DYN_LEV_POW", 2.0))
    # cost model
    spread_pips: float = field(default_factory=lambda: _get_float("FXSIM_SPREAD_PIPS", 0.8))
    commission_per_million: float = field(
        default_factory=lambda: _get_float("FXSIM_COMMISSION", 50.0)
    )

    # --- strategy weights ---
    technical_weight: float = field(default_factory=lambda: _get_float("FXSIM_W_TECH", 0.6))
    fundamental_weight: float = field(default_factory=lambda: _get_float("FXSIM_W_FUND", 0.4))
    entry_threshold: float = field(default_factory=lambda: _get_float("FXSIM_ENTRY_TH", 0.20))
    exit_threshold: float = field(default_factory=lambda: _get_float("FXSIM_EXIT_TH", 0.08))
    # Fixed 2:1 take-profit suits mean-reversion but caps trend winners short.
    # Default OFF: the trend edge needs winners to run (exits via signal/stop).
    use_take_profit: bool = field(
        default_factory=lambda: os.getenv("FXSIM_USE_TAKE_PROFIT", "0") not in ("0", "false", "")
    )

    # --- fundamental analyzer ---
    # "stub" (neutral), "file" (data/fundamental.json), or "anthropic" (live LLM).
    # Default "stub": the shipped default reduces to the bare trend edge offline
    # (no static sample bias polluting it). Set "anthropic" (+ key) for the real
    # Opus news/macro bias at the key moments.
    fundamental_mode: str = field(
        default_factory=lambda: os.getenv("FXSIM_FUND_MODE", "stub")
    )
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(
        default_factory=lambda: os.getenv("FXSIM_FUND_MODEL", "claude-opus-4-8")
    )

    # --- strategy selection --------------------------------------------------
    # "ai" (trend edge + Opus/event overlay, default), "trend" (bare filter),
    # "combined"/"off" (plain technical+fundamental blend).
    strategy: str = field(default_factory=lambda: os.getenv("FXSIM_STRATEGY", "ai"))
    # ~100-day trend filter on H1 bars — the OOS-validated edge (research_run8).
    trend_sma: int = field(default_factory=lambda: int(_get_float("FXSIM_TREND_SMA", 2400)))
    # What the AI layer uses as its technical base signal:
    #   "trend"     = the validated trend filter (default; the actual edge)
    #   "technical" = the mechanical MA/MACD/RSI/BB ensemble (loses OOS — legacy)
    ai_base: str = field(default_factory=lambda: os.getenv("FXSIM_AI_BASE", "trend"))

    # --- AI decision layer ---------------------------------------------------
    # Who makes the final call:
    #   "rule"      = deterministic, offline-capable risk-aware decider
    #   "anthropic" = Claude weighs technicals + fundamentals + events and decides
    #   "hybrid"    = rule for free on quiet bars; consult Opus only at the moments
    #                 that matter (actionable / borderline / disagreement / event),
    #                 as a veto-only gate. Falls back to rule with no API key.
    # Default "hybrid": keep the Opus fundamental/event check "for the key moments"
    # while staying offline-safe and cheap.
    decision_mode: str = field(
        default_factory=lambda: os.getenv("FXSIM_DECISION_MODE", "hybrid")
    )
    decision_model: str = field(
        default_factory=lambda: os.getenv("FXSIM_DECISION_MODEL", "claude-opus-4-8")
    )
    # Economic-calendar backend: "file" (data/calendar.json), "stub", "anthropic"
    calendar_mode: str = field(
        default_factory=lambda: os.getenv("FXSIM_CALENDAR_MODE", "file")
    )
    # Stand aside this many minutes on EITHER side of a high-impact event.
    event_blackout_min: float = field(
        default_factory=lambda: _get_float("FXSIM_EVENT_BLACKOUT_MIN", 60.0)
    )
    # Trim conviction when a high-impact event is within this many minutes ahead.
    event_caution_min: float = field(
        default_factory=lambda: _get_float("FXSIM_EVENT_CAUTION_MIN", 360.0)
    )

    @property
    def oanda_host(self) -> str:
        # explicit override wins (e.g. OANDA Japan / a regional v20 endpoint)
        override = os.getenv("FXSIM_OANDA_HOST", "").strip()
        if override:
            return override.rstrip("/")
        if self.oanda_env == "live":
            return "https://api-fxtrade.oanda.com"
        return "https://api-fxpractice.oanda.com"


settings = Settings()


def pip_size(instrument: str) -> float:
    """Pip size for an instrument. JPY pairs quote to 0.01, others to 0.0001."""
    return 0.01 if instrument.endswith("JPY") else 0.0001
