"""Statistics for results tables (ROADMAP P2.4; McNemar pulled forward from P9.3).

Question-level bootstrap 95% confidence intervals for every rate, and McNemar's exact test for
two systems scored on the same questions. Pure Python, seeded, so results are reproducible.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass


def bootstrap_ci(
    outcomes: Sequence[bool], n_boot: int = 10_000, level: float = 0.95, seed: int = 0
) -> tuple[float, float] | None:
    """Percentile bootstrap CI for the share of True outcomes, resampling questions.

    None for an empty sample (a rate with no questions has no interval)."""
    n = len(outcomes)
    if n == 0:
        return None
    rng = random.Random(seed)
    values = [int(o) for o in outcomes]
    means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(n_boot))
    tail = (1 - level) / 2
    lo = means[int(math.floor(tail * (n_boot - 1)))]
    hi = means[int(math.ceil((1 - tail) * (n_boot - 1)))]
    return lo, hi


@dataclass(frozen=True)
class McNemar:
    n: int  # questions both systems answered
    both_correct: int
    only_a: int  # A correct, B not
    only_b: int  # B correct, A not
    both_wrong: int
    p_value: float  # exact two-sided binomial test on the discordant pairs


def mcnemar(a_correct: Sequence[bool], b_correct: Sequence[bool]) -> McNemar:
    """McNemar's exact test on paired outcomes (same questions, same order)."""
    if len(a_correct) != len(b_correct):
        raise ValueError("paired outcomes must have the same length")
    pairs = list(zip(a_correct, b_correct, strict=True))
    only_a = sum(a and not b for a, b in pairs)
    only_b = sum(b and not a for a, b in pairs)
    discordant = only_a + only_b
    if discordant == 0:
        p = 1.0
    else:
        k = min(only_a, only_b)
        p = min(1.0, 2 * sum(math.comb(discordant, i) for i in range(k + 1)) / 2**discordant)
    return McNemar(
        n=len(pairs),
        both_correct=sum(a and b for a, b in pairs),
        only_a=only_a,
        only_b=only_b,
        both_wrong=sum(not a and not b for a, b in pairs),
        p_value=p,
    )


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile (q in 0..100); None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def rate(k: int, n: int, outcomes: Sequence[bool] | None = None) -> str:
    """ "8/10, 80.0% [55.0–100.0]": count, percentage and bootstrap 95% CI."""
    if n == 0:
        return "0/0, n/a"
    ci = bootstrap_ci(outcomes if outcomes is not None else [True] * k + [False] * (n - k))
    assert ci is not None
    return f"{k}/{n}, {100 * k / n:.1f}% [{100 * ci[0]:.1f}–{100 * ci[1]:.1f}]"
