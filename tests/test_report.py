"""M1 report from dummy test runs, subset and full split (ROADMAP M1.9). No model calls."""

import json
from pathlib import Path

import pytest

from finqa.cli import build_parser
from finqa.config import CONFIGS_DIR
from finqa.eval import dummies, report, runner
from finqa.eval.questions import load_questions
from finqa.eval.scoring import Gold, Judgment

FIXTURE = Path(__file__).parent / "fixtures" / "financebench_sample.jsonl"
CLEAN_MAIN = runner.GitState(commit="a" * 40, short="aaaaaaa", branch="main", dirty=False)
IDS = ["fb_synth_001", "fb_synth_002", "fb_synth_003"]
GOLD = {
    "fb_synth_001": Gold("fb_synth_001", "42", "number", 42.0, "USD"),  # dummy answers 42
    "fb_synth_002": Gold("fb_synth_002", "Yes, 1.4.", "text_with_numbers", None, ""),
    "fb_synth_003": Gold("fb_synth_003", "$1,200", "number", 1200.0, "USD"),
}
CONFIGS = ("baselines/s0_closed_book.yaml", "grid/r0_v0.yaml")


def judge_says_no(question, gold_answer, model_answer):
    return Judgment(correct=False, reason="different conclusion")


@pytest.fixture
def setup(tmp_path: Path):
    splits = tmp_path / "splits.json"
    types = dict(zip(IDS, ["single_fact", "calculation", "qualitative"], strict=True))
    splits.write_text(json.dumps({"dev": [], "test": IDS, "question_types": types}))
    subset = tmp_path / report.SUBSET
    subset.write_text(json.dumps({"ids": IDS}))
    runs = tmp_path / "runs"
    for name in CONFIGS:
        runner.draft_command(
            str(CONFIGS_DIR / name),
            split="test",
            subset=subset,
            runs_dir=runs,
            splits_path=splits,
            financebench_path=FIXTURE,
            git=CLEAN_MAIN,
            generator=dummies.generate,
        )
    questions = {q.question_id: q for q in load_questions("test", splits, FIXTURE)}
    return runs, tmp_path / "docs", questions


def draft_full(runs: Path, splits: Path) -> None:
    for name in CONFIGS:
        runner.draft_command(
            str(CONFIGS_DIR / name),
            split="test",
            runs_dir=runs,
            splits_path=splits,
            financebench_path=FIXTURE,
            git=runner.GitState(commit="b" * 40, short="bbbbbbb", branch="main", dirty=False),
            generator=dummies.generate,
        )


def make_report(runs: Path, docs: Path, questions, scope: str = "subset") -> int:
    return report.report_command(
        "m1",
        scope=scope,
        runs_dir=runs,
        docs_dir=docs,
        questions=questions,
        gold=GOLD,
        make_judge=lambda cfg, run_id: judge_says_no,
        locate=lambda q: (None, None),
        lookup=None,
    )


def test_report_writes_every_m1_table_and_figure(setup):
    runs, docs, questions = setup
    assert make_report(runs, docs, questions) == 0
    results = (docs / "RESULTS_midterm_subset.md").read_text(encoding="utf-8")
    assert not (docs / "RESULTS.md").exists()
    assert "S0 vs R0 on the test subset" in results
    for title in ("Table M1-A", "Contamination check", "Table M1-B", "Figure M1-1", "Table M1-C"):
        assert title in results
    assert "| **all** | 1/3, 33.3% [" in results
    assert "| S0 vs R0 | 3 | 1 | 0 | 0 | 2 | 1.0000 |" in results
    assert "| Filings indexed | 819 (206 10-K, 613 10-Q) |" in results  # real Phase 1 data
    figure = (docs / "figures" / "m1_error_types_midterm_subset.tex").read_text(encoding="utf-8")
    assert r"\texttt{retrieval\_miss} & \rule{0.600\linewidth}{1.6ex} 2 \\" in figure

    r0_run = report.find_run(runs, report.R0, report.SUBSET)
    spotcheck = (r0_run / "error_spotcheck.csv").read_text(encoding="utf-8").splitlines()
    assert len(spotcheck) == 1 + 2  # header + the two incorrect answers
    assert len((r0_run / "scores.jsonl").read_text(encoding="utf-8").splitlines()) == 3


def test_report_refuses_runs_on_different_questions(setup):
    runs, docs, questions = setup
    s0_drafts = report.find_run(runs, report.S0, report.SUBSET) / "drafts.jsonl"
    lines = s0_drafts.read_text(encoding="utf-8").splitlines(keepends=True)
    s0_drafts.write_text("".join(lines[:2]), encoding="utf-8")
    with pytest.raises(runner.RunRefused, match="different questions"):
        make_report(runs, docs, questions)


def test_full_scope_reads_full_split_runs_only(setup):
    runs, docs, questions = setup
    with pytest.raises(runner.RunRefused, match="full test split"):
        make_report(runs, docs, questions, scope="full")  # only subset runs exist so far
    draft_full(runs, runs.parent / "splits.json")
    full_r0 = report.find_run(runs, report.R0)
    assert json.loads((full_r0 / "run_meta.json").read_text(encoding="utf-8"))["subset"] is None
    assert full_r0 != report.find_run(runs, report.R0, report.SUBSET)

    assert make_report(runs, docs, questions, scope="full") == 0
    results = (docs / "RESULTS.md").read_text(encoding="utf-8")
    assert "S0 vs R0 on the test split" in results
    assert "All 3 test questions" in results
    assert "--scope full" in results
    assert full_r0.name in results
    assert (docs / "figures" / "m1_error_types.tex").exists()
    assert (full_r0 / "scores.jsonl").exists()
    assert not (docs / "RESULTS_midterm_subset.md").exists()


def test_missing_run_unknown_milestone_and_scope_are_refused(tmp_path: Path):
    with pytest.raises(runner.RunRefused, match="no test run"):
        report.find_run(tmp_path, report.R0)
    with pytest.raises(runner.RunRefused, match="milestone"):
        report.report_command("m2", runs_dir=tmp_path)
    with pytest.raises(runner.RunRefused, match="scope"):
        report.report_command("m1", scope="half", runs_dir=tmp_path)


def test_cli_report_arguments():
    args = build_parser().parse_args(["report", "--milestone", "m1"])
    assert (args.milestone, args.scope) == ("m1", "full")
    args = build_parser().parse_args(["report", "--milestone", "m1", "--scope", "subset"])
    assert args.scope == "subset"
    with pytest.raises(SystemExit):
        build_parser().parse_args(["report", "--milestone", "m9"])
