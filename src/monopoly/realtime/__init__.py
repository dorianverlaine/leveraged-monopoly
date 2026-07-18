"""Real-time transport plane -- authoritative rooms over WebSocket.

Mirrors the Cloudflare edge design (architecture 7): a stateless entrypoint
(:class:`~monopoly.realtime.hub.GameHub`) routes players to per-game authoritative
rooms (:class:`~monopoly.realtime.room.GameRoom`), each of which owns exactly one
``GameState`` mutated only through ``reduce``. The room is transport-agnostic and
unit-testable; :mod:`~monopoly.realtime.server` is the thin ``websockets`` adapter
around it.

The engine, bots, and simulation packages remain dependency-free. Only the server
needs the optional ``websockets`` dependency (``pip install -e ".[realtime]"``).
"""

from __future__ import annotations

from .hub import GameHub, resolve_config
from .room import ActionOutcome, GameRoom, RoomPhase, Seat

__all__ = [
    "GameHub",
    "resolve_config",
    "GameRoom",
    "RoomPhase",
    "Seat",
    "ActionOutcome",
]
