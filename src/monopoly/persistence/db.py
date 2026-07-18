"""SQLite connection and schema -- the local stand-in for D1 (architecture 7.3, 9).

Games, participants, and users all live in one small relational schema. This is
intentionally the *only* module that touches ``sqlite3`` directly: swapping the
cloud target to D1 later means replacing this module's connection layer, while
:mod:`monopoly.persistence.store` (the repository API) stays the same.

No credentials or auth ever pass through here -- a player is identified only by
an opaque ``player_key`` string the client supplies (e.g. from ``localStorage``),
matching the architecture's "auth handled by the client/session layer, never
through the game" rule (architecture 11).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union

# Default on-disk location for a locally-run server. A cloud deployment targets
# D1 instead and never touches this path.
DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "leveraged-monopoly" / "games.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id                  TEXT PRIMARY KEY,
    room_code           TEXT NOT NULL,
    config_json         TEXT NOT NULL,
    -- Stored as TEXT, not INTEGER: seeds are drawn from secrets.randbits(64),
    -- which can exceed SQLite's signed 64-bit INTEGER range and lose precision.
    seed                TEXT NOT NULL,
    roster_json         TEXT NOT NULL,
    action_log_json     TEXT NOT NULL,
    winner_id           INTEGER,
    winner_name         TEXT,
    rounds_played       INTEGER NOT NULL,
    shocks_fired        INTEGER NOT NULL,
    truncated           INTEGER NOT NULL,
    started_at          TEXT NOT NULL,
    ended_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS game_participants (
    game_id     TEXT NOT NULL REFERENCES games(id),
    seat        INTEGER NOT NULL,
    player_key  TEXT,
    name        TEXT NOT NULL,
    is_bot      INTEGER NOT NULL,
    policy      TEXT NOT NULL DEFAULT '',
    net_worth   REAL NOT NULL,
    status      TEXT NOT NULL,
    is_winner   INTEGER NOT NULL,
    PRIMARY KEY (game_id, seat)
);

CREATE INDEX IF NOT EXISTS idx_participants_player_key
    ON game_participants(player_key);

CREATE TABLE IF NOT EXISTS users (
    player_key      TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    games_played    INTEGER NOT NULL DEFAULT 0,
    games_won       INTEGER NOT NULL DEFAULT 0,
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL
);
"""


def connect(db_path: Union[str, Path] = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open (creating if needed) a game-history database and apply the schema.

    Pass ``":memory:"`` for an ephemeral database (used by tests). Row access
    returns :class:`sqlite3.Row` so callers can use both index and name lookup.
    """
    path_str = str(db_path)
    if path_str != ":memory:":
        Path(path_str).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path_str)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    return conn
