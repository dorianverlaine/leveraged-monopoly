"""Tests for the real-time plane -- exercised through the transport-agnostic room.

No sockets and no asyncio here: the room takes opaque session-id strings and
returns plain dicts, so the full lobby -> play -> bots flow is unit-testable.
"""

from __future__ import annotations

from monopoly.config import quick_match
from monopoly.engine.state import GamePhase
from monopoly.realtime.hub import GameHub, resolve_config
from monopoly.realtime.room import RoomPhase


def _room_with_host(players: int = 4, player_key=None):
    hub = GameHub()
    room = hub.create_room(resolve_config("quick", players))
    seat, token = room.add_human("sess-host", "Alice", player_key=player_key)
    return hub, room, seat, token


def _run_to_completion(room, guard_limit: int = 10_000) -> None:
    """Drive a started room (bots + a minimal human policy) to game over."""
    guard = 0
    while not room.is_over and guard < guard_limit:
        guard += 1
        if room.bot_up():
            room.advance_bots()
            continue
        active = room.state.turn.active_player
        session = room.seats[active].session_id
        if room.state.turn.phase == GamePhase.AWAIT_ROLL:
            room.handle_action(session, {"type": "roll_dice"})
        else:
            room.handle_action(session, {"type": "end_turn"})


# --- Lobby -----------------------------------------------------------------

def test_host_takes_seat_zero_and_others_join_bot_seats():
    hub, room, seat, token = _room_with_host(players=4)
    assert seat == 0
    assert room.host_seat == 0
    assert token  # a reconnection token was issued

    seat1, _ = room.add_human("sess-bob", "Bob")
    assert seat1 == 1
    # Bob's seat is now human; the rest stay bots.
    assert room.seats[1].is_bot is False
    assert room.seats[2].is_bot is True


def test_only_host_can_start():
    hub, room, seat, token = _room_with_host()
    room.add_human("sess-bob", "Bob")

    err = room.start("sess-bob")            # non-host
    assert err is not None and err["code"] == "not_host"
    assert room.phase == RoomPhase.LOBBY

    assert room.start("sess-host") is None  # host
    assert room.phase == RoomPhase.PLAYING
    assert room.state is not None


# --- Play & anti-cheat -----------------------------------------------------

def test_action_player_id_is_overridden_by_seat():
    # Anti-cheat: a client claiming another player's id still acts only as its
    # own bound seat.
    hub, room, seat, token = _room_with_host()
    room.start("sess-host")
    assert room.state.turn.phase == GamePhase.AWAIT_ROLL

    # Host (seat 0) sends a roll but lies that it is player 1's action.
    outcome = room.handle_action("sess-host", {"type": "roll_dice", "player_id": 1})
    assert outcome.ok
    # It resolved as seat 0's roll (seat 0 moved), not player 1's.
    assert room.state.players[0].position != 0
    assert room.state.turn.phase == GamePhase.AWAIT_ACTION


def test_action_from_unseated_session_rejected():
    hub, room, seat, token = _room_with_host()
    room.start("sess-host")
    outcome = room.handle_action("sess-stranger", {"type": "roll_dice"})
    assert not outcome.ok
    assert outcome.error["code"] == "not_seated"


def test_action_before_start_rejected():
    hub, room, seat, token = _room_with_host()
    outcome = room.handle_action("sess-host", {"type": "roll_dice"})
    assert not outcome.ok
    assert outcome.error["code"] == "not_playing"


# --- Reconnect / disconnect ------------------------------------------------

def test_reconnect_with_token_rebinds_seat():
    hub, room, seat, token = _room_with_host()
    room.start("sess-host")
    room.disconnect("sess-host")
    assert room.seats[0].connected is False

    new_seat = room.reconnect("sess-host-2", token)
    assert new_seat == 0
    assert room.seats[0].connected is True
    assert room.seats[0].session_id == "sess-host-2"
    # After reconnect we can build a resync snapshot for that seat.
    msg = room.state_message_for(0)
    assert msg["you"] == 0 and "state" in msg


def test_disconnected_human_is_bot_driven():
    hub, room, seat, token = _room_with_host()
    room.start("sess-host")
    room.disconnect("sess-host")
    # With the only human gone, every seat is bot-driven -> the game can finish.
    room.advance_bots()
    assert room.is_over


# --- Full game through the room -------------------------------------------

def test_full_game_with_one_human_reaches_game_over():
    hub, room, seat, token = _room_with_host(players=4)
    room.start("sess-host")
    _run_to_completion(room)
    assert room.is_over
    assert room.state.is_over()


# --- Serialization safety --------------------------------------------------

def test_public_state_omits_rng():
    hub, room, seat, token = _room_with_host()
    room.start("sess-host")
    public = room.state.to_public_dict()
    # The RNG state must never reach a client (it predicts future dice/shocks).
    assert "rng" not in public
    assert "board" in public and "players" in public


def test_resolve_config_clamps_player_count():
    assert resolve_config("quick", 99).max_players == 6
    assert resolve_config("quick", 1).max_players == 2
    assert resolve_config("standard", 5).max_players == 5


# --- Persistence handoff ----------------------------------------------------
# The room builds the GameResult / player_keys the persistence layer consumes;
# see tests/test_persistence.py for the storage layer itself and
# RealtimeServer._maybe_persist for how the two are wired together live.

def test_to_game_result_is_none_before_game_over():
    hub, room, seat, token = _room_with_host()
    assert room.to_game_result() is None
    room.start("sess-host")
    assert room.to_game_result() is None  # in progress, not finished


def test_to_game_result_matches_engine_after_completion():
    hub, room, seat, token = _room_with_host(players=3, player_key="alice-key")
    room.start("sess-host")
    _run_to_completion(room)

    result = room.to_game_result()
    assert result is not None
    assert result.seed == room.seed
    assert result.action_log == [a.to_dict() for a in room.action_log]
    from monopoly.engine.reducer import winner

    win = winner(room.state)
    assert result.winner_id == (win.id if win else None)


def test_player_keys_reflects_seat_bindings():
    hub, room, seat, token = _room_with_host(players=3, player_key="alice-key")
    room.add_human("sess-bob", "Bob")  # no player_key -> anonymous guest
    keys = room.player_keys()
    assert keys[0] == "alice-key"
    assert keys[1] is None
    assert keys[2] is None  # untouched bot seat


def test_finished_room_persists_exactly_once_via_server():
    from monopoly.persistence import db
    from monopoly.persistence.store import GameStore
    from monopoly.realtime.server import RealtimeServer

    store = GameStore(db.connect(":memory:"))
    server = RealtimeServer(store=store)

    hub, room, seat, token = _room_with_host(players=3, player_key="alice-key")
    room.start("sess-host")
    _run_to_completion(room)

    server._maybe_persist(room)
    assert room.persisted is True

    recent = store.list_recent_games(limit=5)
    assert len(recent) == 1
    assert recent[0]["room_code"] == room.code

    board = store.leaderboard()
    alice = next(r for r in board if r["player_key"] == "alice-key")
    assert alice["games_played"] == 1

    # Calling again must not create a second record (idempotent persistence).
    server._maybe_persist(room)
    assert len(store.list_recent_games(limit=5)) == 1
