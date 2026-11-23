"""Phase 3 report (the retrieval x calculator 2 x 2) from fake test runs. No model calls."""

import json
from pathlib import Path

import pytest
from test_report import FIXTURE, GOLD, IDS, judge_says_no

from finqa.cli import build_parser
from finqa.config import CONFIGS_DIR, Config
from finqa.eval import report, report_p3, runner, stats
from finqa.eval.questions import load_questions
from finqa.generators.base import Question, RunContext
from finqa.schemas import Claim, Draft

CONFIGS = {
    "r0_v0": "grid/r0_v0.yaml",
    "r0_calc_v0": "ablations/r0_calc_v0.yaml",
    "r1_nocalc_v0": "ablations/r1_nocalc_v0.yaml",
    "r1_v0": "grid/r1_v0.yaml",
}
# which questions each arm answers correctly (fb_synth_002 has a text gold; the judge says no)
CORRECT = {
    "r0_v0": set(),
    "r0_calc_v0": {"fb_synth_001"},
    "r1_nocalc_v0": {"fb_synth_001", "fb_synth_003"},
    "r1_v0": {"fb_synth_001", "fb_synth_003"},
}
VALUES = {"fb_synth_001": 42.0, "fb_synth_003": 1200.0}


def fake_generate(question: Question, cfg: Config, ctx: RunContext) -> Draft:
    right = question.question_id in CORRECT[cfg.name]
    value = VALUES.get(question.question_id, 1.0) if right else 7.0
    claim = Claim(
        claim_id="c1", metric="answer", value=value, unit="USD", period="FY2022", chunk_ids=[]
    )
    return Draft(
        question_id=question.question_id,
        retrieval_arm=cfg.retrieval.arm,
        answer_text=f"{value}",
        claims=[claim],
        answer_claim_id="c1",
        evidence={},
        trace_id=ctx.trace_id,
        latency_s=1.0,
        tokens_in=100,
        tokens_out=10,
    )


def git(commit: str = "c", branch: str = "main", dirty: bool = False) -> runner.GitState:
    return runner.GitState(commit=commit * 40, short=commit * 7, branch=branch, dirty=dirty)


@pytest.fixture
def setup(tmp_path: Path):
    splits = tmp_path / "splits.json"
    types = dict(zip(IDS, ["single_fact", "calculation", "qualitative"], strict=True))
    splits.write_text(json.dumps({"dev": [], "test": IDS, "question_types": types}))
    runs = tmp_path / "runs"
    for name in CONFIGS.values():
        draft(runs, splits, name)
    questions = {q.question_id: q for q in load_questions("test", splits, FIXTURE)}
    return runs, tmp_path / "docs", questions, splits


def draft(runs: Path, splits: Path, config: str, state: runner.GitState | None = None) -> None:
    runner.draft_command(
        str(CONFIGS_DIR / config),
        split="test",
        runs_dir=runs,
        splits_path=splits,
        financebench_path=FIXTURE,
        git=state or git(),
        generator=fake_generate,
    )


def make_report(runs: Path, docs: Path, questions) -> int:
    return report.report_command(
        "p3",
        runs_dir=runs,
        docs_dir=docs,
        questions=questions,
        gold=GOLD,
        make_judge=lambda cfg, run_id: judge_says_no,
    )


def test_arms_are_the_four_configs() -> None:
    assert set(report_p3.ARMS.values()) == set(CONFIGS)
    for name, path in CONFIGS.items():
        assert (CONFIGS_DIR / path).exists() and Path(path).stem == name


def test_report_writes_the_2x2_effects_types_and_efficiency(setup) -> None:
    runs, docs, questions, _ = setup
    assert make_report(runs, docs, questions) == 0
    results = (docs / "RESULTS_P3.md").read_text(encoding="utf-8")
    for title in ("Table P3-A", "Table P3-B", "Table P3-C", "Table P3-D"):
        assert title in results
    assert "all from commit `ccccccc` on main" in results
    assert "| Single-shot | R0: 0/3, 0.0% [" in results
    assert "| R0+calc: 1/3, 33.3% [" in results
    assert "| Agent | R1−calc: 2/3, 66.7% [" in results and "| R1: 2/3, 66.7% [" in results
    # effects: A correct, B correct, difference, A only, B only, p
    assert "| Calculator, single-shot retrieval | R0 → R0+calc | 3 | 0 | 1 | +33.3 [" in results
    assert (
        "| Calculator, agent | R1−calc → R1 | 3 | 2 | 2 | +0.0 [+0.0, +0.0] | 0 | 0 | 1.0000 |"
        in results
    )
    assert "| Agent retrieval, no calculator | R0 → R1−calc | 3 | 0 | 2 | +66.7 [" in results
    assert "| 0 | 2 | 0.5000 |" in results
    assert "**R1 (`" in results  # per-arm accuracy by type
    assert "| R0+calc | 1.00 / 1.00 |" in results  # efficiency
    for run_dir in runs.iterdir():
        assert len((run_dir / "scores.jsonl").read_text(encoding="utf-8").splitlines()) == 3


def test_report_needs_every_arm(setup) -> None:
    runs, docs, questions, _ = setup
    for run_dir in runs.iterdir():
        if run_dir.name.endswith("r1_nocalc_v0_ccccccc"):
            (run_dir / "run_meta.json").unlink()
    with pytest.raises(runner.RunRefused, match="no full test-split run of r1_nocalc_v0"):
        make_report(runs, docs, questions)


def test_report_refuses_arms_from_different_commits(setup) -> None:
    runs, docs, questions, splits = setup
    draft(runs, splits, CONFIGS["r1_v0"], git("d"))  # a newer R1 run at another commit
    with pytest.raises(runner.RunRefused, match="different commits"):
        make_report(runs, docs, questions)


def test_report_refuses_a_run_not_from_clean_main(setup) -> None:
    runs, docs, questions, _ = setup
    for meta_path in runs.glob("*r0_calc_v0*/run_meta.json"):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["git_dirty"] = True
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(runner.RunRefused, match="R0\\+calc was not run from a clean main"):
        make_report(runs, docs, questions)


def test_report_refuses_incomplete_runs(setup) -> None:
    runs, docs, questions, _ = setup
    drafts = next(runs.glob("*r1_v0*/drafts.jsonl"))
    lines = drafts.read_text(encoding="utf-8").splitlines(keepends=True)
    drafts.write_text("".join(lines[:2]), encoding="utf-8")
    with pytest.raises(runner.RunRefused, match="do not all cover the 3 test questions"):
        make_report(runs, docs, questions)


def test_report_ignores_dev_and_subset_runs(setup) -> None:
    runs, _, _, _ = setup
    run_dir, meta = report_p3.find_full_test_run(runs, "r1_v0")
    assert meta["split"] == "test" and meta["subset"] is None
    meta_path = run_dir / "run_meta.json"
    meta_path.write_text(json.dumps({**meta, "split": "dev"}), encoding="utf-8")
    with pytest.raises(runner.RunRefused, match="no full test-split run of r1_v0"):
        report_p3.find_full_test_run(runs, "r1_v0")


def test_p3_has_no_subset_scope(setup) -> None:
    runs, docs, questions, _ = setup
    with pytest.raises(runner.RunRefused, match="full test split only"):
        report.report_command("p3", scope="subset", runs_dir=runs, docs_dir=docs)


def test_cli_accepts_the_p3_milestone() -> None:
    args = build_parser().parse_args(["report", "--milestone", "p3"])
    assert args.milestone == "p3" and args.scope == "full"


# --- Paired difference CI ----------------------------------------------------------------------


def test_paired_diff_ci_known_cases() -> None:
    assert stats.paired_diff_ci([], []) is None
    assert stats.paired_diff_ci([True, False], [True, False]) == (0.0, 0.0)
    assert stats.paired_diff_ci([False] * 10, [True] * 10) == (1.0, 1.0)
    lo, hi = stats.paired_diff_ci([False] * 5 + [True] * 5, [True] * 10)
    assert 0.1 <= lo <= 0.5 <= hi <= 0.9
    assert stats.paired_diff_ci([False] * 5 + [True] * 5, [True] * 10) == (lo, hi)  # seeded
    with pytest.raises(ValueError):
        stats.paired_diff_ci([True], [True, False])
