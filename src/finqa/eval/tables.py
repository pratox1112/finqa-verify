"""Results tables (ROADMAP P2.4, M1.3; guide §2.4).

Accuracy by question type with counts, refusals and selective accuracy, latency and token
percentiles, estimated cost, and a paired McNemar comparison of two systems. Every percentage
is shown with its count and a question-level bootstrap 95% confidence interval:
"8/10, 80.0% [55.0–100.0]".

Correctness comes only from finqa.eval.scoring (gold answers). Claim-level correctness for
intermediate claims (no gold value) needs the human sample of guide §2.3 and is not tabulated
here; the answer claim is scored for every question.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from finqa.eval import stats
from finqa.eval.scoring import AnswerScore, Gold, Judge, score_draft, score_verified
from finqa.generators.base import Question
from finqa.schemas import Draft, VerifiedResult

TYPES = ("single_fact", "calculation", "multi_period", "qualitative")
# Groq list price for qwen/qwen3.8-27b, USD per million tokens (docs/DECISIONS.md, 2026-10-30).
PRICE_IN_PER_M = 0.80
PRICE_OUT_PER_M = 4.00


@dataclass(frozen=True)
class Row:
    """One scored question of one system (a draft set, or a verification arm over it)."""

    question_id: str
    question_type: str
    outcome: str
    method: str
    reason: str
    latency_s: float
    tokens_in: int
    tokens_out: int
    failed: bool


def score_run(
    drafts: Sequence[Draft],
    questions: dict[str, Question],
    gold: dict[str, Gold],
    tolerance: float,
    judge: Judge | None = None,
    verified: Sequence[VerifiedResult] | None = None,
) -> list[Row]:
    """Score every draft (or every verified result over those drafts) against gold."""
    by_id = {d.question_id: d for d in drafts}
    rows: list[Row] = []
    if verified is None:
        for d in drafts:
            q = questions[d.question_id]
            s = score_draft(d, q.question, gold[d.question_id], tolerance, judge)
            rows.append(_row(q, s, d.latency_s, d.tokens_in, d.tokens_out, d.error is not None))
    else:
        for r in verified:
            d, q = by_id[r.question_id], questions[r.question_id]
            s = score_verified(r, d, q.question, gold[r.question_id], tolerance, judge)
            rows.append(
                _row(
                    q,
                    s,
                    d.latency_s + r.latency_s,
                    d.tokens_in + r.tokens_in,
                    d.tokens_out + r.tokens_out,
                    d.error is not None or r.error is not None,
                )
            )
    return rows


def _row(q: Question, s: AnswerScore, latency: float, t_in: int, t_out: int, failed: bool) -> Row:
    return Row(
        question_id=q.question_id,
        question_type=q.question_type,
        outcome=s.outcome,
        method=s.method,
        reason=s.reason,
        latency_s=latency,
        tokens_in=t_in,
        tokens_out=t_out,
        failed=failed,
    )


def write_rows(rows: Sequence[Row], path: Path) -> None:
    path.write_text("".join(json.dumps(asdict(r)) + "\n" for r in rows), encoding="utf-8")


def read_rows(path: Path) -> list[Row]:
    return [Row(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()]


def accuracy_table(rows: Sequence[Row], title: str) -> str:
    """Accuracy, refusals and selective accuracy by question type, plus an overall row."""
    lines = [
        f"**{title}**",
        "",
        "| Question type | Accuracy | Refused | Selective accuracy | Failed |",
        "|---|---|---|---|---|",
    ]
    groups = [(t, [r for r in rows if r.question_type == t]) for t in TYPES]
    for name, group in [*groups, ("**all**", list(rows))]:
        if not group:
            continue
        correct = [r.outcome == "correct" for r in group]
        refused = [r.outcome == "refused" for r in group]
        answered = [r.outcome == "correct" for r in group if r.outcome != "refused"]
        lines.append(
            f"| {name} | {stats.rate(sum(correct), len(group), correct)} "
            f"| {sum(refused)}/{len(group)} "
            f"| {stats.rate(sum(answered), len(answered), answered)} "
            f"| {sum(r.failed for r in group)} |"
        )
    return "\n".join(lines) + "\n"


def efficiency_table(systems: Sequence[tuple[str, Sequence[Row]]]) -> str:
    """Latency and token percentiles per question, and estimated cost, per system."""
    lines = [
        "| System | Latency p50 / p95 (s) | Tokens in p50 / p95 | Tokens out p50 / p95 "
        "| Est. cost (USD, total / per question) |",
        "|---|---|---|---|---|",
    ]
    for name, rows in systems:
        lat = [r.latency_s for r in rows]
        t_in = [float(r.tokens_in) for r in rows]
        t_out = [float(r.tokens_out) for r in rows]
        cost = (sum(t_in) * PRICE_IN_PER_M + sum(t_out) * PRICE_OUT_PER_M) / 1e6
        per_q = cost / len(rows) if rows else 0.0
        lines.append(
            f"| {name} | {_pair(lat, '.2f')} | {_pair(t_in, '.0f')} | {_pair(t_out, '.0f')} "
            f"| {cost:.4f} / {per_q:.5f} |"
        )
    return "\n".join(lines) + "\n"


def _pair(values: Sequence[float], fmt: str) -> str:
    p50, p95 = stats.percentile(values, 50), stats.percentile(values, 95)
    if p50 is None or p95 is None:
        return "n/a"
    return f"{p50:{fmt}} / {p95:{fmt}}"


def comparison_table(name_a: str, rows_a: Sequence[Row], name_b: str, rows_b: Sequence[Row]) -> str:
    """Paired McNemar test of A vs B on the questions both have."""
    a = {r.question_id: r.outcome == "correct" for r in rows_a}
    b = {r.question_id: r.outcome == "correct" for r in rows_b}
    shared = sorted(a.keys() & b.keys())
    m = stats.mcnemar([a[q] for q in shared], [b[q] for q in shared])
    return (
        f"| Comparison | n | Both correct | {name_a} only | {name_b} only | Both wrong "
        "| McNemar exact p |\n|---|---|---|---|---|---|---|\n"
        f"| {name_a} vs {name_b} | {m.n} | {m.both_correct} | {m.only_a} | {m.only_b} "
        f"| {m.both_wrong} | {m.p_value:.4f} |\n"
    )
