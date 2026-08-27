"""Ollama (ローカルLLM) による要約・ToDo抽出・振り返り生成。

長時間録音は chunk_chars 単位で分割し、チャンクごとに分析 → 最後に統合する
（map-reduce）。Ollama の structured outputs (format にJSONスキーマを渡す) を
使い、出力を必ずJSONで受け取る。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .config import OllamaConfig
from .transcribe import Transcript

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "3〜5文の日本語サマリー"},
        "todos": {
            "type": "array",
            "items": {"type": "string"},
            "description": "会話中のToDo・約束・宿題。無ければ空配列",
        },
        "topics": {
            "type": "array",
            "items": {"type": "string"},
            "description": "主要トピック（短い名詞句）",
        },
        "reflection": {
            "type": "string",
            "description": "日記の振り返りとして使える1〜2文",
        },
    },
    "required": ["summary", "todos", "topics", "reflection"],
}

SYSTEM_PROMPT = (
    "あなたは音声ライフログを整理するアシスタントです。"
    "ウェアラブルレコーダーで録音された日常会話・独り言の文字起こしを読み、"
    "日記に載せるための要約・ToDo抽出・振り返りを日本語で作成します。"
    "文字起こしには誤認識が含まれることを前提に、意味の通る解釈を優先してください。"
    "ToDoは「誰かに何かをすると約束した」「やると宣言した」ものだけを、"
    "実行可能な短い文で抽出してください。"
)


@dataclass
class Analysis:
    summary: str = ""
    todos: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    reflection: str = ""


def _chat_json(cfg: OllamaConfig, prompt: str) -> dict:
    import requests

    resp = requests.post(
        f"{cfg.url.rstrip('/')}/api/chat",
        json={
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": ANALYSIS_SCHEMA,
            "options": {"temperature": 0.2, "num_ctx": 16384},
        },
        timeout=600,
    )
    resp.raise_for_status()
    return json.loads(resp.json()["message"]["content"])


def _timestamped_lines(transcript: Transcript, start: datetime) -> list[str]:
    lines = []
    for seg in transcript.segments:
        clock = (start + timedelta(seconds=seg.start)).strftime("%H:%M")
        lines.append(f"[{clock}] {seg.text}")
    return lines


def _chunk(lines: list[str], max_chars: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        if current and size + len(line) > max_chars:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def analyze(transcript: Transcript, start: datetime, cfg: OllamaConfig) -> Analysis:
    lines = _timestamped_lines(transcript, start)
    if not lines:
        return Analysis()
    chunks = _chunk(lines, cfg.chunk_chars)

    partials: list[dict] = []
    for i, chunk in enumerate(chunks):
        label = f"（{i + 1}/{len(chunks)} 分割目）" if len(chunks) > 1 else ""
        prompt = (
            f"以下は {start.strftime('%Y-%m-%d')} の録音の文字起こしです{label}。"
            "指定のJSON形式で分析結果を返してください。\n\n" + chunk
        )
        partials.append(_chat_json(cfg, prompt))

    if len(partials) == 1:
        data = partials[0]
    else:
        merged_input = json.dumps(partials, ensure_ascii=False, indent=1)
        prompt = (
            "以下は同じ日の録音を分割して分析した結果のリストです。"
            "重複を除いて1つに統合し、指定のJSON形式で返してください。"
            "todosは全チャンクの和集合（重複除去）にしてください。\n\n" + merged_input
        )
        data = _chat_json(cfg, prompt)

    return Analysis(
        summary=str(data.get("summary", "")).strip(),
        todos=[str(t).strip() for t in data.get("todos", []) if str(t).strip()],
        topics=[str(t).strip() for t in data.get("topics", []) if str(t).strip()],
        reflection=str(data.get("reflection", "")).strip(),
    )
