"""Ready-made configs and roster helpers.

Pacing is a set of parameters, not code (design principle #4). These presets are
just convenient bundles of :class:`GameConfig` values -- "quick / standard / long"
-- plus a helper that fills empty seats with bots so 2 humans + 4 bots can play
at 2 a.m. (architecture 4.6).
"""

from __future__ import annotations

from typing import List, Optional

from ..bots.registry import available_policies
from ..engine.player import Player
from ..engine.state import GameConfig, VictoryCondition

# Default rotation used to backfill empty seats with varied opponents.
_DEFAULT_BOT_ROTATION = ["degen", "conservative", "cashflow", "contrarian"]


def quick_match(max_players: int = 4) -> GameConfig:
    """Short, punchy game: small ring, fast inflation, frequent shocks."""
    return GameConfig(
        max_players=max_players,
        map_size=24,
        victory_condition=VictoryCondition.ROUND_LIMIT,
        round_limit=20,
        starting_cash=1500,
        inflation_rate=0.03,
        shock_interval_rounds=6,
        shock_magnitude=0.30,
    )


def standard_match(max_players: int = 6) -> GameConfig:
    """The default balanced game."""
    return GameConfig(
        max_players=max_players,
        map_size=36,
        victory_condition=VictoryCondition.LAST_SOLVENT,
        round_limit=40,
        starting_cash=1500,
        inflation_rate=0.02,
        shock_interval_rounds=8,
        shock_magnitude=0.30,
    )


def long_match(max_players: int = 6) -> GameConfig:
    """Marathon game: big ring, gentler macro, rarer shocks."""
    return GameConfig(
        max_players=max_players,
        map_size=44,
        victory_condition=VictoryCondition.LAST_SOLVENT,
        round_limit=80,
        starting_cash=2000,
        inflation_rate=0.015,
        shock_interval_rounds=10,
        shock_magnitude=0.25,
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
