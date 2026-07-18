"""Account value objects."""

from __future__ import annotations

from dataclasses import dataclass

from . import progression


@dataclass
class Account:
    """A player identity plus profile and progression.

    Mirrors the ``accounts`` table. Never carries a password -- identity comes
    from ``auth_provider`` + ``auth_subject`` (a guest device key, or an external
    provider's subject id).
    """

    id: str
    auth_provider: str
    auth_subject: str
    display_name: str
    avatar: str
    locale: str
    xp: int
    level: int
    rating: int
    games_played: int
    games_won: int
    current_win_streak: int
    best_win_streak: int
    created_at: str
    last_seen: str

    def public_profile(self) -> dict:
        """The profile shape sent to a client (no auth internals).

        Includes a level-progress breakdown so a Duolingo-style XP bar can be
        drawn without the client re-deriving the level curve.
        """
        prog = progression.level_progress(self.xp)
        return {
            "id": self.id,
            "display_name": self.display_name,
            "avatar": self.avatar,
            "locale": self.locale,
            "level": self.level,
            "xp": self.xp,
            "xp_into_level": prog.xp_into_level,
            "xp_for_next_level": prog.xp_for_next_level,
            "rating": self.rating,
            "games_played": self.games_played,
            "games_won": self.games_won,
            "current_win_streak": self.current_win_streak,
            "best_win_streak": self.best_win_streak,
        }


@dataclass
class GameOutcome:
    """One human account's result in a finished game, for progression updates.

    ``rank`` is 0-based placement among *all* seats (0 = winner). ``num_players``
    is the total seat count (used for the XP placement bonus). Bots are never
    represented here -- only seats bound to an account.
    """

    account_id: str
    rank: int
    num_players: int
    bankrupt: bool
