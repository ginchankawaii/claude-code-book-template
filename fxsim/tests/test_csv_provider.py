from pathlib import Path

import pytest

from app.providers.csv import load_csv_file

CASES = {
    "jp_shiftjis": (
        "日時,始値,高値,安値,終値,出来高\n"
        "2024-01-04 09:00:00,141.20,141.55,141.10,141.40,1234\n"
        "2024-01-04 09:15:00,141.40,141.60,141.30,141.52,987\n",
        "cp932",
        2,
    ),
    "en_sep_date_time": (
        "Date,Time,Open,High,Low,Close\n"
        "2024/01/04,09:00,141.20,141.55,141.10,141.40\n"
        "2024/01/04,09:15,141.40,141.60,141.30,141.52\n",
        "utf-8",
        2,
    ),
    "mt_headerless_tab": (
        "2024.01.04\t09:00:00\t141.20\t141.55\t141.10\t141.40\t1200\n"
        "2024.01.04\t09:15:00\t141.40\t141.60\t141.30\t141.52\t900\n",
        "utf-8",
        2,
    ),
    "jp_intraday_quoted": (  # Central Tanshi 10-min export: cp932, quoted, 年月日
        "日付,始値,高値,安値,終値\n"
        '"2026年06月03日 03:00","141.20","141.55","141.10","141.40"\n'
        '"2026年06月03日 03:10","141.40","141.60","141.30","141.52"\n',
        "cp932",
        2,
    ),
    "single_dt_semicolon": (
        "datetime;open;high;low;close\n"
        "2024-01-04T09:00:00;141.20;141.55;141.10;141.40\n",
        "utf-8",
        1,
    ),
}


@pytest.mark.parametrize("name", list(CASES))
def test_csv_formats(tmp_path: Path, name: str):
    data, enc, expected = CASES[name]
    p = tmp_path / f"{name}.csv"
    p.write_bytes(data.encode(enc))
    candles = load_csv_file(p, "USD_JPY", "M15")
    assert len(candles) == expected
    assert candles[0].close == 141.40
    assert candles[0].high >= candles[0].low
    # sorted ascending by time
    assert all(candles[i].time <= candles[i + 1].time for i in range(len(candles) - 1))


def test_csv_skips_malformed_rows(tmp_path: Path):
    p = tmp_path / "x.csv"
    p.write_text(
        "Date,Time,Open,High,Low,Close\n"
        "2024/01/04,09:00,141.20,141.55,141.10,141.40\n"
        "--- footer junk ---\n"
        "2024/01/04,09:15,141.40,141.60,141.30,141.52\n"
    )
    candles = load_csv_file(p, "USD_JPY", "M15")
    assert len(candles) == 2
