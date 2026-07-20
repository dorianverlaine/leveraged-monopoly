"""Tests for the real-time plane -- exercised through the transport-agnostic room.

No sockets and no asyncio here: the room takes opaque session-id strings and
returns plain dicts, so the full lobby -> play -> bots flow is unit-testable.
"""

from __future__ import annotations

from monopoly.config import quick_match
from monopoly.engine.state import GamePhase
from monopoly.realtime.hub import GameHub, resolve_config
from monopoly.realtime.room import RoomPhase


def _room_with_host(players: int = 4, account_id=None):
    hub = GameHub()
    room = hub.create_room(resolve_config("quick", players))
    seat, token = room.add_human("sess-host", "Alice", account_id=account_id)
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


def test_action_forwards_trade_parameters():
    # Regression: the room used to rebuild Action with only tile_index/amount/
    # percent, silently dropping target_player_id / offer_tiles / trade_id, so
    # trading was impossible over the wire even though the engine supported it.
    hub, room, seat, token = _room_with_host(players=3)
    room.add_human("sess-bob", "Bob")
    room.start("sess-host")
    room.state.players[0].cash = 500

    outcome = room.handle_action(
        "sess-host",
        {"type": "propose_trade", "target_player_id": 1, "offer_cash": 100,
         "offer_tiles": {}, "request_cash": 0, "request_tiles": {}},
    )
    assert outcome.ok, outcome.error
    assert len(room.state.trades) == 1
    offer = room.state.trades[0]
    assert offer.proposer_id == 0 and offer.recipient_id == 1
    assert offer.offer_cash == 100

    # And the recipient can resolve it by id, also over the wire.
    accepted = room.handle_action("sess-bob", {"type": "accept_trade", "trade_id": offer.id})
    assert accepted.ok, accepted.error
    assert room.state.trades == []


def test_bots_answer_a_humans_trade_offer():
    # Regression: trading is not turn-gated, so a human can propose at any time --
    # but the live room had no way for a bot to answer outside its own turn, so
    # offers sat unanswered forever and trading looked broken to a real player.
    hub, room, seat, token = _room_with_host(players=3)
    room.start("sess-host")
    room.state.players[0].cash = 2000

    # Offer a bot generous cash for nothing; a fair-value bot should accept.
    outcome = room.handle_action(
        "sess-host",
        {"type": "propose_trade", "target_player_id": 1, "offer_cash": 500,
         "offer_tiles": {}, "request_cash": 0, "request_tiles": {}},
    )
    assert outcome.ok, outcome.error
    assert len(room.state.trades) == 1

    steps = room.resolve_bot_trades()
    assert steps, "the bot recipient never answered the offer"
    assert room.state.trades == []          # resolved, not left dangling
    assert room.state.players[0].cash == 1500  # the cash actually moved


def test_live_rooms_include_the_shark():
    # Regression: the room kept its own copy of the bot rotation, which drifted
    # from the shared one and silently excluded the strongest bot from live play.
    hub = GameHub()
    room = hub.create_room(resolve_config("quick", 6))
    assert "shark" in {s.policy for s in room.seats}


def test_malformed_action_payload_is_rejected_cleanly():
    hub, room, seat, token = _room_with_host()
    room.start("sess-host")
    outcome = room.handle_action("sess-host", {"type": "propose_trade", "offer_tiles": "not-a-dict"})
    assert not outcome.ok  # a bad payload must not crash the room


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

def test_public_state_is_strict_json():
    # Regression: a debt-free player's margin ratio is infinite, and Python
    # serialises float('inf') as bare `Infinity` -- which is NOT valid JSON and
    # which browsers refuse to parse, making the entire state frame unreadable
    # to the web client. Python's own json.loads accepts it, so only a real
    # browser caught this. allow_nan=False is what a strict parser does.
    import json

    hub, room, seat, token = _room_with_host(players=3)
    room.start("sess-host")
    payload = room.state_message_for(0)
    encoded = json.dumps(payload, allow_nan=False)  # raises if Infinity/NaN leak
    assert json.loads(encoded)["state"]["players"][0]["margin_ratio"] is None


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
# The room builds the GameResult / account_ids the persistence layer consumes;
# see tests/test_persistence.py and tests/test_accounts.py for the stores, and
# RealtimeServer._maybe_persist for how they are wired together live.

def test_to_game_result_is_none_before_game_over():
    hub, room, seat, token = _room_with_host()
    assert room.to_game_result() is None
    room.start("sess-host")
    assert room.to_game_result() is None  # in progress, not finished


def test_to_game_result_matches_engine_after_completion():
    hub, room, seat, token = _room_with_host(players=3, account_id="acc-alice")
    room.start("sess-host")
    _run_to_completion(room)

    result = room.to_game_result()
    assert result is not None
    assert result.seed == room.seed
    assert result.action_log == [a.to_dict() for a in room.action_log]
    from monopoly.engine.reducer import winner

    win = winner(room.state)
    assert result.winner_id == (win.id if win else None)


def test_account_ids_reflects_seat_bindings():
    hub, room, seat, token = _room_with_host(players=3, account_id="acc-alice")
    room.add_human("sess-bob", "Bob")  # no account_id -> anonymous guest
    ids = room.account_ids()
    assert ids[0] == "acc-alice"
    assert ids[1] is None
    assert ids[2] is None  # untouched bot seat


def test_finished_room_persists_and_updates_accounts_once_via_server():
    from monopoly.accounts.store import AccountStore
    from monopoly.persistence import db
    from monopoly.persistence.store import GameStore
    from monopoly.realtime.server import RealtimeServer

    conn = db.connect(":memory:")
    game_store = GameStore(conn)
    account_store = AccountStore(conn)
    server = RealtimeServer(game_store=game_store, account_store=account_store)

    alice, _, _ = account_store.create_guest(display_name="Alice")
    hub, room, seat, token = _room_with_host(players=3, account_id=alice.id)
    room.start("sess-host")
    _run_to_completion(room)

    server._maybe_persist(room)
    assert room.persisted is True

    recent = game_store.list_recent_games(limit=5)
    assert len(recent) == 1
    assert recent[0]["room_code"] == room.code

    # Alice's account accrued a game via the coordinator.
    alice2 = account_store.get_account(alice.id)
    assert alice2.games_played == 1
    assert alice2.xp > 0

    # Calling again must not create a second record (idempotent persistence).
    server._maybe_persist(room)
    assert len(game_store.list_recent_games(limit=5)) == 1
    assert account_store.get_account(alice.id).games_played == 1
