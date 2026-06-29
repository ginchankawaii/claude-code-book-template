"""データ入出力ユーティリティ。

CSV からの出走馬読み込みと、デモ用サンプルレースの提供を行う。
"""

from __future__ import annotations

import csv
from pathlib import Path

from .model import Horse

# CSV のヘッダ名と Horse フィールドの対応
_FIELD_TYPES = {
    "name": str,
    "speed": float,
    "recent_form": float,
    "weight": float,
    "odds": float,
    "jockey": float,
    "going_fit": float,
}


def load_horses_csv(path: str | Path) -> list[Horse]:
    """CSV ファイルから出走馬を読み込む。

    最低限 ``name`` 列が必要。その他の列は省略可能で、
    省略時は :class:`Horse` の既定値が使われる。
    """

    path = Path(path)
    horses: list[Horse] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or "name" not in reader.fieldnames:
            raise ValueError("CSV に 'name' 列が必要です")
        for lineno, row in enumerate(reader, start=2):
            kwargs = {}
            for field_name, caster in _FIELD_TYPES.items():
                raw = row.get(field_name)
                if raw is None or raw.strip() == "":
                    continue
                try:
                    kwargs[field_name] = caster(raw.strip())
                except ValueError as exc:
                    raise ValueError(
                        f"{path}:{lineno} 列 '{field_name}' の値が不正です: {raw!r}"
                    ) from exc
            horses.append(Horse(**kwargs))
    if not horses:
        raise ValueError(f"{path} に出走馬データがありません")
    return horses


def sample_race() -> list[Horse]:
    """デモ用のサンプルレース (8頭立て) を返す。"""

    return [
        Horse("サンダーボルト", speed=108, recent_form=1.8, weight=57, odds=3.2, jockey=85, going_fit=78),
        Horse("ミラクルスター", speed=104, recent_form=2.6, weight=55, odds=4.5, jockey=72, going_fit=70),
        Horse("ゴールデンウイング", speed=112, recent_form=3.4, weight=58, odds=5.0, jockey=80, going_fit=60),
        Horse("シルバームーン", speed=98, recent_form=4.0, weight=54, odds=9.0, jockey=60, going_fit=66),
        Horse("ブレイズランナー", speed=101, recent_form=5.2, weight=56, odds=12.0, jockey=68, going_fit=55),
        Horse("クリムゾンフレア", speed=95, recent_form=6.0, weight=53, odds=21.0, jockey=55, going_fit=50),
        Horse("オーシャンブリーズ", speed=90, recent_form=7.5, weight=55, odds=48.0, jockey=48, going_fit=45),
        Horse("ノーザンライト", speed=88, recent_form=8.1, weight=54, odds=80.0, jockey=40, going_fit=40),
    ]


def write_sample_csv(path: str | Path) -> Path:
    """サンプルレースを CSV として書き出す。"""

    path = Path(path)
    fieldnames = list(_FIELD_TYPES.keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for h in sample_race():
            writer.writerow(
                {
                    "name": h.name,
                    "speed": h.speed,
                    "recent_form": h.recent_form,
                    "weight": h.weight,
                    "odds": h.odds,
                    "jockey": h.jockey,
                    "going_fit": h.going_fit,
                }
            )
    return path
