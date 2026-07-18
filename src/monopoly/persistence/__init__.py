"""Persistence: completed-game records, replays, and player stats.

Fills the D1 role from the architecture (7.3, 9) with SQLite as the local
stand-in. :func:`~monopoly.persistence.db.connect` opens the database and applies
the schema; :class:`~monopoly.persistence.store.GameStore` is the repository API
everything else should use -- no other module should touch ``sqlite3`` directly.
"""

from __future__ import annotations

from . import db
from .store import GameStore, utc_now_iso

__all__ = ["db", "GameStore", "utc_now_iso"]
