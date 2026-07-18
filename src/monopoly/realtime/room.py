"""The authoritative game room -- transport-agnostic.

One room owns exactly one authoritative ``GameState`` and is the single place it
may be mutated (only ever through ``reduce``): a single-threaded, in-memory
authoritative object, which is what makes race conditions structurally
impossible. It deliberately knows nothing about WebSockets or asyncio -- it takes
opaque ``session_id`` strings and returns plain dicts -- so the same class can be
driven by the ``websockets`` server here, exercised directly in tests, or run in
any other Python host. At scale, each room is pinned to one server instance (see
docs/decisions/0001-python-only-no-rust.md).

Responsibilities:
* lobby: seat assignment, human/bot backfill, reconnection tokens;
* play: validate a human's action (overriding the claimed player_id with their
  bound seat -- anti-cheat), apply it via ``reduce``, and surface the resulting
  ledger events;
* bots: drive bot seats *and* disconnected human seats so the game never stalls.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..bots.registry import make_policy
from ..engine.actions import Action, end_turn
from ..engine.errors import RuleError
from ..engine.player import Player, PlayerStatus
from ..engine.reducer import reduce
from ..engine.state import GameConfig, GameState, new_game
from ..simulation.runner import GameResult, summarize_game
from . import hints, protocol


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# Upper bound on bot steps processed in one drive, so a pathological state can
# never spin forever inside the server event loop.
_MAX_BOT_STEPS = 5_000


class RoomPhase:
    LOBBY = "lobby"
    PLAYING = "playing"
    OVER = "over"


@dataclass
class Seat:
    """One seat in the room: a human (possibly disconnected) or a bot."""

    index: int
    name: str
    is_bot: bool
    policy: str = ""                       # bot policy name (bots only)
    session_id: Optional[str] = None       # bound connection, if a human
    token: Optional[str] = None            # reconnection secret (humans only)
    connected: bool = False
    # The account that holds this seat (resolved by the server from a session
    # token), used to attribute progression when the game ends. None for bots or
    # anonymous guests who played without logging in.
    account_id: Optional[str] = None

    def summary(self) -> dict:
        """Public lobby view (never exposes the token)."""
        return {
            "seat": self.index,
            "name": self.name,
            "is_bot": self.is_bot,
            "connected": self.connected,
        }


@dataclass
class ActionOutcome:
    """Result of applying a human action: an error for the sender, or events."""

    ok: bool
    error: Optional[dict] = None            # protocol.error(...) payload if not ok
    events: List[dict] = field(default_factory=list)  # ledger entries produced


class GameRoom:
    """One authoritative game, from lobby through to game over."""

    def __init__(
        self,
        code: str,
        config: GameConfig,
        bot_rotation: Optional[List[str]] = None,
        default_policy: str = "conservative",
    ) -> None:
        self.code = code
        self.config = config
        self.default_policy = default_policy
        self.phase = RoomPhase.LOBBY
        self.state: Optional[GameState] = None
        self.seed: Optional[int] = None
        self.host_seat: Optional[int] = None

        # Every accepted action (human or bot), in order -- together with
        # ``seed`` this *is* the replay (architecture 9). Populated once play
        # starts; persisted alongside the final result when the game ends.
        self.action_log: List[Action] = []
        self.started_at: Optional[str] = None
        self.ended_at: Optional[str] = None
        # Guards against double-persisting the same finished game.
        self.persisted: bool = False

        rotation = bot_rotation or ["degen", "conservative", "cashflow", "contrarian"]
        # Start every seat as a bot; humans claim seats from the top as they join.
        self.seats: List[Seat] = [
            Seat(
                index=i,
                name=f"Bot-{rotation[i % len(rotation)]}",
                is_bot=True,
                policy=rotation[i % len(rotation)],
            )
            for i in range(config.max_players)
        ]

    # --- Lobby ----------------------------------------------------------

    def add_human(
        self, session_id: str, name: str, account_id: Optional[str] = None
    ) -> Optional[tuple]:
        """Claim the lowest open bot seat for a human. Returns ``(seat, token)``.

        ``account_id`` is the logged-in account holding the seat (resolved by the
        server from a session token), or ``None`` for an anonymous guest. Returns
        ``None`` if the room is full of humans or no longer in the lobby.
        """
        if self.phase != RoomPhase.LOBBY:
            return None
        for seat in self.seats:
            if seat.is_bot and seat.session_id is None:
                seat.is_bot = False
                seat.policy = ""
                seat.name = name or f"Player {seat.index}"
                seat.session_id = session_id
                seat.token = secrets.token_urlsafe(16)
                seat.connected = True
                seat.account_id = account_id
                if self.host_seat is None:
                    self.host_seat = seat.index
                return seat.index, seat.token
        return None

    def start(self, session_id: str) -> Optional[dict]:
        """Begin the game (host only). Returns a protocol error dict, or ``None``.

        Freezes the seat roster into players and boots a fresh, seeded game.
        """
        if self.phase != RoomPhase.LOBBY:
            return protocol.error("already_started", "The game has already started")
        host = self._seat_by_index(self.host_seat)
        if host is None or host.session_id != session_id:
            return protocol.error("not_host", "Only the host can start the game")

        roster = [
            Player(id=s.index, name=s.name, cash=self.config.starting_cash,
                   is_bot=s.is_bot, policy=s.policy)
            for s in self.seats
        ]
        self.seed = secrets.randbits(64)
        self.state = new_game(self.config, self.seed, roster)
        self.phase = RoomPhase.PLAYING
        self.started_at = _now_iso()
        return None

    # --- Connection lifecycle ------------------------------------------

    def reconnect(self, session_id: str, token: str) -> Optional[int]:
        """Re-bind a connection to a seat via its token. Returns the seat, or None."""
        for seat in self.seats:
            if seat.token is not None and seat.token == token:
                seat.session_id = session_id
                seat.connected = True
                return seat.index
        return None

    def disconnect(self, session_id: str) -> Optional[int]:
        """Mark the seat bound to ``session_id`` as disconnected. Returns the seat.

        The human keeps their seat and token; until they reconnect, a bot drives
        their turns so the game never stalls (architecture 7.4).
        """
        for seat in self.seats:
            if seat.session_id == session_id:
                seat.connected = False
                seat.session_id = None
                return seat.index
        return None

    def seat_for_session(self, session_id: str) -> Optional[Seat]:
        for seat in self.seats:
            if seat.session_id == session_id:
                return seat
        return None

    # --- Play -----------------------------------------------------------

    def handle_action(self, session_id: str, action_dict: dict) -> ActionOutcome:
        """Validate and apply a human's action, returning its outcome.

        The sender's ``player_id`` is taken from their bound seat, never from the
        payload, so a client cannot act as another player.
        """
        if self.phase != RoomPhase.PLAYING or self.state is None:
            return ActionOutcome(False, protocol.error("not_playing", "Game is not in progress"))

        seat = self.seat_for_session(session_id)
        if seat is None:
            return ActionOutcome(False, protocol.error("not_seated", "You are not seated in this room"))

        action = Action(
            type=action_dict.get("type", ""),
            player_id=seat.index,                       # authoritative override
            tile_index=action_dict.get("tile_index"),
            amount=action_dict.get("amount"),
            percent=action_dict.get("percent"),
        )

        before = len(self.state.ledger)
        outcome = reduce(self.state, action)
        if isinstance(outcome, RuleError):
            return ActionOutcome(False, protocol.error(outcome.code, outcome.message))

        self.state = outcome
        self.action_log.append(action)  # the seat-corrected action, not the raw payload
        events = [e.to_dict() for e in self.state.ledger[before:]]
        self._refresh_phase()
        return ActionOutcome(True, events=events)

    def bot_up(self) -> bool:
        """True if it is currently a bot / disconnected seat's turn to act."""
        if self.phase != RoomPhase.PLAYING or self.state is None or self.state.is_over():
            return False
        return self._is_bot_driven(self.seats[self.state.turn.active_player])

    def step_bot(self) -> Optional[List[dict]]:
        """Apply exactly one action for the current bot / disconnected seat.

        Returns the ledger events that step produced, or ``None`` if it is not a
        bot-driven seat's turn. Exposing a *single* step lets the server broadcast
        and pace bot moves one at a time for drama, while ``advance_bots`` drives
        them all at once for headless tests.
        """
        if not self.bot_up():
            return None
        assert self.state is not None
        seat = self.seats[self.state.turn.active_player]

        policy_name = seat.policy if seat.is_bot else self.default_policy
        action = make_policy(policy_name).decide(self.state, seat.index)

        before = len(self.state.ledger)
        outcome = reduce(self.state, action)
        if isinstance(outcome, RuleError):
            # A policy proposed something illegal; fall back to ending the turn.
            action = end_turn(seat.index)
            outcome = reduce(self.state, action)
            if isinstance(outcome, RuleError):
                return None  # cannot progress this seat; let the caller stop
        self.state = outcome
        self.action_log.append(action)
        events = [e.to_dict() for e in self.state.ledger[before:]]
        self._refresh_phase()
        return events

    def advance_bots(self) -> List[List[dict]]:
        """Drive every consecutive bot / disconnected seat until a human is up.

        Returns one entry per bot step (the ledger events it produced). Used by
        the headless tests; the live server prefers :meth:`step_bot` so it can
        pace and broadcast each move.
        """
        steps: List[List[dict]] = []
        guard = 0
        while self.bot_up() and guard < _MAX_BOT_STEPS:
            guard += 1
            events = self.step_bot()
            if events is None:
                break
            steps.append(events)
        return steps

    # --- Broadcasts / views --------------------------------------------

    def lobby_message(self) -> dict:
        return protocol.lobby(
            self.code, [s.summary() for s in self.seats], self.host_seat or 0
        )

    def state_message_for(self, seat_index: int, events: Optional[List[dict]] = None) -> dict:
        """Build the per-seat state broadcast (see protocol.state_message)."""
        assert self.state is not None
        your_turn = (
            not self.state.is_over()
            and self.state.turn.active_player == seat_index
        )
        return protocol.state_message(
            you=seat_index,
            your_turn=your_turn,
            available=hints.available_action_types(self.state, seat_index),
            events=events or [],
            public_state=self.state.to_public_dict(),
        )

    def connected_human_seats(self) -> List[Seat]:
        """Seats currently held by a connected human (broadcast targets)."""
        return [s for s in self.seats if not s.is_bot and s.connected and s.session_id]

    @property
    def is_over(self) -> bool:
        return self.phase == RoomPhase.OVER

    # --- Persistence handoff ---------------------------------------------

    def account_ids(self) -> Dict[int, Optional[str]]:
        """Seat index -> the account id bound to it (or ``None`` for bots/guests)."""
        return {s.index: s.account_id for s in self.seats}

    def to_game_result(self) -> Optional[GameResult]:
        """Package the finished game the same way headless simulation does.

        Returns ``None`` unless the game has actually ended. Reuses
        :func:`~monopoly.simulation.runner.summarize_game` so a live multiplayer
        game and a headless backtest game produce the identical result shape --
        one ingestion point for persistence either way.
        """
        if self.state is None or not self.state.is_over():
            return None
        return summarize_game(
            self.state, self.seed, self.config, self.action_log, truncated=False
        )

    # --- Internals ------------------------------------------------------

    def _seat_by_index(self, index: Optional[int]) -> Optional[Seat]:
        if index is None:
            return None
        return self.seats[index] if 0 <= index < len(self.seats) else None

    def _is_bot_driven(self, seat: Seat) -> bool:
        """A seat is auto-driven if it is a bot or a disconnected human."""
        return seat.is_bot or not seat.connected

    def _refresh_phase(self) -> None:
        if self.state is not None and self.state.is_over():
            if self.phase != RoomPhase.OVER:
                self.ended_at = _now_iso()
            self.phase = RoomPhase.OVER
