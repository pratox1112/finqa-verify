"""Verifier interface and V0 (ROADMAP P4.1). No model calls."""

import inspect
from pathlib import Path

from test_report import GOLD
from test_runner import CLEAN_MAIN, CONFIG, FIXTURE, draft, only_run, splits  # noqa: F401

from finqa.config import CONFIGS_DIR, load_config
from finqa.eval import runner, tables
from finqa.eval.questions import load_questions
from finqa.eval.scoring import Judgment
from finqa.schemas import Claim, Draft, VerifiedResult
from finqa.verifiers import none
from finqa.verifiers.base import result

R0_V0 = load_config(CONFIGS_DIR / "grid" / "r0_v0.yaml")


def make_draft(error: str | None = None) -> Draft:
    claims = [
        Claim(
            claim_id="c1",
            metric="revenue",
            value=1.2e9,
            unit="USD",
            period="FY2022",
            chunk_ids=["k1"],
        ),
        Claim(
            claim_id="c2",
            metric="growth",
            value=12.5,
            unit="%",
            period="FY2022",
            chunk_ids=[],
            derived_from=["c1"],
            expression="c1 / 1e9",
        ),
    ]
    return Draft(
        question_id="q1",
        retrieval_arm="rag",
        answer_text="Revenue was $1.2B.",
        claims=claims,
        answer_claim_id="c1",
        evidence={},
        trace_id="t1",
        latency_s=2.0,
        tokens_in=500,
        tokens_out=50,
        error=error,
    )


def test_v0_returns_the_draft_unchanged() -> None:
    d = make_draft()
    r = none.verify(d, R0_V0)
    assert isinstance(r, VerifiedResult)
    assert r.claims_after == d.claims and r.claims_before == d.claims
    assert r.question_id == "q1" and r.retrieval_arm == "rag" and r.verification_arm == "none"
    assert r.verdicts == [] and r.flagged_claim_ids == [] and r.revisions_used == 0
    assert (r.latency_s, r.tokens_in, r.tokens_out, r.error) == (0.0, 0, 0, None)


def test_v0_keeps_a_failed_draft_failed_through_scoring() -> None:
    # the draft's error is scored by score_verified from the draft itself, not copied here
    r = none.verify(make_draft(error="ValidationError: x"), R0_V0)
    assert r.error is None and r.claims_after == r.claims_before


def test_result_copies_claim_lists() -> None:
    d = make_draft()
    r = result(d, R0_V0)
    r.claims_after.pop()
    assert len(d.claims) == 2 and len(r.claims_before) == 2  # the draft is not modified


def test_v0_matches_the_runner_interface() -> None:
    assert list(inspect.signature(none.verify).parameters) == ["draft", "cfg"]
    assert runner.resolve(runner.VERIFIERS, "none") is none.verify


def test_v0_through_the_runner_scores_exactly_like_the_drafts(
    tmp_path: Path,
    splits: Path,  # noqa: F811  (pytest fixture)
) -> None:
    draft(tmp_path, splits)
    run_dir = only_run(tmp_path)
    assert (
        runner.verify_command(
            run_dir.name,
            CONFIG,
            runs_dir=tmp_path / "runs",
            git=CLEAN_MAIN,
        )
        == 0
    )
    drafts = runner.read_jsonl(run_dir / "drafts.jsonl", Draft)
    verified = runner.read_jsonl(run_dir / "verified_none.jsonl", VerifiedResult)
    assert [v.claims_after for v in verified] == [d.claims for d in drafts]
    questions = {q.question_id: q for q in load_questions("dev", splits, FIXTURE)}
    gold = {q: GOLD[q] for q in questions}

    def judge(question: str, gold_answer: str, answer: str) -> Judgment:
        return Judgment(correct=False, reason="test")

    as_drafts = tables.score_run(drafts, questions, gold, 0.01, judge)
    as_verified = tables.score_run(drafts, questions, gold, 0.01, judge, verified)
    assert [r.outcome for r in as_drafts] == [r.outcome for r in as_verified]
