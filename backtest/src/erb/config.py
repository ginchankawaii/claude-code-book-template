"""config.yaml の読み込み。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(os.environ.get("ERB_CONFIG", "config.yaml"))


@dataclass
class Config:
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Config":
        p = Path(path) if path else DEFAULT_CONFIG_PATH
        with open(p, encoding="utf-8") as fh:
            return cls(raw=yaml.safe_load(fh))

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    def rename_map(self, table: str) -> dict[str, str]:
        """V2 の列名 -> 内部の正準名。"""
        return dict(self.raw["columns"][table])

    @property
    def api_key(self) -> str:
        key = os.environ.get("JQUANTS_API_KEY", "")
        if not key:
            raise RuntimeError(
                "JQUANTS_API_KEY が未設定です。.env に書いて docker compose の env_file で渡してください。"
            )
        return key
