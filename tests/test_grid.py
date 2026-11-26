"""Grid analysis (P8.1 coverage, P9.3 Holm-corrected paired tests, P9.5 flip matrices, P9.6
cost per cell) on small hand-made rows and V2 results. No model calls, no runs on disk."""

import pytest

from finqa.eval import grid, stats, tables
from finqa.schemas import Claim, Draft, Verdict, VerifiedResult


def row(qid: str, outcome: str, latency: float = 1.0) -> tables.Row:
    return tables.Row(
        question_id=qid,
        question_type="single_fact",
        outcome=outcome,
        method="numeric",
        reason="",
        latency_s=latency,
        tokens_in=100,
        tokens_out=10,
        failed=False,
    )


def rows(outcomes: str) -> list[tables.Row]:
    """'cir' -> q0 correct, q1 incorrect, q2 refused."""
    names = {"c": "correct", "i": "incorrect", "r": "refused"}
    return [row(f"q{i}", names[o]) for i, o in enumerate(outcomes)]


# ---------------------------------------------------------------- Holm


def test_holm_hand_computed():
    # sorted: 0.01*3 = 0.03; 0.03*2 = 0.06; 0.04*1 = 0.04 -> running max 0.06
    assert stats.holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


def test_holm_caps_at_one_and_keeps_order():
    adjusted = stats.holm([0.5, 0.9, 0.2])
    assert adjusted == pytest.approx([1.0, 1.0, 0.6])
    assert stats.holm([]) == []


def test_holm_single_test_unchanged():
    assert stats.holm([0.037]) == pytest.approx([0.037])


# ---------------------------------------------------------------- paired tests


def test_planned_pairs_are_nine_distinct_cells():
    assert len(grid.PLANNED_PAIRS) == 9
    assert len(set(grid.PLANNED_PAIRS)) == 9
    assert all(a in grid.CELLS and b in grid.CELLS for a, b in grid.PLANNED_PAIRS)


def test_paired_tests_table_applies_holm_over_the_family():
    cells = {
        "A": rows("iiiiiiiiii"),
        "B": rows("cccccccccc"),  # 10 discordant, all to B: exact p = 2 / 2**10
        "C": rows("iiiiiiiiii"),
    }
    out = grid.paired_tests_table(cells, pairs=[("A", "B"), ("A", "C")])
    p_ab = 2 / 2**10
    assert f"{p_ab:.4f} | {2 * p_ab:.4f} |" in out  # Holm: smallest p x 2
    assert "| A → C | 10 | 0 | 0 | +0.0" in out
    assert "| 1.0000 | 1.0000 |" in out  # no discordant pairs


def test_paired_tests_refuse_different_questions():
    with pytest.raises(ValueError, match="different questions"):
        grid.paired_tests_table({"A": rows("cc"), "B": rows("c")}, pairs=[("A", "B")])


def test_grid_table_has_every_cell_with_ci():
    cells = {label: rows("ci") for label in grid.CELLS}
    out = grid.grid_table(cells)
    assert out.count("1/2, 50.0% [") == 6


# ---------------------------------------------------------------- flip matrices


def test_flip_counts_three_by_three():
    before = rows("cciir")
    after = rows("cicrc")  # c->c, c->i, i->c, i->r, r->c
    counts = grid.flip_counts(before, after)
    assert counts[("correct", "correct")] == 1
    assert counts[("correct", "incorrect")] == 1
    assert counts[("incorrect", "correct")] == 1
    assert counts[("incorrect", "refused")] == 1
    assert counts[("refused", "correct")] == 1
    assert sum(counts.values()) == 5
    assert len(counts) == 9


def test_flip_table_fixed_and_broken():
    out = grid.flip_table(rows("cciir"), rows("cicrc"), "R1-V2")
    assert "Fixed (→ correct): 2. Broken (correct →): 1." in out
    assert "| total | 3 | 1 | 1 | 5 |" in out


def test_flip_refuses_different_questions():
    with pytest.raises(ValueError):
        grid.flip_counts(rows("cc"), rows("c"))


# ---------------------------------------------------------------- coverage


def claim(cid: str) -> Claim:
    return Claim(
        claim_id=cid, metric="revenue", value=1.0, unit="USD", period="FY2022", chunk_ids=[]
    )


def v(cid: str, check: str, ok: bool | None, reason: str, rnd: int = 1) -> Verdict:
    return Verdict(claim_id=cid, ok=ok, check=check, reason=f"round {rnd}: {reason}")


def draft(qid: str, cids: list[str], answer: str | None) -> Draft:
    return Draft(
        question_id=qid,
        retrieval_arm="agentic",
        answer_text="x",
        claims=[claim(c) for c in cids],
        answer_claim_id=answer,
        evidence={},
        trace_id="t",
        latency_s=1.0,
        tokens_in=1,
        tokens_out=1,
    )


def result(qid: str, cids: list[str], verdicts: list[Verdict], error: str | None = None):
    claims = [claim(c) for c in cids]
    return VerifiedResult(
        question_id=qid,
        retrieval_arm="agentic",
        verification_arm="grounded",
        claims_before=claims,
        claims_after=claims,
        verdicts=verdicts,
        revisions_used=0,
        flagged_claim_ids=[],
        latency_s=0.0,
        tokens_in=0,
        tokens_out=0,
        error=error,
    )


NO_MAP = "metric 'widgets' has no XBRL mapping"
QUOTED = "quoted claim: nothing to recompute"
COMPUTED = "computed claim: checked by recomputation"


def computed_claim(cid: str) -> Claim:
    return Claim(
        claim_id=cid,
        metric="margin",
        value=10.0,
        unit="%",
        period="FY2022",
        chunk_ids=[],
        derived_from=["c1"],
        expression="c1 / 2",
    )


@pytest.fixture
def coverage_case():
    """Verdict sets grounded.py can emit: each quoted claim gets cited_text True/False and
    recompute not applicable; each computed claim the reverse."""
    drafts = [
        draft("q0", ["c1"], "c1"),
        draft("q1", ["c1", "c2"], "c2"),
        draft("q2", ["c1"], "c1"),
        draft("q3", [], None),
    ]
    drafts[1] = drafts[1].model_copy(update={"claims": [claim("c1"), computed_claim("c2")]})
    failed = draft("q4", [], None).model_copy(update={"error": "model error"})
    drafts.append(failed)
    verified = [
        # q0: quoted answer claim compared by cited text (pass); XBRL has no mapping
        result(
            "q0",
            ["c1"],
            [
                v("c1", "cited_text", True, "1 USD is stated in k1"),
                v("c1", "xbrl", None, NO_MAP),
                v("c1", "recompute", None, QUOTED),
                v("c1", "cited_text", False, "changed", rnd=2),  # a later round must not count
            ],
        ),
        # q1: c1 quoted, cites nothing retrieved (could not run); answer c2 computed with no
        # inputs in the draft (could not run): the answer claim is not checkable
        result(
            "q1",
            ["c1", "c2"],
            [
                v("c1", "cited_text", False, "cites k9, which is not in the retrieved evidence"),
                v("c1", "xbrl", None, "no XBRL value for revenue FY2022"),
                v("c1", "recompute", None, QUOTED),
                v("c2", "cited_text", None, COMPUTED),
                v("c2", "xbrl", None, "company not known"),
                v("c2", "recompute", False, "inputs c7 are not claims in the draft"),
            ],
        ),
        # q2: verification failed, no verdicts
        result("q2", ["c1"], [], error="boom"),
        # q3: qualitative answer, no claims
        result("q3", [], []),
        # q4: generation failed (V2 returns the empty draft unverified)
        result("q4", [], []),
    ]
    return drafts, verified


def test_round_one_drops_later_rounds_and_prefix(coverage_case):
    _, verified = coverage_case
    first = grid.round_one(verified[0].verdicts)
    assert len(first) == 3
    assert first[0].reason == "1 USD is stated in k1"


def test_check_status_follows_v2_reason_strings():
    def status(check, ok, reason):
        return grid.check_status(Verdict(claim_id="c", ok=ok, check=check, reason=reason))

    assert status("cited_text", True, "1 USD is stated in k1") == (grid.COMPARED, None)
    assert status("cited_text", False, "1 USD is not stated in k1") == (grid.COMPARED, None)
    assert status("cited_text", None, COMPUTED) == (grid.NOT_APPLICABLE, None)
    assert status("recompute", None, QUOTED) == (grid.NOT_APPLICABLE, None)
    assert status("cited_text", False, "cites no evidence") == (grid.NOT_RUN, "no citation")
    assert status("cited_text", False, "cites k1, k2, which is not in the retrieved evidence")[
        1
    ] == ("citation not in the retrieved evidence")
    assert status("xbrl", None, NO_MAP) == (grid.NOT_RUN, "metric not in the XBRL map")
    assert status("xbrl", None, "revenue is in USD, the claim in %")[1] == (
        "unit differs from the XBRL metric"
    )
    assert status("xbrl", None, "company not known")[1] == "company not known"
    assert status("xbrl", None, "no XBRL value for revenue FY2021")[1] == (
        "no XBRL value for the period"
    )
    assert status("xbrl", False, "XBRL revenue FY2021 is 5, not 7") == (grid.COMPARED, None)
    assert status("recompute", False, "c1 / c2 names no input claims")[1] == (
        "expression names no inputs"
    )
    assert status("recompute", False, "inputs c9 are not claims in the draft")[1] == (
        "inputs are not claims in the draft"
    )
    assert status("recompute", False, "c1 / c2 cannot be evaluated on its inputs")[1] == (
        "expression cannot be evaluated"
    )
    assert status("recompute", False, "c1 / c2 = 3, not 4") == (grid.COMPARED, None)
    assert status("xbrl", None, "something new 12.5") == (grid.NOT_RUN, "something new #")


def test_v2_reason_strings_match_the_verifier():
    """The patterns follow finqa.verifiers.grounded: run its checks and classify the results."""
    from finqa.verifiers import grounded

    quoted = claim("c1")
    no_cite = grounded.check_cited_text(quoted, draft("q", ["c1"], "c1"), 0.01)
    assert grid.check_status(no_cite) == (grid.NOT_RUN, "no citation")
    unretrieved = quoted.model_copy(update={"chunk_ids": ["k9"]})
    v_unret = grounded.check_cited_text(unretrieved, draft("q", ["c1"], "c1"), 0.01)
    assert grid.check_status(v_unret)[1] == "citation not in the retrieved evidence"
    assert grid.check_status(grounded.check_recompute(quoted, [quoted], 0.01))[0] == (
        grid.NOT_APPLICABLE
    )
    comp = computed_claim("c2").model_copy(update={"derived_from": ["c7"]})
    assert grid.check_status(grounded.check_recompute(comp, [quoted, comp], 0.01))[1] == (
        "inputs are not claims in the draft"
    )
    assert grid.check_status(grounded.check_cited_text(comp, draft("q", [], None), 0.01))[0] == (
        grid.NOT_APPLICABLE
    )


def test_claim_checks_and_checkable(coverage_case):
    _, verified = coverage_case
    q0 = grid.claim_checks(verified[0])
    assert grid.checkable(q0["c1"])
    q1 = grid.claim_checks(verified[1])
    assert set(q1["c1"]) == {"cited_text", "xbrl", "recompute"}
    assert not grid.checkable(q1["c1"])
    assert not grid.checkable(q1["c2"])


def test_coverage_section(coverage_case):
    drafts, verified = coverage_case
    # q0 incorrect -> correct; q1 incorrect; q2 correct; q3 refused; q4 incorrect
    before = rows("iicri")
    after = rows("cicri")
    out = grid.coverage_section("R1-V2", verified, drafts, before, after)
    assert "Claims: 3 (round 1, the draft's own claims): 2 quoted, 1 computed." in out
    assert "Claims of failed verifications (no verdicts): 1." in out
    # cited_text applies to the 2 quoted claims, compared 1, passed 1
    assert "| cited_text | 2 | 1/2, 50.0% [" in out
    assert "| 1/1, 100.0% [100.0–100.0] | 0/1, 0.0% [0.0–0.0] |" in out
    # recompute applies to the 1 computed claim and could not run
    assert "| recompute | 1 | 0/1, 0.0% [0.0–0.0] | 0/0, n/a | 0/0, n/a |" in out
    assert "| xbrl | 3 | 0/3, 0.0% [" in out
    assert "| **checkable** (any check compared) | 3 | 1/3, 33.3% [" in out
    assert "| **not checkable** | 3 | 2/3, 66.7% [" in out
    # groups: q0 checkable (0/1 -> 1/1), q1 not checkable, q2 verification failed,
    # q3 no answer claim, q4 generation failed
    assert "| answer claim checkable | 1 | 0/1, 0.0% [0.0–0.0] | 1/1, 100.0% [100.0–100.0] |" in out
    assert "| answer claim not checkable | 1 | 0/1, 0.0% [0.0–0.0] | 0/1, 0.0% [0.0–0.0] |" in out
    assert "| no answer claim | 1 |" in out
    assert "| generation failed | 1 |" in out
    assert "| verification failed | 1 | 1/1, 100.0% [100.0–100.0] |" in out
    # reasons: 5 could-not-run results; not-applicable ones (2 quoted, 1 computed) not counted
    assert "Top reasons a check could not run (5 check results;" in out
    assert "| xbrl | metric not in the XBRL map | 1 |" in out
    assert "| cited_text | citation not in the retrieved evidence | 1 |" in out
    assert "| recompute | inputs are not claims in the draft | 1 |" in out
    assert "quoted claim" not in out.split("Top reasons")[1]
    assert "computed claim" not in out.split("Top reasons")[1]


def test_coverage_never_scores_from_verdicts(coverage_case):
    """Rule 10: accuracy comes from the scored rows, not from V2's verdicts. Flip the gold-based
    rows and the accuracy flips; the verdicts stay the same."""
    drafts, verified = coverage_case
    out = grid.coverage_section("R1-V2", verified, drafts, rows("ccccc"), rows("iiiii"))
    assert "| answer claim checkable | 1 | 1/1, 100.0% [100.0–100.0] | 0/1, 0.0% [0.0–0.0] |" in out


# ---------------------------------------------------------------- cost


def test_cost_table_has_one_row_per_cell():
    cells = {label: rows("cc") for label in grid.CELLS}
    out = grid.cost_table(cells)
    for label in grid.CELLS:
        assert f"| {label} |" in out
