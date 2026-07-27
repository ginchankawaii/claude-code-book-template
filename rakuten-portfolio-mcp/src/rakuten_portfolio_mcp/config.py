"""環境変数による設定。MCPクライアント側の env で上書きする前提。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _resolve_data_dir() -> Path:
    """データフォルダの決定。RPM_DATA_DIR を明示するのが本筋。

    未設定時は、リポジトリを直接動かしている場合に限りその data/ を使う。
    wheel としてインストールされている場合はリポジトリ相対が意味を持たないので、
    カレントディレクトリの data/ に落とす。
    """
    env = os.environ.get("RPM_DATA_DIR")
    if env:
        return Path(env).expanduser()

    repo_data = Path(__file__).resolve().parents[2] / "data"
    if repo_data.is_dir():
        return repo_data
    return Path.cwd() / "data"


@dataclass(frozen=True)
class Config:
    data_dir: Path
    # 楽天証券の最低委託保証金維持率。これを割ると追証。
    maintenance_threshold: float = 20.0
    # 警戒ライン。追証まで余裕がどれだけあるかの目安に使う。
    warning_threshold: float = 30.0
    # 新規建に必要な委託保証金率と最低保証金額
    initial_margin_rate: float = 30.0
    min_deposit: float = 300_000.0
    # 代用有価証券の掛目（楽天証券は原則80%）
    substitute_haircut: float = 0.8
    # 譲渡益課税（所得税15% + 復興特別所得税 + 住民税5%）
    tax_rate: float = 0.20315
    # 株価取得元: stooq / none
    price_source: str = "stooq"
    price_cache_ttl_sec: int = 900
    usdjpy: float = 0.0  # 0なら自動取得を試みる

    @classmethod
    def from_env(cls) -> "Config":
        data_dir = _resolve_data_dir()
        return cls(
            data_dir=data_dir,
            maintenance_threshold=_f("RPM_MAINTENANCE_THRESHOLD", 20.0),
            warning_threshold=_f("RPM_WARNING_THRESHOLD", 30.0),
            initial_margin_rate=_f("RPM_INITIAL_MARGIN_RATE", 30.0),
            min_deposit=_f("RPM_MIN_DEPOSIT", 300_000.0),
            substitute_haircut=_f("RPM_SUBSTITUTE_HAIRCUT", 0.8),
            tax_rate=_f("RPM_TAX_RATE", 0.20315),
            price_source=os.environ.get("RPM_PRICE_SOURCE", "stooq").lower(),
            price_cache_ttl_sec=int(_f("RPM_PRICE_CACHE_TTL", 900)),
            usdjpy=_f("RPM_USDJPY", 0.0),
        )

    @property
    def snapshot_dir(self) -> Path:
        return self.data_dir / "snapshots"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / ".cache"
