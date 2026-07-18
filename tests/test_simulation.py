"""Tests for full-game simulation, determinism, and replay."""

from __future__ import annotations

from monopoly.config import build_roster, quick_match, standard_match
from monopoly.simulation import play_game, replay, run_batch


def test_game_reaches_a_terminal_state():
    config = quick_match(max_players=4)
    roster = build_roster(config)
    result = play_game(config, seed=42, roster=roster)
    # A quick match uses a round limit, so it must terminate with a winner.
    assert result.winner_id is not None
    assert result.num_actions > 0
    assert not result.truncated


def test_determinism_same_seed_same_outcome():
    config = quick_match(max_players=4)
    r1 = play_game(config, seed=7, roster=build_roster(config))
    r2 = play_game(config, seed=7, roster=build_roster(config))
    assert r1.to_dict() == r2.to_dict()


def test_different_seeds_generally_differ():
    config = quick_match(max_players=4)
    a = play_game(config, seed=1, roster=build_roster(config))
    b = play_game(config, seed=2, roster=build_roster(config))
    # Not a hard guarantee, but different seeds should not produce identical logs.
    assert a.action_log != b.action_log


def test_replay_reproduces_final_state():
    config = quick_match(max_players=4)
    roster = build_roster(config)
    result = play_game(config, seed=99, roster=roster)

    # Replaying seed + action_log must reproduce the exact final state.
    final = replay(config, seed=99, roster=build_roster(config), action_log=result.action_log)
    from monopoly.engine import valuation

    replayed_players = {
        p.id: round(valuation.net_worth(final, p.id), 2) for p in final.players
    }
    original_players = {p["id"]: p["net_worth"] for p in result.final_players}
    assert replayed_players == original_players


def test_backtest_batch_produces_win_distribution():
    config = standard_match(max_players=4)
    report = run_batch(
        config,
        seeds=list(range(8)),
        roster_factory=lambda: build_roster(config),
    )
    assert report.games == 8
    # Every game should attribute a win to some policy (or 'none' if all died).
    assert sum(report.wins_by_policy.values()) == 8
    assert report.avg_rounds > 0
