"""Tests for the persistence layer: schema, save/read round-trip, replay, stats."""

from __future__ import annotations

import pytest

from monopoly.config import build_roster, quick_match
from monopoly.persistence import db
from monopoly.persistence.store import GameStore
from monopoly.simulation import play_game


@pytest.fixture
def store() -> GameStore:
    # ":memory:" keeps every test isolated and touches no real filesystem.
    return GameStore(db.connect(":memory:"))


def _play_one(seed: int = 1, players: int = 3):
    config = quick_match(max_players=players)
    roster = build_roster(config)
    result = play_game(config, seed, roster)
    return config, result


# --- Save / read round-trip -------------------------------------------------

def test_save_and_get_game_round_trips(store: GameStore):
    config, result = _play_one(seed=1)
    game_id = store.save_completed_game(result, room_code="ABCD")

    record = store.get_game(game_id)
    assert record is not None
    assert record["room_code"] == "ABCD"
    assert record["seed"] == result.seed
    assert record["winner_id"] == result.winner_id
    assert record["winner_name"] == result.winner_name
    assert record["rounds_played"] == result.rounds_played
    assert len(record["action_log"]) == len(result.action_log)
    assert len(record["participants"]) == len(result.final_players)


def test_get_unknown_game_returns_none(store: GameStore):
    assert store.get_game("nope") is None


def test_list_recent_games_orders_newest_first(store: GameStore):
    _, r1 = _play_one(seed=1)
    id1 = store.save_completed_game(r1, room_code="AAAA", started_at="2026-01-01T00:00:00+00:00", ended_at="2026-01-01T00:10:00+00:00")
    _, r2 = _play_one(seed=2)
    id2 = store.save_completed_game(r2, room_code="BBBB", started_at="2026-01-02T00:00:00+00:00", ended_at="2026-01-02T00:10:00+00:00")

    recent = store.list_recent_games(limit=10)
    ids = [g["id"] for g in recent]
    assert ids.index(id2) < ids.index(id1)  # id2 ended later -> comes first


# --- Replay (audit) ---------------------------------------------------------

def test_replay_game_reproduces_stored_winner(store: GameStore):
    config, result = _play_one(seed=42, players=4)
    game_id = store.save_completed_game(result, room_code="REPL")

    state = store.replay_game(game_id)
    from monopoly.engine.reducer import winner

    win = winner(state)
    assert (win.id if win else None) == result.winner_id


def test_replay_unknown_game_raises(store: GameStore):
    with pytest.raises(KeyError):
        store.replay_game("nope")


# --- User stats / leaderboard -----------------------------------------------

def test_player_key_accrues_stats_across_games(store: GameStore):
    config, result = _play_one(seed=7, players=2)
    # Attribute seat 0 to a tracked identity regardless of who actually won;
    # we just verify games_played increments and games_won reflects wins.
    keys = {0: "alice-key"}

    store.save_completed_game(result, room_code="G1", player_keys=keys)
    board = store.leaderboard()
    alice = next(r for r in board if r["player_key"] == "alice-key")
    assert alice["games_played"] == 1
    assert alice["games_won"] == (1 if result.winner_id == 0 else 0)

    # A second game for the same identity accumulates.
    _, result2 = _play_one(seed=8, players=2)
    store.save_completed_game(result2, room_code="G2", player_keys=keys)
    board = store.leaderboard()
    alice = next(r for r in board if r["player_key"] == "alice-key")
    assert alice["games_played"] == 2


def test_anonymous_participants_do_not_create_user_rows(store: GameStore):
    config, result = _play_one(seed=3, players=2)
    store.save_completed_game(result, room_code="ANON")  # no player_keys at all
    assert store.leaderboard() == []


def test_leaderboard_orders_by_wins_desc(store: GameStore):
    # Seed/roster chosen so each game has a determinate winner; we only assert
    # ordering behaviour, not which seed wins.
    _, r1 = _play_one(seed=11, players=2)
    store.save_completed_game(r1, room_code="G1", player_keys={0: "p0", 1: "p1"})
    _, r2 = _play_one(seed=12, players=2)
    store.save_completed_game(r2, room_code="G2", player_keys={0: "p0", 1: "p1"})

    board = store.leaderboard()
    win_counts = {row["player_key"]: row["games_won"] for row in board}
    ordered_wins = [row["games_won"] for row in board]
    assert ordered_wins == sorted(ordered_wins, reverse=True)
    assert sum(win_counts.values()) == 2  # exactly two games, one winner each


# --- Schema sanity -----------------------------------------------------------

def test_connect_applies_schema_without_raising():
    # A second, independent connect() call must also succeed cleanly -- the
    # schema uses CREATE TABLE IF NOT EXISTS throughout, so re-applying it (as
    # every server start does against the on-disk database) is always safe.
    conn = db.connect(":memory:")
    store = GameStore(conn)
    assert store.list_recent_games() == []
