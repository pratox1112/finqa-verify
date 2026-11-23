"""Planted-error suite (ROADMAP P4.7): V2's checks catch every checkable planted error, and
flag no control. No model calls: this is the rule-based half of V2 (P4.3-P4.5)."""

import functools
from collections import Counter

import pytest
from planted.cases import CASES, NWD, Case, lookup
from test_agent import Recording

from finqa.config import CONFIGS_DIR, load_config
from finqa.ingestion.xbrl import load_metric_map
from finqa.llm import LLM
from finqa.schemas import ErrorType, Verdict
from finqa.verifiers.base import result
from finqa.verifiers.grounded import GroundedVerifier, failed

V2 = load_config(CONFIGS_DIR / "grid" / "r0_v2.yaml")


@functools.cache
def verifier() -> GroundedVerifier:
    """Built on first use, not at import (an LLM at collection time disturbs other tests)."""
    return GroundedVerifier(
        V2,
        LLM(V2, Recording()),
        context=lambda qid: ("", NWD),
        metric_map=load_metric_map(),
        lookup=lookup,
    )


def failing_checks(case: Case) -> dict[str, set[str]]:
    d = case.draft()
    out: dict[str, set[str]] = {}
    for v in verifier().check(d, d.claims, NWD):
        if v.ok is False:
            out.setdefault(v.claim_id, set()).add(v.check)
    return out


@pytest.mark.parametrize("case", CASES, ids=[c.case_id for c in CASES])
def test_v2_checks_fail_exactly_where_expected(case: Case) -> None:
    found = failing_checks(case)
    if not case.caught_by:  # a control, or an error V2 cannot see by design
        assert found == {}
        return
    assert set(found) == {case.planted}  # only the planted claim fails
    assert found[case.planted] == case.caught_by


def test_the_suite_covers_every_error_type_and_has_controls() -> None:
    types = Counter(c.error_type for c in CASES)
    assert set(types) == {*ErrorType, None}
    assert types[None] >= 3 and 18 <= len(CASES) <= 25
    assert len({c.case_id for c in CASES}) == len(CASES)


def test_planted_cases_name_their_claim_and_its_true_value() -> None:
    for c in CASES:
        ids = [x.claim_id for x in c.claims]
        if c.error_type is None:
            assert c.planted is None and c.truth is None and not c.caught_by
        else:
            assert c.planted in ids and c.truth is not None and c.note
        if not c.caught_by and c.error_type is not None:
            assert c.note.startswith("NOT CHECKABLE BY V2")


def test_v2_catches_every_checkable_planted_error() -> None:
    checkable = [c for c in CASES if c.caught_by]
    caught = [
        c
        for c in checkable
        if c.planted in failed(verifier().check(c.draft(), c.draft().claims, NWD))
    ]
    assert caught == checkable


# --- The script that runs V1 and V2 with the model (scripts/planted_errors.py) -----------------


def load_script():  # type: ignore[no-untyped-def]
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "planted_errors.py"
    spec = importlib.util.spec_from_file_location("planted_errors", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_reports_caught_and_after_from_verified_results() -> None:
    script = load_script()
    case = next(c for c in CASES if c.case_id == "scale_unscaled")
    d = case.draft()
    fixed = d.claims[0].model_copy(update={"value": 12.45e9})
    flag = Verdict(claim_id="c1", ok=False, check="cited_text", reason="round 1: not stated")
    late = Verdict(claim_id="c1", ok=False, check="cited_text", reason="round 2: not stated")
    r = result(d, V2, claims_after=[fixed], verdicts=[flag])
    assert script.row(case, r, 0.01) == (True, "fixed")
    r = result(d, V2, verdicts=[late])  # flagged only after a revision: not caught at first
    assert script.row(case, r, 0.01) == (False, "kept")
    wrong = d.claims[0].model_copy(update={"value": 1.2e9})
    assert script.row(case, result(d, V2, claims_after=[wrong]), 0.01)[1] == "changed, still wrong"
    assert script.row(case, result(d, V2, error="ValueError: x"), 0.01) == (
        False,
        "error: ValueError: x",
    )


def test_script_writes_a_table_row_per_case() -> None:
    script = load_script()
    rows = {c.case_id: (c.planted is not None, "kept") for c in CASES}
    text = script.markdown(rows, rows, V2)
    assert text.count("\n| `") == len(CASES)
    planted = sum(c.planted is not None for c in CASES)
    checkable = sum(bool(c.caught_by) for c in CASES)
    controls = len(CASES) - planted
    expected = f"| {planted}/{planted} | {checkable}/{checkable} | 0/{planted} | 0/{controls} |"
    assert f"| V1 self-check {expected}" in text
