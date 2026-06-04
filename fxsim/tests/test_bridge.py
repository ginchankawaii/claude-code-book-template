from pathlib import Path

from app import bridge


def test_write_and_read_signal(tmp_path):
    bridge.write_signal("LONG", 0.3, base=tmp_path)
    assert (tmp_path / bridge.SIGNAL_FILE).read_text().strip() == "LONG 0.30"
    bridge.write_signal("FLAT", 0, base=tmp_path)
    assert (tmp_path / bridge.SIGNAL_FILE).read_text().strip() == "FLAT 0.00"


def test_read_status(tmp_path):
    (tmp_path / bridge.STATUS_FILE).write_text(
        "balance,equity,position_lots\n3000000.00,3001234.50,0.30\n")
    s = bridge.read_status(base=tmp_path)
    assert s["balance"] == 3000000.0 and s["equity"] == 3001234.5 and s["position_lots"] == 0.30


def test_read_status_missing_returns_none(tmp_path):
    assert bridge.read_status(base=tmp_path) is None


def test_read_bars_parses_ea_export(tmp_path):
    # mirrors the EA's TimeToString(TIME_DATE|TIME_SECONDS) "YYYY.MM.DD HH:MM:SS"
    (tmp_path / bridge.BARS_FILE).write_text(
        "time,open,high,low,close\n"
        "2026.06.01 00:00:00,158.10,158.90,157.80,158.50\n"
        "2026.06.02 00:00:00,158.50,159.20,158.30,159.00\n")
    bars = bridge.read_bars("USD_JPY", "D", base=tmp_path)
    assert len(bars) == 2
    assert bars[0].open == 158.10 and bars[1].close == 159.00
    assert bars[0].time.year == 2026 and bars[0].time.month == 6
