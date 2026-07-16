"""scripts.diagnose_live — 記録された signals/equity からの読み取り専用フォレンジック。

合成DB(実スキーマ、tmp sqlite)でライブの一連の出来事を再現し、
  * 意図サイクルの復元と出口ラベル (stop / ai-veto / trend)
  * 残高差分による損益帰属
  * AIコンサル回数の復元とコスト概算
  * 異常検知 (ストップ無しLONG、equityギャップ)
  * 読み取り専用性 (書けない・DBを作らない)
を検証する。
"""
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import scripts.diagnose_live as D
from app import bridge, db

T0 = datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc)  # 水曜


def _h(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


@pytest.fixture
def synth_db(tmp_path) -> str:
    """ライブの筋書きを実スキーマで再現した合成DB。

    entry(daily, AI承認) -> hold(gate) -> ストップ退出
    -> AI拒否でエントリー見送り(gate-entry)
    -> entry(daily, AI承認) -> トレンド転換で退出(gate-exit) -> 次の判断で残高確定
    """
    path = str(tmp_path / "live.db")
    db.init_db(path)
    rid = db.create_run(mode="live", instrument="USD_JPY", granularity="H1",
                        initial_balance=300_000.0,
                        params={"system": "steady-ai", "model": "claude-sonnet-4-6",
                                "max_risk": 0.04},
                        db_path=path)

    def sig(t, direction, reason, comp):
        db.record_signal(rid, t, "USD_JPY", "combined", direction,
                         float(direction), reason, comp, db_path=path)

    def eq(t, bal, equity, price):
        db.record_equity(rid, t, bal, equity, price, db_path=path)

    # --- サイクル1: エントリー(残高300k) → 保有 → ストップ ---
    eq(_h(0), 300_000, 300_000, 162.000)
    sig(_h(0), 1, "trend-up; AI approves",
        {"action": "LONG", "trigger": "daily", "trend_up": True, "conviction": 0.8,
         "brake": 1.0, "eff_leverage": 5.0, "stop_price": 161.400,
         "target_lots": 0.09, "position_lots": 0.0})
    eq(_h(6), 300_000, 299_500, 161.900)
    sig(_h(6), 1, "hold",
        {"action": "LONG", "trigger": "gate-rearm", "trend_up": True,
         "brake": 1.0, "eff_leverage": 5.0, "stop_price": 161.400,
         "target_lots": 0.09, "position_lots": 0.09})
    # ストップ退出 (equity記録なし — 本番同様 record_stop_exit はシグナルのみ)
    sig(_h(10), 0, "stop-loss: last 161.380 <= stop 161.400",
        {"action": "FLAT", "trigger": "stop", "stop_price": 161.400,
         "position_lots": 0.09})

    # --- AI拒否でエントリー見送り (トレンドは上) ---
    eq(_h(14), 294_400, 294_400, 161.600)   # ストップの実現損 -5,600 が残高に反映
    sig(_h(14), 0, "trend-up but Opus veto (flat): CPI miss; FOMC ahead",
        {"action": "FLAT", "trigger": "gate-entry", "trend_up": True,
         "conviction": 0.0, "brake": 1.0, "eff_leverage": 5.0,
         "stop_price": None, "target_lots": 0.0, "position_lots": 0.0})

    # --- サイクル2: エントリー → トレンド転換で退出 → 次判断で残高確定 ---
    eq(_h(20), 294_400, 294_400, 161.800)
    sig(_h(20), 1, "trend-up; AI approves",
        {"action": "LONG", "trigger": "daily", "trend_up": True, "conviction": 0.7,
         "brake": 0.70, "eff_leverage": 4.2, "stop_price": 161.200,
         "target_lots": 0.08, "position_lots": 0.0})
    eq(_h(30), 294_400, 295_200, 162.100)
    sig(_h(30), 0, "trend-down: price 161.500 < SMA2400 161.600 -> stand aside",
        {"action": "FLAT", "trigger": "gate-exit", "trend_up": False,
         "brake": 0.70, "eff_leverage": 4.2, "stop_price": None,
         "target_lots": 0.0, "position_lots": 0.08})
    # 次のトレンド下判断 (無料) — 残高にサイクル2の実現損 -2,400 が反映済み
    eq(_h(44), 292_000, 292_000, 161.400)
    sig(_h(44), 0, "trend-down: price 161.400 < SMA2400 161.600 -> stand aside",
        {"action": "FLAT", "trigger": "daily", "trend_up": False,
         "brake": 0.70, "eff_leverage": 4.2, "stop_price": None,
         "target_lots": 0.0, "position_lots": 0.0})
    return path


def _load(path):
    return D.load_run_data(path)


# --------------------------------------------------------------------------- #
# サイクル復元と損益帰属
# --------------------------------------------------------------------------- #
def test_cycles_reconstructed_with_exit_labels(synth_db):
    data = _load(synth_db)
    cycles, vetoed = D.build_cycles(data["signals"])
    assert [c["trigger"] for c in cycles] == ["stop", "trend"]
    assert len(vetoed) == 1
    assert "veto" in vetoed[0]["reason"]
    assert cycles[0]["lots"] == pytest.approx(0.09)
    assert cycles[1]["lots"] == pytest.approx(0.08)


def test_pnl_attributed_from_balance_diffs(synth_db):
    data = _load(synth_db)
    cycles, _ = D.build_cycles(data["signals"])
    D.attach_pnl(cycles, data["equity"])
    # サイクル1: 300,000 -> 294,400 (ストップ後の最初の残高記録)
    assert cycles[0]["pnl"] == pytest.approx(-5_600)
    assert cycles[0]["pnl_method"] == "balance"
    assert cycles[0]["exit_price"] == pytest.approx(161.400)  # ストップはstop_price
    # サイクル2: 294,400 -> 292,000
    assert cycles[1]["pnl"] == pytest.approx(-2_400)
    by = D.pnl_by_trigger(cycles)
    assert by["stop"] == {"n": 1, "pnl": pytest.approx(-5_600)}
    assert by["trend"] == {"n": 1, "pnl": pytest.approx(-2_400)}


def test_open_cycle_without_exit_is_kept(synth_db):
    # 進行中サイクル: 最後にLONGを足すと exit なしで復元される
    data = _load(synth_db)
    rid = data["run"]["id"]
    db.record_signal(rid, _h(50), "USD_JPY", "combined", 1, 1.0, "trend-up; AI approves",
                     {"action": "LONG", "trigger": "daily", "trend_up": True,
                      "brake": 0.7, "eff_leverage": 5.0, "stop_price": 160.9,
                      "target_lots": 0.08, "position_lots": 0.0}, db_path=synth_db)
    cycles, _ = D.build_cycles(_load(synth_db)["signals"])
    assert cycles[-1]["trigger"] == "open" and cycles[-1]["exit_time"] is None


# --------------------------------------------------------------------------- #
# AIコンサル回数とコスト
# --------------------------------------------------------------------------- #
def test_consult_counting(synth_db):
    data = _load(synth_db)
    n = D.count_consults(data["signals"])
    # 課金: entry1(承認) + veto + entry2(承認) = 3。hold(gate-rearm)も課金判断1回。
    assert n["paid"] == 4
    assert n["approved"] == 3 and n["veto"] == 1
    assert n["free_trend_down"] == 2       # gate-exit + daily (トレンド下)
    assert n["stop_records"] == 1
    assert n["unavailable"] == 0


def test_consult_counts_opus_unavailable_as_unpaid(synth_db):
    data = _load(synth_db)
    rid = data["run"]["id"]
    db.record_signal(rid, _h(60), "USD_JPY", "combined", 1, 0.6,
                     "trend-up; Opus unavailable (ANTHROPIC_API_KEY not set)",
                     {"action": "LONG", "trigger": "daily", "trend_up": True,
                      "stop_price": 161.0, "target_lots": 0.08,
                      "position_lots": 0.0}, db_path=synth_db)
    n = D.count_consults(_load(synth_db)["signals"])
    assert n["unavailable"] == 1 and n["paid"] == 4


def test_api_cost_estimate_uses_model_pricing():
    sonnet = D.estimate_api_cost(10, "claude-sonnet-4-6")
    opus = D.estimate_api_cost(10, "claude-opus-4-8")
    assert sonnet["total_usd"] > 0
    assert opus["total_usd"] > sonnet["total_usd"]      # Opusの方が高い
    # 検索コスト: 10回 x 4検索 x $10/1000 = $0.40
    assert sonnet["web_search_usd"] == pytest.approx(0.40)
    assert D.estimate_api_cost(0, "claude-sonnet-4-6")["total_usd"] == 0.0
    # 不明モデルは保守的にOpus価格
    assert D.estimate_api_cost(10, "mystery-model")["pricing"] == D.DEFAULT_PRICING


# --------------------------------------------------------------------------- #
# バックテスト比較
# --------------------------------------------------------------------------- #
def test_backtest_comparison_metrics(synth_db):
    data = _load(synth_db)
    cycles, _ = D.build_cycles(data["signals"])
    D.attach_pnl(cycles, data["equity"])
    cmp_ = D.compare_with_backtest(cycles, data["equity"])
    assert cmp_["n_closed"] == 2 and cmp_["n_stops"] == 1
    assert cmp_["stop_share"] == pytest.approx(0.5)
    assert cmp_["balance0"] == pytest.approx(300_000)
    assert cmp_["return_pct"] == pytest.approx((292_000 / 300_000 - 1) * 100)
    # サイズ使用率: 0.09 lots vs 5.0x * 300k / (162.0 * 100k) = 0.0926 -> ~97%
    utils = [s["util"] for s in cmp_["sizes"] if s["util"]]
    assert utils and 0.9 < utils[0] <= 1.01


def test_backtest_reference_is_hardcoded():
    # docs/RESEARCH.md のリファレンスがスクリプト内に固定されている
    assert D.BACKTEST_REF["cagr_pct"] == 15.5
    assert D.BACKTEST_REF["max_dd_pct"] == 24.6
    assert D.BACKTEST_REF["trades"] == 219
    assert 0 < D.BACKTEST_REF["stop_share"] < 1


# --------------------------------------------------------------------------- #
# 異常検知
# --------------------------------------------------------------------------- #
def test_anomaly_long_run_without_stop(synth_db):
    data = _load(synth_db)
    rid = data["run"]["id"]
    # stop_price の無いLONGだけの連続 (旧記録の破損を再現)
    db.record_signal(rid, _h(70), "USD_JPY", "combined", 1, 1.0, "trend-up",
                     {"action": "LONG", "trigger": "daily", "trend_up": True,
                      "stop_price": None, "target_lots": 0.08,
                      "position_lots": 0.0}, db_path=synth_db)
    data = _load(synth_db)
    cycles, _ = D.build_cycles(data["signals"])
    warns = D.find_anomalies(data["signals"], data["equity"], data["runs"], cycles)
    assert any("ストップ価格の無いLONG" in w and "保有中" in w for w in warns)


def test_anomaly_equity_gap_flagged_but_weekend_ok(synth_db):
    data = _load(synth_db)
    cycles, _ = D.build_cycles(data["signals"])
    warns = D.find_anomalies(data["signals"], data["equity"], data["runs"], cycles)
    assert not any("ギャップ" in w for w in warns)   # 通常間隔は警告なし
    # 平日30時間のギャップを作る (T0=水曜起点、+44h=金曜04時 → +74h=月曜10時は週末OK、
    # 代わりに火曜に30h空ける)
    rid = data["run"]["id"]
    db.record_equity(rid, _h(44 + 100), 292_000, 292_000, 161.0, db_path=synth_db)
    db.record_equity(rid, _h(44 + 134), 292_000, 292_000, 161.0, db_path=synth_db)
    data = _load(synth_db)
    warns = D.find_anomalies(data["signals"], data["equity"], data["runs"], cycles)
    assert any("ギャップ" in w for w in warns)


def test_no_anomalies_on_healthy_records(synth_db):
    data = _load(synth_db)
    cycles, _ = D.build_cycles(data["signals"])
    D.attach_pnl(cycles, data["equity"])
    warns = D.find_anomalies(data["signals"], data["equity"], data["runs"], cycles)
    assert warns == []


def test_brake_history_change_points(synth_db):
    data = _load(synth_db)
    hist = D.brake_history(data["signals"])
    assert [b for _, b in hist] == [1.0, 0.70]      # 変化点のみ


# --------------------------------------------------------------------------- #
# 読み取り専用性とエンドツーエンド
# --------------------------------------------------------------------------- #
def test_connection_is_readonly(synth_db):
    with D._connect_ro(synth_db) as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO equity(run_id,time,balance,equity,price) "
                         "VALUES (1,'x',0,0,0)")


def test_main_missing_db_does_not_create_file(tmp_path, capsys):
    missing = tmp_path / "no_such.db"
    rc = D.main(["--db", str(missing)])
    assert rc == 1
    assert not missing.exists()
    assert "見つかりません" in capsys.readouterr().out


def test_main_end_to_end_report(synth_db, monkeypatch, capsys):
    monkeypatch.setattr(bridge, "read_status",
                        lambda *a, **k: {"balance": 292_000.0, "equity": 291_500.0,
                                         "position_lots": 0.0})
    monkeypatch.setenv("FXSIM_DB", synth_db)
    rc = D.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ライブ診断レポート" in out
    assert "ストップ" in out and "AI拒否" in out
    assert "claude-sonnet-4-6" in out
    assert "-5,600" in out                       # ストップの実測損益
    assert "バックテスト期待値" in out
    # レポートはDBを変更しない
    with D._connect_ro(synth_db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    rc = D.main(["--db", synth_db])
    assert rc == 0
    with D._connect_ro(synth_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == n


def test_main_run_id_not_found(synth_db, capsys):
    rc = D.main(["--db", synth_db, "--run-id", "999"])
    assert rc == 1
    assert "エラー" in capsys.readouterr().out
