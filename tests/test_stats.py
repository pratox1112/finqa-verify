import pytest

from finqa.eval import stats


def test_bootstrap_is_seeded_and_bounded():
    outcomes = [True] * 8 + [False] * 2
    ci = stats.bootstrap_ci(outcomes)
    assert ci == stats.bootstrap_ci(outcomes)
    lo, hi = ci
    assert 0 <= lo <= 0.8 <= hi <= 1


def test_bootstrap_edges():
    assert stats.bootstrap_ci([]) is None
    assert stats.bootstrap_ci([True] * 5) == (1.0, 1.0)
    assert stats.bootstrap_ci([False] * 5) == (0.0, 0.0)


def test_mcnemar_known_values():
    # 6 questions only A gets right, 0 only B: exact p = 2 * (1/2)^6 = 0.03125
    m = stats.mcnemar([True] * 6 + [True, False], [False] * 6 + [True, False])
    assert (m.n, m.both_correct, m.only_a, m.only_b, m.both_wrong) == (8, 1, 6, 0, 1)
    assert m.p_value == pytest.approx(0.03125)


def test_mcnemar_no_discordant_pairs():
    assert stats.mcnemar([True, False], [True, False]).p_value == 1.0


def test_mcnemar_needs_pairs():
    with pytest.raises(ValueError):
        stats.mcnemar([True], [True, False])


def test_percentile_and_rate():
    assert stats.percentile([1, 2, 3, 4], 50) == 2
    assert stats.percentile([1, 2, 3, 4], 95) == 4
    assert stats.percentile([], 50) is None
    assert stats.rate(0, 0) == "0/0, n/a"
    assert stats.rate(8, 10).startswith("8/10, 80.0% [")
