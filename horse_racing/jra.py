"""JRA 由来データの取り込みアダプタ。

JRA-VAN DataLab / netkeiba 等からエクスポートした「日本語ヘッダの
CSV」を、本ツールの :class:`~horse_racing.model.Horse` にマッピングして
読み込む。列名は表記ゆれに耐えるよう複数の別名を許容する。

注意:
    本リポジトリ環境はネットワーク egress が許可リスト制で、JRA/netkeiba
    へのライブアクセスはできない。実データは利用者が JRA-VAN 等から取得した
    CSV を渡す運用とする（netkeiba 等のスクレイピングは各サイト規約を要確認）。
"""

from __future__ import annotations

import csv
from pathlib import Path

from .model import Horse

# Horse フィールド -> 許容する CSV ヘッダ名(別名)の一覧。
# JRA-VAN / netkeiba / 一般的な日本語表記を広めに受ける。
_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "馬名", "馬", "horse"),
    "post_position": ("post_position", "馬番", "番", "umaban"),
    "field_size": ("field_size", "頭数", "出走頭数"),
    "weight": ("weight", "斤量", "負担重量", "斤量(kg)"),
    "odds": ("odds", "単勝", "単勝オッズ", "オッズ"),
    "recent_form": ("recent_form", "近走平均着順", "平均着順", "前走着順"),
    "speed": ("speed", "スピード", "スピード指数"),
    "time_index": ("time_index", "タイム指数", "指数", "speed_figure"),
    "horse_weight": ("horse_weight", "馬体重"),
    "weight_diff": ("weight_diff", "増減", "馬体重増減", "前走比"),
    "distance": ("distance", "距離", "今回距離"),
    "best_distance": ("best_distance", "得意距離", "ベスト距離"),
    "days_since_last": ("days_since_last", "間隔", "前走間隔", "中何週", "休養日数"),
    "class_up": ("class_up", "昇級", "昇級初戦", "クラス替"),
    "jockey": ("jockey", "騎手評価", "騎手"),
    "training": ("training", "調教評価", "調教"),
    "going_fit": ("going_fit", "馬場適性", "適性"),
}

# 馬番から頭数を推定したくない場合に備え、横向き(=不要)な Horse の生フィールド。
_INT_FIELDS = {"post_position", "field_size", "distance", "best_distance", "days_since_last"}
_BOOL_FIELDS = {"class_up"}
# horse_weight は Horse のフィールドに無いため取り込み時は捨てる(増減のみ使用)。
_IGNORED = {"horse_weight"}


def _normalize_header(raw: str) -> str:
    return raw.strip().lstrip("﻿")


def _build_column_map(fieldnames: list[str]) -> dict[str, str]:
    """CSV ヘッダ -> Horse フィールド名 の対応を作る。"""

    alias_to_field: dict[str, str] = {}
    for field_name, aliases in _HEADER_ALIASES.items():
        for alias in aliases:
            alias_to_field[alias] = field_name

    mapping: dict[str, str] = {}
    for col in fieldnames:
        key = _normalize_header(col)
        if key in alias_to_field:
            mapping[col] = alias_to_field[key]
    return mapping


def _parse_bool(raw: str) -> bool:
    return raw.strip() in {"1", "true", "True", "○", "◯", "yes", "Y", "昇級", "あり"}


def load_jra_csv(path: str | Path) -> list[Horse]:
    """JRA 由来の日本語ヘッダ CSV を読み込み Horse のリストを返す。

    `馬名`(または name) 列は必須。認識できない列は無視する。
    `頭数` 列が無くても、`馬番` の最大値から自動補完する。
    """

    path = Path(path)
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"{path} にヘッダがありません")
        colmap = _build_column_map(reader.fieldnames)
        if "name" not in colmap.values():
            raise ValueError("CSV に馬名(name/馬名)列が必要です")
        rows = list(reader)

    horses: list[Horse] = []
    for lineno, row in enumerate(rows, start=2):
        kwargs: dict[str, object] = {}
        for col, field_name in colmap.items():
            if field_name in _IGNORED:
                continue
            raw = row.get(col)
            if raw is None or raw.strip() == "":
                continue
            kwargs[field_name] = _cast(field_name, raw.strip(), path, lineno)
        horses.append(kwargs)  # type: ignore[arg-type]

    if not horses:
        raise ValueError(f"{path} に出走馬データがありません")

    # 頭数が未指定なら馬番の最大値で補完。
    has_field_size = any("field_size" in k for k in horses)  # type: ignore[operator]
    if not has_field_size:
        max_no = max((k.get("post_position", 0) for k in horses), default=0)  # type: ignore[union-attr]
        if max_no:
            for k in horses:
                k.setdefault("field_size", max_no)  # type: ignore[union-attr]

    return [Horse(**k) for k in horses]  # type: ignore[arg-type]


def _cast(field_name: str, raw: str, path: Path, lineno: int):
    try:
        if field_name in _BOOL_FIELDS:
            return _parse_bool(raw)
        if field_name == "name":
            return raw
        # "+8" / "-4" / "480(+8)" のような表記に簡易対応
        if field_name == "weight_diff" and "(" in raw and ")" in raw:
            raw = raw[raw.index("(") + 1 : raw.index(")")]
        cleaned = raw.replace("+", "").replace("kg", "").replace("m", "")
        if field_name in _INT_FIELDS:
            return int(float(cleaned))
        return float(cleaned)
    except ValueError as exc:
        raise ValueError(
            f"{path}:{lineno} 列 '{field_name}' の値が不正です: {raw!r}"
        ) from exc
