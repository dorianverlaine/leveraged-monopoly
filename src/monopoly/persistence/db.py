"""SQLite connection and schema -- the local stand-in for D1 (architecture 7.3, 9).

Games, participants, accounts, and sessions all live in one small relational
schema. This is intentionally the *only* module that touches ``sqlite3``
directly: swapping the cloud target to D1 later means replacing this module's
connection layer, while the repository APIs
(:mod:`monopoly.persistence.store`, :mod:`monopoly.accounts.store`) stay the same.

No passwords or credentials are ever stored here. An account is an *identity plus
profile and progression*, tied to either an opaque guest device key or (later) an
external auth provider's subject id -- the credential exchange itself always
happens at that provider, never in the game, per architecture 11.
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
    -- Human seats carry the account id that held them; bots and anonymous guests
    -- leave it NULL. Deliberately a *soft* reference (no enforced FK): game
    -- records stay decoupled from the accounts table so they can be written
    -- independently, and a cloud D1 target need not enforce it either. The
    -- service coordinator guarantees the account exists in practice.
    account_id  TEXT,
    name        TEXT NOT NULL,
    is_bot      INTEGER NOT NULL,
    policy      TEXT NOT NULL DEFAULT '',
    net_worth   REAL NOT NULL,
    status      TEXT NOT NULL,
    is_winner   INTEGER NOT NULL,
    PRIMARY KEY (game_id, seat)
);

CREATE INDEX IF NOT EXISTS idx_participants_account
    ON game_participants(account_id);

-- An account is an identity + profile + progression. No password ever lives
-- here: (auth_provider, auth_subject) points at where the identity came from
-- ('guest' + a device key, or later 'google'/'github' + that provider's subject).
CREATE TABLE IF NOT EXISTS accounts (
    id                  TEXT PRIMARY KEY,
    auth_provider       TEXT NOT NULL,
    auth_subject        TEXT NOT NULL,
    display_name        TEXT NOT NULL,
    avatar              TEXT NOT NULL DEFAULT '',
    -- UI language; one of the frontend's supported locales (see docs/i18n).
    locale              TEXT NOT NULL DEFAULT 'en',
    xp                  INTEGER NOT NULL DEFAULT 0,
    level               INTEGER NOT NULL DEFAULT 1,
    rating              INTEGER NOT NULL DEFAULT 1000,
    games_played        INTEGER NOT NULL DEFAULT 0,
    games_won           INTEGER NOT NULL DEFAULT 0,
    current_win_streak  INTEGER NOT NULL DEFAULT 0,
    best_win_streak     INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    last_seen           TEXT NOT NULL,
    UNIQUE (auth_provider, auth_subject)
);

-- Opaque bearer session tokens issued to a logged-in client. A token is a
-- capability, never a credential; it maps a connection to an account.
CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    account_id  TEXT NOT NULL REFERENCES accounts(id),
    created_at  TEXT NOT NULL,
    last_used   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_account
    ON sessions(account_id);
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
