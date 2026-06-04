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
    granularity: str = field(default_factory=lambda: os.getenv("FXSIM_GRANULARITY", "M15"))

    # --- account / risk ---
    initial_balance: float = field(default_factory=lambda: _get_float("FXSIM_BALANCE", 100_000.0))
    risk_per_trade: float = field(default_factory=lambda: _get_float("FXSIM_RISK", 0.02))
    max_position_units: int = field(
        default_factory=lambda: int(_get_float("FXSIM_MAX_UNITS", 100_000))
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
    # Trend strategies set this False so exits come from the signal or the stop.
    use_take_profit: bool = field(
        default_factory=lambda: os.getenv("FXSIM_USE_TAKE_PROFIT", "1") not in ("0", "false", "")
    )

    # --- fundamental analyzer ---
    # "stub" (neutral), "file" (data/fundamental.json), or "anthropic" (live LLM)
    fundamental_mode: str = field(
        default_factory=lambda: os.getenv("FXSIM_FUND_MODE", "file")
    )
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(
        default_factory=lambda: os.getenv("FXSIM_FUND_MODEL", "claude-opus-4-8")
    )

    # --- strategy selection --------------------------------------------------
    # "trend" (OOS-validated daily trend filter), "ai", "combined"/"off"
    strategy: str = field(default_factory=lambda: os.getenv("FXSIM_STRATEGY", "ai"))
    trend_sma: int = field(default_factory=lambda: int(_get_float("FXSIM_TREND_SMA", 150)))

    # --- AI decision layer ---------------------------------------------------
    # Who makes the final call:
    #   "rule"      = deterministic, offline-capable risk-aware decider (default)
    #   "anthropic" = Claude weighs technicals + fundamentals + the upcoming
    #                 event calendar and decides (needs key + allow-listed host)
    decision_mode: str = field(
        default_factory=lambda: os.getenv("FXSIM_DECISION_MODE", "rule")
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
