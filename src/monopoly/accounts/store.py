"""Account repository: identities, sessions, and progression.

The only account-facing API the rest of the codebase uses. It owns guest
identity creation, opaque session tokens, profile/locale updates, and applying a
finished game's results to XP/level/rating/streaks (via the pure
:mod:`monopoly.accounts.progression` maths).

Passwordless by design (architecture 11): a guest account is keyed by a random
device key the client stores; external providers can be added later by inserting
an account with that provider's subject id -- the credential check happens at the
provider, never here.
"""

from __future__ import annotations

import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Sequence

from . import progression
from .models import Account, GameOutcome

# Supported UI locales (kept in sync with the frontend i18n catalogue). Stored on
# the account and echoed back so a returning client restores its language.
SUPPORTED_LOCALES = ("en", "zh-Hant", "zh-Hans", "fr")
DEFAULT_LOCALE = "en"

GUEST_PROVIDER = "guest"

_ACCOUNT_COLUMNS = (
    "id, auth_provider, auth_subject, display_name, avatar, locale, xp, level, "
    "rating, games_played, games_won, current_win_streak, best_win_streak, "
    "created_at, last_seen"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_locale(locale: Optional[str]) -> str:
    """Return a supported locale, falling back to the default for anything else."""
    return locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE


class AccountStore:
    """SQLite-backed repository for accounts, sessions, and progression."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # --- Guest identity & sessions -------------------------------------

    def create_guest(
        self,
        display_name: Optional[str] = None,
        locale: Optional[str] = None,
        avatar: str = "",
    ) -> tuple[Account, str, str]:
        """Create a fresh guest account.

        Returns ``(account, device_key, session_token)``. The client stores the
        device key to reclaim this same guest account later (a "remember me"
        secret, not a credential) and the session token to authenticate the
        current connection.
        """
        account_id = uuid.uuid4().hex
        device_key = secrets.token_urlsafe(24)
        now = _now_iso()
        name = display_name or f"Player-{account_id[:6]}"
        loc = normalize_locale(locale)

        with self._conn:
            self._conn.execute(
                f"""
                INSERT INTO accounts (
                    {_ACCOUNT_COLUMNS}
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 1, ?, 0, 0, 0, 0, ?, ?)
                """,
                (
                    account_id,
                    GUEST_PROVIDER,
                    device_key,
                    name,
                    avatar,
                    loc,
                    progression.DEFAULT_RATING,
                    now,
                    now,
                ),
            )
        token = self.issue_session(account_id)
        account = self.get_account(account_id)
        assert account is not None
        return account, device_key, token

    def login_guest(self, device_key: str) -> Optional[tuple[Account, str]]:
        """Reclaim a guest account by its device key. Returns ``(account, token)``."""
        row = self._conn.execute(
            f"SELECT {_ACCOUNT_COLUMNS} FROM accounts WHERE auth_provider = ? AND auth_subject = ?",
            (GUEST_PROVIDER, device_key),
        ).fetchone()
        if row is None:
            return None
        account = _row_to_account(row)
        self._touch(account.id)
        return account, self.issue_session(account.id)

    def issue_session(self, account_id: str) -> str:
        """Mint a new opaque session token bound to ``account_id``."""
        token = secrets.token_urlsafe(24)
        now = _now_iso()
        with self._conn:
            self._conn.execute(
                "INSERT INTO sessions (token, account_id, created_at, last_used) VALUES (?, ?, ?, ?)",
                (token, account_id, now, now),
            )
        return token

    def account_for_session(self, token: str) -> Optional[Account]:
        """Resolve a session token to its account, or ``None`` if unknown."""
        if not token:
            return None
        row = self._conn.execute(
            "SELECT account_id FROM sessions WHERE token = ?", (token,)
        ).fetchone()
        if row is None:
            return None
        with self._conn:
            self._conn.execute(
                "UPDATE sessions SET last_used = ? WHERE token = ?", (_now_iso(), token)
            )
        return self.get_account(row["account_id"])

    # --- Profile -------------------------------------------------------

    def get_account(self, account_id: str) -> Optional[Account]:
        row = self._conn.execute(
            f"SELECT {_ACCOUNT_COLUMNS} FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        return _row_to_account(row) if row else None

    def update_profile(
        self,
        account_id: str,
        display_name: Optional[str] = None,
        avatar: Optional[str] = None,
        locale: Optional[str] = None,
    ) -> Optional[Account]:
        """Patch mutable profile fields; unspecified fields are left unchanged."""
        sets = []
        params: list = []
        if display_name is not None:
            sets.append("display_name = ?")
            params.append(display_name)
        if avatar is not None:
            sets.append("avatar = ?")
            params.append(avatar)
        if locale is not None:
            sets.append("locale = ?")
            params.append(normalize_locale(locale))
        if not sets:
            return self.get_account(account_id)

        sets.append("last_seen = ?")
        params.append(_now_iso())
        params.append(account_id)
        with self._conn:
            self._conn.execute(
                f"UPDATE accounts SET {', '.join(sets)} WHERE id = ?", params
            )
        return self.get_account(account_id)

    def set_locale(self, account_id: str, locale: str) -> Optional[Account]:
        """Convenience wrapper to change just the UI language."""
        return self.update_profile(account_id, locale=locale)

    # --- Progression ---------------------------------------------------

    def record_game_results(self, outcomes: Sequence[GameOutcome]) -> None:
        """Apply one finished game's results to every participating account.

        Ratings are updated together (Elo needs the whole field); XP, level,
        games/wins, and streaks are updated per account. Accounts not found are
        skipped. With fewer than two human accounts, ratings are unchanged (you
        do not gain ladder rating against bots) but XP and stats still accrue.
        """
        accounts = []
        for outcome in outcomes:
            account = self.get_account(outcome.account_id)
            if account is not None:
                accounts.append((account, outcome))
        if not accounts:
            return

        ratings = [acc.rating for acc, _ in accounts]
        ranks = [outcome.rank for _, outcome in accounts]
        new_ratings = progression.update_ratings(ratings, ranks)

        now = _now_iso()
        with self._conn:
            for (account, outcome), new_rating in zip(accounts, new_ratings):
                won = outcome.rank == 0
                new_xp = account.xp + progression.xp_for_game(
                    outcome.rank, outcome.num_players, outcome.bankrupt
                )
                new_level = progression.level_for_xp(new_xp)
                new_streak = account.current_win_streak + 1 if won else 0
                best_streak = max(account.best_win_streak, new_streak)
                self._conn.execute(
                    """
                    UPDATE accounts SET
                        xp = ?, level = ?, rating = ?,
                        games_played = games_played + 1,
                        games_won = games_won + ?,
                        current_win_streak = ?, best_win_streak = ?,
                        last_seen = ?
                    WHERE id = ?
                    """,
                    (
                        new_xp,
                        new_level,
                        new_rating,
                        1 if won else 0,
                        new_streak,
                        best_streak,
                        now,
                        account.id,
                    ),
                )

    def leaderboard(self, limit: int = 20, by: str = "rating") -> List[dict]:
        """Return accounts ranked by ``rating`` (default), ``xp``, or ``wins``."""
        order = {
            "rating": "rating DESC, games_won DESC",
            "xp": "xp DESC, level DESC",
            "wins": "games_won DESC, rating DESC",
        }.get(by, "rating DESC")
        rows = self._conn.execute(
            f"SELECT {_ACCOUNT_COLUMNS} FROM accounts ORDER BY {order} LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_account(row).public_profile() for row in rows]

    # --- Internals ------------------------------------------------------

    def _touch(self, account_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE accounts SET last_seen = ? WHERE id = ?", (_now_iso(), account_id)
            )


def _row_to_account(row: sqlite3.Row) -> Account:
    return Account(
        id=row["id"],
        auth_provider=row["auth_provider"],
        auth_subject=row["auth_subject"],
        display_name=row["display_name"],
        avatar=row["avatar"],
        locale=row["locale"],
        xp=row["xp"],
        level=row["level"],
        rating=row["rating"],
        games_played=row["games_played"],
        games_won=row["games_won"],
        current_win_streak=row["current_win_streak"],
        best_win_streak=row["best_win_streak"],
        created_at=row["created_at"],
        last_seen=row["last_seen"],
    )
