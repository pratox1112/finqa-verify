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

import csv
import io
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from finqa.config import Config
from finqa.eval import error_types, grid, stats, tables
from finqa.eval import report as m1
from finqa.eval.runner import RunRefused, read_jsonl
from finqa.eval.scoring import Gold, Judge, load_gold
from finqa.generators.base import Question
from finqa.schemas import Annotation, Draft, ErrorType, VerifiedResult

RESULTS_FILE = "RESULTS_GRID.md"
RULE_FIGURE = "grid_error_types.tex"
HUMAN_FIGURE = "grid_error_types_human.tex"
# per draft run: one row per wrong answer (P9.7); names cells and error types, so annotators
# must not open it while labelling (like annotation.KEY_FILE)
CANDIDATES_FILE = "grid_error_types_do_not_open_while_labelling.csv"
# one color per error type, in ErrorType order (TikZ, xcolor HTML)
BAR_CM = 8.0
PALETTE = ("4C78A8", "F58518", "54A24B", "E45756", "72B7B2", "B279A2", "9D9D9D")
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


# ---------------------------------------------------------------- P9.2 error types per cell


def rule_diagnoses(
    drafts: Sequence[Draft],
    verified: Sequence[VerifiedResult],
    questions: dict[str, Question],
    gold: dict[str, Gold],
    rows: Sequence[tables.Row],
    found: dict[str, bool],
    tolerance: float,
    locate: m1.Locate,
    metrics: Sequence[str],
    ciks: Sequence[str],
    lookup: error_types.Lookup | None,
) -> list[error_types.Diagnosis]:
    """The rule-based error type (P2.5) of every answer of one cell scored incorrect, read on
    the claims after verification (a revised claim keeps its ID, so the answer claim is the
    same). Refusals and failed generations (no claims to classify) are counted apart."""
    after = {v.question_id: v.claims_after for v in verified}
    revised = [d.model_copy(update={"claims": after[d.question_id]}) for d in drafts]
    failed = {d.question_id for d in drafts if d.error is not None}
    answered = [r for r in rows if r.question_id not in failed]
    return m1.classify_errors(
        revised, questions, gold, answered, found, tolerance, locate, metrics, ciks, lookup
    )


def read_labels(path: Path) -> list[Annotation]:
    """Every label in a final_labels.jsonl, read strictly: an unreadable line refuses the
    file (runner.read_jsonl would cut it off and truncate the file; a report never changes
    its inputs)."""
    if not path.exists():
        raise RunRefused(f"no final labels at {path}")
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(Annotation.model_validate_json(line))
        except ValueError as e:
            raise RunRefused(f"{path.name} line {n} is not a valid label: {e}") from e
    return out


def human_counts(
    annotations: Sequence[Annotation], run_ids: Mapping[str, str]
) -> dict[str, tuple[int, Counter[ErrorType]]]:
    """Per cell: (claims with a final human label, error types of those labelled incorrect).
    Final labels come from Phase 5 (`final_labels.jsonl`, one label per claim and cell); their
    `run_id` is "<draft run>:<verifier arm>" (finqa.eval.annotation.cell_run_id). Refuses a
    file that is not that: a claim labelled twice in one cell (per-annotator labels.jsonl), a
    label of a run that is not one of these six cells, or an incorrect label with no error
    type (the label reader never writes one)."""
    from finqa.eval.annotation import cell_run_id

    cell_of = {
        cell_run_id(run_ids[label.split("-")[0]], arm): label
        for label, (_, arm) in grid.CELLS.items()
    }
    seen: set[tuple[str, str, str]] = set()
    for a in annotations:
        if a.run_id not in cell_of:
            raise RunRefused(f"label of {a.run_id!r} is not one of the six grid cells")
        key = (a.run_id, a.question_id, a.claim_id)
        if key in seen:
            raise RunRefused(
                f"claim {a.claim_id} of {a.question_id} is labelled twice in {a.run_id}; "
                "pass final_labels.jsonl (one label per claim), not labels.jsonl"
            )
        seen.add(key)
        if not a.correct and a.error_type is None:
            raise RunRefused(f"incorrect label with no error type: {key}")
    out: dict[str, tuple[int, Counter[ErrorType]]] = {}
    for rid, label in cell_of.items():
        mine = [a for a in annotations if a.run_id == rid]
        out[label] = (
            len(mine),
            Counter(a.error_type for a in mine if not a.correct and a.error_type is not None),
        )
    return out


def error_type_table(counts: Mapping[str, Counter[ErrorType]], first: str) -> str:
    """Cells as rows, error types as columns, plus the total; `first` heads the total column."""
    lines = [
        "| Cell | " + " | ".join(t.value for t in ErrorType) + f" | {first} |",
        "|---|" + "---|" * (len(ErrorType) + 1),
    ]
    for label in grid.CELLS:
        c = counts[label]
        lines.append(
            f"| {label} | "
            + " | ".join(str(c.get(t, 0)) for t in ErrorType)
            + f" | {sum(c.values())} |"
        )
    return "\n".join(lines) + "\n"


def stacked_tikz(
    counts: Mapping[str, Counter[ErrorType]],
    source: str,
    ends: Mapping[str, str] | None = None,
) -> str:
    """Stacked horizontal bars, one per cell, one segment per error type, as TikZ (the report
    loads tikz and xcolor); `\\input` it inside a figure environment. The longest bar is
    BAR_CM, leaving room for the label after it within an article text width.
    `ends` replaces the count printed after each bar (e.g. "4 of 30 labelled").
    """
    top = max((sum(c.values()) for c in counts.values()), default=0) or 1
    unit = BAR_CM / top
    lines = [
        f"% Generated by `uv run finqa report --milestone grid` ({source}); do not edit by hand.",
        *(rf"\definecolor{{et{i}}}{{HTML}}{{{h}}}" for i, h in enumerate(PALETTE)),
        r"\begin{tikzpicture}[x=1cm, y=0.6cm]",
    ]
    for row, label in enumerate(grid.CELLS):
        y = -row
        lines.append(rf"\node[anchor=east, font=\small] at (0,{y}) {{{label}}};")
        x = 0.0
        for i, t in enumerate(ErrorType):
            n = counts[label].get(t, 0)
            if n:
                lines.append(
                    rf"\fill[et{i}] ({x:.3f},{y - 0.3:.2f}) rectangle ({x + n * unit:.3f},"
                    rf"{y + 0.3:.2f});"
                )
                x += n * unit
        end = ends[label] if ends else str(sum(counts[label].values()))
        lines.append(rf"\node[anchor=west, font=\small] at ({x:.3f},{y}) {{{end}}};")
    legend_y = -len(grid.CELLS) - 0.2
    for i, t in enumerate(ErrorType):
        lx = (i % 3) * 3.6
        ly = legend_y - (i // 3) * 0.7
        name = t.value.replace("_", r"\_")
        lines.append(
            rf"\fill[et{i}] ({lx:.2f},{ly - 0.2:.2f}) rectangle ({lx + 0.3:.2f},{ly + 0.2:.2f}); "
            rf"\node[anchor=west, font=\scriptsize] at ({lx + 0.35:.2f},{ly:.2f}) "
            rf"{{\texttt{{{name}}}}};"
        )
    return "\n".join([*lines, r"\end{tikzpicture}"]) + "\n"


def candidates_csv(diagnoses: Mapping[str, Sequence[error_types.Diagnosis]], r: str) -> str:
    """Every wrong answer of retrieval arm `r`'s three cells with its rule-based type, for
    picking the P9.7 examples (2-3 per error type, by a person)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["cell", "question_id", "error_type", "detail"])
    for label in grid.CELLS:
        if label.startswith(f"{r}-"):
            for d in diagnoses[label]:
                w.writerow([label, d.question_id, d.error_type.value, d.detail])
    return buf.getvalue()


def error_type_section(
    rule: Mapping[str, Sequence[error_types.Diagnosis]],
    rows: Mapping[str, Sequence[tables.Row]],
    human: Mapping[str, tuple[int, Counter[ErrorType]]] | None,
    gen_failed: Mapping[str, int],
) -> str:
    refused = {label: sum(r.outcome == "refused" for r in rows[label]) for label in grid.CELLS}
    rule_counts = {label: Counter(d.error_type for d in rule[label]) for label in grid.CELLS}
    parts = [
        "## Figure G-1: error types per cell\n",
        "**(a) Rule-based, every answer scored incorrect.** The rule classifier (P2.5, "
        "`docs/LABELING_PROTOCOL.md`) on each answer scored incorrect, read on the claims "
        "after verification. Refusals ("
        + ", ".join(f"{label} {refused[label]}" for label in grid.CELLS)
        + ") and failed generations, which have no claims to classify ("
        + ", ".join(f"{label} {gen_failed[label]}" for label in grid.CELLS)
        + f"), are counted apart. Figure: `docs/figures/{RULE_FIGURE}`.\n",
        error_type_table(rule_counts, "wrong answers"),
    ]
    if human is None:
        parts.append(
            "**(b) Human labels, sampled claims.** Pending: no Phase 5 final labels were "
            "given (`--labels`).\n"
        )
        return "\n".join(parts)
    parts += [
        "**(b) Human labels, sampled claims.** Final Phase 5 labels (P5.6) on the sampled "
        "claims (DECISIONS 2026-11-26): every labelled claim, not only answer claims, so the "
        "unit differs from (a). Cells have different numbers of labelled claims, so compare "
        "shares, not bar lengths; the figure prints k of n labelled after each bar. Share "
        "incorrect has a bootstrap 95% CI over labelled claims. "
        f"Figure: `docs/figures/{HUMAN_FIGURE}`.\n",
        "| Cell | Labelled claims | Labelled incorrect |",
        "|---|---|---|",
    ]
    for label in grid.CELLS:
        n, c = human[label]
        k = sum(c.values())
        parts.append(f"| {label} | {n} | {stats.rate(k, n)} |")
    parts += ["", error_type_table({k: v[1] for k, v in human.items()}, "incorrect claims")]
    return "\n".join(parts)


def results_markdown(
    rows: dict[str, list[tables.Row]],
    drafts: dict[str, list[Draft]],
    verified: dict[str, list[VerifiedResult]],
    run_ids: dict[str, str],
    commit: str,
    cfg: Config,
    errors: str = "",
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
    if errors:
        parts.append(errors)
    return "\n".join(parts)


def report_grid(
    runs_dir: Path,
    docs_dir: Path,
    questions: dict[str, Question],
    gold: dict[str, Gold] | None,
    make_judge: Callable[[Config, str], Judge],
    locate: m1.Locate | None = None,
    lookup: error_types.Lookup | None = error_types.xbrl_lookup,
    data_dir: Path = m1.DATA_DIR,
    labels: Path | None = None,
) -> int:
    """Score the six cells and write the grid results, the two error-type figures (P9.2) and
    the per-run list of wrong answers for picking examples (P9.7). `labels` is Phase 5's
    `final_labels.jsonl`; without it the human-label figure is marked pending."""
    gold = gold or load_gold()
    annotations = read_labels(labels) if labels is not None else None
    found, drafts, verified, commit = load_cells(runs_dir, questions)
    run_ids = {r: found[r][0].name for r in RETRIEVAL}
    # validated before anything is written
    human = human_counts(annotations, run_ids) if annotations is not None else None
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

    metrics: list[str] = []
    ciks: list[str] = []
    if lookup is not None:
        from finqa.ingestion.xbrl import load_metric_map

        metrics = list(load_metric_map())
        ciks = [c["cik"] for c in m1._csv(data_dir / "companies.csv")]
    locate = locate or m1.default_locate()
    rule: dict[str, list[error_types.Diagnosis]] = {}
    for r in RETRIEVAL:
        r_cfg = Config.model_validate(found[r][1]["config"])
        _, retrieved = m1.retrieval_section(drafts[r], questions, rows[f"{r}-V0"], r_cfg)
        for label in grid.CELLS:
            if label.startswith(f"{r}-"):
                rule[label] = rule_diagnoses(
                    drafts[r],
                    verified[label],
                    questions,
                    gold,
                    rows[label],
                    retrieved,
                    r_cfg.verification.tolerance,
                    locate,
                    metrics,
                    ciks,
                    lookup,
                )
        (found[r][0] / CANDIDATES_FILE).write_text(candidates_csv(rule, r), encoding="utf-8")

    docs_dir.mkdir(parents=True, exist_ok=True)
    figures = docs_dir / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    rule_counts = {label: Counter(d.error_type for d in rule[label]) for label in grid.CELLS}
    (figures / RULE_FIGURE).write_text(stacked_tikz(rule_counts, "rule-based"), encoding="utf-8")
    if human is not None:
        human_fig = {label: c for label, (_, c) in human.items()}
        ends = {label: f"{sum(c.values())} of {n} labelled" for label, (n, c) in human.items()}
        (figures / HUMAN_FIGURE).write_text(
            stacked_tikz(human_fig, "human labels", ends), encoding="utf-8"
        )
    path = docs_dir / RESULTS_FILE
    gen_failed = {
        label: sum(d.error is not None for d in drafts[label.split("-")[0]]) for label in grid.CELLS
    }
    errors = error_type_section(rule, rows, human, gen_failed)
    path.write_text(
        results_markdown(rows, drafts, verified, run_ids, commit, cfg, errors), encoding="utf-8"
    )
    print(f"grid report: {len(questions)} questions x {len(rows)} cells -> {path}")
    return 0
