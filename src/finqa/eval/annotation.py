"""Claim annotation sheets (P5.2; annotation/guidelines.md, docs/LABELING_PROTOCOL.md §5).

Export, in one step (`scripts/labels.py claim-sheets`):

1. Every claim of every grid cell is collected: for each draft run, the claims after each
   verifier (`verified_none.jsonl` is the draft itself, then `verified_self_check.jsonl` and
   `verified_grounded.jsonl`). Drafts that failed or have no claims have nothing to label.
2. Claims are de-duplicated **within a draft run** (DECISIONS 2026-11-26): the same question,
   the same claim (ID, metric, value, unit, period, citations, expression) and the same inputs
   (every claim it is computed from, recursively) make one row, whatever cells it appears in.
   R0 and R1 claims are always separate rows.
3. Each row shows the company and filing, the question, the gold answer, the system's answer
   text, whether the claim is the answer claim, the claim, its inputs, its cited text (each
   excerpt with its header) and an automatic pre-label (the answer claim of a single-number
   gold, matched against the gold as scoring does; blank otherwise). It never shows the grid
   cell, the verifier's verdicts or an error type.
4. Rows are shuffled with a fixed seed and assigned to annotators: two per row in rotating
   pairs (every pair of annotators shares about the same number of rows), or every annotator
   for a pilot. `sample` keeps only the first N shuffled rows. The key that maps rows back to
   cells is written separately and must not be opened while labelling.

Read-back (`scripts/labels.py claim-labels`): the filled sheets are checked (`correct` yes/no,
`error_type` one of the schema's types for an incorrect claim and empty for a correct one) and
written as `labels.jsonl`, one frozen `Annotation` per annotator, row and grid cell. The cell
is stored in `run_id` as "<draft run>:<verifier arm>" (`cell_run_id`; DECISIONS 2026-11-26),
because a revised claim keeps its claim ID.

Agreement (`scripts/labels.py claim-agreement`; P5.5): only rows every assigned annotator has
labelled count. Each counted row gives one comparison per pair of its annotators (one for a
pair, ten for five pilot annotators), each pair ordered by name. `agreement.md` reports Cohen's
kappa and percent agreement pooled over all comparisons and per pair, for three labels:
`correct` (yes/no); error type (a), the combined label ("correct" or the error type) on every
comparison; and error type (b), the error type on comparisons where both said incorrect.
`disagreements.csv` lists every row whose annotators differ on `correct` or `error_type`, with
the claim as the sheets show it, each annotator's label and empty `final_*` columns, never the
run or the cells. Filled in and saved as `adjudication.csv` (P5.6), it gives the final label of
those rows: `final_labels.jsonl` holds one `Annotation` per row and cell, annotator
"a+b" for agreed rows or "adjudicated"; rows still in disagreement are left out and listed.

Correctness comes from people labelling against gold and the filing; nothing here scores.
"""

from __future__ import annotations

import csv
import json
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

from finqa.eval import stats
from finqa.eval.runner import RunRefused, read_jsonl
from finqa.eval.scoring import Gold, in_gold_unit, matches_gold, rounding_decimals
from finqa.generators.base import Question
from finqa.schemas import Annotation, Chunk, Claim, Draft, ErrorType, VerifiedResult

ARMS = ("none", "self_check", "grounded")
SHEET_COLUMNS = [
    "row_id",
    "company",
    "filing",
    "question",
    "gold_answer",
    "answer_text",
    "answer_claim",
    "metric",
    "value",
    "unit",
    "period",
    "expression",
    "inputs",
    "cited_text",
    "pre_label",
    "correct",
    "error_type",
    "note",
]
KEY_FILE = "KEY_do_not_open_while_labelling.csv"
KEY_COLUMNS = ["row_id", "run_id", "question_id", "claim_id", "cells", "annotators"]
LABELS_FILE = "labels.jsonl"
YES = {"yes", "y", "true", "1", "correct"}
NO = {"no", "n", "false", "0", "incorrect"}
ERROR_TYPES = {e.value for e in ErrorType}
EXCEL_CELL_LIMIT = 32_767


def cell_run_id(run_id: str, arm: str) -> str:
    """The `Annotation.run_id` of a grid cell: the draft run and the verifier arm."""
    return f"{run_id}:{arm}"


@dataclass
class Row:
    """One claim to label, and every cell (verifier arm) of its draft run it appears in."""

    run_id: str
    question_id: str
    claim_id: str
    arms: list[str]
    sheet: dict[str, str] = field(default_factory=dict)


def format_value(value: float) -> str:
    """Full units with thousands separators: 394300000000 -> 394,300,000,000; 12.5 -> 12.5."""
    if value == int(value) and abs(value) < 1e18:
        return f"{int(value):,}"
    return f"{value:,.6f}".rstrip("0").rstrip(".")


def _closure(claim: Claim, by_id: dict[str, Claim]) -> list[Claim]:
    """The claim's inputs, their inputs, and so on (each once, in first-seen order)."""
    out: list[Claim] = []
    todo = list(claim.derived_from)
    while todo:
        cid = todo.pop(0)
        c = by_id.get(cid)
        if c is None or c in out or c.claim_id == claim.claim_id:
            continue
        out.append(c)
        todo.extend(c.derived_from)
    return out


def signature(claim: Claim, claims: Sequence[Claim]) -> str:
    """What makes two claims one row: the claim itself and its inputs, recursively."""
    by_id = {c.claim_id: c for c in claims}
    inputs = sorted(c.model_dump_json() for c in _closure(claim, by_id))
    return json.dumps([claim.model_dump_json(), inputs])


def _describe(c: Claim) -> str:
    text = f"{c.claim_id}: {c.metric} = {format_value(c.value)} {c.unit}, {c.period}"
    if c.expression:
        text += f" (= {c.expression} of {', '.join(c.derived_from)})"
    return text


def inputs_text(claim: Claim, claims: Sequence[Claim]) -> str:
    by_id = {c.claim_id: c for c in claims}
    return "\n".join(_describe(c) for c in _closure(claim, by_id))


def chunk_header(chunk: Chunk) -> str:
    parts = [chunk.ticker, chunk.form, chunk.period or f"FY{chunk.fiscal_year}", chunk.section]
    header = " | ".join(p for p in parts if p)
    if chunk.is_table:
        header += (
            f" | table in units of {format_value(chunk.unit_scale)}"
            if chunk.unit_scale
            else " | table, scale not stated"
        )
    return header


def cited_text(claim: Claim, evidence: dict[str, Chunk]) -> str:
    if not claim.chunk_ids:
        return "(cites nothing)"
    parts = []
    for cid in claim.chunk_ids:
        chunk = evidence.get(cid)
        if chunk is None:
            parts.append(f"[{cid}] (not in the retrieved evidence)")
        else:
            parts.append(f"[{cid}] {chunk_header(chunk)}\n{chunk.text}")
    return "\n---\n".join(parts)


def pre_label(claim: Claim, is_answer: bool, gold: Gold, question: str, tolerance: float) -> str:
    """Whether the answer claim matches a single-number gold, as scoring checks it."""
    if not is_answer or gold.answer_kind != "number" or gold.value is None:
        return ""
    value = in_gold_unit(claim.value, claim.unit, gold.unit)
    ok = matches_gold(value, gold.value, tolerance, rounding_decimals(question))
    return "matches gold" if ok else "does not match gold"


def _meta(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "run_meta.json"
    if not path.exists():
        raise RunRefused(f"no run {run_dir.name} in {run_dir.parent}")
    meta: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return meta


def collect_rows(
    runs_dir: Path,
    run_ids: Sequence[str],
    questions: dict[str, Question],
    gold: dict[str, Gold],
    tolerance: float,
    arms: Sequence[str] = ARMS,
) -> list[Row]:
    """Every distinct claim of every cell of these draft runs, in a stable order."""
    rows: dict[tuple[str, str, str], Row] = {}
    for run_id in run_ids:
        run_dir = runs_dir / run_id
        _meta(run_dir)
        drafts = {d.question_id: d for d in read_jsonl(run_dir / "drafts.jsonl", Draft)}
        for arm in arms:
            path = run_dir / f"verified_{arm}.jsonl"
            if not path.exists():
                raise RunRefused(f"{run_id} has no {path.name}; run that verifier first")
            for result in read_jsonl(path, VerifiedResult):
                draft = drafts.get(result.question_id)
                if draft is None:
                    raise RunRefused(f"{run_id}/{path.name}: no draft for {result.question_id}")
                if draft.error is not None:
                    continue
                for claim in result.claims_after:
                    key = (run_id, result.question_id, signature(claim, result.claims_after))
                    if key in rows:
                        if arm not in rows[key].arms:
                            rows[key].arms.append(arm)
                        continue
                    rows[key] = Row(
                        run_id,
                        result.question_id,
                        claim.claim_id,
                        [arm],
                        _sheet_fields(
                            claim, result.claims_after, draft, questions, gold, tolerance
                        ),
                    )
    return list(rows.values())


def _sheet_fields(
    claim: Claim,
    claims: Sequence[Claim],
    draft: Draft,
    questions: dict[str, Question],
    gold: dict[str, Gold],
    tolerance: float,
) -> dict[str, str]:
    q, g = questions[draft.question_id], gold[draft.question_id]
    is_answer = claim.claim_id == draft.answer_claim_id
    return {
        "company": q.company,
        "filing": q.doc_name,
        "question": q.question,
        "gold_answer": g.answer,
        "answer_text": draft.answer_text,
        "answer_claim": "yes" if is_answer else "no",
        "metric": claim.metric,
        "value": format_value(claim.value),
        "unit": claim.unit,
        "period": claim.period,
        "expression": claim.expression or "",
        "inputs": inputs_text(claim, claims),
        "cited_text": cited_text(claim, draft.evidence),
        "pre_label": pre_label(claim, is_answer, g, q.question, tolerance),
    }


def rotating_pairs(n_rows: int, annotators: Sequence[str]) -> list[list[str]]:
    """Two annotators per row: every pair in turn, so each pair (and each person) gets about
    the same number of rows."""
    if len(set(annotators)) != len(annotators):
        raise ValueError("annotator names must be distinct")
    if len(annotators) < 2:
        raise ValueError("two annotators per claim need at least two annotators")
    pairs = list(combinations(annotators, 2))
    return [list(pairs[i % len(pairs)]) for i in range(n_rows)]


def write_claim_sheets(
    rows: Sequence[Row],
    annotators: Sequence[str],
    out_dir: Path,
    seed: int,
    everyone: bool = False,
    sample: int | None = None,
) -> dict[str, int]:
    """Blind, shuffled sheets (one per annotator) and the key. Returns rows per annotator."""
    if out_dir.exists() and any(out_dir.iterdir()):
        raise RunRefused(f"{out_dir} is not empty; choose a new name")
    order = sorted(rows, key=lambda r: (r.run_id, r.question_id, r.claim_id, r.sheet["value"]))
    random.Random(seed).shuffle(order)
    if sample is not None:
        if not 0 < sample <= len(order):
            raise ValueError(f"cannot sample {sample} of {len(order)} claims")
        order = order[:sample]
    if everyone:
        if len(set(annotators)) != len(annotators) or not annotators:
            raise ValueError("annotator names must be distinct, and at least one is needed")
        who = [list(annotators) for _ in order]
    else:
        who = rotating_pairs(len(order), annotators)
    key: list[dict[str, str]] = []
    sheets: dict[str, list[dict[str, str]]] = {name: [] for name in annotators}
    for i, (row, names) in enumerate(zip(order, who, strict=True), start=1):
        row_id = f"c{i:05d}"
        key.append(
            {
                "row_id": row_id,
                "run_id": row.run_id,
                "question_id": row.question_id,
                "claim_id": row.claim_id,
                "cells": ";".join(a for a in ARMS if a in row.arms),
                "annotators": ";".join(names),
            }
        )
        for name in names:
            sheets[name].append(
                {"row_id": row_id, **row.sheet, "correct": "", "error_type": "", "note": ""}
            )
    _write_csv(out_dir / KEY_FILE, KEY_COLUMNS, key)
    for name, sheet_rows in sheets.items():
        _write_csv(out_dir / f"sheet_{name}.csv", SHEET_COLUMNS, sheet_rows)
    return {name: len(r) for name, r in sheets.items()}


def too_long(rows: Sequence[Row]) -> list[str]:
    """Rows with a cell longer than a spreadsheet cell holds (Excel truncates them)."""
    return [
        f"{r.run_id}/{r.question_id}/{r.claim_id}"
        for r in rows
        if any(len(v) > EXCEL_CELL_LIMIT for v in r.sheet.values())
    ]


def _write_csv(path: Path, columns: Sequence[str], rows: Sequence[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so that Excel opens the sheets with the right characters
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(columns))
        w.writeheader()
        w.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# --- Read-back ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Label:
    row_id: str
    annotator: str
    correct: bool
    error_type: ErrorType | None
    note: str


def parse_label(row: dict[str, str], annotator: str) -> Label | None:
    """The label in one sheet row; None if `correct` is blank. Raises ValueError if invalid."""
    correct = row.get("correct", "").strip().lower()
    error = row.get("error_type", "").strip().lower()
    note = row.get("note", "").strip()
    if not correct:
        if error:
            raise ValueError("error_type is filled in but correct is blank")
        return None
    if correct in YES:
        if error:
            raise ValueError("a correct claim has no error_type")
        return Label(row["row_id"], annotator, True, None, note)
    if correct not in NO:
        raise ValueError(f"correct must be yes or no, not {row['correct']!r}")
    if error not in ERROR_TYPES:
        raise ValueError(
            f"an incorrect claim needs an error_type, one of {sorted(ERROR_TYPES)}; got {error!r}"
        )
    return Label(row["row_id"], annotator, False, ErrorType(error), note)


def read_claim_labels(out_dir: Path) -> tuple[list[Label], list[str]]:
    """(labels, problems) from every sheet; a problem names the sheet and the row."""
    key = {k["row_id"]: k for k in _read_csv(out_dir / KEY_FILE)}
    labels, problems = [], []
    for path in sorted(out_dir.glob("sheet_*.csv")):
        name = path.stem.removeprefix("sheet_")
        for r in _read_csv(path):
            k = key.get(r["row_id"])
            if k is None or name not in k["annotators"].split(";"):
                problems.append(f"{path.name}, row {r['row_id']}: not assigned to {name}")
                continue
            try:
                label = parse_label(r, name)
            except ValueError as e:
                problems.append(f"{path.name}, row {r['row_id']}: {e}")
                continue
            if label is not None:
                labels.append(label)
    return labels, problems


def to_annotations(labels: Sequence[Label], key: Sequence[dict[str, str]]) -> list[Annotation]:
    """One Annotation per label and grid cell its row appears in."""
    by_row = {k["row_id"]: k for k in key}
    out = []
    for lab in labels:
        k = by_row[lab.row_id]
        for arm in k["cells"].split(";"):
            out.append(
                Annotation(
                    question_id=k["question_id"],
                    claim_id=k["claim_id"],
                    run_id=cell_run_id(k["run_id"], arm),
                    annotator=lab.annotator,
                    correct=lab.correct,
                    error_type=lab.error_type,
                    note=lab.note,
                )
            )
    return out


def collect_claim_labels(out_dir: Path) -> tuple[Path, int, int, list[str]]:
    """Write labels.jsonl from the filled sheets: (path, labels, rows still blank, problems).

    Nothing is written if any sheet has a problem."""
    key = _read_csv(out_dir / KEY_FILE)
    labels, problems = read_claim_labels(out_dir)
    path = out_dir / LABELS_FILE
    if problems:
        return path, 0, 0, problems
    expected = sum(len(k["annotators"].split(";")) for k in key)
    annotations = to_annotations(labels, key)
    path.write_text("".join(a.model_dump_json() + "\n" for a in annotations), encoding="utf-8")
    return path, len(labels), expected - len(labels), []


# --- Agreement and final labels ------------------------------------------------------------

AGREEMENT_FILE = "agreement.md"
DISAGREEMENTS_FILE = "disagreements.csv"
ADJUDICATION_FILE = "adjudication.csv"
FINAL_LABELS_FILE = "final_labels.jsonl"
DISCUSS_COLUMNS = [c for c in SHEET_COLUMNS if c not in ("row_id", "correct", "error_type", "note")]
FINAL_COLUMNS = ["final_correct", "final_error_type", "final_note"]
ADJUDICATED = "adjudicated"
KAPPA_AIM = 0.7


def combined(label: Label) -> str:
    """One label for correctness and error type: "correct", or the error type."""
    if label.correct or label.error_type is None:
        return "correct"
    return label.error_type.value


def label_text(label: Label) -> str:
    """'ann: no / wrong_period / from-input' (a correct claim: 'ann: yes / - / unsupported')."""
    parts = ["yes" if label.correct else "no"]
    if label.error_type is not None:
        parts.append(label.error_type.value)
    if label.note:
        if label.error_type is None:
            parts.append("-")
        parts.append(label.note)
    return f"{label.annotator}: {' / '.join(parts)}"


def complete_rows(
    key: Sequence[dict[str, str]], labels: Sequence[Label]
) -> tuple[dict[str, list[Label]], list[str]]:
    """(row_id -> its labels in annotator-name order, for rows every assigned annotator
    labelled; the row IDs still missing a label)."""
    given: dict[str, dict[str, Label]] = {}
    for lab in labels:
        given.setdefault(lab.row_id, {})[lab.annotator] = lab
    complete, incomplete = {}, []
    for k in key:
        names = sorted(k["annotators"].split(";"))
        have = given.get(k["row_id"], {})
        if all(n in have for n in names):
            complete[k["row_id"]] = [have[n] for n in names]
        else:
            incomplete.append(k["row_id"])
    return complete, incomplete


def pair_comparisons(
    rows: dict[str, list[Label]],
) -> dict[tuple[str, str], list[tuple[Label, Label]]]:
    """(annotator, annotator) in name order -> one (first's, second's) label per shared row."""
    out: dict[tuple[str, str], list[tuple[Label, Label]]] = {}
    for labs in rows.values():
        for x, y in combinations(labs, 2):  # labels are in annotator-name order
            out.setdefault((x.annotator, y.annotator), []).append((x, y))
    return out


@dataclass(frozen=True)
class Agreement:
    """Agreement on n comparisons (two annotators' labels of one row)."""

    n: int
    agree: int
    kappa: float | None


def agreement(pairs: Sequence[tuple[Any, Any]]) -> Agreement:
    a, b = [x for x, _ in pairs], [y for _, y in pairs]
    return Agreement(len(pairs), sum(x == y for x, y in pairs), stats.cohen_kappa(a, b))


def on_correct(pairs: Sequence[tuple[Label, Label]]) -> Agreement:
    return agreement([(x.correct, y.correct) for x, y in pairs])


def on_label(pairs: Sequence[tuple[Label, Label]]) -> Agreement:
    """Error type (a): agreement on the combined label, "correct" or the error type."""
    return agreement([(combined(x), combined(y)) for x, y in pairs])


def on_error_type(pairs: Sequence[tuple[Label, Label]]) -> Agreement:
    """Error type (b): agreement on the error type where both annotators said incorrect."""
    return agreement(
        [(combined(x), combined(y)) for x, y in pairs if not x.correct and not y.correct]
    )


def disagreeing(rows: dict[str, list[Label]]) -> list[str]:
    """Rows whose annotators differ on `correct` or on `error_type` (notes may differ)."""
    return [r for r, labs in rows.items() if len({combined(lab) for lab in labs}) > 1]


def _sheet_rows(out_dir: Path) -> dict[str, dict[str, str]]:
    """row_id -> the row as it appears in the first sheet (by annotator name) that has it."""
    out: dict[str, dict[str, str]] = {}
    for path in sorted(out_dir.glob("sheet_*.csv")):
        for r in _read_csv(path):
            out.setdefault(r["row_id"], r)
    return out


def disagreement_sheet(
    out_dir: Path, rows: dict[str, list[Label]], disagree: Sequence[str], width: int
) -> list[dict[str, str]]:
    """One row per disagreement: the claim as annotators saw it, each label, empty finals.
    Never the run, the cells or anything else from the key."""
    sheet = _sheet_rows(out_dir)
    out = []
    for row_id in disagree:
        r = {"row_id": row_id, **{c: sheet[row_id].get(c, "") for c in DISCUSS_COLUMNS}}
        r.update({f"label_{i}": "" for i in range(1, width + 1)})
        r.update({f"label_{i}": label_text(lab) for i, lab in enumerate(rows[row_id], start=1)})
        r.update({c: "" for c in FINAL_COLUMNS})
        out.append(r)
    return out


def read_adjudication(path: Path, row_ids: set[str]) -> tuple[dict[str, Label], list[str]]:
    """(row_id -> adjudicated label, problems) from a filled adjudication sheet, checked with
    the sheets' rules (`parse_label`). Rows with blank finals are not adjudicated yet."""
    rows = _read_csv(path)
    if rows and any(c not in rows[0] for c in ("row_id", *FINAL_COLUMNS)):
        return {}, [f"{path.name}: needs the columns row_id, {', '.join(FINAL_COLUMNS)}"]
    out: dict[str, Label] = {}
    problems = []
    for r in rows:
        row_id = (r["row_id"] or "").strip()
        where = f"{path.name}, row {row_id}"
        if row_id not in row_ids:
            problems.append(f"{where}: not a row of this folder's key")
            continue
        if row_id in out:
            problems.append(f"{where}: adjudicated twice")
            continue
        final = {
            "row_id": row_id,
            "correct": r["final_correct"] or "",
            "error_type": r["final_error_type"] or "",
            "note": r["final_note"] or "",
        }
        try:
            label = parse_label(final, ADJUDICATED)
        except ValueError as e:
            problems.append(f"{where}: {e} (in the final_* columns)")
            continue
        if label is not None:
            out[row_id] = label
    return out, problems


def final_labels(
    key: Sequence[dict[str, str]], rows: dict[str, list[Label]], adjudicated: dict[str, Label]
) -> tuple[list[Annotation], list[str]]:
    """(one Annotation per final label and grid cell, rows still in disagreement).

    An adjudicated row takes the adjudicated label (annotator "adjudicated"); a complete row
    whose annotators agree takes their label (annotator "a+b", notes joined with "; ").
    Incomplete rows and rows still in disagreement are left out."""
    final, unresolved = [], []
    for k in key:
        row_id = k["row_id"]
        if row_id in adjudicated:
            final.append(adjudicated[row_id])
            continue
        labs = rows.get(row_id)
        if labs is None:
            continue
        if len({combined(lab) for lab in labs}) > 1:
            unresolved.append(row_id)
            continue
        final.append(
            Label(
                row_id,
                "+".join(sorted(lab.annotator for lab in labs)),
                labs[0].correct,
                labs[0].error_type,
                "; ".join(lab.note for lab in labs if lab.note),
            )
        )
    return to_annotations(final, key), unresolved


def _share(k: int, n: int) -> str:
    return f"{k}/{n}, {100 * k / n:.0f}%" if n else "0/0, n/a"


def _kappa(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def _assigned_pairs(key: Sequence[dict[str, str]]) -> list[tuple[str, str]]:
    return sorted({p for k in key for p in combinations(sorted(k["annotators"].split(";")), 2)})


def agreement_markdown(
    key: Sequence[dict[str, str]],
    rows: dict[str, list[Label]],
    incomplete: Sequence[str],
    adjudicated: dict[str, Label],
    unresolved: Sequence[str] | None,
    n_final: int | None,
) -> str:
    """The agreement report; `unresolved` and `n_final` are None when no final labels were
    written."""
    pairs = _assigned_pairs(key)
    by_pair = pair_comparisons(rows)
    pooled = [c for pair in pairs for c in by_pair.get(pair, [])]
    disagree = disagreeing(rows)
    corr, lab, err = on_correct(pooled), on_label(pooled), on_error_type(pooled)
    lines = [
        "# Claim annotation agreement\n",
        "Generated by `scripts/labels.py claim-agreement`; do not edit by hand "
        "(annotation/guidelines.md §7, docs/LABELING_PROTOCOL.md §5). "
        f"Aim: Cohen's kappa {KAPPA_AIM} or more.\n",
        f"Rows: {len(key)}. Labelled by every assigned annotator (counted): {len(rows)}. "
        f"Incomplete (left out): {len(incomplete)}.\n",
        "Pooled over annotator pairs: each counted row gives one comparison per pair of its "
        "annotators (1 for two annotators, 10 for five). Cohen's kappa is computed on all "
        "comparisons together, each as (first annotator by name, second annotator).\n",
        f"- **Correct (yes/no):** {corr.n} comparisons on {len(rows)} rows; agreement "
        f"{_share(corr.agree, corr.n)}; Cohen's kappa {_kappa(corr.kappa)}.",
        "- **Error type (a), combined label** (`correct` or the error type, all comparisons): "
        f"{lab.n} comparisons; agreement {_share(lab.agree, lab.n)}; "
        f"Cohen's kappa {_kappa(lab.kappa)}.",
        "- **Error type (b), among incorrect** (error type, only comparisons where both "
        f"annotators said incorrect): {err.n} comparisons; agreement "
        f"{_share(err.agree, err.n)}; Cohen's kappa {_kappa(err.kappa)}.",
        "",
        "## Per pair\n",
        "| Pair | Rows | Correct: agreement | Correct: kappa | (a) Combined label: agreement "
        "| (a) Combined label: kappa | (b) Error type, both incorrect: agreement "
        "| (b) Error type, both incorrect: kappa |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for pair in pairs:
        cs = by_pair.get(pair, [])
        c, la, e = on_correct(cs), on_label(cs), on_error_type(cs)
        lines.append(
            f"| {pair[0]}–{pair[1]} | {len(cs)} | {_share(c.agree, c.n)} | {_kappa(c.kappa)} "
            f"| {_share(la.agree, la.n)} | {_kappa(la.kappa)} | {_share(e.agree, e.n)} "
            f"| {_kappa(e.kappa)} |"
        )
    lines += [
        "",
        "## Disagreements and final labels\n",
        "Rows where annotators differ on correct or on error type: "
        f"{_share(len(disagree), len(rows))} of counted rows, listed in `{DISAGREEMENTS_FILE}`. "
        f"To adjudicate, copy it to `{ADJUDICATION_FILE}` and fill in final_correct, "
        "final_error_type and final_note (the pair first, then a third annotator; the "
        "adjudicated label is final).\n",
        f"Adjudicated rows: {len(adjudicated)}.\n",
    ]
    if unresolved is None or n_final is None:
        lines.append(f"No `{FINAL_LABELS_FILE}` written: no `{ADJUDICATION_FILE}` yet.\n")
    else:
        lines.append(f"`{FINAL_LABELS_FILE}`: {n_final} annotations (one per row and cell).\n")
        if unresolved:
            lines.append(
                "**Still in disagreement, not adjudicated (left out of the final labels):** "
                + ", ".join(unresolved)
                + "\n"
            )
    if incomplete:
        lines.append("**Incomplete rows (left out):** " + ", ".join(incomplete) + "\n")
    return "\n".join(lines)


@dataclass(frozen=True)
class ClaimAgreement:
    report: Path
    disagreements: Path
    final: Path | None  # None when no final labels were written
    counted: int
    incomplete: int
    disagree: int
    unresolved: int
    problems: list[str]


def claim_agreement(out_dir: Path) -> ClaimAgreement:
    """Write agreement.md and disagreements.csv, and final_labels.jsonl when adjudication.csv
    exists or nothing needs adjudicating. Nothing is written if a sheet has a problem."""
    key = _read_csv(out_dir / KEY_FILE)
    labels, problems = read_claim_labels(out_dir)
    adj_path = out_dir / ADJUDICATION_FILE
    adjudicated: dict[str, Label] = {}
    if adj_path.exists():
        adjudicated, adj_problems = read_adjudication(adj_path, {k["row_id"] for k in key})
        problems += adj_problems
    report, sheet_path = out_dir / AGREEMENT_FILE, out_dir / DISAGREEMENTS_FILE
    if problems:
        return ClaimAgreement(report, sheet_path, None, 0, 0, 0, 0, problems)
    rows, incomplete = complete_rows(key, labels)
    disagree = disagreeing(rows)
    width = max([2, *(len(k["annotators"].split(";")) for k in key)])
    labels_columns = [f"label_{i}" for i in range(1, width + 1)]
    _write_csv(
        sheet_path,
        ["row_id", *DISCUSS_COLUMNS, *labels_columns, *FINAL_COLUMNS],
        disagreement_sheet(out_dir, rows, disagree, width),
    )
    final_path: Path | None = None
    unresolved: list[str] | None = None
    n_final: int | None = None
    if adj_path.exists() or not disagree:
        annotations, unresolved = final_labels(key, rows, adjudicated)
        final_path = out_dir / FINAL_LABELS_FILE
        final_path.write_text(
            "".join(a.model_dump_json() + "\n" for a in annotations), encoding="utf-8"
        )
        n_final = len(annotations)
    report.write_text(
        agreement_markdown(key, rows, incomplete, adjudicated, unresolved, n_final),
        encoding="utf-8",
    )
    return ClaimAgreement(
        report,
        sheet_path,
        final_path,
        len(rows),
        len(incomplete),
        len(disagree),
        len(disagree) if unresolved is None else len(unresolved),
        [],
    )
