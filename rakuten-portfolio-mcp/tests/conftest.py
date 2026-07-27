from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from rakuten_portfolio_mcp.config import Config

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


@pytest.fixture
def sample_csv() -> Path:
    return SAMPLES / "assetbalance_sample_20260724.csv"


@pytest.fixture
def data_dir(tmp_path: Path, sample_csv: Path) -> Path:
    """サンプルCSVだけが入ったデータフォルダ。"""
    shutil.copy(sample_csv, tmp_path / sample_csv.name)
    return tmp_path


@pytest.fixture
def cfg(data_dir: Path) -> Config:
    # テストで外部通信させない
    return Config(data_dir=data_dir, price_source="none")
