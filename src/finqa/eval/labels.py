"""Human labels: judge-human agreement on text-gold answers, and gold errata adjudication
(docs/LABELING_PROTOCOL.md §3, §5, §6; DECISIONS 2026-11-08 points 2 and 4, 2026-11-22).

Judge agreement, in three steps (scripts/labels.py):

1. `judge-sheets`: every text-gold answer of the given runs that the judge scored (failed and
   refused drafts are scored without the judge, so they are left out) goes into a blind sheet
   per labeller: row ID, question, gold answer, the model's answer text (exactly what the
   judge saw), and empty `correct` and `note` columns. Rows of all runs are shuffled together;
   the sheets never show the system, the run or the judge's verdict. `double` rows go to two
   labellers, for labeller-labeller agreement; the rest to one, round robin. The key that maps
   rows back to runs is written separately and must not be opened while labelling.
2. People fill in `correct` (yes/no) with the judge's rules plus the hedging rule (§6), and
   optional notes (`gold-ambiguous`, `technical-failure`).
3. `judge-agreement`: reads the filled sheets, an optional `adjudication.csv` (row_id, correct,
   note) for rows two labellers disagreed on, and each run's `scores.jsonl` (written by
   `finqa report`), then writes `agreement.md` (judge-human agreement per system with counts,
   CIs and Cohen's kappa; labeller-labeller kappa; rows to adjudicate; every disagreement) and
   `annotations.jsonl` (the final human label per row, as the frozen `Annotation` schema).

Gold errata (`errata-sheets`, `errata-compare`): one sheet per annotator with each candidate's
question, gold answer and FinanceBench's own source (document link, evidence page and text,
justification), never a system's answer. Each annotator records whether the gold matches or
contradicts the filing. A gold is corrected only when both say it contradicts the filing with
the same value; anything else goes to a third person, and an unclear case keeps the gold.

Nothing here changes how answers are scored: labels are compared with the judge, and any
switch to human labels or to corrected golds is a team decision recorded in DECISIONS.md.
"""

from __future__ import annotations

import csv
import json
import random
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finqa.eval import stats, tables
from finqa.eval.runner import RunRefused, read_jsonl
from finqa.eval.scoring import Gold, is_refusal
from finqa.generators.base import Question
from finqa.schemas import Annotation, Draft

SHEET_COLUMNS = ["row_id", "question", "gold_answer", "model_answer", "correct", "note"]
KEY_FILE = "KEY_do_not_open_while_labelling.csv"
KEY_COLUMNS = ["row_id", "run_id", "config_name", "question_id", "claim_id", "labellers"]
YES = {"yes", "y", "true", "1", "correct"}
NO = {"no", "n", "false", "0", "incorrect"}

# Gold errata candidates (DECISIONS 2026-11-08 points 2 and 3; docs/TRACE_REVIEW.md pattern G).
# The reasons are for the team, not for the annotators' sheets.
ERRATA_CANDIDATES: dict[str, str] = {
    "financebench_id_00585": "Boeing tax rate: gold seems to flip the sign of (0.6)% and 14.8%",
    "financebench_id_05718": "American Water dividends: filing reports $389M against $0.40B",
    "financebench_id_04672": "3M net PP&E: billions gold with a trailing zero",
    "financebench_id_04980": "PepsiCo capex: billions gold with a trailing zero",
    "financebench_id_04103": "General Mills CCC: fewer decimals than the question asks",
    "financebench_id_06272": "Coca-Cola payout ratio: fewer decimals than the question asks",
    "financebench_id_00080": "PayPal working capital (dev): $1.6B not reproducible",
    "financebench_id_00283": "Pfizer (dev): 77.78 looks like a misreading of the filing",
}
ERRATA_COLUMNS = [
    "financebench_id",
    "company",
    "question",
    "gold_answer",
    "doc_name",
    "doc_link",
    "evidence_pages",
    "financebench_evidence",
    "financebench_justification",
    "verdict",
    "correct_value",
    "location",
    "note",
]
VERDICTS = ("matches", "contradicts", "unclear")


def _write_csv(path: Path, columns: Sequence[str], rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(columns))
        w.writeheader()
        w.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def parse_yes_no(value: str) -> bool | None:
    """True / False for a filled-in label, None for a blank one; anything else is an error."""
    v = value.strip().lower()
    if not v:
        return None
    if v in YES:
        return True
    if v in NO:
        return False
    raise ValueError(f"not a yes/no label: {value!r}")


# --- Judge agreement: sheets ----------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    run_id: str
    config_name: str
    question_id: str
    claim_id: str
    question: str
    gold_answer: str
    model_answer: str


def judged_items(
    runs_dir: Path, run_ids: Sequence[str], questions: dict[str, Question], gold: dict[str, Gold]
) -> list[Item]:
    """Every text-gold answer the judge scored in these runs."""
    items = []
    for run_id in run_ids:
        run_dir = runs_dir / run_id
        meta_path = run_dir / "run_meta.json"
        if not meta_path.exists():
            raise RunRefused(f"no run {run_id} in {runs_dir}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        for d in read_jsonl(run_dir / "drafts.jsonl", Draft):
            g = gold[d.question_id]
            if g.answer_kind == "number" or d.error is not None:
                continue
            if is_refusal(d.claims, d.answer_text):
                continue
            items.append(
                Item(
                    run_id=run_id,
                    config_name=meta["config_name"],
                    question_id=d.question_id,
                    claim_id=d.answer_claim_id or "",
                    question=questions[d.question_id].question,
                    gold_answer=g.answer,
                    model_answer=d.answer_text,
                )
            )
    return items


def assign(n_items: int, labellers: Sequence[str], double: int) -> list[list[str]]:
    """Labellers per item (items already shuffled): the first `double` items get two labellers
    (pairs in rotation), the rest one each, round robin, so the load stays even."""
    if not labellers:
        raise ValueError("at least one labeller is needed")
    if double and len(labellers) < 2:
        raise ValueError("double coding needs at least two labellers")
    if double > n_items:
        raise ValueError(f"cannot double-code {double} of {n_items} items")
    k = len(labellers)
    out: list[list[str]] = []
    for i in range(n_items):
        if i < double:
            out.append([labellers[i % k], labellers[(i + 1 + (i // k) % (k - 1)) % k]])
        else:
            out.append([labellers[i % k]])
    return out


def write_judge_sheets(
    items: Sequence[Item], labellers: Sequence[str], double: int, out_dir: Path, seed: int
) -> dict[str, int]:
    """Blind sheets, one per labeller, and the key. Returns rows per labeller."""
    if out_dir.exists() and any(out_dir.iterdir()):
        raise RunRefused(f"{out_dir} is not empty; choose a new name")
    order = list(items)
    random.Random(seed).shuffle(order)
    who = assign(len(order), labellers, double)
    key: list[dict[str, str]] = []
    sheets: dict[str, list[dict[str, str]]] = {name: [] for name in labellers}
    for i, (item, names) in enumerate(zip(order, who, strict=True), start=1):
        row_id = f"r{i:04d}"
        key.append(
            {
                "row_id": row_id,
                "run_id": item.run_id,
                "config_name": item.config_name,
                "question_id": item.question_id,
                "claim_id": item.claim_id,
                "labellers": ";".join(names),
            }
        )
        for name in names:
            sheets[name].append(
                {
                    "row_id": row_id,
                    "question": item.question,
                    "gold_answer": item.gold_answer,
                    "model_answer": item.model_answer,
                    "correct": "",
                    "note": "",
                }
            )
    _write_csv(out_dir / KEY_FILE, KEY_COLUMNS, key)
    for name, rows in sheets.items():
        _write_csv(out_dir / f"sheet_{name}.csv", SHEET_COLUMNS, rows)
    return {name: len(rows) for name, rows in sheets.items()}


# --- Judge agreement: results ---------------------------------------------------------------


@dataclass(frozen=True)
class Resolved:
    row_id: str
    config_name: str
    run_id: str
    question_id: str
    claim_id: str
    human: bool
    annotator: str
    note: str


def read_labels(out_dir: Path) -> dict[str, dict[str, tuple[bool | None, str]]]:
    """row_id -> labeller -> (label or None if blank, note), from every sheet_*.csv."""
    labels: dict[str, dict[str, tuple[bool | None, str]]] = {}
    for path in sorted(out_dir.glob("sheet_*.csv")):
        name = path.stem.removeprefix("sheet_")
        for r in _read_csv(path):
            try:
                value = parse_yes_no(r["correct"])
            except ValueError as e:
                raise RunRefused(f"{path.name}, row {r['row_id']}: {e}") from e
            labels.setdefault(r["row_id"], {})[name] = (value, r.get("note", "").strip())
    return labels


def resolve(
    key: Sequence[dict[str, str]],
    labels: dict[str, dict[str, tuple[bool | None, str]]],
    adjudicated: dict[str, tuple[bool, str]],
) -> tuple[list[Resolved], list[str], list[str], list[tuple[bool, bool]]]:
    """(final labels, rows still blank, rows to adjudicate, labeller pairs on double rows)."""
    final, blank, conflict, pairs = [], [], [], []
    for k in key:
        row = k["row_id"]
        given = labels.get(row, {})
        names = k["labellers"].split(";")
        values = [given.get(n, (None, ""))[0] for n in names]
        notes = "; ".join(n for _, n in given.values() if n)
        if any(v is None for v in values):
            blank.append(row)
            continue
        if len(values) == 2:
            pairs.append((bool(values[0]), bool(values[1])))
        if row in adjudicated:
            human, note = adjudicated[row]
            annotator = "adjudicated"
            notes = "; ".join(x for x in (notes, note) if x)
        elif len(set(values)) > 1:
            conflict.append(row)
            continue
        else:
            human, annotator = bool(values[0]), "+".join(sorted(names))
        final.append(
            Resolved(
                row,
                k["config_name"],
                k["run_id"],
                k["question_id"],
                k["claim_id"],
                human,
                annotator,
                notes,
            )
        )
    return final, blank, conflict, pairs


def judge_verdicts(runs_dir: Path, run_ids: set[str]) -> dict[tuple[str, str], tables.Row]:
    """(run_id, question_id) -> scored row, from each run's scores.jsonl."""
    out = {}
    for run_id in sorted(run_ids):
        path = runs_dir / run_id / "scores.jsonl"
        if not path.exists():
            raise RunRefused(f"{run_id} has no scores.jsonl; run `finqa report` first")
        for r in tables.read_rows(path):
            out[(run_id, r.question_id)] = r
    return out


def _kappa(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def agreement_markdown(
    final: Sequence[Resolved],
    verdicts: dict[tuple[str, str], tables.Row],
    blank: Sequence[str],
    conflict: Sequence[str],
    pairs: Sequence[tuple[bool, bool]],
) -> str:
    lines = [
        "# Judge-human agreement on text-gold answers\n",
        "Generated by `scripts/labels.py judge-agreement`; do not edit by hand. Human labels "
        "follow docs/LABELING_PROTOCOL.md §3 and §6 (hedging rule). Agreement = rows where the "
        "judge's verdict equals the final human label; bootstrap 95% CIs over rows.\n",
        f"Rows labelled and resolved: {len(final)}. Still blank: {len(blank)}. "
        f"To adjudicate (two labellers disagree): {len(conflict)}.\n",
        "| System | n | Agreement | Judge yes, human no | Judge no, human yes "
        "| Cohen's kappa (judge vs human) |",
        "|---|---|---|---|---|---|",
    ]
    systems = sorted({f.config_name for f in final})
    for system in [*systems, "**all**"]:
        group = [f for f in final if system in ("**all**", f.config_name)]
        judge = [verdicts[(f.run_id, f.question_id)].outcome == "correct" for f in group]
        human = [f.human for f in group]
        same = [j == h for j, h in zip(judge, human, strict=True)]
        yes_no = sum(j and not h for j, h in zip(judge, human, strict=True))
        no_yes = sum(h and not j for j, h in zip(judge, human, strict=True))
        lines.append(
            f"| {system} | {len(group)} | {stats.rate(sum(same), len(same), same)} | {yes_no} "
            f"| {no_yes} | {_kappa(stats.cohen_kappa(judge, human))} |"
        )
    a = [x for x, _ in pairs]
    b = [y for _, y in pairs]
    same_pairs = [x == y for x, y in pairs]
    lines += [
        "",
        f"**Labeller-labeller agreement** on {len(pairs)} double-coded rows: "
        f"{stats.rate(sum(same_pairs), len(same_pairs), same_pairs)}, Cohen's kappa "
        f"{_kappa(stats.cohen_kappa(a, b))} (aim: 0.7 or more, protocol §5).\n",
    ]
    if conflict:
        lines.append(
            "**To adjudicate** (add to adjudication.csv: row_id, correct, note): "
            + ", ".join(conflict)
            + "\n"
        )
    lines += [
        "## Disagreements between judge and human\n",
        "| Row | System | Question | Judge | Human | Judge's reason | Notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for f in final:
        v = verdicts[(f.run_id, f.question_id)]
        if (v.outcome == "correct") != f.human:
            reason = v.reason.replace("|", "/").replace("\n", " ")
            note = f.note.replace("|", "/").replace("\n", " ")
            lines.append(
                f"| {f.row_id} | {f.config_name} | {f.question_id} | {v.outcome} "
                f"| {'correct' if f.human else 'incorrect'} | {reason} | {note} |"
            )
    return "\n".join(lines) + "\n"


def judge_agreement(out_dir: Path, runs_dir: Path) -> tuple[Path, Path]:
    key = _read_csv(out_dir / KEY_FILE)
    labels = read_labels(out_dir)
    adjudicated: dict[str, tuple[bool, str]] = {}
    adj_path = out_dir / "adjudication.csv"
    if adj_path.exists():
        for r in _read_csv(adj_path):
            value = parse_yes_no(r["correct"])
            if value is not None:
                adjudicated[r["row_id"]] = (value, r.get("note", "").strip())
    final, blank, conflict, pairs = resolve(key, labels, adjudicated)
    verdicts = judge_verdicts(runs_dir, {k["run_id"] for k in key})
    for f in final:
        v = verdicts.get((f.run_id, f.question_id))
        if v is None or v.method != "judge":
            raise RunRefused(f"{f.row_id}: {f.run_id} has no judge verdict for {f.question_id}")
    report = out_dir / "agreement.md"
    report.write_text(agreement_markdown(final, verdicts, blank, conflict, pairs), "utf-8")
    annotations = out_dir / "annotations.jsonl"
    annotations.write_text(
        "".join(
            Annotation(
                question_id=f.question_id,
                claim_id=f.claim_id,
                run_id=f.run_id,
                annotator=f.annotator,
                correct=f.human,
                error_type=None,
                note=f.note,
            ).model_dump_json()
            + "\n"
            for f in final
        ),
        encoding="utf-8",
    )
    return report, annotations


# --- Gold errata ----------------------------------------------------------------------------


def errata_rows(records: dict[str, dict[str, Any]], ids: Sequence[str]) -> list[dict[str, str]]:
    rows = []
    for qid in ids:
        r = records[qid]
        evidence = r.get("evidence") or []
        rows.append(
            {
                "financebench_id": qid,
                "company": r["company"],
                "question": r["question"],
                "gold_answer": r["answer"],
                "doc_name": r["doc_name"],
                "doc_link": r.get("doc_link", ""),
                "evidence_pages": ";".join(
                    str(e.get("evidence_page_num", "")) for e in evidence if isinstance(e, dict)
                ),
                "financebench_evidence": "\n---\n".join(
                    str(e.get("evidence_text", "")) for e in evidence if isinstance(e, dict)
                ),
                "financebench_justification": str(r.get("justification") or ""),
                "verdict": "",
                "correct_value": "",
                "location": "",
                "note": "",
            }
        )
    return rows


def write_errata_sheets(
    records: dict[str, dict[str, Any]], annotators: Sequence[str], out_dir: Path
) -> list[Path]:
    if len(annotators) != 2:
        raise ValueError("errata need exactly two annotators (DECISIONS 2026-11-08)")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise RunRefused(f"{out_dir} is not empty; choose a new name")
    rows = errata_rows(records, list(ERRATA_CANDIDATES))
    paths = []
    for name in annotators:
        path = out_dir / f"errata_{name}.csv"
        _write_csv(path, ERRATA_COLUMNS, rows)
        paths.append(path)
    return paths


def compare_errata(out_dir: Path) -> Path:
    """errata.md: per candidate, both verdicts and the outcome under the errata rule."""
    sheets = sorted(out_dir.glob("errata_*.csv"))
    if len(sheets) != 2:
        raise RunRefused(f"expected two errata sheets in {out_dir}, found {len(sheets)}")
    names = [p.stem.removeprefix("errata_") for p in sheets]
    data = [{r["financebench_id"]: r for r in _read_csv(p)} for p in sheets]
    lines = [
        "# Gold errata: two-annotator check\n",
        "Generated by `scripts/labels.py errata-compare`. Rule (DECISIONS 2026-11-08): a gold is "
        "corrected only when both annotators find it contradicts the filing, with the same "
        "value; otherwise a third person decides, and an unclear case keeps the gold.\n",
        f"| Candidate | {names[0]} | {names[1]} | Outcome |",
        "|---|---|---|---|",
    ]
    for qid in data[0]:
        a, b = data[0][qid], data[1].get(qid)
        if b is None:
            raise RunRefused(f"{qid} is missing from {sheets[1].name}")
        va, vb = a["verdict"].strip().lower(), b["verdict"].strip().lower()
        for name, v in ((names[0], va), (names[1], vb)):
            if v and v not in VERDICTS:
                raise RunRefused(f"{name}, {qid}: verdict must be one of {VERDICTS}, not {v!r}")
        if not va or not vb:
            outcome = "not finished"
        elif va == vb == "contradicts":
            same = a["correct_value"].strip() == b["correct_value"].strip()
            outcome = (
                f"**correct the gold to {a['correct_value'].strip()}**"
                if same
                else "third person: both say contradicts, values differ"
            )
        elif va == vb == "matches":
            outcome = "gold stands"
        else:
            outcome = "third person decides"

        def cell(r: dict[str, str], v: str) -> str:
            value = f" ({r['correct_value'].strip()})" if r["correct_value"].strip() else ""
            return (v or "—") + value

        lines.append(f"| {qid} | {cell(a, va)} | {cell(b, vb)} | {outcome} |")
    path = out_dir / "errata.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
