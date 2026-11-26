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


def make_report(runs: Path, docs: Path, questions, milestone: str = "grid", labels=None) -> int:
    return report.report_command(
        milestone,
        runs_dir=runs,
        docs_dir=docs,
        questions=questions,
        gold=GOLD,
        make_judge=lambda cfg, run_id: judge_says_no,
        locate=lambda q: (None, None),
        lookup=None,
        labels=labels,
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


# ---------------------------------------------------------------- P9.2 error types, Gate 9


def cell_row(out: str, label: str, after: str) -> str:
    """The first line starting with "| {label} |" after the heading `after`."""
    section = out.split(after, 1)[1]
    return next(line for line in section.splitlines() if line.startswith(f"| {label} |"))


def test_rule_based_error_types_per_cell(setup) -> None:
    runs, docs, questions, _, run_ids = setup
    assert make_report(runs, docs, questions) == 0
    out = (docs / report_grid.RESULTS_FILE).read_text(encoding="utf-8")
    assert "## Figure G-1: error types per cell" in out
    # wrong answers: R0 3 (V2 fixes fb_synth_001 -> 2); R1 1 (the text-gold question)
    for label, wrong in (("R0-V0", 3), ("R0-V1", 3), ("R0-V2", 2), ("R1-V0", 1), ("R1-V2", 1)):
        assert cell_row(out, label, "(a) Rule-based").endswith(f"| {wrong} |")
    assert "Pending: no Phase 5 final labels" in out
    fig = (docs / "figures" / report_grid.RULE_FIGURE).read_text(encoding="utf-8")
    assert fig.count(r"\node[anchor=east") == 6
    assert "rule-based" in fig
    assert not (docs / "figures" / report_grid.HUMAN_FIGURE).exists()
    rows = (runs / run_ids["r0_v0"] / report_grid.CANDIDATES_FILE).read_text().splitlines()
    assert rows[0] == "cell,question_id,error_type,detail"
    assert len(rows) == 1 + 3 + 3 + 2  # header + R0's three cells


def test_human_label_error_types(setup, tmp_path: Path) -> None:
    from finqa.eval.annotation import cell_run_id
    from finqa.schemas import Annotation

    runs, docs, questions, _, run_ids = setup
    r1 = run_ids["r1_v0"]
    labels = [
        Annotation(
            question_id="fb_synth_001",
            claim_id="c1",
            run_id=cell_run_id(r1, "grounded"),
            annotator="a+b",
            correct=True,
            error_type=None,
        ),
        Annotation(
            question_id="fb_synth_002",
            claim_id="c1",
            run_id=cell_run_id(r1, "grounded"),
            annotator="a+b",
            correct=False,
            error_type="wrong_period",
        ),
        Annotation(
            question_id="fb_synth_003",
            claim_id="c1",
            run_id=cell_run_id(r1, "none"),
            annotator="adjudicated",
            correct=False,
            error_type="arithmetic",
        ),
    ]
    path = tmp_path / "final_labels.jsonl"
    path.write_text("".join(a.model_dump_json() + "\n" for a in labels), encoding="utf-8")
    assert make_report(runs, docs, questions, labels=path) == 0
    out = (docs / report_grid.RESULTS_FILE).read_text(encoding="utf-8")
    assert "| R1-V2 | 2 | 1/2, 50.0% [" in out
    assert "| R1-V0 | 1 | 1/1, 100.0% [" in out
    assert "| R0-V0 | 0 | 0/0, n/a |" in out
    human = out.split("(b) Human labels", 1)[1]
    row = cell_row(human, "R1-V2", "incorrect claims |")
    assert row == "| R1-V2 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |"  # wrong_period first
    fig = (docs / "figures" / report_grid.HUMAN_FIGURE).read_text(encoding="utf-8")
    assert "{1 of 2 labelled}" in fig and "{0 of 0 labelled}" in fig


def write_labels(path: Path, labels) -> Path:
    path.write_text("".join(a.model_dump_json() + "\n" for a in labels), encoding="utf-8")
    return path


def label(run_id: str, arm: str, qid: str = "fb_synth_001", correct: bool = True, et=None):
    from finqa.eval.annotation import cell_run_id
    from finqa.schemas import Annotation

    return Annotation(
        question_id=qid,
        claim_id="c1",
        run_id=cell_run_id(run_id, arm),
        annotator="a+b",
        correct=correct,
        error_type=et,
    )


def test_labels_twice_in_a_cell_are_refused(setup, tmp_path: Path) -> None:
    runs, docs, questions, _, run_ids = setup
    one = label(run_ids["r1_v0"], "grounded")
    path = write_labels(tmp_path / "labels.jsonl", [one, one])
    with pytest.raises(runner.RunRefused, match="labelled twice"):
        make_report(runs, docs, questions, labels=path)


def test_bad_labels_are_refused_before_any_write(setup, tmp_path: Path) -> None:
    runs, docs, questions, _, run_ids = setup
    one = label(run_ids["r1_v0"], "grounded")
    path = write_labels(tmp_path / "labels.jsonl", [one, one])
    with pytest.raises(runner.RunRefused, match="labelled twice"):
        make_report(runs, docs, questions, labels=path)
    assert not list(runs.glob("*/scores_*.jsonl"))
    assert not list(runs.glob(f"*/{report_grid.CANDIDATES_FILE}"))


def test_an_unreadable_label_line_is_refused_and_the_file_kept(setup, tmp_path: Path) -> None:
    runs, docs, questions, _, run_ids = setup
    good = label(run_ids["r1_v0"], "grounded").model_dump_json()
    path = tmp_path / "final_labels.jsonl"
    text = good + "\n{not json\n" + good.replace("fb_synth_001", "fb_synth_003")  # no newline
    path.write_text(text, encoding="utf-8")
    with pytest.raises(runner.RunRefused, match="line 2 is not a valid label"):
        make_report(runs, docs, questions, labels=path)
    assert path.read_text(encoding="utf-8") == text


def test_labels_of_another_run_are_refused(setup, tmp_path: Path) -> None:
    runs, docs, questions, _, _ = setup
    path = write_labels(tmp_path / "f.jsonl", [label("2026-01-01_r1_v0_dev0000", "none")])
    with pytest.raises(runner.RunRefused, match="not one of the six grid cells"):
        make_report(runs, docs, questions, labels=path)


def test_incorrect_label_without_error_type_is_refused(setup, tmp_path: Path) -> None:
    runs, docs, questions, _, run_ids = setup
    path = write_labels(tmp_path / "f.jsonl", [label(run_ids["r0_v0"], "none", correct=False)])
    with pytest.raises(runner.RunRefused, match="no error type"):
        make_report(runs, docs, questions, labels=path)


def test_missing_labels_are_refused_before_anything_is_written(setup, tmp_path: Path) -> None:
    runs, docs, questions, _, run_ids = setup
    with pytest.raises(runner.RunRefused, match="no final labels"):
        make_report(runs, docs, questions, labels=tmp_path / "missing.jsonl")
    assert not list(runs.glob("*/scores_*.jsonl"))
    assert not (docs / report_grid.RESULTS_FILE).exists()


def test_failed_generations_are_not_classified(setup) -> None:
    from finqa.schemas import Claim, Draft, VerifiedResult

    def d(qid: str, error: str | None) -> Draft:
        claims = (
            []
            if error
            else [
                Claim(
                    claim_id="c1", metric="m", value=7.0, unit="USD", period="FY2022", chunk_ids=[]
                )
            ]
        )
        return Draft(
            question_id=qid,
            retrieval_arm="rag",
            answer_text="7",
            claims=claims,
            answer_claim_id=None if error else "c1",
            evidence={},
            trace_id="t",
            latency_s=0.0,
            tokens_in=0,
            tokens_out=0,
            error=error,
        )

    def v(draft: Draft) -> VerifiedResult:
        return VerifiedResult(
            question_id=draft.question_id,
            retrieval_arm="rag",
            verification_arm="none",
            claims_before=draft.claims,
            claims_after=draft.claims,
            verdicts=[],
            revisions_used=0,
            flagged_claim_ids=[],
            latency_s=0.0,
            tokens_in=0,
            tokens_out=0,
        )

    drafts = [d("fb_synth_001", None), d("fb_synth_003", "model error")]
    rows = [tables_row("fb_synth_001"), tables_row("fb_synth_003")]
    questions = setup[2]
    out = report_grid.rule_diagnoses(
        drafts,
        [v(x) for x in drafts],
        questions,
        GOLD,
        rows,
        {},
        0.01,
        lambda q: (None, None),
        [],
        [],
        None,
    )
    assert [x.question_id for x in out] == ["fb_synth_001"]


def test_stacked_tikz_scales_the_longest_bar_to_8cm() -> None:
    from collections import Counter

    from finqa.schemas import ErrorType

    counts = {label: Counter() for label in grid.CELLS}
    counts["R0-V0"] = Counter({ErrorType.WRONG_PERIOD: 3, ErrorType.ARITHMETIC: 1})  # total 4
    counts["R1-V2"] = Counter({ErrorType.OTHER: 2})
    tex = report_grid.stacked_tikz(counts, "test")
    # R0-V0 (row 0): 3/4 of 8 cm, then 1/4; R1-V2 (row 5): 2/4 of 8 cm
    assert r"\fill[et0] (0.000,-0.30) rectangle (6.000,0.30);" in tex
    assert r"\fill[et3] (6.000,-0.30) rectangle (8.000,0.30);" in tex
    assert r"\fill[et6] (0.000,-5.30) rectangle (4.000,-4.70);" in tex
    for t in ErrorType:
        assert t.value.replace("_", r"\_") in tex
    assert tex.rstrip().endswith(r"\end{tikzpicture}")


def test_report_all_runs_every_report_and_lists_refusals(setup, capsys) -> None:
    runs, docs, questions, _, _ = setup
    assert make_report(runs, docs, questions, milestone="all") == 2  # no m1 or p3 runs here
    printed = capsys.readouterr().err
    assert "refused: m1:" in printed and "refused: p3:" in printed
    assert "refused: grid" not in printed
    assert (docs / report_grid.RESULTS_FILE).exists()
    assert not (docs / "RESULTS.md").exists() and not (docs / "RESULTS_P3.md").exists()


def test_report_all_refuses_a_subset_scope(setup) -> None:
    runs, docs, questions, _, _ = setup
    with pytest.raises(runner.RunRefused, match="for --milestone m1 only"):
        report.report_command("all", "subset", runs_dir=runs, docs_dir=docs, questions=questions)


def test_cli_report_defaults_to_all_and_takes_labels() -> None:
    args = build_parser().parse_args(["report"])
    assert args.milestone == "all" and args.labels is None
    args = build_parser().parse_args(["report", "--milestone", "grid", "--labels", "x.jsonl"])
    assert args.labels == Path("x.jsonl")


def tables_row(qid: str):
    from finqa.eval import tables

    return tables.Row(
        question_id=qid,
        question_type="single_fact",
        outcome="incorrect",
        method="numeric",
        reason="",
        latency_s=0.0,
        tokens_in=0,
        tokens_out=0,
        failed=False,
    )
