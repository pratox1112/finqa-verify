"""Phase 3 report: the retrieval x calculator 2 x 2 on the test split (ROADMAP P3.8, P3.9).

    uv run finqa report --milestone p3

Reads the newest full test-split run of each arm in runs/ (run_meta.json: split "test", subset
null), checks that all four come from one clean commit on main and cover the same questions,
scores them against gold (finqa.eval.scoring; text answers through each run's own model as
judge, whose calls are cached) and writes:

  docs/RESULTS_P3.md          Table P3-A (the 2 x 2), Table P3-B (the four effects, paired),
                              Table P3-C (accuracy by question type, per arm),
                              Table P3-D (efficiency per question) and
                              Table P3-E (errata sensitivity: P3-A and P3-B with the corrected
                              golds of data/gold_errata.csv; DECISIONS 2026-11-22)
  runs/{run_id}/scores.jsonl  one scored row per question, per run

The arms (configs; docs/DECISIONS.md 2026-11-22):
  R0       configs/grid/r0_v0.yaml               single-shot retrieval, no calculator
  R0+calc  configs/ablations/r0_calc_v0.yaml     single-shot retrieval, calculator
  R1-calc  configs/ablations/r1_nocalc_v0.yaml   agent, no calculator
  R1       configs/grid/r1_v0.yaml               agent, calculator

Correctness comes only from finqa.eval.scoring against FinanceBench gold (ROADMAP rule 10).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path

from finqa.config import Config
from finqa.eval import stats, tables
from finqa.eval.runner import RunRefused, read_jsonl
from finqa.eval.scoring import Gold, Judge, load_errata, load_gold, with_errata
from finqa.generators.base import Question
from finqa.schemas import Draft

# label -> config name, in table order
ARMS: dict[str, str] = {
    "R0": "r0_v0",
    "R0+calc": "r0_calc_v0",
    "R1−calc": "r1_nocalc_v0",
    "R1": "r1_v0",
}
# (effect, arm without the factor, arm with it)
EFFECTS: list[tuple[str, str, str]] = [
    ("Calculator, single-shot retrieval", "R0", "R0+calc"),
    ("Calculator, agent", "R1−calc", "R1"),
    ("Agent retrieval, no calculator", "R0", "R1−calc"),
    ("Agent retrieval, with calculator", "R0+calc", "R1"),
    ("Agent with calculator vs single-shot without (R1 vs R0)", "R0", "R1"),
]
RESULTS_FILE = "RESULTS_P3.md"


def find_full_test_run(runs_dir: Path, config_name: str) -> tuple[Path, dict]:
    """The newest full test-split run of `config_name` (run IDs start with the date)."""
    matches = []
    for meta_path in sorted(runs_dir.glob("*/run_meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if (meta["config_name"], meta["split"], meta.get("subset")) == (config_name, "test", None):
            matches.append((meta_path.parent, meta))
    if not matches:
        raise RunRefused(f"no full test-split run of {config_name} in {runs_dir}")
    return matches[-1]


def check_runs(metas: dict[str, dict]) -> str:
    """The commit all four runs share; refuses runs from different commits, a branch other
    than main or a dirty tree (the runner refuses those for test runs too)."""
    commits = {label: m["git_commit"] for label, m in metas.items()}
    if len(set(commits.values())) != 1:
        listed = ", ".join(f"{label} {c[:7]}" for label, c in commits.items())
        raise RunRefused(f"the four arms come from different commits ({listed}); rerun them")
    for label, m in metas.items():
        if m["git_branch"] != "main" or m["git_dirty"]:
            raise RunRefused(f"{label} was not run from a clean main")
    return next(iter(commits.values()))


def _correct(rows: Sequence[tables.Row]) -> dict[str, bool]:
    return {r.question_id: r.outcome == "correct" for r in rows}


def _cell(rows: Sequence[tables.Row]) -> str:
    correct = [r.outcome == "correct" for r in rows]
    return stats.rate(sum(correct), len(correct), correct)


def grid_table(rows: dict[str, list[tables.Row]]) -> str:
    return (
        "\n".join(
            [
                "| Retrieval | No calculator | Calculator |",
                "|---|---|---|",
                f"| Single-shot | R0: {_cell(rows['R0'])} | R0+calc: {_cell(rows['R0+calc'])} |",
                f"| Agent | R1−calc: {_cell(rows['R1−calc'])} | R1: {_cell(rows['R1'])} |",
            ]
        )
        + "\n"
    )


def effects_table(rows: dict[str, list[tables.Row]]) -> str:
    lines = [
        "| Effect | A → B | n | A correct | B correct | Difference B − A, pp [95% CI] "
        "| A only | B only | McNemar exact p |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for effect, a_label, b_label in EFFECTS:
        a, b = _correct(rows[a_label]), _correct(rows[b_label])
        ids = sorted(a)
        xa, xb = [a[q] for q in ids], [b[q] for q in ids]
        m = stats.mcnemar(xa, xb)
        ci = stats.paired_diff_ci(xa, xb)
        assert ci is not None
        diff = 100 * (sum(xb) - sum(xa)) / len(ids)
        lines.append(
            f"| {effect} | {a_label} → {b_label} | {m.n} | {sum(xa)} | {sum(xb)} "
            f"| {diff:+.1f} [{100 * ci[0]:+.1f}, {100 * ci[1]:+.1f}] "
            f"| {m.only_a} | {m.only_b} | {m.p_value:.4f} |"
        )
    return "\n".join(lines) + "\n"


def _changed(a: Sequence[tables.Row], b: Sequence[tables.Row]) -> int:
    return sum(x.outcome != y.outcome for x, y in zip(a, b, strict=True))


def errata_section(
    rows: dict[str, list[tables.Row]],
    errata_rows: dict[str, list[tables.Row]],
    corrected: list[str],
) -> str:
    parts = ["## Table P3-E: errata sensitivity\n"]
    if not corrected:
        parts.append("No corrected gold (`data/gold_errata.csv`) falls in these questions.\n")
        return "\n".join(parts)
    changed = ", ".join(f"{label} {_changed(rows[label], errata_rows[label])}" for label in ARMS)
    parts += [
        "The same answers scored against the corrected golds of `data/gold_errata.csv` "
        "(DECISIONS 2026-11-22: two AI agent annotators, human sign-off). Strict scoring "
        "above stays primary. Corrected golds in these questions: "
        + ", ".join(f"`{q}`" for q in corrected)
        + f". Outcomes that change, per arm: {changed}.\n",
        grid_table(errata_rows),
        effects_table(errata_rows),
    ]
    return "\n".join(parts)


def results_markdown(
    rows: dict[str, list[tables.Row]],
    run_ids: dict[str, str],
    commit: str,
    cfg: Config,
    errata_rows: dict[str, list[tables.Row]] | None = None,
    corrected: list[str] | None = None,
) -> str:
    n = len(rows["R1"])
    runs = ", ".join(f"{label} `{run_ids[label]}`" for label in ARMS)
    parts = [
        "# Phase 3 results: retrieval × calculator\n",
        "Generated by `uv run finqa report --milestone p3`; do not edit by hand. "
        f"Runs: {runs}, all from commit `{commit[:7]}` on main. Model `{cfg.model.id}`, "
        f"thinking `{cfg.model.thinking}`, temperature {cfg.model.temperature}. "
        f"All {n} test questions (`data/splits.json`), no verification (V0). Strict scoring "
        "against FinanceBench gold; a failed generation scores incorrect. Bootstrap 95% CIs "
        "over questions.\n",
        "## Table P3-A: accuracy, retrieval × calculator\n",
        grid_table(rows),
        "## Table P3-B: effects (paired, same questions)\n",
        "Each row compares two arms that differ in one factor (the last row in both). The "
        "difference CI is a paired bootstrap over questions; the McNemar test uses the "
        "questions only one arm got right.\n",
        effects_table(rows),
        "## Table P3-C: accuracy by question type\n",
        *(
            tables.accuracy_table(rows[label], f"{label} (`{run_ids[label]}`, n={n})")
            for label in ARMS
        ),
        "## Table P3-D: efficiency per question\n",
        tables.efficiency_table([(label, rows[label]) for label in ARMS]),
    ]
    if errata_rows is not None:
        parts.append(errata_section(rows, errata_rows, corrected or []))
    return "\n".join(parts)


def report_p3(
    runs_dir: Path,
    docs_dir: Path,
    questions: dict[str, Question],
    gold: dict[str, Gold] | None,
    make_judge: Callable[[Config, str], Judge],
    errata: dict[str, dict[str, str]] | None = None,
) -> int:
    gold = gold or load_gold()
    errata = load_errata() if errata is None else errata
    corrected = sorted(q for q in errata if q in questions)
    errata_gold = with_errata(gold, {q: errata[q] for q in corrected})
    found = {label: find_full_test_run(runs_dir, name) for label, name in ARMS.items()}
    commit = check_runs({label: meta for label, (_, meta) in found.items()})
    rows: dict[str, list[tables.Row]] = {}
    errata_rows: dict[str, list[tables.Row]] = {}
    cfg: Config | None = None
    for label, (run_dir, meta) in found.items():
        cfg = Config.model_validate(meta["config"])
        drafts = read_jsonl(run_dir / "drafts.jsonl", Draft)
        judge = make_judge(cfg, run_dir.name)
        rows[label] = tables.score_run(drafts, questions, gold, cfg.verification.tolerance, judge)
        tables.write_rows(rows[label], run_dir / "scores.jsonl")
        # only the corrected questions are scored again
        rescored = {
            r.question_id: r
            for r in tables.score_run(
                [d for d in drafts if d.question_id in errata_gold and d.question_id in corrected],
                questions,
                errata_gold,
                cfg.verification.tolerance,
                judge,
            )
        }
        errata_rows[label] = [rescored.get(r.question_id, r) for r in rows[label]]
    ids = {label: {r.question_id for r in r_} for label, r_ in rows.items()}
    if any(s != set(questions) for s in ids.values()):
        short = ", ".join(f"{label} {len(s)}" for label, s in ids.items())
        raise RunRefused(
            f"the arms do not all cover the {len(questions)} test questions ({short}); "
            "finish the runs first"
        )
    assert cfg is not None
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / RESULTS_FILE
    run_ids = {label: run_dir.name for label, (run_dir, _) in found.items()}
    path.write_text(
        results_markdown(rows, run_ids, commit, cfg, errata_rows, corrected), encoding="utf-8"
    )
    print(f"P3 report: {len(questions)} questions per arm -> {path}")
    return 0
