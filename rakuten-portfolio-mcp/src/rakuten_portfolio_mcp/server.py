"""MCPサーバー本体。

各ツールは「事実と数値」を返すことに徹する。売買の結論はここで出さず、
呼び出し側のClaudeが flags と数値を見て判断・助言する構成にしている。
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from . import service, snapshots
from .analysis import brief, concentration, margin, pnl, risk
from .config import Config

mcp = FastMCP("rakuten-portfolio")


def _cfg() -> Config:
    # 毎回読み直す。MCPクライアント側で env を変えたときに再起動だけで効くように。
    return Config.from_env()


@mcp.tool()
def list_sources() -> dict[str, Any]:
    """読み込み対象のファイル一覧と最終更新日時を返す。データが古くないかの確認に使う。"""
    return service.list_sources(_cfg())


@mcp.tool()
def inspect_file(filename: str) -> dict[str, Any]:
    """CSVの文字コード・検出したヘッダ・解釈できた件数を返す診断ツール。

    ポジションが0件になるなど読み込みがおかしいときに、
    どの列をどう認識したかを確認するために使う。
    """
    return service.inspect_file(_cfg(), filename)


@mcp.tool()
def get_portfolio(refresh_prices: bool = False) -> dict[str, Any]:
    """現物・信用・現金を正規化したポートフォリオ全体を返す。

    refresh_prices=True で株価を取り直す（既定はCSV記載の現在値を優先）。
    """
    cfg = _cfg()
    pf = service.load_portfolio(cfg, refresh=refresh_prices)
    return pf.to_dict()


@mcp.tool()
def get_margin_status() -> dict[str, Any]:
    """信用取引の状況。委託保証金維持率、追証までの下落率、返済期限の近い建玉を返す。"""
    cfg = _cfg()
    pf = service.load_portfolio(cfg)
    return margin.summarize(pf, cfg)


@mcp.tool()
def analyze_concentration(top_n: int = 10) -> dict[str, Any]:
    """銘柄集中度。現物と信用建玉を通算したエクスポージャーとHHIを返す。"""
    pf = service.load_portfolio(_cfg())
    return concentration.summarize(pf, top_n=top_n)


@mcp.tool()
def simulate_shock(scenarios: Optional[list[float]] = None) -> dict[str, Any]:
    """相場が一律で下落した場合の損益と維持率を試算する。

    scenarios は変動率(%)のリスト。省略時は -3/-5/-10/-15/-20/-30%。
    """
    cfg = _cfg()
    pf = service.load_portfolio(cfg)
    return risk.summarize(pf, cfg, scenarios)


@mcp.tool()
def simulate_single_name(symbol: str, shock_pct: float = -20.0) -> dict[str, Any]:
    """特定銘柄だけが動いた場合の影響を試算する。決算前のリスク確認用。"""
    cfg = _cfg()
    pf = service.load_portfolio(cfg)
    return risk.single_name_shock(pf, symbol, shock_pct, cfg)


@mcp.tool()
def list_expiring_margin(within_days: int = 30) -> dict[str, Any]:
    """返済期限が近い信用建玉を返す。制度信用は建日から6ヶ月で自動補完している。"""
    pf = service.load_portfolio(_cfg())
    return {
        "within_days": within_days,
        "positions": margin.expiring_positions(pf, within_days),
    }


@mcp.tool()
def get_pnl_summary() -> dict[str, Any]:
    """損益サマリ。NISA/課税口座の区分、概算税額、損益通算の候補を返す。"""
    cfg = _cfg()
    pf = service.load_portfolio(cfg)
    return pnl.summarize(pf, cfg)


@mcp.tool()
def get_advice_brief(refresh_prices: bool = False) -> dict[str, Any]:
    """診断に必要な情報を一括で返す。

    ポートフォリオ・集中度・信用・ストレステスト・損益・注意フラグを1つにまとめる。
    「俺のポートフォリオ見て」と言われたらまずこれを呼べばよい。
    """
    cfg = _cfg()
    pf = service.load_portfolio(cfg, refresh=refresh_prices)
    return brief.build(pf, cfg)


@mcp.tool()
def save_snapshot(label: str = "") -> dict[str, Any]:
    """現時点の集計をスナップショットとして保存する。後で推移比較に使う。"""
    cfg = _cfg()
    pf = service.load_portfolio(cfg)
    path = snapshots.save(pf, cfg, label)
    return {"saved": path.name, "path": str(path)}


@mcp.tool()
def list_snapshots() -> dict[str, Any]:
    """保存済みスナップショットの一覧。"""
    return {"snapshots": snapshots.listing(_cfg())}


@mcp.tool()
def compare_snapshots(older: str, newer: str) -> dict[str, Any]:
    """2つのスナップショットを比較して、純資産・維持率・保有銘柄の変化を返す。"""
    return snapshots.compare(_cfg(), older, newer)


@mcp.prompt()
def portfolio_review() -> str:
    """ポートフォリオ全体をレビューさせるプロンプト。"""
    return (
        "get_advice_brief を呼んで、私の楽天証券のポートフォリオをレビューしてほしい。\n"
        "次の順で、数字を根拠として引用しながら簡潔にまとめること。\n"
        "1. 全体像（純資産、現金比率、レバレッジ）\n"
        "2. 信用取引の余力と追証までの距離。危険水域なら最優先で指摘する\n"
        "3. 集中度。特定銘柄への偏りと、それが下落したときの実額インパクト\n"
        "4. 損益と税制（NISA枠の使い方、損益通算の余地）\n"
        "5. flags に出ている項目のうち、対応が必要なもの\n"
        "断定的な売買推奨ではなく、リスクの所在と選択肢の整理として書くこと。"
    )


@mcp.prompt()
def margin_check() -> str:
    """信用建玉の健全性だけを手早く確認するプロンプト。"""
    return (
        "get_margin_status と simulate_shock を呼んで、信用建玉の状態を確認してほしい。"
        "維持率、追証までの下落率、返済期限が近い建玉を中心に、危険度の高い順に報告すること。"
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
