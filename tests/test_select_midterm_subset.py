import json
from pathlib import Path

from select_midterm_subset import OUT, SPLITS, allocate, select


def test_allocation_is_proportional_and_sums_to_size():
    assert allocate({"a": 31, "b": 24, "c": 35, "d": 17}, 40) == {"a": 12, "b": 9, "c": 13, "d": 6}
    assert sum(allocate({"a": 1, "b": 1, "c": 1}, 2).values()) == 2


def test_subset_is_stratified_and_inside_test():
    splits = json.loads(SPLITS.read_text(encoding="utf-8"))
    subset = select(splits)
    ids = subset["ids"]
    assert len(ids) == len(set(ids)) == 40
    assert set(ids) <= set(splits["test"])
    types = splits["question_types"]
    for t, n in subset["counts"].items():
        assert sum(types[q] == t for q in ids) == n


def test_same_seed_same_subset_and_matches_committed_file():
    splits = json.loads(SPLITS.read_text(encoding="utf-8"))
    assert select(splits) == select(splits)
    assert select(splits, seed=1)["ids"] != select(splits)["ids"]
    assert json.loads(Path(OUT).read_text(encoding="utf-8")) == select(splits)
