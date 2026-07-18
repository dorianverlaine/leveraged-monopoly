"""Pure progression maths: XP, levels, and multiplayer Elo.

No I/O and no persistence -- just deterministic functions over numbers, in the
same spirit as the engine kernel. This keeps the "how much does a game reward a
player" and "how does a result move ratings" rules in one testable place, so the
store layer only has to persist the results.

The style is deliberately chess.com / Duolingo shaped:
* **XP + levels** give a always-goes-up sense of progress (Duolingo).
* **Elo rating** gives a competitive ladder that can go down (chess.com).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

# --- XP & levels -----------------------------------------------------------

# XP awarded for the various things that can happen in one finished game.
XP_FOR_PLAYING = 50          # just for finishing a game
XP_FOR_WINNING = 100         # the winner's bonus
XP_FOR_SURVIVING = 30        # not bankrupt at the end
XP_PER_RANK_ABOVE_LAST = 10  # placement bonus: (N-1-rank) * this

# Level curve: level L costs 100*L XP to reach from L-1, so the cumulative XP
# needed to *be* level L is 100 * (1 + 2 + ... + (L-1)) = 50 * L * (L-1).
_LEVEL_STEP = 100


def xp_for_game(rank: int, num_players: int, bankrupt: bool) -> int:
    """XP a player earns from one finished game.

    ``rank`` is 0-based and 0 = winner. ``num_players`` is the seat count. The
    reward always beats zero so every game feels like progress (Duolingo-style),
    while placement and the win bonus keep it meaningful.
    """
    xp = XP_FOR_PLAYING
    if rank == 0:
        xp += XP_FOR_WINNING
    if not bankrupt:
        xp += XP_FOR_SURVIVING
    # Placement bonus: finishing higher than last place is worth a little more.
    xp += max(0, (num_players - 1 - rank)) * XP_PER_RANK_ABOVE_LAST
    return xp


def cumulative_xp_for_level(level: int) -> int:
    """Total XP required to have reached ``level`` (level 1 is the start, 0 XP)."""
    if level <= 1:
        return 0
    n = level - 1
    return _LEVEL_STEP * (n * (n + 1)) // 2


def level_for_xp(xp: int) -> int:
    """The level a given cumulative XP total corresponds to (starts at 1)."""
    if xp < 0:
        raise ValueError("xp cannot be negative")
    level = 1
    while cumulative_xp_for_level(level + 1) <= xp:
        level += 1
    return level


@dataclass
class LevelProgress:
    """A snapshot of where a player sits within their current level (for UI bars)."""

    level: int
    xp_into_level: int       # XP earned beyond the current level's threshold
    xp_for_next_level: int   # XP span from this level to the next
    total_xp: int

    def fraction(self) -> float:
        """Progress toward the next level in [0, 1] (0 at the floor of a level)."""
        if self.xp_for_next_level <= 0:
            return 0.0
        return self.xp_into_level / self.xp_for_next_level


def level_progress(total_xp: int) -> LevelProgress:
    """Break a cumulative XP total into level + progress-within-level (for a UI bar)."""
    level = level_for_xp(total_xp)
    floor_xp = cumulative_xp_for_level(level)
    next_xp = cumulative_xp_for_level(level + 1)
    return LevelProgress(
        level=level,
        xp_into_level=total_xp - floor_xp,
        xp_for_next_level=next_xp - floor_xp,
        total_xp=total_xp,
    )


# --- Multiplayer Elo -------------------------------------------------------

DEFAULT_RATING = 1000
_ELO_K = 32          # maximum swing per game (scaled by field size below)
_ELO_DIVISOR = 400   # standard Elo logistic scale


def _expected_score(rating_a: int, rating_b: int) -> float:
    """Standard Elo expectation that A beats B, in [0, 1]."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / _ELO_DIVISOR))


def update_ratings(
    ratings: Sequence[int], ranks: Sequence[int], k: int = _ELO_K
) -> List[int]:
    """Return new ratings for a multiplayer result.

    ``ratings[i]`` and ``ranks[i]`` describe player *i*; ``ranks`` are 0-based with
    0 = best (ties allowed). Uses the well-known pairwise generalisation of Elo:
    every player is scored against every other (win = 1, tie = 0.5, loss = 0), and
    the per-pair deltas are averaged so a 6-player game does not swing wildly. A
    solo "game" (one player) is a no-op.
    """
    n = len(ratings)
    if n != len(ranks):
        raise ValueError("ratings and ranks must have the same length")
    if n < 2:
        return list(ratings)

    new_ratings: List[int] = []
    for i in range(n):
        actual = 0.0
        expected = 0.0
        for j in range(n):
            if i == j:
                continue
            expected += _expected_score(ratings[i], ratings[j])
            if ranks[i] < ranks[j]:
                actual += 1.0
            elif ranks[i] == ranks[j]:
                actual += 0.5
        # Average over opponents so the total change stays on an Elo-like scale.
        delta = k * (actual - expected) / (n - 1)
        new_ratings.append(round(ratings[i] + delta))
    return new_ratings


def ranks_from_standings(standings: Sequence[Tuple[bool, float]]) -> List[int]:
    """Convert (is_bankrupt, net_worth) standings into 0-based ranks (0 = best).

    Solvent players outrank bankrupt ones; within each group, higher net worth
    ranks better. Equal keys share a rank (standard competition ranking).
    """
    # Sort a copy of the indices best-first: solvent before bankrupt, then by
    # net worth descending.
    order = sorted(
        range(len(standings)),
        key=lambda i: (standings[i][0], -standings[i][1]),
    )
    ranks = [0] * len(standings)
    current_rank = 0
    for position, idx in enumerate(order):
        if position > 0:
            prev = order[position - 1]
            if standings[idx] != standings[prev]:
                current_rank = position
        ranks[idx] = current_rank
    return ranks
