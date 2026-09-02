"""設定ファイルからは変更できない制約。

仕様として固定されているもの:
  - 除外銘柄 8053 / 9719 / 7518
  - ロングのみ。空売りしない（ショート側のロジックは存在しない）
"""

from __future__ import annotations

#: 除外銘柄。4桁表記で保持し、突合時に5桁へ展開する。
EXCLUDED_CODES_4 = frozenset({"8053", "9719", "7518"})

#: J-Quants の Code は5桁（末尾に "0" が付く）。4桁・5桁のどちらでも一致させる。
EXCLUDED_CODES = frozenset(
    set(EXCLUDED_CODES_4) | {c + "0" for c in EXCLUDED_CODES_4}
)

#: ロングのみ。この値は変更してはならない。
LONG_ONLY = True

#: 売買単位。
SHARES_PER_LOT = 100


def normalize_code(code: object) -> str:
    """銘柄コードを文字列に正規化する。

    J-Quants は5桁（"86970"）、一般的な表記は4桁（"8697"）。
    どちらで来ても比較できるよう、素の文字列として返す。
    """
    s = str(code).strip()
    if s.endswith(".0"):  # CSV 経由で float 化された場合
        s = s[:-2]
    return s


def is_excluded(code: object) -> bool:
    """仕様でハードコードされた除外銘柄かどうか。"""
    s = normalize_code(code)
    if s in EXCLUDED_CODES:
        return True
    # 5桁で来た場合の4桁比較（"80530" -> "8053"）
    if len(s) == 5 and s.endswith("0") and s[:4] in EXCLUDED_CODES_4:
        return True
    return False
