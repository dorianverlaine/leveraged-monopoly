"""WebSocket server -- the thin transport adapter around the authoritative room.

This is the only module that touches asyncio and the ``websockets`` library. It
maps connections to opaque session ids, forwards parsed frames to the hub/room,
and fans authoritative state broadcasts back out. All game logic lives in
:mod:`monopoly.realtime.room`; keeping the network shell this thin keeps the room
transport-agnostic and lets the whole server run as a long-lived Python process
(on AWS, in the deployment plan).

Run it::

    pip install -e ".[realtime]"
    monopoly-server --host 0.0.0.0 --port 8765

``websockets`` is an optional dependency; it is imported lazily so the rest of the
package (engine, bots, simulation) stays dependency-free.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from typing import Dict, Optional

from ..accounts import record_finished_game
from ..accounts.store import AccountStore
from ..persistence import db as persistence_db
from ..persistence.store import GameStore
from .hub import GameHub, resolve_config
from .room import GameRoom, RoomPhase
from . import protocol

# Delay between successive bot moves, so a bot turn animates instead of flashing
# past. Tunable; the game is turn-based and tolerant of latency (architecture 6.2).
_BOT_STEP_DELAY_SECONDS = 0.6


class Connection:
    """A live client connection bound to one session id and (later) one room."""

    def __init__(self, session_id: str, ws) -> None:
        self.session_id = session_id
        self.ws = ws
        self.room: Optional[GameRoom] = None
        # Set once the client authenticates (guest or session token).
        self.account_id: Optional[str] = None


class RealtimeServer:
    """Owns the hub, the connection table, and the broadcast machinery.

    ``game_store`` / ``account_store`` are optional repositories. When both are
    provided, every finished game is persisted exactly once and the participating
    accounts get their XP / level / rating / streaks updated (architecture 7.3,
    9). Pass ``None`` (the default) to run stateless, e.g. in tests -- the CLI
    entry point (``main``) wires up a real database by default.
    """

    def __init__(
        self,
        game_store: Optional[GameStore] = None,
        account_store: Optional[AccountStore] = None,
    ) -> None:
        self.hub = GameHub()
        self.game_store = game_store
        self.account_store = account_store
        # session_id -> Connection (the socket registry the room deliberately
        # does not hold, so the room stays transport-agnostic).
        self.connections: Dict[str, Connection] = {}

    # --- Connection lifecycle ------------------------------------------

    async def handle(self, ws) -> None:
        """Top-level handler for one WebSocket connection."""
        session_id = uuid.uuid4().hex
        conn = Connection(session_id, ws)
        self.connections[session_id] = conn
        try:
            async for raw in ws:
                await self._on_message(conn, raw)
        finally:
            await self._on_close(conn)

    async def _on_close(self, conn: Connection) -> None:
        """Handle a dropped connection: free the seat to bot control, notify room."""
        self.connections.pop(conn.session_id, None)
        room = conn.room
        if room is None:
            return
        room.disconnect(conn.session_id)
        # If it was this player's turn, bots must take over so play continues.
        await self._drive_bots(room)
        await self._broadcast_state(room)
        self.hub.prune_finished()

    # --- Message routing ------------------------------------------------

    async def _on_message(self, conn: Connection, raw) -> None:
        try:
            msg = json.loads(raw)
            if not isinstance(msg, dict) or "type" not in msg:
                raise ValueError("frame must be a JSON object with a 'type'")
        except (ValueError, TypeError) as exc:
            await self._send(conn, protocol.error("bad_frame", str(exc)))
            return

        handlers = {
            protocol.ClientMsg.AUTHENTICATE: self._authenticate,
            protocol.ClientMsg.CREATE_ROOM: self._create_room,
            protocol.ClientMsg.JOIN_ROOM: self._join_room,
            protocol.ClientMsg.RECONNECT: self._reconnect,
            protocol.ClientMsg.START: self._start,
            protocol.ClientMsg.ACTION: self._action,
        }
        handler = handlers.get(msg["type"])
        if handler is None:
            await self._send(conn, protocol.error("unknown_type", f"Unknown message '{msg['type']}'"))
            return
        await handler(conn, msg)

    async def _authenticate(self, conn: Connection, msg: dict) -> None:
        """Log the connection in as a guest (optionally reclaiming an account) or
        via an existing session token, binding it to an account for progression."""
        if self.account_store is None:
            await self._send(conn, protocol.error("no_accounts", "Accounts are disabled on this server"))
            return

        mode = msg.get("mode", "guest")
        if mode == "session":
            account = self.account_store.account_for_session(msg.get("token", ""))
            if account is None:
                await self._send(conn, protocol.error("bad_session", "Session token not recognised"))
                return
            conn.account_id = account.id
            await self._send(conn, protocol.authenticated(msg["token"], account.public_profile()))
            return

        # Guest mode: reclaim by device key if given, else create a new guest.
        device_key = msg.get("device_key")
        new_device_key: Optional[str] = None
        if device_key:
            reclaimed = self.account_store.login_guest(device_key)
            if reclaimed is None:
                await self._send(conn, protocol.error("bad_device_key", "Guest account not found"))
                return
            account, token = reclaimed
        else:
            account, new_device_key, token = self.account_store.create_guest(
                display_name=msg.get("name"), locale=msg.get("locale")
            )
        conn.account_id = account.id
        await self._send(
            conn, protocol.authenticated(token, account.public_profile(), device_key=new_device_key)
        )

    async def _create_room(self, conn: Connection, msg: dict) -> None:
        account = self._resolve_account(conn, msg)
        config = resolve_config(msg.get("preset", "quick"), int(msg.get("players", 4)))
        room = self.hub.create_room(config)
        seat_token = room.add_human(
            conn.session_id, self._seat_name(msg, account, "Host"), account_id=conn.account_id
        )
        if seat_token is None:  # should not happen on a fresh room
            await self._send(conn, protocol.error("room_full", "Room is full"))
            return
        seat, token = seat_token
        conn.room = room
        await self._send(conn, protocol.room_created(room.code, seat, token))
        await self._broadcast_lobby(room)

    async def _join_room(self, conn: Connection, msg: dict) -> None:
        account = self._resolve_account(conn, msg)
        room = self.hub.get(msg.get("room", ""))
        if room is None:
            await self._send(conn, protocol.error("no_such_room", "Room not found"))
            return
        seat_token = room.add_human(
            conn.session_id, self._seat_name(msg, account, "Player"), account_id=conn.account_id
        )
        if seat_token is None:
            await self._send(conn, protocol.error("cannot_join", "Room is full or already started"))
            return
        seat, token = seat_token
        conn.room = room
        await self._send(conn, protocol.joined(room.code, seat, token))
        await self._broadcast_lobby(room)

    def _resolve_account(self, conn: Connection, msg: dict):
        """Bind the connection to an account from an inline ``session`` token, if
        provided and not already authenticated. Returns the account or ``None``."""
        if conn.account_id is None and self.account_store is not None and msg.get("session"):
            account = self.account_store.account_for_session(msg["session"])
            if account is not None:
                conn.account_id = account.id
                return account
        if conn.account_id is not None and self.account_store is not None:
            return self.account_store.get_account(conn.account_id)
        return None

    @staticmethod
    def _seat_name(msg: dict, account, fallback: str) -> str:
        """Pick a display name: explicit > account profile > fallback."""
        return msg.get("name") or (account.display_name if account else None) or fallback

    async def _reconnect(self, conn: Connection, msg: dict) -> None:
        room = self.hub.get(msg.get("room", ""))
        if room is None:
            await self._send(conn, protocol.error("no_such_room", "Room not found"))
            return
        seat = room.reconnect(conn.session_id, msg.get("token", ""))
        if seat is None:
            await self._send(conn, protocol.error("bad_token", "Reconnect token not recognised"))
            return
        conn.room = room
        # Resync: ship the full current state (or lobby) to just this client.
        if room.state is not None:
            await self._send(conn, room.state_message_for(seat))
        else:
            await self._send(conn, room.lobby_message())

    async def _start(self, conn: Connection, msg: dict) -> None:
        room = conn.room
        if room is None:
            await self._send(conn, protocol.error("no_room", "Join or create a room first"))
            return
        err = room.start(conn.session_id)
        if err is not None:
            await self._send(conn, err)
            return
        await self._broadcast_state(room)
        # The opening seat could be a bot (e.g. host left before starting).
        await self._drive_bots(room)

    async def _action(self, conn: Connection, msg: dict) -> None:
        room = conn.room
        if room is None:
            await self._send(conn, protocol.error("no_room", "You are not in a room"))
            return
        outcome = room.handle_action(conn.session_id, msg.get("action", {}))
        if not outcome.ok:
            await self._send(conn, outcome.error)
            return
        await self._broadcast_state(room, outcome.events)
        await self._drive_bots(room)

    # --- Bots -----------------------------------------------------------

    async def _drive_bots(self, room: GameRoom) -> None:
        """Step bot / disconnected seats one at a time, broadcasting each move."""
        while room.bot_up():
            events = room.step_bot()
            if events is None:
                break
            await self._broadcast_state(room, events)
            await asyncio.sleep(_BOT_STEP_DELAY_SECONDS)

    # --- Sending --------------------------------------------------------

    async def _broadcast_state(self, room: GameRoom, events=None) -> None:
        """Send a per-seat state frame to every connected human in the room."""
        if room.state is None:
            await self._broadcast_lobby(room)
            return
        for seat in room.connected_human_seats():
            conn = self.connections.get(seat.session_id)
            if conn is not None:
                await self._send(conn, room.state_message_for(seat.index, events))
        # Every state broadcast is a natural checkpoint to notice a just-finished
        # game and persist it exactly once (see room.persisted).
        self._maybe_persist(room)

    def _maybe_persist(self, room: GameRoom) -> None:
        """Persist a room's completed game (and update accounts) once, when done.

        Synchronous and cheap (a few local SQLite writes) so it is safe to call
        from the broadcast path without awaiting; ``room.persisted`` makes this
        idempotent even if called from multiple broadcast points. Requires both
        stores; with either missing, persistence is simply skipped.
        """
        if (
            self.game_store is None
            or self.account_store is None
            or room.phase != RoomPhase.OVER
            or room.persisted
        ):
            return
        result = room.to_game_result()
        if result is None:
            return
        record_finished_game(
            self.game_store,
            self.account_store,
            result,
            account_ids_by_seat=room.account_ids(),
            room_code=room.code,
            started_at=room.started_at,
            ended_at=room.ended_at,
        )
        room.persisted = True

    async def _broadcast_lobby(self, room: GameRoom) -> None:
        message = room.lobby_message()
        for seat in room.connected_human_seats():
            conn = self.connections.get(seat.session_id)
            if conn is not None:
                await self._send(conn, message)

    async def _send(self, conn: Connection, payload: dict) -> None:
        """Serialize and send one frame, ignoring a closed socket.

        ``allow_nan=False`` is deliberate: Python happily emits bare ``Infinity``
        / ``NaN``, which are *not* valid JSON and which browsers refuse to parse
        -- a single such value silently makes the whole frame unreadable to a web
        client. Failing loudly here turns that into an obvious server error
        instead of a mystery on the client.
        """
        try:
            body = json.dumps(payload, allow_nan=False)
        except ValueError:
            body = json.dumps(
                protocol.error("bad_state", "State contained a non-JSON value")
            )
        try:
            await conn.ws.send(body)
        except Exception:
            # The connection is going away; _on_close will clean it up.
            pass


async def _serve(
    host: str,
    port: int,
    game_store: Optional[GameStore],
    account_store: Optional[AccountStore],
) -> None:
    # Lazy import so the optional dependency is only required to actually serve.
    try:
        import websockets
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "The 'websockets' package is required to run the server. "
            "Install it with:  pip install -e \".[realtime]\""
        ) from exc

    server = RealtimeServer(game_store=game_store, account_store=account_store)
    async with websockets.serve(server.handle, host, port):
        print(f"Leveraged Monopoly realtime server listening on ws://{host}:{port}")
        if game_store is not None:
            print("Accounts + game history are being recorded (see monopoly-history).")
        await asyncio.Future()  # run forever


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Leveraged Monopoly WebSocket server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--db",
        default=None,
        help=f"SQLite path for accounts + game history (default: {persistence_db.DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Disable persistence entirely (no accounts, no game history)",
    )
    args = parser.parse_args(argv)

    game_store = None
    account_store = None
    if not args.no_persist:
        # Accounts and game history share one database (one identity model).
        conn = persistence_db.connect(args.db or persistence_db.DEFAULT_DB_PATH)
        game_store = GameStore(conn)
        account_store = AccountStore(conn)

    try:
        asyncio.run(_serve(args.host, args.port, game_store, account_store))
    except KeyboardInterrupt:  # pragma: no cover
        print("\nShutting down.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
