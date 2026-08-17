from pathlib import Path

from app.providers.csv import load_csv_file
from app.resample import resample


def test_loads_histdata_semicolon_combined_datetime(tmp_path):
    # HistData generic ASCII M1: "YYYYMMDD HHMMSS;O;H;L;C;V", no header
    p = tmp_path / "USD_JPY.csv"
    p.write_text(
        "20240102 000000;140.100;140.200;140.050;140.150;0\n"
        "20240102 000100;140.150;140.300;140.120;140.250;0\n"
        "20240102 000200;140.250;140.260;140.000;140.050;0\n"
    )
    cs = load_csv_file(p, "USD_JPY", "M1")
    assert len(cs) == 3
    assert cs[0].open == 140.100 and cs[0].close == 140.150
    assert cs[0].time.year == 2024 and cs[0].time.hour == 0 and cs[0].time.minute == 0
    assert cs[1].time.minute == 1


def test_loads_mt_style_separate_date_time(tmp_path):
    # MT export: date,time,O,H,L,C,V
    p = tmp_path / "USD_JPY.csv"
    p.write_text(
        "2024.01.02,00:00,140.10,140.20,140.05,140.15,10\n"
        "2024.01.02,00:15,140.15,140.30,140.12,140.25,12\n"
    )
    cs = load_csv_file(p, "USD_JPY", "M15")
    assert len(cs) == 2
    assert cs[0].open == 140.10 and cs[0].volume == 10
    assert cs[1].time.minute == 15


def test_resample_m1_to_m15_rolls_up_ohlcv(tmp_path):
    p = tmp_path / "USD_JPY.csv"
    # 30 one-minute bars across two M15 buckets
    lines = []
    base_close = 100.0
    for i in range(30):
        hh = f"{i//60:02d}"; mm = f"{i%60:02d}"
        o = 100.0 + i * 0.01
        c = o + 0.005
        hi = c + 0.02
        lo = o - 0.02
        lines.append(f"20240102 00{mm}00;{o:.3f};{hi:.3f};{lo:.3f};{c:.3f};1")
    # fix HHMMSS formatting: minutes 00..29 within hour 00
    lines = [f"20240102 00{m:02d}00;{100.0+m*0.01:.3f};{100.0+m*0.01+0.02:.3f};"
             f"{100.0+m*0.01-0.02:.3f};{100.0+m*0.01+0.005:.3f};1" for m in range(30)]
    p.write_text("\n".join(lines))
    m1 = load_csv_file(p, "USD_JPY", "M1")
    assert len(m1) == 30
    m15 = resample(m1, "M15")
    assert len(m15) == 2                       # 00:00 and 00:15 buckets
    first = m15[0]
    assert first.open == m1[0].open            # first open of bucket
    assert first.close == m1[14].close         # last close in 00:00-00:14
    assert first.high == max(c.high for c in m1[:15])
    assert first.low == min(c.low for c in m1[:15])
    assert first.volume == 15                  # 15 one-minute bars merged
    assert first.time.minute == 0 and m15[1].time.minute == 15
