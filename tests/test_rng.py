"""Tests for the deterministic RNG -- the foundation of every guarantee."""

from __future__ import annotations

from monopoly.engine.rng import SeededRng


def test_same_seed_same_sequence():
    a = SeededRng.from_seed(12345)
    b = SeededRng.from_seed(12345)
    assert [a.next_u64() for _ in range(20)] == [b.next_u64() for _ in range(20)]


def test_different_seeds_diverge():
    a = SeededRng.from_seed(1)
    b = SeededRng.from_seed(2)
    assert [a.next_u64() for _ in range(10)] != [b.next_u64() for _ in range(10)]


def test_randint_within_bounds_and_uniform_ish():
    rng = SeededRng.from_seed(99)
    counts = {i: 0 for i in range(1, 7)}
    for _ in range(6000):
        roll = rng.roll_die(6)
        assert 1 <= roll <= 6
        counts[roll] += 1
    # Every face should appear; rough uniformity (not a strict statistical test).
    assert all(c > 700 for c in counts.values())


def test_randint_single_value():
    rng = SeededRng.from_seed(7)
    assert rng.randint(5, 5) == 5


def test_next_float_range():
    rng = SeededRng.from_seed(3)
    for _ in range(1000):
        f = rng.next_float()
        assert 0.0 <= f < 1.0


def test_clone_is_independent():
    rng = SeededRng.from_seed(42)
    rng.next_u64()
    clone = rng.clone()
    assert clone.next_u64() == SeededRng(state=rng.state).next_u64()
