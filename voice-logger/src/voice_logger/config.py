"""設定ファイル (TOML) の読み込み。"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

DEFAULT_SECTION_HEADING = "## 🎙️ 会話ログ（自動生成）"

# 受信APIが既定で受け付ける接続元（ループバック + RFC1918 + リンクローカル + ULA）
DEFAULT_ALLOWED_NETWORKS = [
    "127.0.0.0/8", "::1/128",
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "169.254.0.0/16", "fe80::/10", "fc00::/7",
]

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
class IngestConfig:
    """デバイス受信API (`voice-logger serve`) の設定。

    既定値は「LAN内のみ・TLS必須・認証必須」。外に晒す設定は明示的に書かないと有効にならない。
    """

    # 既定は 0.0.0.0 ではなくループバック。LANに出すときは自機のLAN IPを明示的に書く
    host: str = "127.0.0.1"
    port: int = 8443
    # サーバ証明書（PEM）。未設定かつ allow_plaintext=false なら起動を拒否する
    tls_cert: str = ""
    tls_key: str = ""
    # mTLS: クライアント証明書を検証するCA（PEM）
    client_ca: str = ""
    require_mtls: bool = True
    # 証明書のCNが X-MindClip-Device と一致することまで要求するか
    cert_cn_must_match_device: bool = False
    # 平文HTTPを許可（テスト・実験用。既定は禁止）
    allow_plaintext: bool = False
    # 共有秘密 HMAC-SHA256 の鍵。hex 64文字。環境変数 MINDCLIP_HMAC_KEY でも指定可
    hmac_key_hex: str = ""
    hmac_key_file: str = ""
    # デバイスごとに鍵を分けたい場合: { "mindclip-01" = "<hex>" } または "@/path/to/keyfile"
    devices: dict[str, str] = field(default_factory=dict)
    # 接続元IPの許可範囲（空リストなら制限なし）
    allowed_networks: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_NETWORKS))
    # 1ファイルの上限（超過は 413）
    max_bytes: int = 128 * 1024 * 1024
    # これを下回る空き容量では受けない（507）
    min_free_bytes: int = 512 * 1024 * 1024
    # ボディ受信のソケットタイムアウト秒
    socket_timeout_sec: int = 120


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
    ingest: IngestConfig = field(default_factory=IngestConfig)


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
    ingest_raw = dict(raw.get("ingest", {}))
    known = {f.name for f in fields(IngestConfig)}
    unknown = set(ingest_raw) - known
    if unknown:
        raise ValueError(f"[ingest] に未知のキーがあります: {sorted(unknown)}")
    ingest = IngestConfig(**ingest_raw)

    whisper = WhisperConfig(**raw.get("whisper", {}))
    ollama = OllamaConfig(**raw.get("ollama", {}))
    diary = DiaryConfig(**raw.get("diary", {}))
    return Config(paths=paths, whisper=whisper, ollama=ollama, diary=diary, ingest=ingest)
