"""ローカル完結型・音声ライフログパイプライン (Phase 0)。

音声ファイル → faster-whisper (Silero VAD内蔵) → Ollama (ローカルLLM) 分析
→ Obsidian Daily Note 追記。外部クラウドには一切データを送らない。
"""

__version__ = "0.1.0"
