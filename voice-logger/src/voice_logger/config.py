"""設定ファイル (TOML) の読み込み。"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SECTION_HEADING = "## 🎙️ 会話ログ（自動生成）"

CONFIG_SEARCH_PATHS = [
    Path("config.toml"),
    Path("~/.config/voice-logger/config.toml").expanduser(),
]


@dataclass
class PathsConfig:
    inbox: Path
    archive: Path
    state: Path
    obsidian_vault: Path
    daily_notes_dir: str = "Daily Notes"


@dataclass
class WhisperConfig:
    model: str = "large-v3-turbo"
    device: str = "auto"
    compute_type: str = "auto"
    language: str = "ja"


@dataclass
class OllamaConfig:
    url: str = "http://localhost:11434"
    model: str = "qwen3:14b"
    chunk_chars: int = 12000


@dataclass
class DiaryConfig:
    date_format: str = "%Y-%m-%d"
    section_heading: str = DEFAULT_SECTION_HEADING


@dataclass
class Config:
    paths: PathsConfig
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    diary: DiaryConfig = field(default_factory=DiaryConfig)


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(p))


def find_config_path(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("VOICE_LOGGER_CONFIG")
    if env:
        return Path(env)
    for candidate in CONFIG_SEARCH_PATHS:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "設定ファイルが見つかりません。config.example.toml をコピーして "
        "config.toml を作成するか、--config で指定してください。"
    )


def load_config(path: Path) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    p = raw.get("paths", {})
    paths = PathsConfig(
        inbox=_expand(p.get("inbox", "~/voice-logger/inbox")),
        archive=_expand(p.get("archive", "~/voice-logger/archive")),
        state=_expand(p.get("state", "~/voice-logger/state")),
        obsidian_vault=_expand(p.get("obsidian_vault", "~/Obsidian")),
        daily_notes_dir=p.get("daily_notes_dir", "Daily Notes"),
    )
    whisper = WhisperConfig(**raw.get("whisper", {}))
    ollama = OllamaConfig(**raw.get("ollama", {}))
    diary = DiaryConfig(**raw.get("diary", {}))
    return Config(paths=paths, whisper=whisper, ollama=ollama, diary=diary)
