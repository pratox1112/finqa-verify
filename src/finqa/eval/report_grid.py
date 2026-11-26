"""Grid report: retrieval (R0, R1) x verification (V0, V1, V2) on the test split.

    uv run finqa report --milestone grid

Reads the newest full test-split draft run of R0 (configs/grid/r0_v0.yaml) and R1
(configs/grid/r1_v0.yaml) in runs/, and in each the three verified files the verify stage
writes there (verified_none.jsonl, verified_self_check.jsonl, verified_grounded.jsonl; ROADMAP
P4.8). Refuses draft runs from different commits, a branch other than main or a dirty tree, and
any cell that does not cover every test question. Scores every cell against gold
(finqa.eval.scoring; text answers through the run's own model as judge, whose calls are cached)
and writes:

  docs/RESULTS_GRID.md               Table G-A (accuracy per cell), G-B (the 9 planned paired
                                     tests, Holm-corrected; P9.3), G-C (flip matrices, V1 and
                                     V2; P9.5), G-D (V2 coverage; P8.1), G-E (cost and latency
                                     per cell; P9.6). Every rate has a bootstrap 95% CI (P9.4).
  runs/{run_id}/scores_{arm}.jsonl   one scored row per question, per cell

Strict scoring against FinanceBench gold only (ROADMAP rule 10); the analysis functions are in
finqa.eval.grid, the design in docs/DECISIONS.md 2026-11-25.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from finqa.config import Config
from finqa.eval import grid, stats, tables
from finqa.eval.runner import RunRefused, read_jsonl
from finqa.eval.scoring import Gold, Judge, load_gold
from finqa.generators.base import Question
from finqa.schemas import Draft, VerifiedResult

RESULTS_FILE = "RESULTS_GRID.md"
RETRIEVAL = ("R0", "R1")


def find_newest_full_test_run(runs_dir: Path, config_name: str) -> tuple[Path, dict]:
    """The full test-split run of `config_name` that started last (run_meta.json "started").
    Run IDs sort by date then commit hash, so two runs on one day would sort by hash."""
    matches = []
    for meta_path in runs_dir.glob("*/run_meta.json"):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if (meta["config_name"], meta["split"], meta.get("subset")) == (config_name, "test", None):
            matches.append((meta["started"], meta_path.parent, meta))
    if not matches:
        raise RunRefused(f"no full test-split run of {config_name} in {runs_dir}")
    _, run_dir, meta = max(matches, key=lambda m: (m[0], m[1].name))  # ties: by run ID
    return run_dir, meta


def check_draft_runs(metas: dict[str, dict]) -> str:
    """The commit both draft runs share; refuses different commits or a run not from a clean
    main (the runner refuses those for test runs too)."""
    commits = {label: m["git_commit"] for label, m in metas.items()}
    if len(set(commits.values())) != 1:
        listed = ", ".join(f"{label} {c[:7]}" for label, c in commits.items())
        raise RunRefused(f"the R0 and R1 drafts come from different commits ({listed})")
    for label, m in metas.items():
        if m["git_branch"] != "main" or m["git_dirty"]:
            raise RunRefused(f"{label} drafts were not run from a clean main")
    return next(iter(commits.values()))


def load_cells(
    runs_dir: Path, questions: dict[str, Question]
) -> tuple[
    dict[str, tuple[Path, dict]], dict[str, list[Draft]], dict[str, list[VerifiedResult]], str
]:
    """Draft runs, drafts per retrieval arm and verified results per cell, all checked."""
    found: dict[str, tuple[Path, dict]] = {}
    for r in RETRIEVAL:
        config_name = grid.CELLS[f"{r}-V0"][0]
        found[r] = find_newest_full_test_run(runs_dir, config_name)
    commit = check_draft_runs({r: meta for r, (_, meta) in found.items()})
    drafts: dict[str, list[Draft]] = {}
    verified: dict[str, list[VerifiedResult]] = {}
    want = set(questions)
    for label, (_, arm) in grid.CELLS.items():
        r = label.split("-")[0]
        run_dir = found[r][0]
        if r not in drafts:
            drafts[r] = read_jsonl(run_dir / "drafts.jsonl", Draft)
            ids = [d.question_id for d in drafts[r]]
            if set(ids) != want or len(ids) != len(want):
                raise RunRefused(f"{r} drafts do not cover the {len(want)} test questions")
        verified[label] = read_jsonl(run_dir / f"verified_{arm}.jsonl", VerifiedResult)
        got_ids = [v.question_id for v in verified[label]]
        got = set(got_ids)
        if len(got_ids) != len(got):
            raise RunRefused(f"{label}: verified_{arm}.jsonl repeats a question")
        if got != want:
            raise RunRefused(
                f"{label} covers {len(got & want)} of the {len(want)} test questions "
                f"(verified_{arm}.jsonl in {run_dir.name}); finish the verify run first"
            )
    return found, drafts, verified, commit


def outcomes_table(
    rows: Mapping[str, Sequence[tables.Row]],
    drafts: Mapping[str, Sequence[Draft]],
    verified: Mapping[str, Sequence[VerifiedResult]],
) -> str:
    """Per cell: accuracy, refusals, selective accuracy (accuracy on answered questions) and
    failure counts. A failed generation scores incorrect; a failed verification keeps the
    draft unchanged, so it is scored as its draft (runner.failed_verification)."""
    lines = [
        "| Cell | Accuracy | Refused | Selective accuracy | Generation failed "
        "| Verification failed |",
        "|---|---|---|---|---|---|",
    ]
    for label in grid.CELLS:
        group = rows[label]
        correct = [r.outcome == "correct" for r in group]
        refused = [r.outcome == "refused" for r in group]
        answered = [r.outcome == "correct" for r in group if r.outcome != "refused"]
        r_arm = label.split("-")[0]
        gen_failed = sum(d.error is not None for d in drafts[r_arm])
        ver_failed = sum(v.error is not None for v in verified[label])
        lines.append(
            f"| {label} | {stats.rate(sum(correct), len(group), correct)} "
            f"| {stats.rate(sum(refused), len(group), refused)} "
            f"| {stats.rate(sum(answered), len(answered), answered)} "
            f"| {gen_failed} | {ver_failed} |"
        )
    return "\n".join(lines) + "\n"


def results_markdown(
    rows: dict[str, list[tables.Row]],
    drafts: dict[str, list[Draft]],
    verified: dict[str, list[VerifiedResult]],
    run_ids: dict[str, str],
    commit: str,
    cfg: Config,
) -> str:
    n = len(rows["R1-V0"])
    runs = ", ".join(f"{r} `{run_ids[r]}`" for r in RETRIEVAL)
    parts = [
        "# Grid results: retrieval × verification\n",
        "Generated by `uv run finqa report --milestone grid`; do not edit by hand. "
        f"Draft runs: {runs}, both from commit `{commit[:7]}` on main; each verifier ran over "
        "those saved drafts. The verify stage records no commit of its own in the run folder; "
        "the verify job and its commit are in PROGRESS.md (P4.8). "
        f"Model `{cfg.model.id}`, thinking `{cfg.model.thinking}`, "
        f"temperature {cfg.model.temperature}. All {n} test questions (`data/splits.json`). "
        "Strict scoring against FinanceBench gold; a failed generation scores incorrect, a "
        "failed verification is scored as its unchanged draft (counts in Table G-A). Bootstrap "
        "95% CIs over questions. Design: docs/DECISIONS.md 2026-11-25.\n",
        "## Table G-A: accuracy per cell\n",
        grid.grid_table(rows),
        "\n",
        outcomes_table(rows, drafts, verified),
        "## Table G-B: planned paired tests (Holm-corrected)\n",
        "McNemar's exact test on the questions only one cell got right, Holm step-down over "
        "the 9 planned pairs; the difference CI is a paired bootstrap over questions.\n",
        grid.paired_tests_table(rows),
        "## Table G-C: flip matrices (before vs after verification)\n",
    ]
    for r in RETRIEVAL:
        for v in ("V1", "V2"):
            parts.append(grid.flip_table(rows[f"{r}-V0"], rows[f"{r}-{v}"], f"{r}: V0 → {v}"))
    parts.append("## Table G-D: V2 verification coverage\n")
    parts.append(
        "Which claims V2's three checks could compare against evidence (round 1: the draft's "
        "own claims). A claim is checkable when at least one check compared it. Accuracy is "
        "against gold, never V2's verdicts.\n"
    )
    for r in RETRIEVAL:
        label = f"{r}-V2"
        parts.append(
            grid.coverage_section(label, verified[label], drafts[r], rows[f"{r}-V0"], rows[label])
        )
    parts += [
        "## Table G-E: cost and latency per cell (draft plus verification)\n",
        grid.cost_table(rows),
    ]
    return "\n".join(parts)


def report_grid(
    runs_dir: Path,
    docs_dir: Path,
    questions: dict[str, Question],
    gold: dict[str, Gold] | None,
    make_judge: Callable[[Config, str], Judge],
) -> int:
    gold = gold or load_gold()
    found, drafts, verified, commit = load_cells(runs_dir, questions)
    rows: dict[str, list[tables.Row]] = {}
    cfg: Config | None = None
    for label, (_, arm) in grid.CELLS.items():
        r = label.split("-")[0]
        run_dir, meta = found[r]
        cfg = Config.model_validate(meta["config"])
        judge = make_judge(cfg, run_dir.name)
        rows[label] = tables.score_run(
            drafts[r], questions, gold, cfg.verification.tolerance, judge, verified=verified[label]
        )
        tables.write_rows(rows[label], run_dir / f"scores_{arm}.jsonl")
    assert cfg is not None
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / RESULTS_FILE
    run_ids = {r: found[r][0].name for r in RETRIEVAL}
    path.write_text(
        results_markdown(rows, drafts, verified, run_ids, commit, cfg), encoding="utf-8"
    )
    print(f"grid report: {len(questions)} questions x {len(rows)} cells -> {path}")
    return 0
