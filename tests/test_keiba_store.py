"""keiba M0/M5: DuckDB境界とJV-Link固定長パーサのテスト。"""

import numpy as np
import pytest

from keiba.jvlink import (
    ENCODING,
    FieldSpec,
    RealJVLinkBackend,
    RecordSpec,
    parse_fixed_record,
    record_type_of,
)
from keiba.reader import SyntheticBackend
from keiba.store import DuckDBBackend, load_dataset, save_dataset
from keiba.synth import SyntheticConfig, generate_dataset


def test_duckdb_roundtrip(tmp_path):
    runners, races = generate_dataset(SyntheticConfig(n_days=30, seed=4))
    p = tmp_path / "keiba.duckdb"
    save_dataset(runners, races, p)
    r2, ra2 = load_dataset(p)
    assert len(r2) == len(runners)
    assert len(ra2) == len(races)
    assert set(r2.columns) == set(runners.columns)


def test_duckdb_backend_feeds_pipeline(tmp_path):
    """取得層が書いた DuckDB を分析層が読んで end-to-end で動く(境界の疎結合)。"""
    runners, races = SyntheticBackend(SyntheticConfig(n_days=140, seed=2)).load()
    p = tmp_path / "k.duckdb"
    save_dataset(runners, races, p)

    from keiba.backtest import WalkForwardConfig, walk_forward
    from keiba.features import build_features
    from keiba.model import ModelConfig

    feat = build_features(DuckDBBackend(p).load()[0])
    bt = walk_forward(feat, ModelConfig(num_boost_round=80),
                      wf_config=WalkForwardConfig(train_min_days=70, valid_days=30, test_days=30))
    assert bt["n_folds"] >= 1


def test_load_missing_db_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_dataset(tmp_path / "nope.duckdb")


def test_fixed_length_parser():
    spec = RecordSpec("SE", (
        FieldSpec("record_type", 0, 2, "str"),
        FieldSpec("umaban", 2, 2, "int"),
        FieldSpec("weight", 4, 3, "int"),
        FieldSpec("hweight", 7, 4, "float"),
    ))
    rec = "SE07057 480".encode(ENCODING)
    parsed = parse_fixed_record(rec, spec)
    assert parsed == {"record_type": "SE", "umaban": 7, "weight": 57, "hweight": 480.0}
    assert record_type_of(rec) == "SE"


def test_field_scale_and_empty():
    spec = RecordSpec("RA", (FieldSpec("w", 0, 4, "float", scale=10.0),
                             FieldSpec("blank", 4, 3, "int")))
    rec = "0573   ".encode(ENCODING)
    out = parse_fixed_record(rec, spec)
    assert abs(out["w"] - 57.3) < 1e-9   # scale=10
    assert out["blank"] == 0             # 空はゼロ


def test_unknown_record_skipped():
    spec = RecordSpec("SE", (FieldSpec("record_type", 0, 2, "str"),))
    b = RealJVLinkBackend(specs={"SE": spec})
    recs = ["SExxx".encode(ENCODING), "ZZyyy".encode(ENCODING), "SEzzz".encode(ENCODING)]
    assert len(b.parse_records(recs)) == 2


def test_real_backend_load_guarded_on_linux():
    # サンドボックス(Linux)では COM 不可で明示エラー
    with pytest.raises(NotImplementedError):
        RealJVLinkBackend().load()
