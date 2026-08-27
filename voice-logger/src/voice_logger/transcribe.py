"""faster-whisper による文字起こし。VAD (Silero) は faster-whisper 内蔵のものを使う。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import WhisperConfig


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


def _get_model(cfg: WhisperConfig):
    # モデルロードは数十秒かかるためプロセス内でキャッシュ（watchモードで効く）
    from faster_whisper import WhisperModel

    key = (cfg.model, cfg.device, cfg.compute_type)
    if key not in _model_cache:
        _model_cache[key] = WhisperModel(
            cfg.model, device=cfg.device, compute_type=cfg.compute_type
        )
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
