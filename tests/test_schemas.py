"""Every shared schema survives a JSON round trip unchanged (ROADMAP P0.3)."""

import json

import pytest
from pydantic import BaseModel

from finqa.schemas import (
    Annotation,
    Chunk,
    Claim,
    Draft,
    ErrorType,
    Verdict,
    VerifiedResult,
)

CHUNK = Chunk(
    chunk_id="0000320193-22-000108:item7:t3:r0",
    cik="0000320193",
    ticker="AAPL",
    form="10-K",
    fiscal_year=2022,
    period="FY2022",
    section="Item 7",
    is_table=True,
    unit_scale=1e6,
    text="| | 2022 | 2021 |\n|---|---|---|\n| Net sales | 394,328 | 365,817 |",
    source_accession="0000320193-22-000108",
)
TEXT_CHUNK = CHUNK.model_copy(
    update={"chunk_id": "c-text", "is_table": False, "unit_scale": None, "period": None}
)
CLAIM = Claim(
    claim_id="c1",
    metric="net sales",
    value=394_328_000_000.0,
    unit="USD",
    period="FY2022",
    chunk_ids=[CHUNK.chunk_id],
)
DERIVED = Claim(
    claim_id="c3",
    metric="net sales growth",
    value=7.79,
    unit="%",
    period="FY2022",
    chunk_ids=[CHUNK.chunk_id],
    derived_from=["c1", "c2"],
    expression="(c1 - c2) / c2 * 100",
)
DRAFT = Draft(
    question_id="financebench_id_00001",
    retrieval_arm="rag",
    answer_text="Apple's FY2022 net sales were $394.3 billion.",
    claims=[CLAIM, DERIVED],
    evidence={CHUNK.chunk_id: CHUNK, TEXT_CHUNK.chunk_id: TEXT_CHUNK},
    trace_id="trace-1",
    latency_s=2.5,
    tokens_in=4200,
    tokens_out=180,
)
VERDICT_OK = Verdict(claim_id="c1", ok=True, check="cited_text", reason="matches table")
VERDICT_NONE = Verdict(claim_id="c3", ok=None, check="xbrl", reason="metric not mapped")
RESULT = VerifiedResult(
    question_id=DRAFT.question_id,
    retrieval_arm="rag",
    verification_arm="grounded",
    claims_before=DRAFT.claims,
    claims_after=DRAFT.claims,
    verdicts=[VERDICT_OK, VERDICT_NONE],
    revisions_used=0,
    flagged_claim_ids=["c3"],
    latency_s=0.4,
    tokens_in=0,
    tokens_out=0,
)
ANNOTATION = Annotation(
    claim_id="c1",
    run_id="2026-11-10_r0_v2_a1b2c3d",
    annotator="annotator-1",
    correct=False,
    error_type=ErrorType.WRONG_UNIT,
    note="reported millions as billions",
)
CORRECT_ANNOTATION = ANNOTATION.model_copy(update={"correct": True, "error_type": None})

EXAMPLES: list[BaseModel] = [
    CHUNK,
    TEXT_CHUNK,
    CLAIM,
    DERIVED,
    DRAFT,
    VERDICT_OK,
    VERDICT_NONE,
    RESULT,
    ANNOTATION,
    CORRECT_ANNOTATION,
]


@pytest.mark.parametrize("model", EXAMPLES, ids=lambda m: type(m).__name__)
def test_json_round_trip(model: BaseModel) -> None:
    restored = type(model).model_validate_json(model.model_dump_json())
    assert restored == model


@pytest.mark.parametrize("model", EXAMPLES, ids=lambda m: type(m).__name__)
def test_jsonl_line_round_trip(model: BaseModel) -> None:
    # Runs are stored as JSONL: one json.dumps line per record.
    line = json.dumps(model.model_dump(mode="json"))
    assert "\n" not in line
    assert type(model).model_validate(json.loads(line)) == model


def test_error_type_serializes_as_plain_string() -> None:
    assert json.loads(ANNOTATION.model_dump_json())["error_type"] == "wrong_unit_or_scale"
    assert {e.value for e in ErrorType} == {
        "wrong_period",
        "wrong_unit_or_scale",
        "wrong_line_item",
        "arithmetic",
        "retrieval_miss",
        "wrong_company",
        "other",
    }


def test_claim_defaults_are_not_shared() -> None:
    a = Claim(claim_id="a", metric="m", value=1, unit="USD", period="FY2022", chunk_ids=[])
    b = Claim(claim_id="b", metric="m", value=1, unit="USD", period="FY2022", chunk_ids=[])
    a.derived_from.append("x")
    assert b.derived_from == []
