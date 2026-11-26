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


@pytest.fixture
def coverage_case():
    drafts = [draft("q0", ["c1"], "c1"), draft("q1", ["c1", "c2"], "c2"), draft("q2", ["c1"], None)]
    verified = [
        # q0: answer claim checked by cited_text (pass); the xbrl and recompute checks cannot run
        result(
            "q0",
            ["c1"],
            [
                v("c1", "cited_text", True, "1 USD is stated in k1"),
                v("c1", "xbrl", None, NO_MAP),
                v("c1", "recompute", None, QUOTED),
                # a later round must not count
                v("c1", "cited_text", False, "changed", rnd=2),
            ],
        ),
        # q1: c1 checkable (fails), answer claim c2 has no check that ran
        result(
            "q1",
            ["c1", "c2"],
            [
                v("c1", "cited_text", False, "1 USD is not stated in k1"),
                v("c1", "xbrl", None, "no XBRL value for revenue FY2022"),
                v("c1", "recompute", None, QUOTED),
                v("c2", "cited_text", None, "computed claim: checked by recomputation"),
                v("c2", "xbrl", None, "company not known"),
                v("c2", "recompute", None, QUOTED),
            ],
        ),
        # q2: verification failed, no verdicts
        result("q2", ["c1"], [], error="boom"),
    ]
    return drafts, verified


def test_round_one_drops_later_rounds_and_prefix(coverage_case):
    _, verified = coverage_case
    first = grid.round_one(verified[0].verdicts)
    assert len(first) == 3
    assert first[0].reason == "1 USD is stated in k1"


def test_claim_checks_and_checkable(coverage_case):
    _, verified = coverage_case
    checks = grid.claim_checks(verified[1])
    assert checks["c1"] == {"cited_text": False, "xbrl": None, "recompute": None}
    assert not any(ok is not None for ok in checks["c2"].values())


def test_reason_categories():
    assert grid.reason_category(NO_MAP) == "metric not in the XBRL map"
    assert grid.reason_category("revenue is in USD, the claim in %") == (
        "unit differs from the XBRL metric"
    )
    assert grid.reason_category("no XBRL value for revenue FY2021") == (
        "no XBRL value for the period"
    )
    assert grid.reason_category("company not known") == "company not known"
    assert grid.reason_category("something new 12.5") == "something new #"


def test_coverage_section(coverage_case):
    drafts, verified = coverage_case
    before = rows("iic")  # V0: q0 incorrect, q1 incorrect, q2 correct
    after = rows("cic")  # V2: q0 fixed
    out = grid.coverage_section("R1-V2", verified, drafts, before, after)
    assert "Claims checked: 3" in out
    assert "failed verification (no verdicts): 1" in out
    # cited_text ran on 2 of 3 claims, passed 1 of 2
    assert "| cited_text | 2/3, 66.7% [" in out
    assert "| 1/2, 50.0% [" in out
    assert "| xbrl | 0/3, 0.0% [" in out
    assert "| **any check** | 2/3, 66.7% [" in out
    assert "| **no check** | 1/3, 33.3% [" in out
    # q0 answer claim checkable: before 0/1, after 1/1; q1 not checkable
    assert "| answer claim checkable | 1 | 0/1, 0.0% [0.0–0.0] | 1/1, 100.0% [100.0–100.0] |" in out
    assert "| answer claim not checkable | 1 |" in out
    assert "| verification failed | 1 |" in out
    # 3 quoted-claim recomputes are the top reason
    assert "| recompute | quoted claim (nothing to compute) | 3 |" in out


def test_coverage_never_scores_from_verdicts(coverage_case):
    """Rule 10: accuracy comes from the scored rows, not from V2's verdicts. Flip the gold-based
    rows and the accuracy flips; the verdicts stay the same."""
    drafts, verified = coverage_case
    out = grid.coverage_section("R1-V2", verified, drafts, rows("ccc"), rows("iii"))
    assert "| answer claim checkable | 1 | 1/1, 100.0% [100.0–100.0] | 0/1, 0.0% [0.0–0.0] |" in out


# ---------------------------------------------------------------- cost


def test_cost_table_has_one_row_per_cell():
    cells = {label: rows("cc") for label in grid.CELLS}
    out = grid.cost_table(cells)
    for label in grid.CELLS:
        assert f"| {label} |" in out
