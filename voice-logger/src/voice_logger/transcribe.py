"""faster-whisper による文字起こし。VAD (Silero) は faster-whisper 内蔵のものを使う。

推論は完全にローカルだが、モデル名を渡すと faster-whisper (huggingface_hub) は
ロードのたびに huggingface.co へ更新確認に行く。`[whisper] offline` が "auto"（既定）
なら、まずキャッシュだけでロードを試み（通信ゼロ）、無いときに限りダウンロードする。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from .config import WhisperConfig
from .errors import ServiceUnavailable

logger = logging.getLogger("voice_logger")


@dataclass
class Segment:
    start: float  # 録音先頭からの秒
    end: float
    text: str


@dataclass
class Transcript:
    segments: list[Segment]
    language: str
    duration: float  # 音声全体の秒数

    @property
    def text(self) -> str:
        return "\n".join(s.text for s in self.segments)

    def is_empty(self) -> bool:
        return not any(s.text.strip() for s in self.segments)


_model_cache: dict[tuple[str, str, str], object] = {}


def _offline_mode(cfg: WhisperConfig) -> str:
    value = cfg.offline
    if isinstance(value, str):
        value = value.strip().lower()
    if value in (True, "true", "on", "1"):
        return "always"
    if value in (False, "false", "off", "0"):
        return "never"
    if value == "auto":
        return "auto"
    raise ServiceUnavailable(
        f"[whisper] offline の値が不正です: {cfg.offline!r}（true / false / \"auto\"）")


def _load_model(cfg: WhisperConfig):
    mode = _offline_mode(cfg)
    # huggingface_hub は import 時に環境変数を読むので、必ず import より前に設定する
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    if mode == "always":
        os.environ["HF_HUB_OFFLINE"] = "1"
    from faster_whisper import WhisperModel

    def load(local_only: bool):
        return WhisperModel(cfg.model, device=cfg.device, compute_type=cfg.compute_type,
                            local_files_only=local_only)

    if mode == "never":
        return load(False)
    try:
        return load(True)
    except (OSError, ValueError) as exc:  # キャッシュに無い (LocalEntryNotFoundError)
        if mode == "always":
            raise ServiceUnavailable(
                f"whisper モデル '{cfg.model}' がキャッシュにありません ([whisper] offline = true)。"
                " 一度 offline = \"auto\" にしてネット接続のある状態で起動し、"
                f"ダウンロードしてください: {exc}") from exc
        logger.warning(
            "whisper モデル '%s' がキャッシュに無いため huggingface.co から取得します"
            "（外部通信はこの初回だけ。送るのはモデルの要求のみで、音声は送りません）", cfg.model)
        return load(False)


def _get_model(cfg: WhisperConfig):
    # モデルロードは数十秒かかるためプロセス内でキャッシュ（watchモードで効く）
    key = (cfg.model, cfg.device, cfg.compute_type)
    if key not in _model_cache:
        try:
            _model_cache[key] = _load_model(cfg)
        except ServiceUnavailable:
            raise
        except Exception as exc:
            # ロード失敗は録音ファイルのせいではない（未インストール・未取得・メモリ不足）
            raise ServiceUnavailable(
                f"whisper モデル '{cfg.model}' をロードできません: {exc}") from exc
    return _model_cache[key]


def transcribe(path: Path, cfg: WhisperConfig) -> Transcript:
    model = _get_model(cfg)
    segments_iter, info = model.transcribe(
        str(path),
        language=cfg.language or None,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 700},
        condition_on_previous_text=False,  # 長時間録音での繰り返し暴走を防ぐ
    )
    segments = [
        Segment(start=s.start, end=s.end, text=s.text.strip())
        for s in segments_iter
        if s.text.strip()
    ]
    return Transcript(
        segments=segments,
        language=info.language,
        duration=info.duration,
    )
