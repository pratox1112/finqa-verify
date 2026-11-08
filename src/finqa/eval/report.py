"""Midterm report: every M1 table and figure from saved runs (ROADMAP M1.3-M1.7, M1.9).

    uv run finqa report --milestone m1                   # full test split (default)
    uv run finqa report --milestone m1 --scope subset    # the 40-question midterm subset

Reads the newest S0 and R0 test-split runs of the chosen scope in runs/ (run_meta.json: split
"test"; subset null for the full split, "midterm_subset.json" for the subset), scores them
against gold (finqa.eval.scoring; text answers through each run's own model as judge, whose
calls are cached) and writes (the subset scope adds "_midterm_subset" to the docs file names):

  docs/RESULTS.md                        Tables M1-A (accuracy, efficiency, S0 vs R0),
                                         M1-B (retrieval diagnostic), M1-C (pipeline and model
                                         reliability), the R0 error breakdown and the
                                         contamination check
  docs/figures/m1_error_types.tex        Figure M1-1, a plain-LaTeX bar chart for the report
  runs/{run_id}/scores.jsonl             one scored row per question, per run
  runs/{R0 run_id}/error_spotcheck.csv   the classified R0 errors, for the human spot-check

Nothing here decides correctness except finqa.eval.scoring; the retrieval diagnostic and the
error classifier only describe answers already scored (ROADMAP rule 10).
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path

from finqa.config import Config
from finqa.eval import error_types, retrieval_diag, stats, tables
from finqa.eval.questions import load_questions
from finqa.eval.runner import RUNS_DIR, RunRefused, read_jsonl
from finqa.eval.scoring import Gold, Judge, load_gold
from finqa.generators.base import Question
from finqa.schemas import Draft, ErrorType

REPO_ROOT = RUNS_DIR.parent
DOCS_DIR = REPO_ROOT / "docs"
DATA_DIR = REPO_ROOT / "data"
PILOT_PATH = DOCS_DIR / "PILOT.md"
SUBSET = "midterm_subset.json"
SCOPES: dict[str, str | None] = {"full": None, "subset": SUBSET}  # --scope -> meta "subset"
S0, R0 = "s0_closed_book", "r0_v0"

# question_id -> (cik, 10-K fiscal year or None) for the classifier's XBRL rules
Locate = Callable[[Question], tuple[str | None, int | None]]


# --- Runs ------------------------------------------------------------------------------------


def find_run(runs_dir: Path, config_name: str, subset: str | None = None) -> Path:
    """The newest test-split run of `config_name` on `subset` (None = the full test split;
    run IDs start with the date)."""
    matches = []
    for meta_path in sorted(runs_dir.glob("*/run_meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if (meta["config_name"], meta["split"], meta.get("subset")) == (
            config_name,
            "test",
            subset,
        ):
            matches.append(meta_path.parent)
    if not matches:
        where = subset or "the full test split"
        raise RunRefused(f"no test run of {config_name} on {where} in {runs_dir}")
    return matches[-1]


def run_config(run_dir: Path) -> Config:
    meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
    return Config.model_validate(meta["config"])


# --- Sections --------------------------------------------------------------------------------


def accuracy_section(rows: dict[str, list[tables.Row]], n: int, scope: str = "full") -> str:
    if scope == "subset":
        where = "test subset"
        about = (
            f"Stratified subset of {n} of the 107 test questions, fixed before any test run "
            "(`data/midterm_subset.json`, DECISIONS.md 2026-11-07)."
        )
    else:
        where = "test split"
        about = f"All {n} test questions (`data/splits.json`)."
    parts = [f"## Table M1-A: S0 vs R0 on the {where}\n"]
    parts.append(
        f"{about} Bootstrap 95% CIs over questions. Selective accuracy = correct / answered "
        "(refusals left out). Strict scoring against FinanceBench gold; a failed generation "
        "scores incorrect.\n"
    )
    parts.append(tables.accuracy_table(rows[S0], f"S0 closed-book ({where}, n={n})"))
    parts.append(tables.accuracy_table(rows[R0], f"R0 single-shot RAG ({where}, n={n})"))
    parts.append("**Efficiency per question**\n")
    parts.append(tables.efficiency_table([("S0", rows[S0]), ("R0", rows[R0])]))
    parts.append("**Paired comparison (same questions)**\n")
    parts.append(tables.comparison_table("S0", rows[S0], "R0", rows[R0]))
    return "\n".join(parts)


def contamination_section(rows: Sequence[tables.Row]) -> str:
    correct = [r.outcome == "correct" for r in rows]
    lines = [
        "## Contamination check (M1.6)\n",
        f"S0 answers without any retrieval: {stats.rate(sum(correct), len(rows), correct)} "
        "correct overall; by question type in Table M1-A. A closed-book model that answered "
        "many of these questions would suggest it memorized FinanceBench or the filings.",
    ]
    ci = stats.bootstrap_ci(correct)
    if ci is not None and ci[0] >= 0.3:
        lines.append(
            "\n**FLAG: closed-book accuracy is high (CI lower bound >= 30%); treat retrieval "
            "gains with caution.**"
        )
    return "\n".join(lines) + "\n"


def retrieval_section(
    drafts: Sequence[Draft], questions: dict[str, Question], rows: Sequence[tables.Row], cfg: Config
) -> tuple[str, dict[str, bool]]:
    d = cfg.diagnostics
    found: dict[str, bool] = {}
    for draft in drafts:
        gold = questions[draft.question_id].gold_evidence
        if draft.error is None and gold:
            diag = retrieval_diag.diagnose(
                draft, gold, d.evidence_shingle_size, d.evidence_overlap_threshold
            )
            found[draft.question_id] = diag.gold_evidence_retrieved
    outcome = {r.question_id: r.outcome == "correct" for r in rows}
    hit = [found[q] for q in found]
    when_hit = [outcome[q] for q in found if found[q]]
    when_miss = [outcome[q] for q in found if not found[q]]
    text = "\n".join(
        [
            "## Table M1-B: R0 retrieval diagnostic\n",
            "Gold evidence counts as retrieved when some retrieved chunk shares at least "
            f"{d.evidence_overlap_threshold:.0%} of the word {d.evidence_shingle_size}-grams of "
            "a FinanceBench gold evidence page (P2.6; read only for this diagnostic).\n",
            "| | Result |",
            "|---|---|",
            f"| Gold evidence retrieved | {stats.rate(sum(hit), len(hit), hit)} |",
            "| R0 accuracy when retrieved "
            f"| {stats.rate(sum(when_hit), len(when_hit), when_hit)} |",
            "| R0 accuracy when not retrieved "
            f"| {stats.rate(sum(when_miss), len(when_miss), when_miss)} |",
        ]
    )
    return text + "\n", found


def classify_errors(
    drafts: Sequence[Draft],
    questions: dict[str, Question],
    gold: dict[str, Gold],
    rows: Sequence[tables.Row],
    retrieved: dict[str, bool],
    tolerance: float,
    locate: Locate,
    metrics: Sequence[str],
    ciks: Sequence[str],
    lookup: error_types.Lookup | None,
) -> list[error_types.Diagnosis]:
    """One error type per R0 answer scored incorrect (refusals are counted separately)."""
    by_id = {d.question_id: d for d in drafts}
    out = []
    for r in rows:
        if r.outcome != "incorrect":
            continue
        d, q = by_id[r.question_id], questions[r.question_id]
        claim = next((c for c in d.claims if c.claim_id == d.answer_claim_id), None)
        cik, year = locate(q)
        out.append(
            error_types.classify(
                r.question_id,
                claim,
                d.claims,
                gold[r.question_id].value,
                tolerance,
                retrieved.get(r.question_id),
                cik=cik,
                fiscal_year=year,
                metrics=metrics,
                other_ciks=ciks,
                lookup=lookup,
            )
        )
    return out


def error_section(diagnoses: Sequence[error_types.Diagnosis], refused: int) -> str:
    counts = Counter(d.error_type for d in diagnoses)
    lines = [
        "## Figure M1-1: R0 error breakdown\n",
        f"Rule-based classifier (P2.5, `docs/LABELING_PROTOCOL.md`) on the {len(diagnoses)} "
        f"R0 answers scored incorrect; the {refused} refusals are a separate outcome. "
        "Figure: `docs/figures/m1_error_types.tex`.\n",
        "| Error type | Count |",
        "|---|---|",
    ]
    lines += [f"| {t.value} | {counts.get(t, 0)} |" for t in ErrorType]
    return "\n".join(lines) + "\n"


def figure_tex(diagnoses: Sequence[error_types.Diagnosis]) -> str:
    """Figure M1-1 as a horizontal bar chart in plain LaTeX (no packages); `\\input` it
    inside a figure environment. Bars are scaled so the longest is 0.6 of the line width."""
    counts = Counter(d.error_type for d in diagnoses)
    top = max(counts.values(), default=0) or 1
    lines = [
        "% Generated by `uv run finqa report --milestone m1`; do not edit by hand.",
        r"\begin{tabular}{@{}r@{\hspace{0.6em}}l@{}}",
    ]
    for t in ErrorType:
        name, n = t.value.replace("_", r"\_"), counts.get(t, 0)
        lines.append(rf"\texttt{{{name}}} & \rule{{{0.6 * n / top:.3f}\linewidth}}{{1.6ex}} {n} \\")
    return "\n".join([*lines, r"\end{tabular}"]) + "\n"


def spotcheck_csv(
    diagnoses: Sequence[error_types.Diagnosis], questions: dict[str, Question]
) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["question_id", "company", "doc_name", "error_type", "detail", "human_agrees"])
    for d in diagnoses:
        q = questions[d.question_id]
        w.writerow([d.question_id, q.company, q.doc_name, d.error_type.value, d.detail, ""])
    return buf.getvalue()


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def reliability_section(data_dir: Path = DATA_DIR, pilot_path: Path = PILOT_PATH) -> str:
    """Table M1-C from the Phase 0 and 1 outputs (no model calls)."""
    manifest = _csv(data_dir / "filings_manifest.csv")
    forms = Counter(r["form"] for r in manifest)
    chunks = _csv(data_dir / "chunk_stats.csv")
    parse = _csv(data_dir / "parse_stats.csv")

    def total(rows: list[dict[str, str]], col: str) -> int:
        return sum(int(r[col]) for r in rows)

    n_chunks = total(chunks, "text_chunks") + total(chunks, "table_chunks")
    tables_n, scaled = total(chunks, "tables"), total(chunks, "tables_with_scale")
    expected, fallback = total(parse, "sections_expected"), total(parse, "heading_fallback")
    qa = (data_dir / "QA_CHECKS.md").read_text(encoding="utf-8")
    qa_line = re.search(r"\*\*(\d+) 10-Ks:\*\* (\d+) pass, (\d+) warn, (\d+) flag", qa)
    pilot = pilot_path.read_text(encoding="utf-8")
    tool = re.search(r"\| Tool-call success \| ([^|]+) \|", pilot)
    valid = re.search(r"\| Structured-output validity \| ([^|]+) \|", pilot)
    rows = [
        ("Companies", f"{len({r['cik'] for r in manifest})}"),
        (
            "Filings indexed",
            f"{len(manifest)} ({forms.get('10-K', 0)} 10-K, {forms.get('10-Q', 0)} 10-Q)",
        ),
        ("Chunks", f"{n_chunks:,} ({total(chunks, 'table_chunks'):,} table chunks)"),
        ("Tables", f"{tables_n:,}"),
        ("Section parsing fallback rate", f"{fallback}/{expected} ({fallback / expected:.1%})"),
        (
            "Unit-scale detection rate (tables)",
            f"{scaled:,}/{tables_n:,} ({scaled / tables_n:.1%})",
        ),
        (
            "10-K quality checks",
            f"{qa_line.group(2)} pass, {qa_line.group(3)} warn, {qa_line.group(4)} flag "
            f"of {qa_line.group(1)}"
            if qa_line
            else "see data/QA_CHECKS.md",
        ),
        ("Scope", "127 of 150 FinanceBench questions (10-K and 10-Q only; data/SCOPE.md)"),
        ("Model pilot: tool-call success", tool.group(1).strip() if tool else "see PILOT.md"),
        (
            "Model pilot: structured-output validity",
            valid.group(1).strip() if valid else "see PILOT.md",
        ),
    ]
    lines = ["## Table M1-C: pipeline and model reliability\n", "| | |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    return "\n".join(lines) + "\n"


# --- Command ---------------------------------------------------------------------------------


def default_judge(cfg: Config, run_id: str) -> Judge:
    from finqa.eval.scoring import llm_judge
    from finqa.llm import LLM

    return llm_judge(LLM(cfg), run_id)


def default_locate() -> Locate:
    from finqa.tools.resolver import CompanyResolver

    resolver = CompanyResolver.from_csv()

    def locate(q: Question) -> tuple[str | None, int | None]:
        company = resolver.resolve(q.company).company
        return (company.cik if company else None, q.doc_period if q.doc_type == "10k" else None)

    return locate


def report_command(
    milestone: str,
    scope: str = "full",
    runs_dir: Path = RUNS_DIR,
    docs_dir: Path = DOCS_DIR,
    data_dir: Path = DATA_DIR,
    questions: dict[str, Question] | None = None,
    gold: dict[str, Gold] | None = None,
    make_judge: Callable[[Config, str], Judge] = default_judge,
    locate: Locate | None = None,
    lookup: error_types.Lookup | None = error_types.xbrl_lookup,
) -> int:
    """`finqa report`: regenerate every table and figure for a milestone (ROADMAP M1.9)."""
    if milestone != "m1":
        raise RunRefused(f"no report for milestone {milestone!r} yet")
    if scope not in SCOPES:
        raise RunRefused(f"unknown scope {scope!r}; use one of {sorted(SCOPES)}")
    subset = SCOPES[scope]
    suffix = "" if scope == "full" else "_midterm_subset"
    questions = questions or {q.question_id: q for q in load_questions("test")}
    gold = gold or load_gold()
    rows: dict[str, list[tables.Row]] = {}
    drafts: dict[str, list[Draft]] = {}
    cfgs: dict[str, Config] = {}
    for name in (S0, R0):
        run_dir = find_run(runs_dir, name, subset)
        cfgs[name] = cfg = run_config(run_dir)
        drafts[name] = read_jsonl(run_dir / "drafts.jsonl", Draft)
        judge = make_judge(cfg, run_dir.name)
        rows[name] = tables.score_run(
            drafts[name], questions, gold, cfg.verification.tolerance, judge
        )
        tables.write_rows(rows[name], run_dir / "scores.jsonl")
    if {r.question_id for r in rows[S0]} != {r.question_id for r in rows[R0]}:
        raise RunRefused("S0 and R0 runs cover different questions; finish both first")

    r0_cfg = cfgs[R0]
    retrieval, found = retrieval_section(drafts[R0], questions, rows[R0], r0_cfg)
    metrics: list[str] = []
    ciks: list[str] = []
    if lookup is not None:
        from finqa.ingestion.xbrl import load_metric_map

        metrics = list(load_metric_map())
        ciks = [r["cik"] for r in _csv(data_dir / "companies.csv")]
    diagnoses = classify_errors(
        drafts[R0],
        questions,
        gold,
        rows[R0],
        found,
        r0_cfg.verification.tolerance,
        locate or default_locate(),
        metrics,
        ciks,
        lookup,
    )
    refused = sum(r.outcome == "refused" for r in rows[R0])
    n = len(rows[R0])
    runs = ", ".join(f"`{find_run(runs_dir, name, subset).name}`" for name in (S0, R0))
    results = "\n".join(
        [
            "# Results\n",
            f"Generated by `uv run finqa report --milestone m1 --scope {scope}`; do not edit "
            "by hand. "
            f"Runs: {runs}. Model `{r0_cfg.model.id}`, thinking `{r0_cfg.model.thinking}`, "
            f"temperature {r0_cfg.model.temperature}.\n",
            accuracy_section(rows, n, scope),
            contamination_section(rows[S0]),
            retrieval,
            error_section(diagnoses, refused),
            reliability_section(data_dir),
        ]
    )
    (docs_dir / "figures").mkdir(parents=True, exist_ok=True)
    results_path = docs_dir / f"RESULTS{suffix}.md"
    results_path.write_text(results, encoding="utf-8")
    (docs_dir / "figures" / f"m1_error_types{suffix}.tex").write_text(
        figure_tex(diagnoses), encoding="utf-8"
    )
    (find_run(runs_dir, R0, subset) / "error_spotcheck.csv").write_text(
        spotcheck_csv(diagnoses, questions), encoding="utf-8"
    )
    print(f"M1 report ({scope}): {n} questions per system -> {results_path}")
    return 0
