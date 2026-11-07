"""Pick the stratified test subset for the midterm runs (ROADMAP M1.1, M1.2).

The free Groq tier allows about 200,000 tokens a day, so R0 on all 107 test questions takes
about 2.5 days (docs/DECISIONS.md, 2026-11-07). The midterm therefore reports S0 and R0 on 40
test questions, allocated to question types in proportion to the test split (largest
remainder) and drawn with a fixed seed. The file is written once, before any test-split run,
and frozen (CI frozen-file guard). The full test split replaces these numbers afterwards.

    uv run python scripts/select_midterm_subset.py
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SPLITS = ROOT / "data" / "splits.json"
OUT = ROOT / "data" / "midterm_subset.json"
SIZE = 40
SEED = 20261107


def allocate(counts: dict[str, int], size: int) -> dict[str, int]:
    """Split `size` across types in proportion to `counts` (largest remainder, ties by name)."""
    total = sum(counts.values())
    exact = {t: n * size / total for t, n in counts.items()}
    alloc = {t: int(x) for t, x in exact.items()}
    by_remainder = sorted(counts, key=lambda t: (-(exact[t] - alloc[t]), t))
    for t in by_remainder[: size - sum(alloc.values())]:
        alloc[t] += 1
    return alloc


def select(splits: dict[str, Any], size: int = SIZE, seed: int = SEED) -> dict[str, Any]:
    test: list[str] = splits["test"]
    types: dict[str, str] = splits["question_types"]
    counts = dict(sorted(Counter(types[q] for q in test).items()))
    alloc = allocate(counts, size)
    rng = random.Random(seed)
    picked: list[str] = []
    for t in sorted(alloc):
        picked += rng.sample(sorted(q for q in test if types[q] == t), alloc[t])
    return {
        "note": "Midterm test subset (ROADMAP M1.1, M1.2; docs/DECISIONS.md 2026-11-07). "
        "Frozen once on main. Written by scripts/select_midterm_subset.py.",
        "seed": seed,
        "size": size,
        "counts": alloc,
        "ids": sorted(picked),
    }


def main() -> int:
    subset = select(json.loads(SPLITS.read_text(encoding="utf-8")))
    OUT.write_text(json.dumps(subset, indent=2) + "\n", encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {subset['size']} questions {subset['counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
