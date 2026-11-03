"""Numeric citation check: is the claimed value in a cited chunk?"""

from finqa.eval.citation_check import (
    check_citations,
    check_claim,
    chunk_values,
    citation_precision,
)
from finqa.schemas import Chunk, Claim, Draft

TOL = 0.01


def chunk(cid, text, scale=1e6):
    return Chunk(
        chunk_id=cid,
        cik="0000066740",
        ticker="MMM",
        form="10-K",
        fiscal_year=2018,
        period="FY2018",
        section="Item 8",
        is_table=True,
        unit_scale=scale,
        text=text,
        source_accession="x",
    )


CASH_FLOW = chunk("cf", "| Purchases of property, plant and equipment (PP&E) | (1,577) | (1,373) |")
PROSE = chunk("text", "Capital expenditures were $1.6 billion in 2018.", scale=None)


def claim(value, cites, cid="c1", **kw):
    return Claim(
        claim_id=cid,
        metric="capital_expenditure",
        value=value,
        unit=kw.pop("unit", "USD"),
        period="FY2018",
        chunk_ids=cites,
        **kw,
    )


def draft(claims, *chunks):
    return Draft(
        question_id="q",
        retrieval_arm="rag",
        answer_text="",
        claims=claims,
        evidence={c.chunk_id: c for c in chunks},
        trace_id="t",
        latency_s=0,
        tokens_in=0,
        tokens_out=0,
    )


def test_table_value_at_the_tables_scale_ignoring_parentheses():
    assert 1_577e6 in chunk_values(CASH_FLOW)
    d = draft([claim(1_577e6, ["cf"])], CASH_FLOW)
    assert check_claim(d.claims[0], d, TOL).supported is True


def test_value_not_in_the_cited_chunk():
    d = draft([claim(1_420e6, ["cf"])], CASH_FLOW)  # another year's figure
    assert check_claim(d.claims[0], d, TOL).supported is False


def test_scale_words_in_prose():
    d = draft([claim(1.6e9, ["text"]), claim(1.6e15, ["text"], cid="c2")], PROSE)
    assert [c.supported for c in check_citations(d, TOL)] == [True, False]


def test_not_checkable_cases():
    derived = claim(14.8, ["cf"], cid="c2", unit="%", derived_from=["c1"], expression="a / 100")
    d = draft([claim(1_577e6, []), derived, claim(1_577e6, ["missing"], cid="c3")], CASH_FLOW)
    assert [c.supported for c in check_citations(d, TOL)] == [None, None, None]


def test_precision_counts_only_checkable_claims():
    d = draft(
        [claim(1_577e6, ["cf"]), claim(9e9, ["cf"], cid="c2"), claim(1.0, [], cid="c3")],
        CASH_FLOW,
    )
    assert citation_precision(check_citations(d, TOL)) == (1, 2)
