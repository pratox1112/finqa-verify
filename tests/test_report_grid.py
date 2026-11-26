"""Grid report (retrieval x verification) from fake test runs. No model calls."""

import json
from pathlib import Path

import pytest
from test_report import FIXTURE, GOLD, judge_says_no
from test_report_p3 import fake_generate, git

from finqa.cli import build_parser
from finqa.config import CONFIGS_DIR, Config
from finqa.eval import grid, report, report_grid, runner
from finqa.eval.questions import load_questions
from finqa.schemas import Draft, Verdict, VerifiedResult

VERIFY_CONFIGS = {
    ("r0_v0", "none"): "grid/r0_v0.yaml",
    ("r0_v0", "self_check"): "grid/r0_v1.yaml",
    ("r0_v0", "grounded"): "grid/r0_v2.yaml",
    ("r1_v0", "none"): "grid/r1_v0.yaml",
    ("r1_v0", "self_check"): "grid/r1_v1.yaml",
    ("r1_v0", "grounded"): "grid/r1_v2.yaml",
}


def fake_verify(draft: Draft, cfg: Config) -> VerifiedResult:
    """V0 and V1 keep the claims. V2 compares c1 with its cited text (fails), XBRL cannot run,
    recomputation does not apply to a quoted claim; V2
    corrects fb_synth_001 to the gold value 42, so R0 gains one question."""
    claims = list(draft.claims)
    verdicts: list[Verdict] = []
    if cfg.verification.arm == "grounded":
        verdicts = [
            Verdict(
                claim_id="c1",
                ok=False,
                check="cited_text",
                reason="round 1: 7 USD is not stated in k1",
            ),
            Verdict(
                claim_id="c1",
                ok=None,
                check="xbrl",
                reason="round 1: metric 'answer' has no XBRL mapping",
            ),
            Verdict(
                claim_id="c1",
                ok=None,
                check="recompute",
                reason="round 1: quoted claim: nothing to recompute",
            ),
        ]
        if draft.question_id == "fb_synth_001":
            claims = [claims[0].model_copy(update={"value": 42.0})]
    return VerifiedResult(
        question_id=draft.question_id,
        retrieval_arm=draft.retrieval_arm,
        verification_arm=cfg.verification.arm,
        claims_before=list(draft.claims),
        claims_after=claims,
        verdicts=verdicts,
        revisions_used=int(claims != list(draft.claims)),
        flagged_claim_ids=[],
        latency_s=0.5,
        tokens_in=50,
        tokens_out=5,
    )


def draft(runs: Path, splits: Path, config: str, state: runner.GitState | None = None) -> str:
    runner.draft_command(
        str(CONFIGS_DIR / config),
        split="test",
        runs_dir=runs,
        splits_path=splits,
        financebench_path=FIXTURE,
        git=state or git(),
        generator=fake_generate,
    )
    name = Path(config).stem
    return sorted(p.name for p in runs.glob(f"*_{name}_*"))[-1]


def verify(runs: Path, run_id: str, config: str) -> None:
    runner.verify_command(
        run_id, str(CONFIGS_DIR / config), runs_dir=runs, git=git(), verifier=fake_verify
    )


@pytest.fixture
def setup(tmp_path: Path):
    import json

    splits = tmp_path / "splits.json"
    ids = ["fb_synth_001", "fb_synth_002", "fb_synth_003"]
    types = dict(zip(ids, ["single_fact", "calculation", "qualitative"], strict=True))
    splits.write_text(json.dumps({"dev": [], "test": ids, "question_types": types}))
    runs = tmp_path / "runs"
    run_ids = {name: draft(runs, splits, f"grid/{name}.yaml") for name in ("r0_v0", "r1_v0")}
    for (name, _), config in VERIFY_CONFIGS.items():
        verify(runs, run_ids[name], config)
    questions = {q.question_id: q for q in load_questions("test", splits, FIXTURE)}
    return runs, tmp_path / "docs", questions, splits, run_ids


def make_report(runs: Path, docs: Path, questions) -> int:
    return report.report_command(
        "grid",
        runs_dir=runs,
        docs_dir=docs,
        questions=questions,
        gold=GOLD,
        make_judge=lambda cfg, run_id: judge_says_no,
    )


def test_verify_configs_match_the_grid_cells() -> None:
    from finqa.config import load_config
    from finqa.eval import grid

    assert set(VERIFY_CONFIGS) == set(grid.CELLS.values())
    for (name, arm), path in VERIFY_CONFIGS.items():
        cfg = load_config(str(CONFIGS_DIR / path))
        assert cfg.verification.arm == arm
        drafts_cfg = load_config(str(CONFIGS_DIR / f"grid/{name}.yaml"))
        assert cfg.retrieval.arm == drafts_cfg.retrieval.arm


def test_report_writes_every_table(setup) -> None:
    runs, docs, questions, _, run_ids = setup
    assert make_report(runs, docs, questions) == 0
    out = (docs / report_grid.RESULTS_FILE).read_text(encoding="utf-8")
    for title in ("Table G-A", "Table G-B", "Table G-C", "Table G-D", "Table G-E"):
        assert title in out
    assert "both from commit `ccccccc` on main" in out
    # accuracy: R0 0/3 except V2 (fixes fb_synth_001); R1 2/3 everywhere
    r0_row = next(line for line in out.splitlines() if line.startswith("| R0 | "))
    assert r0_row.count("0/3, 0.0% [") == 2 and "| 1/3, 33.3% [" in r0_row
    r1_row = next(line for line in out.splitlines() if line.startswith("| R1 | "))
    assert r1_row.count("2/3, 66.7% [") == 3
    # outcomes: R1-V2 2/3 correct, 0 refused, selective 2/3, no failures
    r1v2 = next(line for line in out.splitlines() if line.startswith("| R1-V2 | 2/3"))
    assert "| 0/3, 0.0% [0.0–0.0] |" in r1v2  # refused
    assert r1v2.endswith("| 0 | 0 |")  # generation failed, verification failed
    assert "a failed verification is scored as its unchanged draft" in out
    # paired test R0-V0 -> R0-V2: 0 vs 1 correct, 1 discordant (p = 1), Holm p = 1
    assert "| R0-V0 → R0-V2 | 3 | 0 | 1 | +33.3 [" in out
    assert "| 0 | 1 | 1.0000 | 1.0000 |" in out
    for a, b in grid.PLANNED_PAIRS:
        assert f"| {a} → {b} | 3 |" in out
    # flips: R0 V0 -> V2 fixes one question, breaks none
    assert "**R0: V0 → V2**" in out
    assert "Fixed (→ correct): 1. Broken (correct →): 0." in out
    # coverage: every claim compared by cited text only; recompute not applicable
    assert "### R0-V2" in out and "### R1-V2" in out
    assert "| cited_text | 3 | 3/3, 100.0% [" in out
    assert "| xbrl | 3 | 0/3, 0.0% [" in out
    assert "| recompute | 0 | 0/0, n/a |" in out
    assert "| answer claim checkable | 3 |" in out
    assert "| xbrl | metric not in the XBRL map | 3 |" in out
    # cost: one row per cell
    for label in ("R0-V0", "R0-V1", "R0-V2", "R1-V0", "R1-V1", "R1-V2"):
        assert f"| {label} |" in out
    for run_id in run_ids.values():
        for arm in ("none", "self_check", "grounded"):
            scores = runs / run_id / f"scores_{arm}.jsonl"
            assert len(scores.read_text(encoding="utf-8").splitlines()) == 3


def test_report_refuses_an_unfinished_cell(setup) -> None:
    runs, docs, questions, _, run_ids = setup
    (runs / run_ids["r1_v0"] / "verified_self_check.jsonl").unlink()
    with pytest.raises(runner.RunRefused, match="R1-V1 covers 0 of the 3 test questions"):
        make_report(runs, docs, questions)


def test_report_refuses_a_partly_verified_cell(setup) -> None:
    runs, docs, questions, _, run_ids = setup
    path = runs / run_ids["r0_v0"] / "verified_grounded.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text("".join(lines[:2]), encoding="utf-8")
    with pytest.raises(runner.RunRefused, match="R0-V2 covers 2 of the 3"):
        make_report(runs, docs, questions)


def test_report_refuses_drafts_from_different_commits(setup) -> None:
    runs, docs, questions, splits, _ = setup
    newer = draft(runs, splits, "grid/r1_v0.yaml", git("d"))  # newer R1 drafts, other commit
    for (name, _), config in VERIFY_CONFIGS.items():
        if name == "r1_v0":
            verify(runs, newer, config)
    with pytest.raises(runner.RunRefused, match="different commits"):
        make_report(runs, docs, questions)


def test_report_refuses_drafts_not_from_clean_main(setup) -> None:
    runs, docs, questions, _, run_ids = setup
    meta_path = runs / run_ids["r0_v0"] / "run_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["git_dirty"] = True
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(runner.RunRefused, match="R0 drafts were not run from a clean main"):
        make_report(runs, docs, questions)


def test_report_refuses_a_repeated_question(setup) -> None:
    runs, docs, questions, _, run_ids = setup
    path = runs / run_ids["r1_v0"] / "verified_grounded.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text("".join(lines + lines[:1]), encoding="utf-8")
    with pytest.raises(runner.RunRefused, match="R1-V2: verified_grounded.jsonl repeats"):
        make_report(runs, docs, questions)


def test_report_refuses_repeated_drafts(setup) -> None:
    runs, docs, questions, _, run_ids = setup
    path = runs / run_ids["r0_v0"] / "drafts.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text("".join(lines + lines[:1]), encoding="utf-8")
    with pytest.raises(runner.RunRefused, match="R0 drafts do not cover"):
        make_report(runs, docs, questions)


def test_newest_run_is_chosen_by_start_time_not_run_id(tmp_path: Path) -> None:
    for name, started in (
        ("2026-11-22_r0_v0_fffffff", "2026-11-22T09:00:00+00:00"),
        ("2026-11-22_r0_v0_0000000", "2026-11-22T18:00:00+00:00"),
    ):
        (tmp_path / name).mkdir()
        meta = {"config_name": "r0_v0", "split": "test", "subset": None, "started": started}
        (tmp_path / name / "run_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    run_dir, _ = report_grid.find_newest_full_test_run(tmp_path, "r0_v0")
    assert run_dir.name == "2026-11-22_r0_v0_0000000"  # later start, although it sorts first


def test_report_refuses_a_subset_scope(setup) -> None:
    runs, docs, questions, _, _ = setup
    with pytest.raises(runner.RunRefused, match="full test split only"):
        report.report_command("grid", "subset", runs_dir=runs, docs_dir=docs, questions=questions)


def test_cli_accepts_the_grid_milestone() -> None:
    args = build_parser().parse_args(["report", "--milestone", "grid"])
    assert args.milestone == "grid"
