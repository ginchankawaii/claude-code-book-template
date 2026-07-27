"""データフォルダを走査して Portfolio を組み立てる入口。

拡張子でローダーを振り分けるだけの薄い層。MarketSpeed II RSS がExcelから吐く
CSVも列名さえ拾えれば csv_rakuten がそのまま食える（列名の同義語は normalize.py に足す）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ..models import Portfolio
from .csv_rakuten import inspect as inspect_csv
from .csv_rakuten import load_csv
from .manual import load_manual

CSV_SUFFIXES = {".csv", ".tsv", ".txt"}
MANUAL_SUFFIXES = {".yaml", ".yml", ".json"}
SUPPORTED = CSV_SUFFIXES | MANUAL_SUFFIXES

__all__ = ["load_csv", "load_manual", "inspect_csv", "discover", "load_all", "SUPPORTED"]


def discover(data_dir: Path) -> list[Path]:
    """データフォルダ直下の対象ファイルを新しい順に返す。

    `.example.` を含むファイルとスナップショット置き場は除外する。
    """
    if not data_dir.exists():
        return []
    files = [
        p
        for p in data_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in SUPPORTED
        and ".example." not in p.name
        and not p.name.startswith(".")
    ]
    return sorted(files, key=lambda p: (p.stat().st_mtime, p.name), reverse=True)


def load_file(path: Path) -> Portfolio:
    if path.suffix.lower() in MANUAL_SUFFIXES:
        return load_manual(path)
    return load_csv(path)


def load_all(paths: Iterable[Path]) -> Portfolio:
    """複数ファイルを読んで1つに統合する。

    同じ銘柄が複数ファイルに出てきても合算はしない（同じCSVを2回置くと
    二重計上になる）ので、重複の警告だけ出して判断はユーザーに委ねる。
    """
    merged = Portfolio()
    for path in paths:
        try:
            merged.merge(load_file(path))
        except Exception as exc:  # 1ファイルの失敗で全体を落とさない
            merged.warnings.append(f"{path.name}: 読み込み失敗 ({exc})")

    _warn_duplicates(merged)
    return merged


def _warn_duplicates(pf: Portfolio) -> None:
    seen: dict[tuple[str, str], set[str]] = {}
    for p in pf.spot:
        seen.setdefault((p.symbol, p.account), set()).add(p.source)
    for key, sources in seen.items():
        if len(sources) > 1:
            pf.warnings.append(
                f"銘柄 {key[0]}（{key[1]}）が複数ファイルに存在: {', '.join(sorted(sources))}。"
                "二重計上の可能性があるので古いファイルを消すか確認してほしい。"
            )
