"""Error classifier (ROADMAP P2.5): one hand-made example per error type."""

import pytest

from finqa.eval.error_types import classify, evaluate, recompute, wrong_scale, xbrl_lookup
from finqa.schemas import Claim, ErrorType

TOL = 0.01
CIK, OTHER = "0000066740", "0000874761"
# A fake XBRL cache: (cik, metric, period) -> reported values.
FACTS = {
    (CIK, "capital_expenditure", "FY2018"): [1_577e6],
    (CIK, "capital_expenditure", "FY2017"): [1_373e6],
    (CIK, "revenue", "FY2018"): [32_765e6],
    (OTHER, "capital_expenditure", "FY2018"): [2_404e6],
}
METRICS = ("capital_expenditure", "revenue")


def lookup(cik, metric, period):
    return FACTS.get((cik, metric, period), [])


def claim(value, metric="capital_expenditure", cid="c1", **kw):
    return Claim(
        claim_id=cid,
        metric=metric,
        value=value,
        unit=kw.pop("unit", "USD"),
        period="FY2018",
        chunk_ids=[],
        **kw,
    )


def kind(c, claims=None, retrieved=True, gold=1_577e6):
    d = classify(
        "q",
        c,
        claims or [c],
        gold,
        TOL,
        retrieved,
        cik=CIK,
        fiscal_year=2018,
        metrics=METRICS,
        other_ciks=[CIK, OTHER],
        lookup=lookup,
    )
    return d.error_type


def test_wrong_unit_or_scale():
    assert kind(claim(1_577e3)) == ErrorType.WRONG_UNIT  # thousands for millions
    assert kind(claim(1_577e9)) == ErrorType.WRONG_UNIT
    assert wrong_scale(0.125, 12.5, TOL) == pytest.approx(0.01)  # fraction for a percent


def test_wrong_period():
    assert kind(claim(1_373e6)) == ErrorType.WRONG_PERIOD


def test_wrong_line_item():
    assert kind(claim(32_765e6)) == ErrorType.WRONG_LINE_ITEM


def test_wrong_company():
    assert kind(claim(2_404e6)) == ErrorType.WRONG_COMPANY


def test_arithmetic():
    a = claim(100.0, metric="x", cid="c1")
    b = claim(80.0, metric="y", cid="c2")
    growth = claim(
        30.0,
        metric="growth",
        cid="c3",
        unit="%",
        derived_from=["c1", "c2"],
        expression="(a - b) / b",
    )  # correct is 25%
    assert kind(growth, [a, b, growth], gold=25.0) == ErrorType.ARITHMETIC


def test_retrieval_miss_and_other():
    off = claim(999e6, metric="something_unmapped")
    assert kind(off, retrieved=False) == ErrorType.RETRIEVAL_MISS
    assert kind(off, retrieved=True) == ErrorType.OTHER


def test_text_gold_only_retrieval_miss_or_other():
    d = classify("q", None, [], None, TOL, gold_evidence_retrieved=False)
    assert d.error_type == ErrorType.RETRIEVAL_MISS
    assert classify("q", None, [], None, TOL, None).error_type == ErrorType.OTHER


def test_xbrl_rules_skipped_for_quarterly_questions():
    d = classify(
        "q",
        claim(1_373e6),
        [],
        1_577e6,
        TOL,
        True,
        cik=CIK,
        fiscal_year=None,
        metrics=METRICS,
        lookup=lookup,
    )
    assert d.error_type == ErrorType.OTHER


def test_evaluate_is_arithmetic_only():
    assert evaluate("(a - b) / b", {"a": 100.0, "b": 80.0}) == 0.25
    assert evaluate("-c1 * 2 ** 2", {"c1": 3.0}) == -12.0
    for bad in ("__import__('os')", "a.real", "[1, 2]", "unknown + 1"):
        with pytest.raises(ValueError):
            evaluate(bad, {"a": 1.0})


def test_recompute_with_claim_ids_and_percent():
    a, b = claim(100.0, cid="c1"), claim(80.0, cid="c2")
    pct = claim(25.0, cid="c3", unit="%", derived_from=["c1", "c2"], expression="(c1 - c2) / c2")
    assert recompute(pct, [a, b, pct]) == pytest.approx(25.0)
    assert recompute(claim(1.0), [a]) is None  # no expression


def test_real_xbrl_cache_restated_3m_operating_income():
    from finqa.ingestion.xbrl import FACTS_DIR

    if not (FACTS_DIR / "CIK0000066740.json").exists():  # never download in unit tests
        pytest.skip("XBRL cache not available (data/xbrl from the shared folder)")
    values = xbrl_lookup("0000066740", "operating_income", "FY2017")
    assert any(abs(v - 7_820e6) < 1e6 for v in values)  # as reported in the FY2017 10-K
    assert any(abs(v - 7_692e6) < 1e6 for v in values)  # restated in the FY2018 10-K
