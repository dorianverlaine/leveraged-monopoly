"""Repository for completed games and player stats.

Fills the "games" + "users" role from the architecture's D1 plane (7.3, 9):
persist the seed + action_log of every finished game (the whole replay in a few
KB) plus enough participant rows to answer "how many games has X won" without
re-parsing JSON. ``GameStore`` is the only thing the rest of the codebase talks
to; it never leaks raw SQL to callers.

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
    """SQLite-backed repository for completed games, participants, and users."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # --- Writing ----------------------------------------------------------

    def save_completed_game(
        self,
        result: GameResult,
        room_code: str,
        player_keys: Optional[Dict[int, Optional[str]]] = None,
        started_at: Optional[str] = None,
        ended_at: Optional[str] = None,
    ) -> str:
        """Persist a finished game and update participant/user stats.

        ``player_keys`` maps seat index -> an opaque client-supplied identity, or
        ``None``/absent for bots and anonymous humans (their game still gets
        recorded; they just accrue no cross-game stats). Returns the new game id.
        """
        player_keys = player_keys or {}
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
                key = player_keys.get(seat)
                self._conn.execute(
                    """
                    INSERT INTO game_participants (
                        game_id, seat, player_key, name, is_bot, policy,
                        net_worth, status, is_winner
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        game_id,
                        seat,
                        key,
                        p["name"],
                        int(p["is_bot"]),
                        p.get("policy", ""),
                        p["net_worth"],
                        p["status"],
                        int(is_winner),
                    ),
                )
                if key:
                    self._upsert_user_stats(key, p["name"], won=is_winner, when=now)

        return game_id

    def _upsert_user_stats(self, player_key: str, display_name: str, won: bool, when: str) -> None:
        """Create or update a user's running stats after one of their games."""
        self._conn.execute(
            """
            INSERT INTO users (player_key, display_name, games_played, games_won, first_seen, last_seen)
            VALUES (?, ?, 1, ?, ?, ?)
            ON CONFLICT(player_key) DO UPDATE SET
                display_name = excluded.display_name,
                games_played = games_played + 1,
                games_won = games_won + excluded.games_won,
                last_seen = excluded.last_seen
            """,
            (player_key, display_name, int(won), when, when),
        )

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

    def leaderboard(self, limit: int = 20) -> List[dict]:
        """Return known players ranked by win count, most wins first."""
        rows = self._conn.execute(
            """
            SELECT player_key, display_name, games_played, games_won,
                   CAST(games_won AS REAL) / games_played AS win_rate
            FROM users
            ORDER BY games_won DESC, win_rate DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

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
