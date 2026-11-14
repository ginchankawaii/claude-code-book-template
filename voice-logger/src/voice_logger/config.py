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
    # 何度やっても処理できない音声の隔離先。未指定なら inbox の隣の `failed/`
    # （inbox の中に置くと再帰スキャンでまた拾ってしまうため、必ず inbox の外）
    failed: Path | None = None

    def quarantine_dir(self) -> Path:
        return self.failed if self.failed is not None else self.inbox.parent / "failed"


@dataclass
class WhisperConfig:
    model: str = "large-v3-turbo"
    device: str = "auto"
    compute_type: str = "auto"
    language: str = "ja"
    # モデル取得のための外部通信 (huggingface.co) の扱い:
    #   "auto" … キャッシュ済みなら一切通信しない。無いときだけ初回ダウンロードする
    #   true   … 常に通信しない（キャッシュに無ければエラー）
    #   false  … 起動のたびに huggingface.co へ更新確認に行く（従来の挙動）
    offline: bool | str = "auto"


@dataclass
class OllamaConfig:
    url: str = "http://localhost:11434"
    model: str = "qwen3:14b"
    chunk_chars: int = 12000
    # コンテキスト長（トークン）。chunk_chars の日本語テキスト + 出力が収まる値にする。
    # 大きいほどメモリを食い、CPU推論では遅くなる
    num_ctx: int = 16384
    # 1回の推論を待つ上限（秒）
    timeout_sec: int = 600
    # 思考モードを持つモデル (qwen3 等) の切替。None なら何も送らずモデルの既定に任せる
    think: bool | None = None


@dataclass
class WatchConfig:
    """`voice-logger watch` の再試行と安定判定。"""

    # 同じファイルの処理がこの回数失敗したら隔離ディレクトリへ移す
    max_failures: int = 5
    # ファイル単位の再試行間隔: retry_base_sec × 2^(失敗回数-1)、上限 retry_max_sec
    retry_base_sec: int = 60
    retry_max_sec: int = 3600
    # 最終更新からこの秒数たつまでは「コピー途中かもしれない」として触らない。
    # 負の値ならスキャン間隔の2倍
    min_age_sec: int = -1


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
    # 1回の送受信を待つ上限秒。TLSハンドシェイクと「次のリクエストのヘッダが揃うまで」の
    # 合計時間の上限にも使う
    socket_timeout_sec: int = 120
    # ボディ受信に許す最低速度。1リクエストの持ち時間は
    # socket_timeout_sec + Content-Length / この値 秒で、超えた接続はサーバから切る
    # （1バイトずつ送り続ける接続に同時接続枠を握られ続けないため）
    min_bytes_per_sec: int = 8192


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
    watch: WatchConfig = field(default_factory=WatchConfig)


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
        failed=_expand(p["failed"]) if p.get("failed") else None,
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
    watch = WatchConfig(**raw.get("watch", {}))
    return Config(paths=paths, whisper=whisper, ollama=ollama, diary=diary, ingest=ingest,
                  watch=watch)
