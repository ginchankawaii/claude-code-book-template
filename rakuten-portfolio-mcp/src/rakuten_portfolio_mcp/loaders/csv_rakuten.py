"""楽天証券からダウンロードしたCSVを読む。

楽天証券の「保有商品一覧」CSVは1ファイルの中に
「国内株式(現物)」「投資信託」「外国株式」…といったセクションが縦に並び、
セクションごとにヘッダ行が現れる。列名も商品種別ごとに違う。

そこで固定の列位置には一切依存せず、
  1. ヘッダらしい行を見つけてブロックに切る
  2. ブロックの列構成とラベルから商品種別を判定する
  3. 同義語テーブル経由で値を取り出す
という順で読む。列が増減しても壊れないのが狙い。
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from pathlib import Path
from typing import Optional

from .. import normalize as nz
from ..models import (
    AssetClass,
    MarginAccount,
    MarginKind,
    MarginPosition,
    MarginSide,
    Portfolio,
    SpotPosition,
)

# 楽天証券のCSVはCP932が主。UTF-8で出力される画面もあるので順に試す。
ENCODINGS = ("utf-8-sig", "cp932", "utf-8", "shift_jis", "euc_jp")

# ヘッダ行判定に使う語彙。これらのうち2つ以上当たればヘッダとみなす。
_HEADER_HINTS = (
    *nz.SYMBOL,
    *nz.NAME,
    *nz.QUANTITY,
    *nz.AVG_COST,
    *nz.LAST_PRICE,
    *nz.MARKET_VALUE,
    *nz.OPEN_PRICE,
    *nz.OPEN_DATE,
)


class Block:
    """CSV内の1セクション。"""

    def __init__(self, label: str, header: list[str], rows: list[list[str]]) -> None:
        self.label = label
        self.header = header
        self.rows = rows
        self.hmap = nz.HeaderMap(header)

    def __repr__(self) -> str:  # デバッグ用
        return f"<Block {self.label!r} cols={len(self.header)} rows={len(self.rows)}>"


def decode_file(path: Path) -> tuple[str, str]:
    """(本文, 使った文字コード) を返す。全滅したら置換読みで最後まで通す。"""
    raw = path.read_bytes()
    for enc in ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("cp932", errors="replace"), "cp932(replace)"


def read_rows(path: Path) -> tuple[list[list[str]], str]:
    text, enc = decode_file(path)
    delimiter = "\t" if path.suffix.lower() in (".tsv", ".txt") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [[nz.normalize_text(c) for c in row] for row in reader], enc


def _is_header(row: list[str]) -> bool:
    if sum(1 for c in row if c) < 2:
        return False
    return nz.HeaderMap(row).score(_HEADER_HINTS) >= 2


def _is_label(row: list[str]) -> bool:
    """「国内株式(現物)」のような単独セルの見出し行。"""
    filled = [c for c in row if c]
    return len(filled) == 1 and len(filled[0]) <= 40


def split_blocks(rows: list[list[str]]) -> list[Block]:
    blocks: list[Block] = []
    pending_label = ""
    current: Optional[Block] = None

    for row in rows:
        if not any(row):
            current = None  # 空行でセクション終了
            continue
        if _is_header(row):
            current = Block(pending_label, row, [])
            blocks.append(current)
            pending_label = ""
            continue
        if current is None:
            if _is_label(row):
                pending_label = next(c for c in row if c)
            continue
        current.rows.append(row)

    return [b for b in blocks if b.rows]


def _asset_class(label: str, hmap: nz.HeaderMap) -> AssetClass:
    text = label
    if any(k in text for k in ("米国", "外国", "海外", "US", "ＵＳ")):
        return AssetClass.US_STOCK
    if any(k in text for k in ("投資信託", "ファンド", "投信")):
        return AssetClass.FUND
    if "債券" in text:
        return AssetClass.BOND
    # ラベルが無いCSVもあるので列名から推測する
    if hmap.has_any(("基準価額", "ファンド名", "口数")):
        return AssetClass.FUND
    return AssetClass.JP_STOCK


def _is_margin_block(label: str, hmap: nz.HeaderMap) -> bool:
    if any(k in label for k in ("信用", "建玉")):
        return True
    # 「建単価」「建日」「返済期限」があれば列構成だけで信用と判る
    return hmap.score(("建単価", "建日", "返済期限", "弁済期限", "建株数")) >= 2


def _side(value: Optional[str]) -> MarginSide:
    v = value or ""
    if any(k in v for k in ("売建", "売り建", "空売", "ショート", "SHORT", "売")):
        return MarginSide.SHORT
    return MarginSide.LONG


def _kind(value: Optional[str], label: str = "") -> MarginKind:
    v = (value or "") + label
    if "いちにち" in v or "デイトレ" in v:
        return MarginKind.DAYTRADE
    if "制度" in v:
        return MarginKind.SEIDO
    if "一般" in v or "無期限" in v or "短期" in v:
        return MarginKind.IPPAN
    return MarginKind.UNKNOWN


def _fund_multiplier(asset_class: AssetClass, hmap: nz.HeaderMap) -> float:
    """投資信託の基準価額は1万口あたり表示。口数×基準価額/10000 が評価額。"""
    if asset_class is not AssetClass.FUND:
        return 1.0
    return 1.0 / 10000.0


def _parse_spot_block(block: Block, source: str) -> list[SpotPosition]:
    h = block.hmap
    asset_class = _asset_class(block.label, h)
    multiplier = _fund_multiplier(asset_class, h)
    out: list[SpotPosition] = []

    for row in block.rows:
        name = h.get(row, nz.NAME) or ""
        symbol = nz.parse_symbol(h.get(row, nz.SYMBOL) or "")
        if not symbol and not name:
            continue
        # 合計行はコードが空で「合計」等が入る。分析側で二重計上するので捨てる。
        if any(k in name for k in ("合計", "小計", "総計")):
            continue

        qty = nz.to_number(h.get(row, nz.QUANTITY))
        if not qty:
            continue

        avg_cost = nz.to_number(h.get(row, nz.AVG_COST)) or 0.0
        last = nz.to_number(
            h.get(row, nz.LAST_PRICE, exclude=("前日比", "騰落", "評価額"))
        )

        # 単価が取れなくても評価額があれば逆算できる
        if last is None:
            mv = nz.to_number(h.get(row, nz.MARKET_VALUE))
            if mv is not None and qty:
                last = mv / (qty * multiplier)

        currency = h.get(row, nz.CURRENCY) or (
            "USD" if asset_class is AssetClass.US_STOCK else "JPY"
        )

        out.append(
            SpotPosition(
                symbol=symbol or name,
                name=name,
                asset_class=asset_class,
                account=h.get(row, nz.ACCOUNT) or "不明",
                quantity=qty,
                avg_cost=avg_cost,
                last_price=last,
                currency=currency.upper() if currency else "JPY",
                price_multiplier=multiplier,
                source=source,
            )
        )
    return out


def _parse_margin_block(block: Block, source: str) -> list[MarginPosition]:
    h = block.hmap
    out: list[MarginPosition] = []

    for row in block.rows:
        name = h.get(row, nz.NAME) or ""
        symbol = nz.parse_symbol(h.get(row, nz.SYMBOL) or "")
        if not symbol and not name:
            continue
        if any(k in name for k in ("合計", "小計", "総計")):
            continue

        qty = nz.to_number(h.get(row, nz.OPEN_QTY))
        if not qty:
            continue

        open_price = nz.to_number(h.get(row, nz.OPEN_PRICE)) or 0.0
        last = nz.to_number(
            h.get(row, nz.LAST_PRICE, exclude=("前日比", "騰落", "建単価"))
        )
        kind = _kind(h.get(row, nz.MARGIN_KIND), block.label)

        out.append(
            MarginPosition(
                symbol=symbol or name,
                name=name,
                side=_side(h.get(row, nz.MARGIN_SIDE) or block.label),
                kind=kind,
                quantity=qty,
                open_price=open_price,
                last_price=last,
                open_date=nz.parse_date(h.get(row, nz.OPEN_DATE)),
                due_date=nz.parse_date(h.get(row, nz.DUE_DATE)),
                accrued_cost=abs(nz.to_number(h.get(row, nz.ACCRUED_COST)) or 0.0),
                source=source,
            )
        )
    return out


def _scan_scalars(rows: list[list[str]]) -> tuple[float, Optional[MarginAccount], Optional[str]]:
    """「保証金現金,1,200,000」のような2セルの明細行から口座情報を拾う。"""
    cash = 0.0
    cash_deposit: Optional[float] = None
    substitute: Optional[float] = None
    asof: Optional[str] = None

    for row in rows:
        filled = [c for c in row if c]
        if not filled:
            continue
        joined = "".join(filled)

        if asof is None and any(k in joined for k in ("基準日", "作成日", "出力日", "時点")):
            d = nz.parse_date(filled[-1]) or nz.parse_date(joined)
            if d:
                asof = d.isoformat()

        if len(filled) != 2:
            continue
        label, value = filled[0], nz.to_number(filled[1])
        if value is None:
            continue
        if any(k in label for k in ("預り金", "現金残高", "buying", "MRF", "証券総合口座")):
            cash += value
        elif any(k in label for k in nz.CASH_DEPOSIT):
            cash_deposit = value
        elif any(k in label for k in nz.SUBSTITUTE):
            substitute = value

    account = None
    if cash_deposit is not None or substitute is not None:
        account = MarginAccount(
            cash_deposit=cash_deposit or 0.0,
            substitute_value=substitute or 0.0,
        )
    return cash, account, asof


def load_csv(path: Path) -> Portfolio:
    """CSV1本を読んで Portfolio にする。1ファイルに現物と信用が混在してもよい。"""
    rows, encoding = read_rows(path)
    source = path.name
    pf = Portfolio(sources=[f"{source} ({encoding})"])

    blocks = split_blocks(rows)
    if not blocks:
        pf.warnings.append(
            f"{source}: ヘッダ行を検出できなかった。inspect_file ツールで中身を確認してほしい。"
        )

    for block in blocks:
        if _is_margin_block(block.label, block.hmap):
            pf.margin.extend(_parse_margin_block(block, source))
        else:
            pf.spot.extend(_parse_spot_block(block, source))

    cash, account, asof = _scan_scalars(rows)
    pf.cash += cash
    if account:
        pf.margin_account = account
    pf.asof = asof or _asof_from_name(path)

    if not pf.spot and not pf.margin and blocks:
        pf.warnings.append(
            f"{source}: セクションは見つかったがポジション行を1件も解釈できなかった。"
        )
    return pf


def _asof_from_name(path: Path) -> Optional[str]:
    """assetbalance(all)_20260727.csv のようなファイル名から基準日を拾う。"""
    import re

    m = re.search(r"(20\d{2})[-_/]?(\d{2})[-_/]?(\d{2})", path.stem)
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def inspect(path: Path) -> dict:
    """診断用。文字コードと検出したブロック構成を返す。

    CSVの列名が想定外で読めなかったときに、何をどう認識したかを見るためのもの。
    """
    rows, encoding = read_rows(path)
    blocks = split_blocks(rows)
    return {
        "file": path.name,
        "encoding": encoding,
        "total_rows": len(rows),
        "blocks": [
            {
                "label": b.label,
                "classified_as": "margin" if _is_margin_block(b.label, b.hmap) else "spot",
                "header": b.header,
                "row_count": len(b.rows),
                "sample_row": b.rows[0] if b.rows else None,
            }
            for b in blocks
        ],
        "unclaimed_rows": [r for r in rows if len([c for c in r if c]) == 2][:20],
    }
