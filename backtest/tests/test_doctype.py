"""DocType の分類。

値は 2026-09-02 の probe で J-Quants から実際に返ってきたものをそのまま使う。
推測ではなく実データで固定する。
"""

import pytest

from erb.events import classify_doc_type, is_fy_closing, is_reit

# 5年分（開示 94,987件）から実際に現れた DocType の全34種
REAL_DOC_TYPES = [
    "1QFinancialStatements_Consolidated_Foreign",
    "1QFinancialStatements_Consolidated_IFRS",
    "1QFinancialStatements_Consolidated_JP",
    "1QFinancialStatements_Consolidated_US",
    "1QFinancialStatements_NonConsolidated_IFRS",
    "1QFinancialStatements_NonConsolidated_JP",
    "2QFinancialStatements_Consolidated_Foreign",
    "2QFinancialStatements_Consolidated_IFRS",
    "2QFinancialStatements_Consolidated_JP",
    "2QFinancialStatements_Consolidated_REIT",
    "2QFinancialStatements_Consolidated_US",
    "2QFinancialStatements_NonConsolidated_Foreign",
    "2QFinancialStatements_NonConsolidated_IFRS",
    "2QFinancialStatements_NonConsolidated_JP",
    "3QFinancialStatements_Consolidated_Foreign",
    "3QFinancialStatements_Consolidated_IFRS",
    "3QFinancialStatements_Consolidated_JP",
    "3QFinancialStatements_Consolidated_US",
    "3QFinancialStatements_NonConsolidated_IFRS",
    "3QFinancialStatements_NonConsolidated_JP",
    "DividendForecastRevision",
    "EarnForecastRevision",
    "FYFinancialStatements_Consolidated_Foreign",
    "FYFinancialStatements_Consolidated_IFRS",
    "FYFinancialStatements_Consolidated_JP",
    "FYFinancialStatements_Consolidated_REIT",
    "FYFinancialStatements_Consolidated_US",
    "FYFinancialStatements_NonConsolidated_IFRS",
    "FYFinancialStatements_NonConsolidated_JP",
    "OtherPeriodFinancialStatements_Consolidated_IFRS",
    "OtherPeriodFinancialStatements_Consolidated_JP",
    "OtherPeriodFinancialStatements_NonConsolidated_JP",
    "REITDividendForecastRevision",
    "REITEarnForecastRevision",
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


def test_reit_is_detected_in_both_positions():
    """REIT は末尾に付く形と先頭に付く形の両方がある。

    区切り文字（_REIT）で判定すると REITEarnForecastRevision を取りこぼし、
    投資法人の分配金予想修正が事業会社の業績予想修正に混ざる。
    5年分では 309件が該当した。
    """
    assert is_reit("FYFinancialStatements_Consolidated_REIT") is True
    assert is_reit("2QFinancialStatements_Consolidated_REIT") is True
    assert is_reit("REITEarnForecastRevision") is True
    assert is_reit("REITDividendForecastRevision") is True

    assert is_reit("FYFinancialStatements_Consolidated_JP") is False
    assert is_reit("EarnForecastRevision") is False
    assert is_reit("DividendForecastRevision") is False


def test_no_real_doc_type_is_a_false_reit_positive():
    """REIT でないものを REIT と誤判定していないこと。"""
    flagged = {d for d in REAL_DOC_TYPES if is_reit(d)}
    assert flagged == {
        "2QFinancialStatements_Consolidated_REIT",
        "FYFinancialStatements_Consolidated_REIT",
        "REITDividendForecastRevision",
        "REITEarnForecastRevision",
    }


def test_other_period_statements_are_classified():
    """決算期変更などの変則決算。5年分で19件あった。"""
    assert classify_doc_type(
        "OtherPeriodFinancialStatements_Consolidated_JP") == "financial_statements"


def test_fy_closing_detected_from_real_cur_per_type():
    """probe のサンプルでは CurPerType は "FY"。"""
    assert is_fy_closing("FY") is True
    assert is_fy_closing("1Q") is False
    assert is_fy_closing("2Q") is False
    assert is_fy_closing("3Q") is False
