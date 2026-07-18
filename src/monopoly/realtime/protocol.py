"""The WebSocket wire protocol -- the contract between client and server.

All frames are JSON text. This module is the single source of truth for message
shapes so the frontend, the server, and any tests agree. It has no dependency on
the transport (``websockets``) or on asyncio, so the same contract holds however
the server is hosted.

Design (architecture 1 & 6.2): clients are dumb. They send *intent* and receive
the full authoritative state to re-render. The server never trusts a client's
claimed ``player_id`` -- it overrides it with the seat bound to that connection.

Client -> Server
----------------
* ``{"type": "authenticate", "mode": "guest", "device_key": str?, "name": str?, "locale": str?}``
* ``{"type": "authenticate", "mode": "session", "token": str}``
* ``{"type": "create_room", "name": str?, "preset": "quick|standard|long", "players": int, "session": str?}``
* ``{"type": "join_room", "room": str, "name": str?, "session": str?}``
* ``{"type": "reconnect", "room": str, "token": str}``
* ``{"type": "start"}``                              (host only)
* ``{"type": "action", "action": {"type": ..., ...}}``  (player_id is ignored/overridden)

``session`` is the token returned by ``authenticate``; it binds the seat to an
account so progression (XP / level / rating) accrues. It is a server-issued
bearer capability, never a password. Omit it (and skip ``authenticate``) to play
as an anonymous guest -- the game still runs, it just earns no progression.
``authenticate mode=guest`` with a stored ``device_key`` reclaims a previous
guest account; without one it creates a new guest and returns a fresh
``device_key`` for the client to remember.

Server -> Client
----------------
* ``{"type": "authenticated", "session": str, "device_key": str?, "account": <profile>}``
* ``{"type": "room_created", "room": str, "seat": int, "token": str}``
* ``{"type": "joined", "room": str, "seat": int, "token": str}``
* ``{"type": "lobby", "room": str, "seats": [...], "host": int}``
* ``{"type": "state", "you": int, "your_turn": bool, "available": [str],``
  ``  "events": [ledger-entry], "state": <public GameState>}``
* ``{"type": "event", "kind": str, "note": str}``   (optional drama beats)
* ``{"type": "error", "code": str, "message": str}``
"""

from __future__ import annotations

from typing import Any, Dict, List


class ClientMsg:
    """Message ``type`` values a client may send."""

    AUTHENTICATE = "authenticate"
    CREATE_ROOM = "create_room"
    JOIN_ROOM = "join_room"
    RECONNECT = "reconnect"
    START = "start"
    ACTION = "action"


class ServerMsg:
    """Message ``type`` values the server may send."""

    AUTHENTICATED = "authenticated"
    ROOM_CREATED = "room_created"
    JOINED = "joined"
    LOBBY = "lobby"
    STATE = "state"
    EVENT = "event"
    ERROR = "error"


# --- Server -> client builders --------------------------------------------

def authenticated(session: str, account: dict, device_key: str | None = None) -> Dict[str, Any]:
    """Confirm a login: the session token, the account profile, and (for a newly
    created guest) the device key the client should store to return later."""
    msg: Dict[str, Any] = {
        "type": ServerMsg.AUTHENTICATED,
        "session": session,
        "account": account,
    }
    if device_key is not None:
        msg["device_key"] = device_key
    return msg


def room_created(room: str, seat: int, token: str) -> Dict[str, Any]:
    return {"type": ServerMsg.ROOM_CREATED, "room": room, "seat": seat, "token": token}


def joined(room: str, seat: int, token: str) -> Dict[str, Any]:
    return {"type": ServerMsg.JOINED, "room": room, "seat": seat, "token": token}


def lobby(room: str, seats: List[dict], host: int) -> Dict[str, Any]:
    return {"type": ServerMsg.LOBBY, "room": room, "seats": seats, "host": host}


def state_message(
    you: int,
    your_turn: bool,
    available: List[str],
    events: List[dict],
    public_state: dict,
) -> Dict[str, Any]:
    """Build the per-recipient state broadcast.

    ``you`` is the recipient's seat, so the client knows which player is theirs.
    ``available`` is a best-effort hint of currently-legal action types for that
    seat (the server still validates every action authoritatively). ``events`` are
    the ledger entries appended by the action that triggered this broadcast --
    the raw material for drama popups.
    """
    return {
        "type": ServerMsg.STATE,
        "you": you,
        "your_turn": your_turn,
        "available": available,
        "events": events,
        "state": public_state,
    }


def event(kind: str, note: str) -> Dict[str, Any]:
    return {"type": ServerMsg.EVENT, "kind": kind, "note": note}


def error(code: str, message: str) -> Dict[str, Any]:
    return {"type": ServerMsg.ERROR, "code": code, "message": message}


# --- Validation helpers ----------------------------------------------------

class ProtocolError(Exception):
    """Raised when an incoming frame is malformed (bad JSON handled by caller)."""


def require_fields(msg: dict, fields: List[str]) -> None:
    """Raise :class:`ProtocolError` if any required field is missing."""
    missing = [f for f in fields if f not in msg]
    if missing:
        raise ProtocolError(f"Missing field(s): {', '.join(missing)}")
