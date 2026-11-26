"""Analysis of the 2 x 3 grid: retrieval (R0, R1) x verification (V0, V1, V2).

ROADMAP P8.1 (verification coverage), P9.3 (paired tests, Holm), P9.4 (a bootstrap CI on every
rate), P9.5 (flip matrices) and P9.6 (cost and latency per cell). Pure functions over scored rows
(finqa.eval.tables.Row) and saved V2 results; no model calls. Design choices are in
docs/DECISIONS.md, 2026-11-25:

  - the planned pairs are the 9 below, one Holm family;
  - coverage uses V2's round-1 verdicts (the checks on the draft's own claims);
  - a claim is checkable when at least one of V2's checks compared it against evidence; a
    check "could not run" when it had nothing to compare (no or unretrieved citation, no or
    unknown inputs, an expression that does not evaluate, XBRL's ok=None cases), and is "not
    applicable" to the claim type it skips by design (cited text: computed claims;
    recomputation: quoted claims);
  - accuracy for checkable vs uncheckable is at the answer-claim level (only it has a gold);
  - flip matrices are 3 x 3: correct / incorrect / refused, before vs after verification.

Correctness comes only from finqa.eval.scoring against FinanceBench gold (ROADMAP rule 10):
V2's verdicts here only say which claims could be checked, never whether an answer is right.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence

from finqa.eval import stats, tables
from finqa.schemas import Draft, Verdict, VerifiedResult

# cell label -> (draft config name, verification arm); verified_{arm}.jsonl sits in the draft run
CELLS: dict[str, tuple[str, str]] = {
    "R0-V0": ("r0_v0", "none"),
    "R0-V1": ("r0_v0", "self_check"),
    "R0-V2": ("r0_v0", "grounded"),
    "R1-V0": ("r1_v0", "none"),
    "R1-V1": ("r1_v0", "self_check"),
    "R1-V2": ("r1_v0", "grounded"),
}
# the planned comparisons (A, B): one Holm family (DECISIONS 2026-11-25)
PLANNED_PAIRS: list[tuple[str, str]] = [
    ("R0-V0", "R0-V1"),
    ("R0-V0", "R0-V2"),
    ("R0-V1", "R0-V2"),
    ("R1-V0", "R1-V1"),
    ("R1-V0", "R1-V2"),
    ("R1-V1", "R1-V2"),
    ("R0-V0", "R1-V0"),
    ("R0-V1", "R1-V1"),
    ("R0-V2", "R1-V2"),
]
OUTCOMES = ("correct", "incorrect", "refused")
CHECKS = ("cited_text", "xbrl", "recompute")
ROUND_1 = "round 1: "


# ---------------------------------------------------------------- P9.3 / P9.4 paired tests


def _correct(rows: Sequence[tables.Row]) -> dict[str, bool]:
    return {r.question_id: r.outcome == "correct" for r in rows}


def paired_tests_table(
    rows: Mapping[str, Sequence[tables.Row]],
    pairs: Sequence[tuple[str, str]] = PLANNED_PAIRS,
) -> str:
    """McNemar's exact test for each planned pair, Holm-adjusted over the family, with the
    accuracy difference and its paired bootstrap 95% CI. Refuses cells that cover different
    questions (a paired test needs the same questions)."""
    results = []
    for a_label, b_label in pairs:
        a, b = _correct(rows[a_label]), _correct(rows[b_label])
        if a.keys() != b.keys():
            raise ValueError(f"{a_label} and {b_label} cover different questions")
        ids = sorted(a)
        xa, xb = [a[q] for q in ids], [b[q] for q in ids]
        results.append((a_label, b_label, xa, xb, stats.mcnemar(xa, xb)))
    adjusted = stats.holm([m.p_value for *_, m in results])
    lines = [
        "| A → B | n | A correct | B correct | Difference B − A, pp [95% CI] | A only | B only "
        "| McNemar exact p | Holm p |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for (a_label, b_label, xa, xb, m), p_holm in zip(results, adjusted, strict=True):
        n = len(xa)
        ci = stats.paired_diff_ci(xa, xb)
        diff = f"{100 * (sum(xb) - sum(xa)) / n:+.1f}" if n else "n/a"
        ci_text = f" [{100 * ci[0]:+.1f}, {100 * ci[1]:+.1f}]" if ci is not None else ""
        lines.append(
            f"| {a_label} → {b_label} | {n} | {sum(xa)} | {sum(xb)} | {diff}{ci_text} "
            f"| {m.only_a} | {m.only_b} | {m.p_value:.4f} | {p_holm:.4f} |"
        )
    return "\n".join(lines) + "\n"


def grid_table(rows: Mapping[str, Sequence[tables.Row]]) -> str:
    """Accuracy of each cell, with count and bootstrap 95% CI (the RQ1 grid)."""

    def cell(label: str) -> str:
        correct = [r.outcome == "correct" for r in rows[label]]
        return stats.rate(sum(correct), len(correct), correct)

    lines = ["| Retrieval | V0 (none) | V1 (self-check) | V2 (grounded) |", "|---|---|---|---|"]
    for r in ("R0", "R1"):
        lines.append(f"| {r} | {cell(f'{r}-V0')} | {cell(f'{r}-V1')} | {cell(f'{r}-V2')} |")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- P9.5 flip matrices


def flip_counts(
    before: Sequence[tables.Row], after: Sequence[tables.Row]
) -> dict[tuple[str, str], int]:
    """(outcome before, outcome after) -> questions, on the questions both cover."""
    b = {r.question_id: r.outcome for r in before}
    a = {r.question_id: r.outcome for r in after}
    if b.keys() != a.keys():
        raise ValueError("before and after cover different questions")
    counts = Counter((b[q], a[q]) for q in b)
    return {(x, y): counts.get((x, y), 0) for x in OUTCOMES for y in OUTCOMES}


def flip_table(before: Sequence[tables.Row], after: Sequence[tables.Row], title: str) -> str:
    """3 x 3 matrix: rows = outcome before verification (V0), columns = after."""
    counts = flip_counts(before, after)
    n = sum(counts.values())
    lines = [
        f"**{title}** (n={n}; rows: before, columns: after)",
        "",
        "| Before \\ After | " + " | ".join(OUTCOMES) + " | total |",
        "|---|" + "---|" * (len(OUTCOMES) + 1),
    ]
    for x in OUTCOMES:
        row = [counts[(x, y)] for y in OUTCOMES]
        lines.append(f"| {x} | " + " | ".join(str(c) for c in row) + f" | {sum(row)} |")
    totals = [sum(counts[(x, y)] for x in OUTCOMES) for y in OUTCOMES]
    lines.append("| total | " + " | ".join(str(t) for t in totals) + f" | {n} |")
    fixed = counts[("incorrect", "correct")] + counts[("refused", "correct")]
    broken = counts[("correct", "incorrect")] + counts[("correct", "refused")]
    lines += ["", f"Fixed (→ correct): {fixed}. Broken (correct →): {broken}."]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- P8.1 verification coverage

COMPARED, NOT_APPLICABLE, NOT_RUN = "compared", "not applicable", "could not run"

# By design, V2 checks a quoted claim against its cited text and a computed claim by
# recomputation; the other of the two returns ok=None. That is "not applicable", not a gap.
_NOT_APPLICABLE = {
    "cited_text": re.compile(r"^computed claim: checked by recomputation$"),
    "recompute": re.compile(r"^quoted claim: nothing to recompute$"),
}
# Results with nothing to compare against (DECISIONS 2026-11-25): V2 fails these claims
# (ok=False) or cannot run (ok=None), but either way no evidence was compared. Patterns follow
# the reason strings of finqa.verifiers.grounded.
_NOT_RUN: list[tuple[str, re.Pattern[str], str]] = [
    ("cited_text", re.compile(r"^cites no evidence$"), "no citation"),
    (
        "cited_text",
        re.compile(r", which is not in the retrieved evidence$"),
        "citation not in the retrieved evidence",
    ),
    ("xbrl", re.compile(r"has no XBRL mapping$"), "metric not in the XBRL map"),
    ("xbrl", re.compile(r"^\S+ is in .+, the claim in .+$"), "unit differs from the XBRL metric"),
    ("xbrl", re.compile(r"^company not known$"), "company not known"),
    ("xbrl", re.compile(r"^no XBRL value for "), "no XBRL value for the period"),
    ("recompute", re.compile(r" names no input claims$"), "expression names no inputs"),
    (
        "recompute",
        re.compile(r" are not claims in the draft$"),
        "inputs are not claims in the draft",
    ),
    (
        "recompute",
        re.compile(r" cannot be evaluated on its inputs$"),
        "expression cannot be evaluated",
    ),
]


def round_one(verdicts: Sequence[Verdict]) -> list[Verdict]:
    """V2's checks on the draft's own claims, with the "round 1: " prefix removed."""
    return [
        v.model_copy(update={"reason": v.reason[len(ROUND_1) :]})
        for v in verdicts
        if v.reason.startswith(ROUND_1)
    ]


def check_status(v: Verdict) -> tuple[str, str | None]:
    """(status, reason category): compared, not applicable, or could not run with why.

    ok=None with an unknown reason is "could not run", its text kept with numbers masked so it
    still groups; ok=True/False with no matching reason is "compared"."""
    na = _NOT_APPLICABLE.get(v.check)
    if v.ok is None and na is not None and na.search(v.reason):
        return NOT_APPLICABLE, None
    for check, pattern, label in _NOT_RUN:
        if check == v.check and pattern.search(v.reason):
            return NOT_RUN, label
    if v.ok is None:
        return NOT_RUN, re.sub(r"\d+(\.\d+)?", "#", v.reason)
    return COMPARED, None


def claim_checks(result: VerifiedResult) -> dict[str, dict[str, Verdict]]:
    """claim_id -> {check: round-1 verdict}, for every claim of the draft."""
    out: dict[str, dict[str, Verdict]] = {c.claim_id: {} for c in result.claims_before}
    for v in round_one(result.verdicts):
        if v.check in CHECKS:
            out.setdefault(v.claim_id, {})[v.check] = v
    return out


def checkable(checks: Mapping[str, Verdict]) -> bool:
    """At least one check compared the claim against evidence (DECISIONS 2026-11-25)."""
    return any(check_status(v)[0] == COMPARED for v in checks.values())


def coverage_section(
    label: str,
    verified: Sequence[VerifiedResult],
    drafts: Sequence[Draft],
    rows_before: Sequence[tables.Row],
    rows_after: Sequence[tables.Row],
    top: int = 10,
) -> str:
    """P8.1 for one V2 cell: per-check coverage over the claims each check applies to, claims
    no check could compare, accuracy against gold (V0 and V2) for questions whose answer claim
    was checkable or not, and the top reasons a check could not run. Failed generations and
    failed verifications have no verdicts and are counted apart."""
    by_q = {d.question_id: d for d in drafts}
    claims: list[dict[str, Verdict]] = []
    failed_claims = 0
    answer_group: dict[str, str] = {}
    reasons: Counter[tuple[str, str]] = Counter()
    for r in verified:
        d = by_q[r.question_id]
        if d.error is not None:
            answer_group[r.question_id] = "generation failed"
            continue
        if r.error is not None:
            failed_claims += len(r.claims_before)
            answer_group[r.question_id] = "verification failed"
            continue
        per_claim = claim_checks(r)
        claims += per_claim.values()
        for checks in per_claim.values():
            for v in checks.values():
                status, why = check_status(v)
                if status == NOT_RUN and why is not None:
                    reasons[(v.check, why)] += 1
        if d.answer_claim_id is None or d.answer_claim_id not in per_claim:
            answer_group[r.question_id] = "no answer claim"
        elif checkable(per_claim[d.answer_claim_id]):
            answer_group[r.question_id] = "answer claim checkable"
        else:
            answer_group[r.question_id] = "answer claim not checkable"

    n = len(claims)
    computed = sum(
        c.get("cited_text") is not None and check_status(c["cited_text"])[0] == NOT_APPLICABLE
        for c in claims
    )
    lines = [
        f"### {label}\n",
        f"Claims: {n} (round 1, the draft's own claims): {n - computed} quoted, {computed} "
        f"computed. Claims of failed verifications (no verdicts): {failed_claims}. A check "
        "is not applicable by design to the other claim type (cited text: quoted claims; "
        "recomputation: computed claims); it could not run when it had nothing to compare.\n",
        "| Check | Applies to | Compared (of applicable) | Passed (of compared) "
        "| Failed (of compared) |",
        "|---|---|---|---|---|",
    ]
    for check in CHECKS:
        statuses = [check_status(c[check])[0] for c in claims if check in c]
        applicable = [s for s in statuses if s != NOT_APPLICABLE]
        ran = [s == COMPARED for s in applicable]
        oks = [c[check].ok is True for c in claims if check in c and _compared(c[check])]
        bad = [not ok for ok in oks]
        lines.append(
            f"| {check} | {len(applicable)} | {stats.rate(sum(ran), len(ran), ran)} "
            f"| {stats.rate(sum(oks), len(oks), oks)} | {stats.rate(sum(bad), len(bad), bad)} |"
        )
    any_ran = [checkable(c) for c in claims]
    none_ran = [not x for x in any_ran]
    lines += [
        f"| **checkable** (any check compared) | {n} | {stats.rate(sum(any_ran), n, any_ran)} "
        "| | |",
        f"| **not checkable** | {n} | {stats.rate(sum(none_ran), n, none_ran)} | | |",
        "",
        "Accuracy against gold, by whether V2 could check the answer claim:\n",
        "| Questions | n | Accuracy before (V0) | Accuracy after (V2) |",
        "|---|---|---|---|",
    ]
    before = {r.question_id: r.outcome == "correct" for r in rows_before}
    after = {r.question_id: r.outcome == "correct" for r in rows_after}
    groups = (
        "answer claim checkable",
        "answer claim not checkable",
        "no answer claim",
        "generation failed",
        "verification failed",
    )
    for group in groups:
        ids = sorted(q for q, g in answer_group.items() if g == group)
        if not ids:
            continue
        xb = [before[q] for q in ids]
        xa = [after[q] for q in ids]
        lines.append(
            f"| {group} | {len(ids)} | {stats.rate(sum(xb), len(xb), xb)} "
            f"| {stats.rate(sum(xa), len(xa), xa)} |"
        )
    lines += [
        "",
        f"Top reasons a check could not run ({sum(reasons.values())} check results; "
        "not-applicable checks are not counted):\n",
        "| Check | Reason | Count |",
        "|---|---|---|",
    ]
    lines += [f"| {c} | {why} | {k} |" for (c, why), k in reasons.most_common(top)]
    return "\n".join(lines) + "\n"


def _compared(v: Verdict) -> bool:
    return check_status(v)[0] == COMPARED


# ---------------------------------------------------------------- P9.6 cost and latency


def cost_table(rows: Mapping[str, Sequence[tables.Row]]) -> str:
    """Latency, tokens and estimated cost per cell (draft plus verification)."""
    return tables.efficiency_table([(label, rows[label]) for label in CELLS])
