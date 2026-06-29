"""M5: 実 JV-Link(JRA-VAN DataLab)取込アダプタ。

本モジュールは Windows + 32bit Python + pywin32 + DataLab 会員 を前提とする。
サンドボックス(Linux)では COM 部分は動かないが、**Shift-JIS 固定長レコードの
パーサ枠組みは OS 非依存で動作・テスト可能**(下の RecordSpec / parse_fixed_record)。

取得フロー(research第2.2章):
    JVInit(sid) → JVSetServiceKey(key) → JVOpen(dataspec, fromtime, option)
      → JVStatus でDL監視 → JVRead ループ(SJIS固定長) → JVClose
レコードは先頭2バイトの種別ID(RA/SE/HR/O1...)でディスパッチし、未知IDは読み飛ばす
(仕様準拠・バージョンアップ耐性)。

⚠️ 各フィールドのオフセット/桁は **JV-Data 仕様書(JV-Data4512.xlsx 等)で要確定**。
   ここに置く RA/SE のスペックは枠組みを示す *代表例* であり、本番投入前に
   公式仕様で各 (offset, length) を裏取りすること(誤ると桁ズレで全列破損)。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .reader import JVLinkReader

ENCODING = "cp932"  # Shift-JIS(JV-Data は CP932 固定長)


# ---------------------------------------------------------------------------
# 固定長レコードのパーサ枠組み(OS 非依存・テスト可能)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FieldSpec:
    name: str
    offset: int           # バイトオフセット(0始まり)
    length: int           # バイト長
    kind: str = "str"     # "str" | "int" | "float"
    scale: float = 1.0    # int/float を割るスケール(例: 0.1kg 単位 → scale=10)

    def parse(self, raw: bytes):
        chunk = raw[self.offset : self.offset + self.length]
        text = chunk.decode(ENCODING, errors="replace").strip()
        if self.kind == "str":
            return text
        if text == "":
            return 0 if self.kind == "int" and self.scale == 1.0 else 0.0
        try:
            if self.kind == "int":
                return int(text) if self.scale == 1.0 else int(text) / self.scale
            if self.kind == "float":
                return float(text) / self.scale
        except ValueError:
            return None
        return text


@dataclass(frozen=True)
class RecordSpec:
    record_type: str            # 先頭2バイトの種別ID(例 "RA", "SE")
    fields: tuple               # tuple[FieldSpec]

    def parse(self, raw: bytes) -> dict:
        return {f.name: f.parse(raw) for f in self.fields}


def parse_fixed_record(raw: bytes, spec: RecordSpec) -> dict:
    """1レコード(bytes)を spec に従ってフィールド辞書へ。"""
    return spec.parse(raw)


def record_type_of(raw: bytes) -> str:
    """レコード先頭2バイトの種別IDを返す。"""
    return raw[:2].decode(ENCODING, errors="replace")


# 代表例(★offset/length は JV-Data 仕様書で要確定)。
# 実際の RA/SE はフィールド数が多く桁も厳密。ここでは枠組み確認用の最小サブセット。
RA_SPEC = RecordSpec(
    record_type="RA",
    fields=(
        FieldSpec("record_type", 0, 2, "str"),
        FieldSpec("data_kubun", 2, 1, "str"),
        FieldSpec("year", 11, 4, "int"),
        FieldSpec("month_day", 15, 4, "str"),
        FieldSpec("jyo_code", 19, 2, "str"),    # 競馬場コード
        FieldSpec("race_num", 25, 2, "int"),
        # ↓ 距離・トラックコード等は仕様書で offset 要確定
    ),
)
SE_SPEC = RecordSpec(
    record_type="SE",
    fields=(
        FieldSpec("record_type", 0, 2, "str"),
        FieldSpec("data_kubun", 2, 1, "str"),
        FieldSpec("umaban", 25, 2, "int"),       # 馬番
        FieldSpec("ketto_num", 27, 10, "str"),   # 血統登録番号(=horse_id)
        # 着順・確定タイム等は確定後情報。特徴量化は features 層の PiT 規約に従う。
    ),
)

DEFAULT_SPECS = {"RA": RA_SPEC, "SE": SE_SPEC}


# ---------------------------------------------------------------------------
# COM フロー(Windows 専用。Linux では生成時に明示エラー)
# ---------------------------------------------------------------------------

class JVLinkClient:
    """pywin32 で 'JVDTLab.JVLink' を駆動する薄いラッパ。

    Windows + 32bit Python + pywin32 が必要。64bit から使う場合は DllSurrogate
    設定(research第2.4章)。サービスキーが -100 を返す場合はレジストリ直書きで回避。
    """

    PROGID = "JVDTLab.JVLink"

    def __init__(self, sid: str = "UNKNOWN", service_key: str | None = None):
        self.sid = sid
        self.service_key = service_key
        self._link = None

    def _dispatch(self):  # pragma: no cover - Windows COM のみ
        try:
            import win32com.client  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "pywin32 が必要です(Windows/32bit Python)。"
                "サンドボックス(Linux)では JV-Link COM は利用できません。"
            ) from exc
        return win32com.client.Dispatch(self.PROGID)

    def open(self):  # pragma: no cover
        self._link = self._dispatch()
        rc = self._link.JVInit(self.sid)
        if rc != 0:
            raise RuntimeError(f"JVInit 失敗: {rc}")
        if self.service_key:
            self._link.JVSetServiceKey(self.service_key)
        return self

    def fetch(self, dataspec: str, fromtime: str, option: int = 1):  # pragma: no cover
        """蓄積系を JVOpen → JVRead ループで取得し、生レコード(bytes)を yield。"""
        if self._link is None:
            self.open()
        rc, read_cnt, dl_cnt, last_ts = self._link.JVOpen(dataspec, fromtime, option)
        if rc != 0:
            raise RuntimeError(f"JVOpen 失敗: {rc}")
        try:
            while True:
                rc, buf, size, fname = self._link.JVRead(b"", 0, "")
                if rc == 0:        # EOF
                    break
                if rc == -1:       # 次ファイル境界
                    continue
                if rc < 0:
                    raise RuntimeError(f"JVRead エラー: {rc}")
                yield buf if isinstance(buf, bytes) else bytes(buf)
        finally:
            self._link.JVClose()

    def close(self):  # pragma: no cover
        if self._link is not None:
            try:
                self._link.JVClose()
            except Exception:
                pass
            self._link = None


# ---------------------------------------------------------------------------
# 実データバックエンド(取得 → パース → 正規化 → schema 準拠 DataFrame)
# ---------------------------------------------------------------------------

class RealJVLinkBackend(JVLinkReader):
    """JV-Link から取得し schema 準拠の (runners, races) を返す。

    本番運用では fetch した生レコードを DEFAULT_SPECS でパースし、RA→races、
    SE+オッズ+払戻+馬体重→runners に正規化する。正規化マッピングは features 層が
    要求する列(schema.PRE_RACE_COLUMNS / POST_RACE_COLUMNS)へ合わせること。

    サンドボックスでは COM が無いため load() は明示エラー。代替として
    EveryDB2/jrvltsql が構築した DB を store.DuckDBBackend で読む運用も可。
    """

    def __init__(self, service_key: str | None = None,
                 fromtime: str = "20200101000000",
                 dataspecs: tuple = ("RACE",), specs: dict | None = None):
        self.client = JVLinkClient(service_key=service_key)
        self.fromtime = fromtime
        self.dataspecs = dataspecs
        self.specs = specs or DEFAULT_SPECS

    def load(self) -> tuple[pd.DataFrame, pd.DataFrame]:  # pragma: no cover
        raise NotImplementedError(
            "RealJVLinkBackend.load は Windows/32bit Python/pywin32/DataLab会員 が必要。"
            "サンドボックス(Linux)では動作しない。生レコードのパースは "
            "keiba.jvlink.parse_fixed_record で OS 非依存に検証できる。"
            "正規化(RA→races, SE→runners)は schema 準拠で実装すること。"
        )

    def parse_records(self, raw_records) -> list[dict]:
        """生レコード列を種別IDでディスパッチしてパース(未知IDは読み飛ばす)。"""
        out = []
        for raw in raw_records:
            rid = record_type_of(raw)
            spec = self.specs.get(rid)
            if spec is None:
                continue  # 未知種別は読み飛ばす(仕様準拠)
            out.append(parse_fixed_record(raw, spec))
        return out
