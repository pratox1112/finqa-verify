"""Rule-based error classifier (ROADMAP P2.5, guide §2.5; rules in docs/LABELING_PROTOCOL.md).

For an answer already scored incorrect against gold, assign one ErrorType. The rules are
checked in this order and the first that fires wins:

1. wrong_unit_or_scale  claimed / gold ≈ 10^±2, 10^±3, 10^±6 or 10^±9 (within tolerance)
2. wrong_period         the claimed value is the same metric, same company, another fiscal year
3. wrong_line_item      the claimed value is another metric, same company and period
4. wrong_company        the claimed value is the same metric and period at another company
5. arithmetic           recomputing the claim's expression from its inputs gives another value
6. retrieval_miss       none of the draft's evidence chunks contains the gold evidence (P2.6)
7. other                no rule fired

Rules 1–5 need a gold value, so a text-gold answer judged incorrect can only be
retrieval_miss or other. XBRL (rules 2–4) only names the error; it never decides
correctness (ROADMAP rule 10). Rules 2–4 run only for metrics in data/metric_map.yaml and
annual (10-K) questions, and they are skipped when the lookup has no value.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from finqa.eval.scoring import within_tolerance
from finqa.schemas import Claim, ErrorType

# (cik, metric, period) -> every value the company reported for it; [] when none.
Lookup = Callable[[str, str, str], list[float]]

SCALE_FACTORS = (1e2, 1e3, 1e6, 1e9)  # 1e2: a fraction given for a percent, or the reverse
PERIOD_OFFSETS = (-1, 1, -2, 2, -3)  # years tried for wrong_period, nearest first


@dataclass(frozen=True)
class Diagnosis:
    question_id: str
    error_type: ErrorType
    detail: str


def _matches(value: float, candidates: Iterable[float], tolerance: float) -> bool:
    return any(within_tolerance(value, c, tolerance) for c in candidates)


def wrong_scale(value: float, gold: float, tolerance: float) -> float | None:
    """The factor (e.g. 1e3 or 1e-3) that turns gold into the claimed value, if any."""
    if gold == 0 or value == 0:
        return None
    for f in SCALE_FACTORS:
        for factor in (f, 1 / f):
            if within_tolerance(value, gold * factor, tolerance):
                return factor
    return None


# --- Safe arithmetic (rule 5) ----------------------------------------------------------------

_OPS: dict[type, Callable[..., float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def evaluate(expression: str, variables: dict[str, float]) -> float:
    """Evaluate + - * / ** and parentheses over named numbers; anything else is rejected."""

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in variables:
            return variables[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.operand))
        raise ValueError(f"not plain arithmetic: {ast.dump(node)[:80]}")

    return walk(ast.parse(expression, mode="eval"))


def recompute(claim: Claim, claims: Sequence[Claim]) -> float | None:
    """The claim's expression evaluated on its inputs (`derived_from`). Variables may be the
    input claim IDs ("c1") or letters a, b, c… in `derived_from` order. None if not possible."""
    if not claim.expression or not claim.derived_from:
        return None
    by_id = {c.claim_id: c.value for c in claims}
    if any(i not in by_id for i in claim.derived_from):
        return None
    variables = {i: by_id[i] for i in claim.derived_from}
    variables |= {chr(ord("a") + n): by_id[i] for n, i in enumerate(claim.derived_from)}
    try:
        result = evaluate(claim.expression, variables)
    except (ValueError, ZeroDivisionError, OverflowError, SyntaxError):
        return None
    if claim.unit == "%" and abs(result) < 10 and abs(claim.value) >= 1:
        result *= 100  # the expression gives a fraction; percent claims are percent numbers
    return result


# --- Classifier ------------------------------------------------------------------------------


def classify(
    question_id: str,
    answer_claim: Claim | None,
    claims: Sequence[Claim],
    gold_value: float | None,
    tolerance: float,
    gold_evidence_retrieved: bool | None,
    cik: str | None = None,
    fiscal_year: int | None = None,
    metrics: Sequence[str] = (),
    other_ciks: Sequence[str] = (),
    lookup: Lookup | None = None,
) -> Diagnosis:
    """One ErrorType for an answer scored incorrect. `fiscal_year` is the question's year for
    a 10-K question (None for 10-Q questions, which skips the XBRL rules)."""

    def found(kind: ErrorType, detail: str) -> Diagnosis:
        return Diagnosis(question_id, kind, detail)

    if answer_claim is not None and gold_value is not None:
        value = answer_claim.value
        factor = wrong_scale(value, gold_value, tolerance)
        if factor is not None:
            return found(ErrorType.WRONG_UNIT, f"claimed = gold × {factor:g}")

        metric = answer_claim.metric
        xbrl_ready = lookup is not None and cik is not None and fiscal_year is not None
        if xbrl_ready and metric in metrics:
            assert lookup is not None and cik is not None and fiscal_year is not None
            for offset in PERIOD_OFFSETS:
                period = f"FY{fiscal_year + offset}"
                if _matches(value, lookup(cik, metric, period), tolerance):
                    return found(ErrorType.WRONG_PERIOD, f"{metric} matches {period}")
            target = f"FY{fiscal_year}"
            for other in metrics:
                if other != metric and _matches(value, lookup(cik, other, target), tolerance):
                    return found(ErrorType.WRONG_LINE_ITEM, f"value is {other} {target}")
            for other_cik in other_ciks:
                if other_cik != cik and _matches(
                    value, lookup(other_cik, metric, target), tolerance
                ):
                    return found(ErrorType.WRONG_COMPANY, f"{metric} {target} of CIK {other_cik}")

        recomputed = recompute(answer_claim, claims)
        if recomputed is not None and not within_tolerance(value, recomputed, tolerance):
            return found(
                ErrorType.ARITHMETIC, f"expression gives {recomputed:g}, claimed {value:g}"
            )

    if gold_evidence_retrieved is False:
        return found(ErrorType.RETRIEVAL_MISS, "gold evidence not in the draft's evidence")
    return found(ErrorType.OTHER, "no rule fired")


def xbrl_lookup(cik: str, metric: str, period: str) -> list[float]:
    """Lookup backed by the Phase 1 XBRL cache; [] when the company has no such value."""
    from finqa.ingestion import xbrl

    try:
        return [f.value for f in xbrl.lookup_metric(cik, metric, period)]
    except KeyError:  # no filing for that period in the manifest
        return []
