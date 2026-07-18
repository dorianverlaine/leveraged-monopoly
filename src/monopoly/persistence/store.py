"""Repository for completed-game records and replays.

Fills the "games" role from the architecture's D1 plane (7.3, 9): persist the
seed + action_log of every finished game (the whole replay in a few KB) plus a
participant row per seat. ``GameStore`` is the only thing that touches the game
tables; it never leaks raw SQL to callers.

Player *progression* (XP, level, rating, streaks) is a separate concern and lives
in :class:`monopoly.accounts.store.AccountStore`; the two are joined by the
optional ``account_id`` recorded on each participant.
:func:`monopoly.accounts.service.record_finished_game` is the coordinator that
saves a game here and updates accounts there in one step.

Every finished game -- headless simulation or live multiplayer room -- produces
the same :class:`~monopoly.simulation.runner.GameResult` shape, so
:meth:`GameStore.save_completed_game` is the single ingestion point for both.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..engine.player import Player
from ..engine.state import GameConfig, GameState
from ..simulation.runner import GameResult, replay


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string (the timestamp format used here)."""
    return datetime.now(timezone.utc).isoformat()


class GameStore:
    """SQLite-backed repository for completed-game records and their replays."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # --- Writing ----------------------------------------------------------

    def save_completed_game(
        self,
        result: GameResult,
        room_code: str,
        account_ids_by_seat: Optional[Dict[int, Optional[str]]] = None,
        started_at: Optional[str] = None,
        ended_at: Optional[str] = None,
    ) -> str:
        """Persist a finished game and its per-seat participant rows.

        ``account_ids_by_seat`` maps seat index -> the account that held the seat,
        or ``None``/absent for bots and anonymous guests (their game still gets
        recorded; they just aren't linked to an account). Progression updates are
        the coordinator's job, not this method's. Returns the new game id.
        """
        account_ids = account_ids_by_seat or {}
        game_id = uuid.uuid4().hex
        now = utc_now_iso()
        roster = [
            {"id": p["id"], "name": p["name"], "is_bot": p["is_bot"], "policy": p.get("policy", "")}
            for p in result.final_players
        ]

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO games (
                    id, room_code, config_json, seed, roster_json, action_log_json,
                    winner_id, winner_name, rounds_played, shocks_fired, truncated,
                    started_at, ended_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    room_code,
                    json.dumps(result.config.to_dict()),
                    str(result.seed),
                    json.dumps(roster),
                    json.dumps(result.action_log),
                    result.winner_id,
                    result.winner_name,
                    result.rounds_played,
                    result.shocks_fired,
                    int(result.truncated),
                    started_at or now,
                    ended_at or now,
                ),
            )

            for p in result.final_players:
                seat = p["id"]
                is_winner = seat == result.winner_id
                self._conn.execute(
                    """
                    INSERT INTO game_participants (
                        game_id, seat, account_id, name, is_bot, policy,
                        net_worth, status, is_winner
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        game_id,
                        seat,
                        account_ids.get(seat),
                        p["name"],
                        int(p["is_bot"]),
                        p.get("policy", ""),
                        p["net_worth"],
                        p["status"],
                        int(is_winner),
                    ),
                )

        return game_id

    # --- Reading ------------------------------------------------------------

    def get_game(self, game_id: str) -> Optional[dict]:
        """Return one game's record plus its participants, or ``None`` if unknown."""
        row = self._conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        if row is None:
            return None
        participants = self._conn.execute(
            "SELECT * FROM game_participants WHERE game_id = ? ORDER BY seat", (game_id,)
        ).fetchall()
        return self._game_row_to_dict(row, participants)

    def list_recent_games(self, limit: int = 20) -> List[dict]:
        """Return the most recently finished games, newest first."""
        rows = self._conn.execute(
            "SELECT * FROM games ORDER BY ended_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._game_row_to_dict(row, participants=None) for row in rows]

    def games_for_account(self, account_id: str, limit: int = 20) -> List[dict]:
        """Return the most recent games an account played in, newest first.

        Each entry is the game record joined with that account's own result
        (seat, net worth, whether they won) -- the raw material for a match
        history / profile page.
        """
        rows = self._conn.execute(
            """
            SELECT g.*, p.seat AS my_seat, p.net_worth AS my_net_worth,
                   p.status AS my_status, p.is_winner AS my_is_winner
            FROM game_participants p
            JOIN games g ON g.id = p.game_id
            WHERE p.account_id = ?
            ORDER BY g.ended_at DESC
            LIMIT ?
            """,
            (account_id, limit),
        ).fetchall()
        history = []
        for row in rows:
            entry = self._game_row_to_dict(row, participants=None)
            entry["my_result"] = {
                "seat": row["my_seat"],
                "net_worth": row["my_net_worth"],
                "status": row["my_status"],
                "is_winner": bool(row["my_is_winner"]),
            }
            history.append(entry)
        return history

    def replay_game(self, game_id: str) -> GameState:
        """Reconstruct the final ``GameState`` for a stored game by re-running it.

        Proves the "replay = re-execution" property (architecture 9, 11): if the
        engine now rejects an action from a stored log, the log is corrupt or the
        rules drifted since the game was recorded, and :func:`replay` raises.
        """
        record = self.get_game(game_id)
        if record is None:
            raise KeyError(f"No such game: {game_id}")

        config = GameConfig.from_dict(record["config"])
        roster = [
            Player(id=p["id"], name=p["name"], cash=0, is_bot=p["is_bot"], policy=p["policy"])
            for p in record["roster"]
        ]
        return replay(config, record["seed"], roster, record["action_log"])

    # --- Internals ------------------------------------------------------

    def _game_row_to_dict(self, row: sqlite3.Row, participants: Optional[list]) -> dict:
        """Deserialize a ``games`` row (plus optional participant rows) to a dict."""
        data = {
            "id": row["id"],
            "room_code": row["room_code"],
            "config": json.loads(row["config_json"]),
            "seed": int(row["seed"]),
            "roster": json.loads(row["roster_json"]),
            "action_log": json.loads(row["action_log_json"]),
            "winner_id": row["winner_id"],
            "winner_name": row["winner_name"],
            "rounds_played": row["rounds_played"],
            "shocks_fired": row["shocks_fired"],
            "truncated": bool(row["truncated"]),
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
        }
        if participants is not None:
            data["participants"] = [dict(p) for p in participants]
        return data
