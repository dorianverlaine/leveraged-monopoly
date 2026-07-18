"""Leveraged Monopoly -- the Python backend.

A real-time, turn-based multiplayer board game with modern capital-market
mechanics (leverage, margin calls, systemic shocks, securitization, inflation).

This package is the P0 / P1 backend: a pure, deterministic economic engine plus
bot policies, config presets, and a headless simulation/backtest harness. It is
intentionally modular so individual rule layers, bots, or the persistence/
transport layer can be swapped without touching the kernel (see the project
README and the architecture document).

Quick start
-----------
>>> from monopoly.config import quick_match, build_roster
>>> from monopoly.simulation import play_game
>>> config = quick_match(max_players=4)
>>> roster = build_roster(config)              # all bots
>>> result = play_game(config, seed=42, roster=roster)
>>> result.winner_name is not None
True
"""

from __future__ import annotations

__version__ = "0.1.0"

from . import bots, config, engine, simulation
from .engine import (
    Action,
    GameConfig,
    GameState,
    Player,
    RuleError,
    new_game,
    reduce,
)

__all__ = [
    "__version__",
    "bots",
    "config",
    "engine",
    "simulation",
    "Action",
    "GameConfig",
    "GameState",
    "Player",
    "RuleError",
    "new_game",
    "reduce",
]
