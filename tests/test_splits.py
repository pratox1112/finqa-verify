import pytest
from make_splits import build


def rows(*items):
    return [{"financebench_id": i, "confirmed_type": t} for i, t in items]


def test_dev_is_the_pilot_questions_and_test_the_rest():
    s = build(rows(("a", "calculation"), ("b", "qualitative"), ("c", "single_fact")), {"a"})
    assert s["dev"] == ["a"] and s["test"] == ["b", "c"]
    assert s["question_types"]["b"] == "qualitative"


def test_refuses_unconfirmed_rows():
    with pytest.raises(ValueError, match="not confirmed"):
        build(rows(("a", "calculation"), ("b", "")), {"a"})


def test_refuses_pilot_question_out_of_scope():
    with pytest.raises(ValueError, match="pilot"):
        build(rows(("a", "calculation")), {"a", "z"})
