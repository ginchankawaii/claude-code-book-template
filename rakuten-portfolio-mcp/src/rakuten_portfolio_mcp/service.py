"""ローダー・価格補完・分析をつなぐ層。

MCPサーバーもCLIもここを呼ぶ。MCP SDKに依存しないので、
`python -m rakuten_portfolio_mcp.cli` で普通に動作確認できる。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Optional

from . import loaders, prices
from .config import Config
from .models import Portfolio


def load_portfolio(
    cfg: Config,
    refresh: bool = False,
    only: Optional[list[str]] = None,
) -> Portfolio:
    """データフォルダを読み込んで正規化済みポートフォリオを返す。

    refresh=True のときだけ株価を取り直す。既定はCSV記載の現在値を優先し、
    欠けているものだけ補完する（毎回の外部アクセスを避けるため）。
    """
    files = loaders.discover(cfg.data_dir)
    if only:
        wanted = {n.lower() for n in only}
        files = [f for f in files if f.name.lower() in wanted]

    pf = loaders.load_all(files)

    if not files:
        pf.warnings.append(
            f"{cfg.data_dir} に読み込めるファイルが無い。"
            "楽天証券の保有商品一覧CSVを置くか、portfolio.yaml を作ってほしい。"
        )
        return pf

    prices.convert_to_jpy(pf, cfg)
    prices.enrich(pf, cfg, force=refresh)
    return pf


def list_sources(cfg: Config) -> dict[str, Any]:
    files = loaders.discover(cfg.data_dir)
    now = dt.datetime.now()
    rows = []
    for f in files:
        mtime = dt.datetime.fromtimestamp(f.stat().st_mtime)
        rows.append(
            {
                "name": f.name,
                "kind": "manual" if f.suffix.lower() in loaders.MANUAL_SUFFIXES else "csv",
                "size_bytes": f.stat().st_size,
                "modified_at": mtime.isoformat(timespec="seconds"),
                "age_days": round((now - mtime).total_seconds() / 86400, 1),
            }
        )
    return {
        "data_dir": str(cfg.data_dir),
        "file_count": len(rows),
        "files": rows,
        "hint": (
            "楽天証券Web＞保有商品一覧＞CSVダウンロード、および信用建玉一覧のCSVを"
            f"{cfg.data_dir} に置く。保証金情報は portfolio.yaml の margin_account に手入力。"
        ),
    }


def inspect_file(cfg: Config, filename: str) -> dict[str, Any]:
    """CSVが想定通り解釈できているかを確認する診断用。"""
    path = cfg.data_dir / filename
    if not path.exists():
        return {"error": f"{filename} が {cfg.data_dir} に無い。"}
    if path.suffix.lower() in loaders.MANUAL_SUFFIXES:
        pf = loaders.load_manual(path)
        return {
            "file": filename,
            "kind": "manual",
            "spot_count": len(pf.spot),
            "margin_count": len(pf.margin),
            "warnings": pf.warnings,
        }
    result = loaders.inspect_csv(path)
    parsed = loaders.load_csv(path)
    result["parsed_spot_count"] = len(parsed.spot)
    result["parsed_margin_count"] = len(parsed.margin)
    result["warnings"] = parsed.warnings
    return result
