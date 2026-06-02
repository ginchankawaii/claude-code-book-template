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

    # --- fundamental analyzer ---
    # "stub" (neutral), "file" (data/fundamental.json), or "anthropic" (live LLM)
    fundamental_mode: str = field(
        default_factory=lambda: os.getenv("FXSIM_FUND_MODE", "file")
    )
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(
        default_factory=lambda: os.getenv("FXSIM_FUND_MODEL", "claude-opus-4-8")
    )

    @property
    def oanda_host(self) -> str:
        if self.oanda_env == "live":
            return "https://api-fxtrade.oanda.com"
        return "https://api-fxpractice.oanda.com"


settings = Settings()


def pip_size(instrument: str) -> float:
    """Pip size for an instrument. JPY pairs quote to 0.01, others to 0.0001."""
    return 0.01 if instrument.endswith("JPY") else 0.0001
