"""M0: データ取得層の抽象インターフェース。

分析層は「正規化済み runner/races テーブル」だけを知り、その供給元(合成 or
実 JV-Link)を `JVLinkReader` 抽象で差し替えられるようにする。これにより
サンドボックスでは合成バックエンドでパイプライン全体を完成させ、実データ
到着時は `RealJVLinkBackend`(Windows/32bit COM)に差し替えるだけで済む。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from .synth import SyntheticConfig, generate_dataset


class JVLinkReader(ABC):
    """正規化テーブルを供給する取得層の抽象。

    実装は (runners, races) の2つの DataFrame を返す。列名・可用性は
    keiba.schema に準拠すること。
    """

    @abstractmethod
    def load(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """(runners, races) を返す。"""
        raise NotImplementedError


class SyntheticBackend(JVLinkReader):
    """合成データバックエンド(サンドボックス用)。"""

    def __init__(self, config: SyntheticConfig | None = None):
        self.config = config or SyntheticConfig()

    def load(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        return generate_dataset(self.config)


class RealJVLinkBackend(JVLinkReader):
    """実 JV-Link バックエンド(Windows/32bit COM)の雛形。

    本クラスはサンドボックス(Linux)では動作しない。実運用では
    pywin32 で 'JVDTLab.JVLink' を Dispatch し、
    JVInit → (JVSetServiceKey) → JVOpen/JVRTOpen → JVStatus → JVRead → JVClose
    のフローで Shift-JIS 固定長レコードを取得・パースし、schema 準拠の
    DataFrame に正規化する。未知レコード種別IDは読み飛ばす(仕様準拠)。

    実装は M5 で行う。詳細は docs/RESEARCH_JRAVAN.md の第2章を参照。
    """

    def __init__(self, sqlite_path: str | None = None, service_key: str | None = None):
        self.sqlite_path = sqlite_path
        self.service_key = service_key

    def load(self) -> tuple[pd.DataFrame, pd.DataFrame]:  # pragma: no cover
        raise NotImplementedError(
            "RealJVLinkBackend は M5(実データ取得層)で実装。"
            "Windows + 32bit Python + pywin32 + DataLab会員 が必要。"
            "代替として EveryDB2/jrvltsql が構築した DB を読み込む実装も可。"
        )
