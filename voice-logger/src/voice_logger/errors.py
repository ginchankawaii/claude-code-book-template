"""パイプライン全体で共有する例外。"""

from __future__ import annotations


class ServiceUnavailable(Exception):
    """音声ファイルのせいではない失敗（Ollama 不通・モデル未取得・vault に書けない等）。

    `watch` はこれを「そのファイルの失敗回数」に数えず、全体を待たせて再試行する。
    数えてしまうと、Ollama が落ちているだけで inbox の全ファイルが隔離されてしまう。
    メッセージはそのままログに出すので、利用者が次に打つコマンドまで書くこと。
    """
