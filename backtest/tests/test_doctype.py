"""DocType の分類。

値は 2026-09-02 の probe で J-Quants から実際に返ってきたものをそのまま使う。
推測ではなく実データで固定する。
"""

import pytest

from erb.events import classify_doc_type, is_fy_closing, is_reit

# probe が /fins/summary の1ページから拾った DocType の全値
REAL_DOC_TYPES = [
    "1QFinancialStatements_Consolidated_Foreign",
    "1QFinancialStatements_Consolidated_IFRS",
    "1QFinancialStatements_Consolidated_JP",
    "1QFinancialStatements_Consolidated_US",
    "1QFinancialStatements_NonConsolidated_JP",
    "2QFinancialStatements_Consolidated_IFRS",
    "2QFinancialStatements_Consolidated_JP",
    "2QFinancialStatements_NonConsolidated_JP",
    "3QFinancialStatements_Consolidated_IFRS",
    "3QFinancialStatements_Consolidated_JP",
    "3QFinancialStatements_NonConsolidated_JP",
    "DividendForecastRevision",
    "EarnForecastRevision",
    "FYFinancialStatements_Consolidated_Foreign",
    "FYFinancialStatements_Consolidated_IFRS",
    "FYFinancialStatements_Consolidated_JP",
    "FYFinancialStatements_Consolidated_REIT",
    "FYFinancialStatements_NonConsolidated_JP",
]


def test_every_real_doc_type_is_classified():
    """実データの値が1つも 'other' に落ちないこと。"""
    unclassified = [d for d in REAL_DOC_TYPES if classify_doc_type(d) == "other"]
    assert unclassified == []


def test_earnings_revision_is_the_event_we_trade():
    assert classify_doc_type("EarnForecastRevision") == "earn_forecast_revision"


def test_dividend_revision_is_not_mistaken_for_an_earnings_revision():
    """"DividendForecastRevision" も 'forecastrevision' を含む。

    判定の順序が入れ替わると配当予想修正を業績予想修正として取り込んでしまい、
    対象外のはずのイベントが混入する。
    """
    assert classify_doc_type("DividendForecastRevision") == "dividend_forecast_revision"


@pytest.mark.parametrize("doc", [d for d in REAL_DOC_TYPES if "FinancialStatements" in d])
def test_all_statement_kinds_classify_as_statements(doc):
    assert classify_doc_type(doc) == "financial_statements"


def test_reit_is_detected():
    assert is_reit("FYFinancialStatements_Consolidated_REIT") is True
    assert is_reit("FYFinancialStatements_Consolidated_JP") is False
    assert is_reit("EarnForecastRevision") is False


def test_fy_closing_detected_from_real_cur_per_type():
    """probe のサンプルでは CurPerType は "FY"。"""
    assert is_fy_closing("FY") is True
    assert is_fy_closing("1Q") is False
    assert is_fy_closing("2Q") is False
    assert is_fy_closing("3Q") is False
