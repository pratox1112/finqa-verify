"""Results tables from the dummy run (ROADMAP P2.4 acceptance) and the P0.7 smoke test."""

import json
from pathlib import Path

from finqa.config import BASE_CONFIG, load_config
from finqa.eval import dummies, runner, tables
from finqa.eval.questions import load_questions
from finqa.eval.scoring import Gold, Judgment
from finqa.schemas import Draft, VerifiedResult

FIXTURE = Path(__file__).parent / "fixtures" / "financebench_sample.jsonl"
CLEAN_MAIN = runner.GitState(commit="a" * 40, short="aaaaaaa", branch="main", dirty=False)
GOLD = {
    "fb_synth_001": Gold("fb_synth_001", "42", "number", 42.0, "USD"),  # dummy answers 42
    "fb_synth_002": Gold("fb_synth_002", "Yes, 1.4.", "text_with_numbers", None, ""),
    "fb_synth_003": Gold("fb_synth_003", "$1,200", "number", 1200.0, "USD"),
}


def judge_says_no(question, gold_answer, model_answer):
    return Judgment(correct=False, reason="different conclusion")


def run_dummy(tmp_path: Path) -> tuple[Path, dict]:
    splits = tmp_path / "splits.json"
    splits.write_text(
        json.dumps(
            {
                "dev": ["fb_synth_001", "fb_synth_002", "fb_synth_003"],
                "test": [],
                "question_types": {
                    "fb_synth_001": "single_fact",
                    "fb_synth_002": "calculation",
                    "fb_synth_003": "single_fact",
                },
            }
        )
    )
    runner.draft_command(
        str(BASE_CONFIG),
        split="dev",
        runs_dir=tmp_path / "runs",
        splits_path=splits,
        financebench_path=FIXTURE,
        git=CLEAN_MAIN,
        generator=dummies.generate,
    )
    (run_dir,) = (tmp_path / "runs").iterdir()
    runner.verify_command(
        run_dir.name,
        str(BASE_CONFIG),
        runs_dir=tmp_path / "runs",
        git=CLEAN_MAIN,
        verifier=dummies.verify,
    )
    questions = {q.question_id: q for q in load_questions("dev", splits, FIXTURE)}
    return run_dir, questions


def test_dummy_run_produces_tables_with_counts_and_cis(tmp_path: Path):
    run_dir, questions = run_dummy(tmp_path)
    drafts = runner.read_jsonl(run_dir / "drafts.jsonl", Draft)
    verified = runner.read_jsonl(run_dir / "verified_none.jsonl", VerifiedResult)
    tol = load_config(BASE_CONFIG).verification.tolerance
    rows = tables.score_run(drafts, questions, GOLD, tol, judge_says_no)
    rows_v = tables.score_run(drafts, questions, GOLD, tol, judge_says_no, verified=verified)
    assert [r.outcome for r in rows] == ["correct", "incorrect", "incorrect"]
    assert [r.outcome for r in rows_v] == [r.outcome for r in rows]

    table = tables.accuracy_table(rows, "Dummy, dev")
    assert "| single_fact | 1/2, 50.0% [" in table
    assert "| calculation | 0/1, 0.0% [0.0–0.0]" in table
    assert "| **all** | 1/3, 33.3% [" in table

    path = run_dir / "scores_none.jsonl"
    tables.write_rows(rows, path)
    assert tables.read_rows(path) == rows

    assert "| dummy | 0.00 / 0.00 |" in tables.efficiency_table([("dummy", rows)])
    comparison = tables.comparison_table("A", rows, "B", rows_v)
    assert "| A vs B | 3 | 1 | 0 | 0 | 2 | 1.0000 |" in comparison


def test_refusals_count_separately():
    row = tables.Row("q", "single_fact", "refused", "refusal", "", 1.0, 10, 5, False)
    table = tables.accuracy_table([row], "t")
    assert "| single_fact | 0/1, 0.0% [0.0–0.0] | 1/1 | 0/0, n/a | 0 |" in table
