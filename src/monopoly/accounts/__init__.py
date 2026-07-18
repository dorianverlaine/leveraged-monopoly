"""Accounts: passwordless identity, profiles, and chess.com/Duolingo-style
progression (XP, levels, Elo rating, streaks).

An account is an identity plus profile and progression -- never a password
(architecture 11). Guests are created with a random device key; external auth
providers can be layered on later. :class:`~monopoly.accounts.store.AccountStore`
is the repository API; :mod:`~monopoly.accounts.progression` holds the pure XP and
Elo maths; :func:`~monopoly.accounts.service.record_finished_game` ties a finished
game to progression updates.
"""

from __future__ import annotations

from . import progression
from .models import Account, GameOutcome
from .service import record_finished_game
from .store import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    AccountStore,
    normalize_locale,
)

__all__ = [
    "progression",
    "Account",
    "GameOutcome",
    "AccountStore",
    "record_finished_game",
    "SUPPORTED_LOCALES",
    "DEFAULT_LOCALE",
    "normalize_locale",
]
