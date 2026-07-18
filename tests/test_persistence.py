"""Tests for the game-record persistence layer: save/read, replay, history."""

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


def test_account_id_recorded_on_participants(store: GameStore):
    config, result = _play_one(seed=1, players=2)
    # Bind seat 0 to an account id; seat 1 stays null (bot/anonymous).
    game_id = store.save_completed_game(result, room_code="ACCT", account_ids_by_seat={0: "acc-123"})
    record = store.get_game(game_id)
    by_seat = {p["seat"]: p for p in record["participants"]}
    assert by_seat[0]["account_id"] == "acc-123"
    assert by_seat[1]["account_id"] is None


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


def test_games_for_account_returns_only_that_accounts_games(store: GameStore):
    _, r1 = _play_one(seed=1, players=2)
    store.save_completed_game(r1, room_code="G1", account_ids_by_seat={0: "acc-A"})
    _, r2 = _play_one(seed=2, players=2)
    store.save_completed_game(r2, room_code="G2", account_ids_by_seat={1: "acc-B"})

    a_games = store.games_for_account("acc-A")
    assert len(a_games) == 1
    assert a_games[0]["room_code"] == "G1"
    assert a_games[0]["my_result"]["seat"] == 0
    assert "is_winner" in a_games[0]["my_result"]

    assert store.games_for_account("acc-nobody") == []


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


# --- Schema sanity -----------------------------------------------------------

def test_connect_applies_schema_without_raising():
    # A second, independent connect() call must also succeed cleanly -- the
    # schema uses CREATE TABLE IF NOT EXISTS throughout, so re-applying it (as
    # every server start does against the on-disk database) is always safe.
    conn = db.connect(":memory:")
    store = GameStore(conn)
    assert store.list_recent_games() == []
