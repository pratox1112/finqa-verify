"""Propose a question type for every in-scope FinanceBench question (ROADMAP P2.1).

Writes data/question_types.csv for a human to confirm. Rules, first match wins:
  qualitative   the gold answer has no number, or the answer is a name, list or description
                ("what are", "which debt securities", "which segment had the highest", ...)
  multi_period  the question compares or combines periods: growth, change, trend, CAGR,
                multi-year average, "between FYx and FYy", "improving", "historically".
                An average balance inside a ratio's definition ("average inventory between
                FY2018 and FY2019") does not count: that is a one-period calculation
  single_fact   FinanceBench calls it information extraction and no ratio is defined
  calculation   arithmetic within one period (ratio, margin, turnover, working capital, ...),
                or FinanceBench tags it numerical/logical reasoning
  single_fact   otherwise: one figure read directly from a filing
A person then fills `confirmed_type` and scripts/make_splits.py builds data/splits.json from
the confirmed types. Re-running keeps every confirmed_type already in the file.

    uv run python scripts/propose_question_types.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

from finqa.ingestion import financebench

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "data" / "financebench_audit.csv"
PILOT = ROOT / "data" / "pilot_questions.json"
OUT = ROOT / "data" / "question_types.csv"
TYPES = ("single_fact", "multi_period", "calculation", "qualitative")

QUALITATIVE = re.compile(
    r"^(what are|who are|which debt securities|has [\w &'.-]+ reported|what is the nature"
    r"|what industry|what drove|is [\w &'.-]+ subject|what production|were there any"
    r"|did [\w &'.-]+ report|as of [^?]*spinning)"
    r"|which [\w ()/&'-]+ (had|performed|received)[^?]*\b(best|highest|lowest|largest|biggest)"
    r"|among (all of the|operations)|which [\w ']*segment",
    re.IGNORECASE,
)
# "average X between FY2018 and FY2019" inside a ratio definition is not a multi-period question
RATIO_AVERAGE = re.compile(
    r"average [^.;:]{0,60}?between (fy)?\d+ and (fy)?\d+"
    r"|change in inventor(y|ies)( between (fy)?\d+ and (fy)?\d+)?",
    re.IGNORECASE,
)
DEFINED_METRIC = re.compile(
    r"defined as|\bratio|each shareholder|margin|turnover|calculate", re.IGNORECASE
)
MULTI_PERIOD = re.compile(
    r"growth|year[- ]over[- ]year|\bchange[ds]?\b|\btrend\b|\bcagr\b|\d year average"
    r"|\bbetween (fy|q\d|\d{4})|\bfrom fy\d+ to fy\d+|improv|historically|\bgrow\b"
    r"|\d year total"
    r"|compare[sd]? to|\bdrop\b|increased",
    re.IGNORECASE,
)
CALCULATION = re.compile(
    r"\bratio|each shareholder|per share|margin|turnover|working capital|\bdays\b"
    r"|cash conversion|return on|payout"
    r"|free cash flow|ebitda|\bcompute|calculate|as a %|% of|capital[- ]intensive",
    re.IGNORECASE,
)


def propose(question: str, reasoning: str, answer_kind: str) -> tuple[str, str]:
    if answer_kind == "text":
        return "qualitative", "gold answer has no number"
    if m := QUALITATIVE.search(question):
        return "qualitative", f"answer is a name/list/description: '{m.group(0)[:40]}'"
    if m := MULTI_PERIOD.search(RATIO_AVERAGE.sub("", question)):
        return "multi_period", f"question mentions '{m.group(0)}'"
    if reasoning.startswith("Information extraction") and not DEFINED_METRIC.search(question):
        return "single_fact", "FinanceBench: information extraction, no defined metric"
    if m := CALCULATION.search(question):
        return "calculation", f"question mentions '{m.group(0)}'"
    if re.search(r"numerical|logical", reasoning, re.IGNORECASE):
        return "calculation", f"FinanceBench reasoning: {reasoning}"
    return "single_fact", "one figure, no arithmetic keyword"


def main() -> int:
    audit = {r["financebench_id"]: r for r in csv.DictReader(AUDIT.open(encoding="utf-8"))}
    confirmed: dict[str, str] = {}
    if OUT.exists():
        confirmed = {
            r["financebench_id"]: r["confirmed_type"]
            for r in csv.DictReader(OUT.open(encoding="utf-8"))
        }
    pilot = {q["financebench_id"] for q in json.loads(PILOT.read_text("utf-8"))["questions"]}
    rows = []
    for rec in financebench.load():
        if not financebench.in_scope(rec):
            continue
        a = audit[rec["financebench_id"]]
        reasoning = rec.get("question_reasoning") or ""
        kind, rule = propose(rec["question"], reasoning, a["answer_kind"])
        rows.append(
            {
                "financebench_id": rec["financebench_id"],
                "company": rec["company"],
                "doc_name": rec["doc_name"],
                "pilot": "yes" if rec["financebench_id"] in pilot else "",
                "answer_kind": a["answer_kind"],
                "proposed_type": kind,
                "rule": rule,
                "confirmed_type": confirmed.get(rec["financebench_id"], ""),
                "question": " ".join(rec["question"].split()),
            }
        )
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    counts = {t: sum(r["proposed_type"] == t for r in rows) for t in TYPES}
    print(f"{len(rows)} questions → {OUT.relative_to(ROOT)}: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
