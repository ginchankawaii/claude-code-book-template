"""keiba — JRA-VANデータを見据えた本格競馬予想システムの分析層。

設計方針(docs/RESEARCH_JRAVAN.md より):
  * 最適化対象は的中率ではなく「控除率込みの回収率(ROI)」。
  * データリーク(point-in-time違反)を最大の敵とみなし、特徴量は発走前に
    取得可能な情報のみで構成し、集計は対象レース日より前に限定する。
  * 評価は walk-forward(時系列分割)。バックテストの高ROIはまずリークを疑う。
  * 市場確率(オッズ)は最強の予測子。Benter流に別軸でブレンドし残差を狙う。

取得層(JV-Link/Windows/32bit COM)と分析層(本パッケージ/Linux)は
DBファイル/DataFrameを境界に疎結合。サンドボックスでは合成データで
パイプライン全体を完成させ、実データ到着時に reader を差し替えるだけにする。
"""

from .ingest import IngestConfig, from_duckdb, from_sqlite, normalize, validate_runners
from .reader import JVLinkReader, SyntheticBackend
from .store import DuckDBBackend, load_dataset, save_dataset
from .synth import SyntheticConfig, generate_dataset

__all__ = [
    "JVLinkReader",
    "SyntheticBackend",
    "DuckDBBackend",
    "save_dataset",
    "load_dataset",
    "SyntheticConfig",
    "generate_dataset",
    "normalize",
    "validate_runners",
    "from_duckdb",
    "from_sqlite",
    "IngestConfig",
]
__version__ = "0.4.0"
