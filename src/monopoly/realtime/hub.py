"""The matchmaker / room registry.

Resolve a room code to a room, create rooms, and route joins. It holds the
in-memory map of active rooms for one server instance. When the server is scaled
across instances, this same ``code -> room`` lookup becomes a shared router
(``room code -> owning instance``) so a room always resolves to the process that
holds its authoritative state -- see docs/decisions/0001-python-only-no-rust.md.
"""

from __future__ import annotations

import secrets
from typing import Dict, Optional

from ..config.presets import long_match, quick_match, standard_match
from ..engine.state import GameConfig
from .room import GameRoom, RoomPhase

# Room codes use an unambiguous alphabet (no O/0, I/1) so they are easy to read
# aloud and type on a phone.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 4

_PRESETS = {
    "quick": quick_match,
    "standard": standard_match,
    "long": long_match,
}


def resolve_config(preset: str, players: int) -> GameConfig:
    """Build a config from a preset name and a requested seat count."""
    factory = _PRESETS.get(preset, quick_match)
    players = max(2, min(players or 4, 6))
    return factory(max_players=players)


class GameHub:
    """Registry of active rooms."""

    def __init__(self) -> None:
        self._rooms: Dict[str, GameRoom] = {}

    def create_room(self, config: GameConfig) -> GameRoom:
        """Create a room with a fresh, unique code."""
        code = self._unique_code()
        room = GameRoom(code, config)
        self._rooms[code] = room
        return room

    def get(self, code: str) -> Optional[GameRoom]:
        """Look up a room by code (case-insensitive)."""
        if not code:
            return None
        return self._rooms.get(code.upper())

    def remove(self, code: str) -> None:
        """Drop a room from the registry (e.g. once finished and empty)."""
        self._rooms.pop(code.upper(), None)

    def prune_finished(self) -> None:
        """Remove finished rooms that have no connected humans left."""
        stale = [
            code
            for code, room in self._rooms.items()
            if room.phase == RoomPhase.OVER and not room.connected_human_seats()
        ]
        for code in stale:
            self._rooms.pop(code, None)

    @property
    def room_count(self) -> int:
        return len(self._rooms)

    def _unique_code(self) -> str:
        for _ in range(1000):
            code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
            if code not in self._rooms:
                return code
        raise RuntimeError("Could not allocate a unique room code")
