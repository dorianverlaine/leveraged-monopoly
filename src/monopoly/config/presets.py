"""Ready-made configs and roster helpers.

Pacing is a set of parameters, not code (design principle #4). These presets are
just convenient bundles of :class:`GameConfig` values -- "quick / standard / long"
-- plus a helper that fills empty seats with bots so 2 humans + 4 bots can play
at 2 a.m. (architecture 4.6).

**Balance note.** These values were tuned empirically with the backtest, not by
intuition (architecture 5.2). Two findings drove them:

1. *Starting cash must be low relative to property prices*, or players never need
   to borrow -- and with no debt, systemic shocks and margin calls never fire, so
   the game degenerates into plain Monopoly.
2. *Inflation must roughly recover a shock between shocks* -- i.e. ``(1+inflation)
   ** shock_interval ~= 1/(1-shock_magnitude)``. If it doesn't, shock damage
   compounds far faster than assets appreciate, so holding cash beats holding
   property, hoarding wins, and the capital-market layer becomes a trap that
   optimal play avoids (the *opposite* of the architecture's "asset-holders win
   lying down" thesis, 4.4). With recovery tuned in, each shock is still a sharp
   -30% jolt (drama preserved) but buying / leverage / monopolies pay off.

Together these make skilled aggression beat passivity: the ``shark`` bot (which
leverages between shocks and de-risks right before them) is the strongest policy,
while the ``degen`` (which stays levered into shocks) still dies. See
``analysis/sweep.py`` to re-tune.
"""

from __future__ import annotations

from typing import List, Optional

from ..bots.registry import available_policies
from ..engine.player import Player
from ..engine.state import GameConfig, VictoryCondition

# Default rotation used to backfill empty seats with varied opponents.
_DEFAULT_BOT_ROTATION = ["shark", "degen", "conservative", "cashflow", "contrarian"]


def quick_match(max_players: int = 4) -> GameConfig:
    """Short, punchy game: small ring, tight cash, frequent shocks."""
    return GameConfig(
        max_players=max_players,
        map_size=24,
        victory_condition=VictoryCondition.ROUND_LIMIT,
        round_limit=20,
        starting_cash=250,
        inflation_rate=0.08,
        shock_interval_rounds=4,
        shock_magnitude=0.35,
        maintenance_ratio=1.40,
        max_leverage_ratio=0.80,
        interest_rate=0.10,
    )


def standard_match(max_players: int = 6) -> GameConfig:
    """The default balanced game."""
    return GameConfig(
        max_players=max_players,
        map_size=36,
        victory_condition=VictoryCondition.LAST_SOLVENT,
        round_limit=45,
        starting_cash=450,
        inflation_rate=0.05,
        shock_interval_rounds=6,
        shock_magnitude=0.30,
        maintenance_ratio=1.40,
        max_leverage_ratio=0.80,
        interest_rate=0.10,
    )


def long_match(max_players: int = 6) -> GameConfig:
    """Marathon game: big ring, more cash, gentler but relentless macro."""
    return GameConfig(
        max_players=max_players,
        map_size=44,
        victory_condition=VictoryCondition.LAST_SOLVENT,
        round_limit=80,
        starting_cash=800,
        inflation_rate=0.035,
        shock_interval_rounds=9,
        shock_magnitude=0.28,
        maintenance_ratio=1.35,
        max_leverage_ratio=0.80,
        interest_rate=0.06,
    )


def build_roster(
    config: GameConfig,
    human_names: Optional[List[str]] = None,
    fill_with_bots: bool = True,
    bot_rotation: Optional[List[str]] = None,
) -> List[Player]:
    """Create a player roster: named humans first, then bot backfill.

    ``config.starting_cash`` is applied later by ``new_game``; here we only assign
    ids, names, and bot policies. Ids are sequential seat indices starting at 0.
    """
    human_names = human_names or []
    rotation = bot_rotation or _DEFAULT_BOT_ROTATION
    valid = set(available_policies())
    rotation = [name for name in rotation if name in valid] or list(valid)

    roster: List[Player] = []
    for name in human_names[: config.max_players]:
        roster.append(Player(id=len(roster), name=name, cash=config.starting_cash))

    if fill_with_bots:
        while len(roster) < config.max_players:
            policy_name = rotation[len(roster) % len(rotation)]
            roster.append(
                Player(
                    id=len(roster),
                    name=f"Bot-{policy_name}-{len(roster)}",
                    cash=config.starting_cash,
                    is_bot=True,
                    policy=policy_name,
                )
            )

    if not roster:
        raise ValueError("Roster is empty: provide human_names or enable fill_with_bots")

    return roster
