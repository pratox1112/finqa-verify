"""V2 grounded verification checks (ROADMAP P4.3-P4.5). No model calls, no network."""

import pytest

from finqa.ingestion.xbrl import load_metric_map, metric_for, normalize_metric
from finqa.schemas import Chunk, Claim, Draft
from finqa.verifiers.grounded import (
    CITED_TEXT,
    RECOMPUTE,
    XBRL,
    check_cited_text,
    check_recompute,
    check_xbrl,
    chunk_values,
)

TOL = 0.01


def chunk(cid: str, text: str, scale: float | None = 1e6) -> Chunk:
    return Chunk(
        chunk_id=cid,
        cik="0000066740",
        ticker="MMM",
        form="10-K",
        fiscal_year=2018,
        period="FY2018",
        section="Item 8",
        is_table=scale is not None,
        unit_scale=scale,
        text=text,
        source_accession="a1",
    )


CASH_FLOW = chunk("cf", "| Purchases of property, plant and equipment (PP&E) | (1,577) | (1,373) |")
PER_SHARE = chunk("eps", "| Net income | 5,349 |\n| Diluted earnings per share | $ 8.89 |")
PROSE = chunk("text", "Capital expenditures were $1.6 billion in 2018, up 15%.", scale=None)
THOUSANDS = chunk("th", "| Total revenue | 2,450,301 |", scale=1e3)


def claim(value: float, cites: list[str], unit: str = "USD", **kw: object) -> Claim:
    return Claim(
        claim_id=str(kw.pop("claim_id", "c1")),
        metric="capex",
        value=value,
        unit=unit,  # type: ignore[arg-type]
        period="FY2018",
        chunk_ids=cites,
        **kw,  # type: ignore[arg-type]
    )


def draft(*chunks: Chunk) -> Draft:
    return Draft(
        question_id="q",
        retrieval_arm="rag",
        answer_text="",
        claims=[],
        evidence={c.chunk_id: c for c in chunks},
        trace_id="t",
        latency_s=0,
        tokens_in=0,
        tokens_out=0,
    )


def check(c: Claim, *chunks: Chunk) -> tuple[bool | None, str]:
    v = check_cited_text(c, draft(*chunks), TOL)
    assert v.check == CITED_TEXT and v.claim_id == c.claim_id
    return v.ok, v.reason


# --- The acceptance case: a millions-scaled table against a billions-stated claim --------------


def test_billions_claim_matches_a_millions_table() -> None:
    # "$1.577B" is stored as 1577000000; the table shows (1,577) in millions
    assert check(claim(1.577e9, ["cf"]), CASH_FLOW) == (True, "1.577e+09 USD is stated in cf")


def test_the_unscaled_number_is_a_scale_error_for_usd() -> None:
    ok, reason = check(claim(1577.0, ["cf"]), CASH_FLOW)
    assert ok is False and "table in units of 1e+06" in reason
    assert check(claim(1.577e6, ["cf"]), CASH_FLOW)[0] is False  # thousands for millions


def test_thousands_tables_scale_too() -> None:
    assert check(claim(2.450301e9, ["th"]), THOUSANDS)[0] is True
    assert check(claim(2.45e9, ["th"]), THOUSANDS)[0] is True  # within 1%


def test_sign_is_ignored_and_tolerance_is_relative() -> None:
    assert check(claim(-1.577e9, ["cf"]), CASH_FLOW)[0] is True  # outflow in parentheses
    assert check(claim(1.373e9, ["cf"]), CASH_FLOW)[0] is True  # any number in the chunk
    assert check(claim(1.59e9, ["cf"]), CASH_FLOW)[0] is True  # 0.8% off
    assert check(claim(1.60e9, ["cf"]), CASH_FLOW)[0] is False  # 1.5% off


# --- Units that keep their raw value -------------------------------------------------------


def test_per_share_in_a_millions_table_is_not_rescaled() -> None:
    assert check(claim(8.89, ["eps"], unit="USD/share"), PER_SHARE)[0] is True
    assert check(claim(5.349e9, ["eps"]), PER_SHARE)[0] is True
    assert check(claim(5349.0, ["eps"]), PER_SHARE)[0] is False  # a USD claim must be scaled


def test_values_with_their_own_scale_and_percentages_are_never_rescaled() -> None:
    assert check(claim(1.6e9, ["text"]), PROSE)[0] is True
    assert check(claim(15.0, ["text"], unit="%"), PROSE)[0] is True
    stated = chunk("s", "| Revenue (in $ billions) | $32.8 billion | 12.5% |")
    assert check(claim(3.28e10, ["s"]), stated)[0] is True
    assert check(claim(12.5, ["s"], unit="%"), stated)[0] is True
    assert check(claim(1.25e7, ["s"], unit="%"), stated)[0] is False


@pytest.mark.parametrize(
    "unit, expected",
    [("USD", [1.577e9, 1.373e9]), ("shares", [1577.0, 1.577e9, 1373.0, 1.373e9])],
)
def test_chunk_values_by_unit(unit: str, expected: list[float]) -> None:
    assert chunk_values(CASH_FLOW, unit) == expected  # type: ignore[arg-type]


def test_a_chunk_with_no_stated_scale_gives_raw_values() -> None:
    plain = chunk("p", "| Revenue | 1,577 |", scale=None)
    assert chunk_values(plain, "USD") == [1577.0]
    assert check(claim(1577.0, ["p"]), plain)[0] is True


# --- When the check does not pass ----------------------------------------------------------


def test_a_value_in_no_cited_chunk_fails_even_if_another_chunk_has_it() -> None:
    ok, reason = check(claim(1.6e9, ["cf"]), CASH_FLOW, PROSE)  # PROSE has it but is not cited
    assert ok is False and reason.startswith("1.6e+09 USD is not stated in cf")


def test_any_cited_chunk_can_support_the_claim() -> None:
    assert check(claim(1.6e9, ["cf", "text"]), CASH_FLOW, PROSE) == (
        True,
        "1.6e+09 USD is stated in text",
    )


def test_uncited_and_unretrieved_citations_fail() -> None:
    assert check(claim(1.577e9, []), CASH_FLOW) == (False, "cites no evidence")
    ok, reason = check(claim(1.577e9, ["k9"]), CASH_FLOW)
    assert ok is False and "k9, which is not in the retrieved evidence" in reason


def test_computed_claims_are_left_to_recomputation() -> None:
    growth = claim(14.86, [], unit="%", derived_from=["c1", "c2"], expression="(c1-c2)/c2*100")
    assert check(growth, CASH_FLOW) == (None, "computed claim: checked by recomputation")


# --- Check 2: XBRL -------------------------------------------------------------------------

METRICS = load_metric_map()
XBRL_FACTS = {
    ("0000066740", "capital_expenditure", "FY2018"): [1.577e9],
    ("0000066740", "revenue", "FY2018"): [3.2765e10, 3.2348e10],  # restated in a later 10-K
    ("0000066740", "eps_diluted", "FY2018"): [8.89],
}


def fake_lookup(cik: str, metric: str, period: str) -> list[float]:
    return XBRL_FACTS.get((cik, metric, period), [])


def xbrl(c: Claim, cik: str | None = "0000066740") -> tuple[bool | None, str]:
    v = check_xbrl(c, cik, TOL, METRICS, fake_lookup)
    assert v.check == XBRL and v.claim_id == c.claim_id
    return v.ok, v.reason


def named(metric: str, value: float, unit: str = "USD", period: str = "FY2018") -> Claim:
    return claim(value, ["cf"], unit=unit).model_copy(update={"metric": metric, "period": period})


def test_xbrl_match_ignoring_sign() -> None:
    assert xbrl(named("Capital expenditures", 1.577e9)) == (
        True,
        "matches XBRL capital_expenditure FY2018",
    )
    assert xbrl(named("Purchases of property, plant & equipment (PP&E)", -1.58e9))[0] is True
    assert xbrl(named("Diluted EPS", 8.89, unit="USD/share"))[0] is True


def test_xbrl_mismatch_reports_the_filed_values() -> None:
    assert xbrl(named("capex", 1.373e9)) == (
        False,
        "XBRL capital_expenditure FY2018 is 1.577e+09 USD, not 1.373e+09",
    )
    assert xbrl(named("capex", 1577.0))[0] is False  # a scale error


def test_any_restated_value_passes() -> None:
    assert xbrl(named("Total revenues", 3.2348e10))[0] is True
    assert xbrl(named("Total revenues", 3.2765e10))[0] is True
    ok, reason = xbrl(named("Total revenues", 3.0e10))
    assert ok is False and "3.2765e+10, 3.2348e+10" in reason


@pytest.mark.parametrize(
    "c, cik, reason",
    [
        (named("Data Center net revenue", 6.0e9), "0000066740", "has no XBRL mapping"),
        (named("gross margin", 45.0, unit="%"), "0000066740", "has no XBRL mapping"),
        (named("capex", 12.0, unit="%"), "0000066740", "is in USD, the claim in %"),
        (named("capex", 1.577e9), None, "company not known"),
        (named("capex", 1.577e9, period="FY2017"), "0000066740", "no XBRL value"),
        (named("total assets", 3.7e10), "0000066740", "no XBRL value"),
    ],
)
def test_xbrl_does_not_run_without_a_mapping_unit_company_or_value(
    c: Claim, cik: str | None, reason: str
) -> None:
    ok, why = xbrl(c, cik)
    assert ok is None and reason in why  # unverifiable, never a failure


@pytest.mark.parametrize(
    "name, metric",
    [
        ("Capital expenditures (purchases of property and equipment)", "capital_expenditure"),
        ("Net income attributable to Pfizer Inc.", "net_income"),
        ("net income attributable to noncontrolling interests", None),
        ("Accounts receivable — net", "accounts_receivable"),
        ("Total stockholders’ equity", "shareholders_equity"),
        ("Long-term debt", "long_term_debt"),
        ("PP&E, net", "ppe_net"),
        ("Unadjusted (GAAP) operating profit", "operating_income"),
        ("Data Center net revenue", None),
        ("Walmart U.S. operating income", None),
        ("dividends declared per share", None),
    ],
)
def test_metric_names_map_through_aliases(name: str, metric: str | None) -> None:
    assert metric_for(name, METRICS) == metric


def test_every_alias_is_normalised_and_names_one_metric() -> None:
    aliases = [a for m in METRICS.values() for a in m.aliases]
    assert len(aliases) == len(set(aliases))
    assert all(a == normalize_metric(a) for a in aliases)
    assert all(m.aliases for m in METRICS.values())


# --- Check 3: recomputation ---------------------------------------------------------------


def inputs(capex: float = 1.577e9, prior: float = 1.373e9) -> list[Claim]:
    return [
        claim(capex, ["cf"], claim_id="c1"),
        claim(prior, ["cf"], claim_id="c2").model_copy(update={"period": "FY2017"}),
    ]


def growth(value: float, expression: str = "(c1 - c2) / c2 * 100", **kw: object) -> Claim:
    update = {"derived_from": ["c1", "c2"], "expression": expression, **kw}
    return claim(value, [], unit="%", claim_id="c3").model_copy(update=update)


def recheck(c: Claim, cs: list[Claim] | None = None) -> tuple[bool | None, str]:
    v = check_recompute(c, (cs if cs is not None else inputs()) + [c], TOL)
    assert v.check == RECOMPUTE and v.claim_id == "c3"
    return v.ok, v.reason


def test_a_correct_computation_passes() -> None:
    assert recheck(growth(14.86)) == (True, "(c1 - c2) / c2 * 100 = 14.858")
    assert recheck(growth(14.86, "(a - b) / b * 100"))[0] is True  # letters in input order
    assert recheck(growth(14.86, "(c1 - c2) / c2"))[0] is True  # a fraction for a % claim


def test_a_wrong_computation_fails_with_the_recomputed_value() -> None:
    assert recheck(growth(12.0)) == (False, "(c1 - c2) / c2 * 100 = 14.858, not 12")
    assert recheck(growth(-14.86))[0] is False  # sign matters in arithmetic
    usd = claim(2.95e9, [], claim_id="c3").model_copy(
        update={"derived_from": ["c1", "c2"], "expression": "c1 + c2"}
    )
    assert recheck(usd)[0] is True
    assert recheck(usd.model_copy(update={"value": 2.95e6}))[0] is False


def test_recomputation_uses_the_inputs_current_values() -> None:
    # after a revision fixes c1, the derived claim is checked against the revised value
    assert recheck(growth(14.86), inputs(capex=1.6e9))[0] is False


def test_computed_claims_that_cannot_be_recomputed_fail() -> None:
    ok, reason = recheck(growth(14.86, derived_from=[]))
    assert ok is False and "names no input claims" in reason
    ok, reason = recheck(growth(14.86, derived_from=["c1", "c9"]))
    assert ok is False and "c9 are not claims in the draft" in reason
    for bad in ("c1 / (c2 - c2)", "max(c1, c2)", "c1 +"):
        ok, reason = recheck(growth(14.86, bad))
        assert ok is False and "cannot be evaluated" in reason


def test_quoted_claims_are_not_recomputed() -> None:
    c = claim(1.577e9, ["cf"], claim_id="c3")
    assert recheck(c) == (None, "quoted claim: nothing to recompute")


# --- Regressions found on the dev run (2026-11-23) --------------------------------------------


def test_a_small_percent_computed_with_times_100_is_not_multiplied_again() -> None:
    # dev 00563: (c8 - c7) / c7 * 100 = -9.96 was read as a fraction and became -996
    falling = inputs(capex=1.236e9)  # (1.236 - 1.373) / 1.373 = -9.98%
    c = growth(-9.98)
    assert check_recompute(c, falling + [c], TOL).ok is True
    as_fraction = growth(-9.98, "(c1 - c2) / c2")
    assert check_recompute(as_fraction, falling + [as_fraction], TOL).ok is True
    wrong = growth(-8.5)
    v = check_recompute(wrong, falling + [wrong], TOL)
    assert v.ok is False and v.reason.endswith("not -8.5") and "-9.97" in v.reason


def test_a_table_with_no_stated_scale_allows_any_scale() -> None:
    # dev 04481: "Operating profit | $ | 11,512" in a table whose scale is not stated
    unscaled = chunk("u", "| Operating profit | $ | 11,512 | $ | 11,162 |", scale=None)
    unscaled = unscaled.model_copy(update={"is_table": True})
    for value in (11512.0, 11.512e6, 11.512e9):
        assert check(claim(value, ["u"]), unscaled)[0] is True
    ok, reason = check(claim(11.7e9, ["u"]), unscaled)
    assert ok is False and "table scale not stated" in reason
    # prose numbers are read as written
    assert check(claim(1.6e6, ["text"]), PROSE)[0] is False
