"""Provider factory."""
from __future__ import annotations

from ..config import settings
from .base import DataProvider
from .sample import SampleProvider


def get_provider(name: str | None = None) -> DataProvider:
    name = (name or settings.data_provider).lower()
    if name == "oanda":
        from .oanda import OandaProvider  # imported lazily so offline use needs no token

        return OandaProvider()
    if name == "csv":
        from .csv import CsvProvider  # real data exported from any broker

        return CsvProvider()
    if name == "sample":
        return SampleProvider()
    raise ValueError(f"Unknown data provider: {name!r}")


__all__ = ["DataProvider", "SampleProvider", "get_provider"]
