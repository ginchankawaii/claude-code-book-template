"""銘柄マスタの信用区分は、その時点のスナップショットで判定する（先読みしない）。"""

from datetime import date

import pandas as pd

from erb.cli import _attach_loanable, _restrict_to_margin_eligible


def _master():
    # A0001: 2023-01 は制度信用のみ(1)、2024-01 から貸借(2)。B0002: ずっと非対象(0)。C0003: ずっと貸借
    rows = []
    for d, cls_a in ((date(2023, 1, 5), "1"), (date(2024, 1, 5), "2"), (date(2025, 1, 6), "2")):
        rows.append({"date": d, "code": "A0001", "margin_class": cls_a, "margin_class_name": ""})
        rows.append({"date": d, "code": "B0002", "margin_class": "0", "margin_class_name": ""})
        rows.append({"date": d, "code": "C0003", "margin_class": "2", "margin_class_name": "貸借銘柄"})
    return pd.DataFrame(rows)


def test_loanable_uses_snapshot_at_disclosure_date():
    ev = pd.DataFrame({
        "code": ["A0001", "A0001", "A0001", "C0003", "B0002"],
        "disc_date": [date(2022, 6, 1), date(2023, 6, 1), date(2024, 6, 1), date(2023, 6, 1), date(2024, 6, 1)],
        "entry_date": [date(2022, 6, 2), date(2023, 6, 2), date(2024, 6, 3), date(2023, 6, 2), date(2024, 6, 4)],
    })
    out = _attach_loanable(ev, _master())
    # 2022 は最初のスナップショット(1)で代用 → False、2023 は 1 → False、2024 は 2 → True
    assert list(out["loanable"]) == [False, False, True, True, False]
    assert list(out.index) == list(ev.index)


def test_loanable_falls_back_to_entry_date_and_no_master():
    ev = pd.DataFrame({"code": ["A0001"], "disc_date": [pd.NaT], "entry_date": [date(2024, 6, 3)]})
    assert list(_attach_loanable(ev, _master())["loanable"]) == [True]
    assert list(_attach_loanable(ev, None)["loanable"]) == [False]


def test_margin_eligibility_changes_over_time():
    days = [date(2023, 6, 1), date(2024, 6, 3)]
    daily = pd.DataFrame([{"date": d, "code": c, "close": 100.0} for d in days for c in ("A0001", "B0002", "C0003")])
    out = _restrict_to_margin_eligible(daily, _master())
    kept = set(zip(out["code"], out["date"]))
    assert ("B0002", days[0]) not in kept and ("B0002", days[1]) not in kept
    assert ("A0001", days[0]) in kept and ("A0001", days[1]) in kept
    assert ("C0003", days[0]) in kept
    assert len(out) == 4
