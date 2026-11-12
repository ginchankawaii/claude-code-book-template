"""Central configuration.

Values are read from environment variables (see .env.example) so the same
code path works for offline backtests and live OANDA paper trading.
"""
from __future__ import annotations

import os
import unicodedata
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


def _norm(raw: str) -> str:
    """NFKC so a full-width '２．５' left by a Japanese IME parses as 2.5, and
    strip stray quotes/spaces. The owner edits .env on a Japanese keyboard."""
    return unicodedata.normalize("NFKC", raw).strip().strip('"').strip("'")


def _get_float(name: str, default: float) -> float:
    """Read a float from the environment. A value that does not parse is LOUD,
    never silent: round-7 found that a typo in FXSIM_MAX_LEVERAGE silently
    restored the shipped MAXIMUM of 5.0 — the dial the owner reached for to
    reduce risk failed OPEN."""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(_norm(raw))
    except ValueError:
        print(f"[cfg] WARNING: {name}={raw!r} is not a number — using the default "
              f"{default}. Fix .env: this is NOT the value you set.", flush=True)
        return default


_TRUE_WORDS = {"1", "true", "on", "yes", "y"}
_FALSE_WORDS = {"0", "false", "off", "no", "n"}


def _get_bool(name: str, default: bool) -> bool:
    """Read an on/off dial. NFKC + case-folded like the float dials: the raw
    comparison read a full-width '０' (Japanese IME), 'off' or 'False' as ON —
    FXSIM_DD_BRAKE=off switched the brake on and FXSIM_DYN_LEVERAGE=off left
    the ramp on (Round-10B). Anything else is LOUD and keeps the default."""
    raw = os.getenv(name)
    if raw is None:
        return default
    v = _norm(raw).lower()
    if v == "":
        return default
    if v in _TRUE_WORDS:
        return True
    if v in _FALSE_WORDS:
        return False
    print(f"[cfg] WARNING: {name}={raw!r} is not on/off (1/0) — using the default "
          f"{'1' if default else '0'}. Fix .env: this is NOT the value you set.", flush=True)
    return default


# I2: in the live system notional never exceeds this multiple of equity.
LEVERAGE_CEILING = 5.0


def _get_leverage_cap(name: str = "FXSIM_MAX_LEVERAGE", default: float = 5.0) -> float:
    """The hard leverage ceiling, always a real cap in (0, LEVERAGE_CEILING].

    The sizing code reads a cap of 0 or below as NO cap — risk-based sizing then
    set 10-25x at a 272,000 JPY account — and .env.example said '0 disables',
    so a value typed to mean 'off' or 'no leverage' did the opposite
    (Round-10B). Zero, negative or NaN is refused LOUDLY and becomes 1.0, the
    least exposure the ramp knows; above the ceiling it is held at the ceiling.
    Explicit Settings(max_leverage=...) in tests and research is untouched."""
    v = _get_float(name, default)
    if not (v > 0):                                   # 0, negative, NaN
        print(f"[cfg] WARNING: {name}={os.getenv(name)!r} would REMOVE the leverage cap — "
              f"using 1.0. Allowed: above 0, at most {LEVERAGE_CEILING:g}.", flush=True)
        return 1.0
    if v > LEVERAGE_CEILING:
        print(f"[cfg] WARNING: {name}={os.getenv(name)!r} is above the hard ceiling — "
              f"using {LEVERAGE_CEILING:g}.", flush=True)
        return LEVERAGE_CEILING
    return v


_AUTHORITIES = ("shadow", "entry", "full")


def _get_authority(name: str = "FXSIM_AI_AUTHORITY") -> str:
    """shadow / entry / full, case- and width-insensitive. An unknown value is
    LOUD and falls back to shadow: 'Shadow' used to be kept verbatim and took
    the non-shadow sizing branch (the AI's own conviction)."""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return "shadow"
    v = _norm(raw).lower()
    if v in _AUTHORITIES:
        return v
    print(f"[cfg] WARNING: {name}={raw!r} is not one of {'/'.join(_AUTHORITIES)} — "
          f"using shadow (advisory only).", flush=True)
    return "shadow"


def _get_int(name: str, default: int, minimum: int = 1) -> int:
    """A whole-number dial (bar counts, unit caps). 'nan' or 'inf' parse as
    floats and then raised in int() at IMPORT — the brain died before its first
    log line and the supervisor restarted it into the same crash (I6,
    Round-10B). Non-finite or below `minimum` is LOUD and keeps the default."""
    v = _get_float(name, float(default))
    if not (v == v and abs(v) != float("inf")) or v < minimum:
        print(f"[cfg] WARNING: {name}={os.getenv(name)!r} is not a usable whole number — "
              f"using the default {default}.", flush=True)
        return default
    return int(v)


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
        default_factory=lambda: _get_int("FXSIM_MAX_UNITS", 100_000)
    )
    # Hard leverage ceiling: notional (units * price) may never exceed
    # max_leverage * equity, regardless of risk_per_trade or ATR. This is both
    # the "aggression dial" and a safety brake — without it a small ATR (e.g.
    # intraday, or the old fixed-rate era) lets risk-based sizing explode to
    # absurd leverage. Read from the environment it is always a real cap in
    # (0, 5] (_get_leverage_cap: 0 no longer disables it). docs/RESEARCH.md has
    # the return/DD trade-off across leverage levels.
    max_leverage: float = field(default_factory=lambda: _get_leverage_cap("FXSIM_MAX_LEVERAGE", 5.0))
    # Conviction-scaled leverage: within the SAME hard max_leverage cap, pull
    # exposure down toward dyn_lev_floor when price drifts back toward the trend
    # SMA (the whipsaw zone), full cap when the trend is well established. Cuts
    # max drawdown ~34%->26% at equal-or-higher CAGR, robust OOS (docs/RESEARCH.md,
    # app/sizing.conviction_leverage). ON by default; set FXSIM_DYN_LEVERAGE=0 for
    # the old flat-cap behaviour. Never raises leverage above max_leverage.
    dyn_leverage: bool = field(
        default_factory=lambda: _get_bool("FXSIM_DYN_LEVERAGE", True)
    )
    # Ramp width: full cap once price is this many ATRs above the SMA (1.5 = the
    # robust central pick from the parameter sweep).
    dyn_lev_atr_mult: float = field(default_factory=lambda: _get_float("FXSIM_DYN_LEV_ATR", 1.5))
    # Floor leverage when price sits right at the SMA (1x = conservative but held).
    dyn_lev_floor: float = field(default_factory=lambda: _get_float("FXSIM_DYN_LEV_FLOOR", 1.0))
    # Ramp shape exponent on strength. 1.0 (linear) is the default since the
    # Round-4 overfitting tribunal: the convex (2.0) pick's +0.052 Sharpe edge
    # fails a deflated-Sharpe charge at EVERY assumed trial count N>=25 (rounds
    # 1-3 ran ~200 variants) — reverted per the pre-registered rule. The BASE
    # timing edge itself survives its permutation null at p<=0.014; only the
    # ramp-shape refinement could not pay its selection bill. docs/RESEARCH.md.
    dyn_lev_pow: float = field(default_factory=lambda: _get_float("FXSIM_DYN_LEV_POW", 1.0))
    # Drawdown brake on live sizing: OFF by default since Round-4 — first-ever
    # backtest of this live-only layer showed it costs -4.3pp CAGR while
    # WORSENING maxDD (de-levers into recoveries). Opt in with FXSIM_DD_BRAKE=1.
    dd_brake: bool = field(
        default_factory=lambda: _get_bool("FXSIM_DD_BRAKE", False)
    )
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
        default_factory=lambda: _get_bool("FXSIM_USE_TAKE_PROFIT", False)
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
    trend_sma: int = field(default_factory=lambda: _get_int("FXSIM_TREND_SMA", 2400, minimum=2))
    # What the AI layer uses as its technical base signal:
    #   "trend"     = the validated trend filter (default; the actual edge)
    #   "technical" = the mechanical MA/MACD/RSI/BB ensemble (loses OOS — legacy)
    ai_base: str = field(default_factory=lambda: os.getenv("FXSIM_AI_BASE", "trend"))

    # What the AI overlay may overrule (round-3 inquest, docs/RESEARCH.md: the
    # overlay is the only UNVALIDATED layer; its hold-liquidation and entry-veto
    # paths were confirmed return-negative in structure, and the edge's profit is
    # concentrated in a handful of long-held trends):
    #   "shadow" (default) = advisory only. The AI is still consulted and its
    #       view logged at the key moments, but decisions follow the validated
    #       edge (trend gate + stop). Builds the forward record needed to ever
    #       prove the veto skill before re-granting authority.
    #   "entry" = may veto FRESH entries only; can never liquidate an open
    #       position. Opt-in event protection at the cost of missed entries.
    #   "full"  = legacy: may also flatten holds (unvalidated exit path).
    ai_authority: str = field(default_factory=_get_authority)

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
