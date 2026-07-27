"""CSVの表記ゆれを吸収するための正規化ユーティリティ。

楽天証券のCSVは出力画面・時期・商品種別でヘッダ名や単位表記が変わる。
列名を完全一致で決め打ちすると簡単に壊れるので、同義語テーブル＋部分一致で解決する。
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from typing import Iterable, Optional, Sequence

# 全角記号・BOM・単位注記を落とすための除去パターン
_NOISE = re.compile(r"[\s　]|[\[\]【】（）\(\)]|[・･]")
_TRAILING_UNIT = re.compile(r"(円|株|口|％|%|倍|日|件|jpy|usd)+$", re.IGNORECASE)

# 日本語の会計表記で使われるマイナス記号
_MINUS_MARKS = ("▲", "△", "−", "－", "‐", "‑", "―", "ー")


def normalize_text(s: Optional[str]) -> str:
    """全角→半角、空白除去、BOM除去。ヘッダ照合と値の前処理の共通入口。"""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    return s.replace("﻿", "").strip()


def normalize_header(s: Optional[str]) -> str:
    """ヘッダ照合用のキー。記号・空白・末尾単位を落として比較しやすくする。"""
    s = normalize_text(s)
    s = _NOISE.sub("", s)
    s = _TRAILING_UNIT.sub("", s)
    return s.lower()


def to_number(value: object) -> Optional[float]:
    """「1,234円」「▲5.2%」「+3,000」「--」などを float に落とす。

    数値として読めないものは例外ではなく None を返す。CSVの1セルが欠けただけで
    ポートフォリオ全体の読み込みが落ちるのを避けるため。
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)

    s = normalize_text(value)
    if not s:
        return None

    negative = False
    for mark in _MINUS_MARKS:
        if mark in s:
            # ▲/△ は先頭に付く負号。ハイフン類は通常のマイナスとして後段で処理
            if mark in ("▲", "△"):
                negative = True
            s = s.replace(mark, "-")

    s = s.replace(",", "").replace("円", "").replace("株", "").replace("口", "")
    s = s.replace("%", "").replace("倍", "").replace("+", "").strip()

    # "-" や "--" や "N/A" のような欠損表現
    if s in ("", "-", "--", "---", "n/a", "na", "nan", "*"):
        return None

    try:
        num = float(s)
    except ValueError:
        # "1234.5(円)" のような残骸から数字だけ拾う最後の試み
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        if not m:
            return None
        num = float(m.group())

    return -abs(num) if negative else num


def parse_date(value: object) -> Optional[dt.date]:
    """2026/7/27, 2026-07-27, 20260727, 26/07/27 などを日付にする。"""
    s = normalize_text(value)
    if not s:
        return None
    s = re.sub(r"[年月]", "/", s).replace("日", "")
    s = s.strip("/")

    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y%m%d", "%y/%m/%d", "%Y/%m", "%m/%d"):
        try:
            parsed = dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
        if fmt == "%m/%d":
            # 年が省略されたCSVは今年として扱う
            parsed = parsed.replace(year=dt.date.today().year)
        return parsed
    return None


def parse_symbol(value: object) -> str:
    """銘柄コードの正規化。国内株の4桁は文字列のまま保つ（先頭0落ち防止）。"""
    s = normalize_text(value).upper()
    s = s.strip("'\"")
    if re.fullmatch(r"\d+(\.0)?", s):
        s = s.split(".")[0]
        # 国内株コードは4〜5桁。CSVによって "7203" が数値化されるので0埋めし直す
        if len(s) <= 4:
            s = s.zfill(4)
    return s


class HeaderMap:
    """ヘッダ行から「意味のある列名 → 列インデックス」を解決する。

    完全一致 → 前方一致 → 部分一致 の順で緩めていく。厳しい順に試すことで
    「評価損益」と「評価損益率」のような紛らわしい列を取り違えにくくする。
    """

    def __init__(self, header: Sequence[str]) -> None:
        self.raw = list(header)
        self.keys = [normalize_header(h) for h in header]

    def find(self, candidates: Iterable[str], exclude: Iterable[str] = ()) -> Optional[int]:
        cands = [normalize_header(c) for c in candidates]
        excl = [normalize_header(e) for e in exclude if e]

        def blocked(key: str) -> bool:
            return any(e and e in key for e in excl)

        for cand in cands:
            for i, key in enumerate(self.keys):
                if key == cand and not blocked(key):
                    return i
        for cand in cands:
            for i, key in enumerate(self.keys):
                if key.startswith(cand) and not blocked(key):
                    return i
        for cand in cands:
            for i, key in enumerate(self.keys):
                if cand and cand in key and not blocked(key):
                    return i
        return None

    def get(
        self,
        row: Sequence[str],
        candidates: Iterable[str],
        exclude: Iterable[str] = (),
    ) -> Optional[str]:
        idx = self.find(candidates, exclude)
        if idx is None or idx >= len(row):
            return None
        return normalize_text(row[idx])

    def has_any(self, candidates: Iterable[str]) -> bool:
        return self.find(candidates) is not None

    def score(self, candidates: Iterable[str]) -> int:
        """ヘッダ行らしさの判定に使う。候補語のうち何個当たったか。"""
        return sum(1 for c in candidates if self.find([c]) is not None)


# --- 列名の同義語テーブル ------------------------------------------------
# 楽天証券のCSV/画面コピペ/MarketSpeed II RSS で観測される表記を並べる。
# 新しい表記に出くわしたらここに1行足すだけで対応できるようにしてある。

SYMBOL = ("銘柄コード", "コード", "証券コード", "ティッカー", "symbol", "code", "銘柄ｺｰﾄﾞ")
NAME = ("銘柄名", "銘柄", "ファンド名", "商品名", "name", "銘柄・ファンド名")
ACCOUNT = ("口座区分", "口座", "預り区分", "account")
QUANTITY = ("保有数量", "数量", "保有株数", "株数", "残高数量", "保有口数", "口数", "quantity")
AVG_COST = ("平均取得価額", "取得単価", "平均取得単価", "取得価額", "簿価単価", "平均約定単価")
LAST_PRICE = ("現在値", "時価", "基準価額", "終値", "現值", "現在価格", "last")
MARKET_VALUE = ("時価評価額", "評価額", "残高評価額", "評価金額")
PNL = ("評価損益", "含み損益", "損益")
PNL_PCT = ("評価損益率", "損益率", "評価損益割合")
CURRENCY = ("通貨", "通貨単位", "currency")

MARGIN_SIDE = ("売買区分", "建区分", "取引区分", "建玉区分", "売買")
MARGIN_KIND = ("信用区分", "建玉種別", "信用取引区分", "弁済期限区分", "商品区分")
OPEN_DATE = ("建日", "約定日", "新規建日", "建玉日")
DUE_DATE = ("返済期限", "弁済期限", "期日", "決済期限")
OPEN_PRICE = ("建単価", "建値", "新規建単価", "約定単価")
OPEN_QTY = ("建株数", "建玉数量", "保有株数", "株数", "数量", "建数量")
ACCRUED_COST = ("諸経費", "金利", "貸株料", "経費", "手数料等", "諸経費等")

CASH_DEPOSIT = ("保証金現金", "現金保証金", "受入保証金現金", "差入保証金現金")
SUBSTITUTE = ("代用有価証券", "代用有価証券評価額", "代用証券評価額")
