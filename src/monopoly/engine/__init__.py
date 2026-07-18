"""The deterministic economic engine -- the shared kernel.

This is the heart of the whole system (architecture 3): a pure, seeded,
side-effect-free reducer over an explicit game state. Everything else -- the
real-time plane, the backtest cluster, replays, anti-cheat -- is plumbing around
this single function.

Public API
----------
* :func:`~monopoly.engine.reducer.reduce` -- ``reduce(state, action) -> state | RuleError``
* :func:`~monopoly.engine.state.new_game` -- build a fresh game
* :class:`~monopoly.engine.state.GameState`, :class:`~monopoly.engine.state.GameConfig`
* :class:`~monopoly.engine.actions.Action` (+ ergonomic constructors)
* :class:`~monopoly.engine.errors.RuleError`
* :mod:`~monopoly.engine.valuation` -- derived metrics (net worth, margin ratio)
"""

from __future__ import annotations

from . import actions, valuation
from .actions import Action, ActionType
from .board import Tile, TileType, build_board
from .errors import RuleError, RuleErrorCode
from .market import Market
from .player import Player, PlayerStatus
from .reducer import reduce, winner
from .rng import SeededRng
from .state import (
    GameConfig,
    GamePhase,
    GameState,
    Transaction,
    TurnState,
    VictoryCondition,
    new_game,
)

__all__ = [
    "actions",
    "valuation",
    "Action",
    "ActionType",
    "Tile",
    "TileType",
    "build_board",
    "RuleError",
    "RuleErrorCode",
    "Market",
    "Player",
    "PlayerStatus",
    "reduce",
    "winner",
    "SeededRng",
    "GameConfig",
    "GamePhase",
    "GameState",
    "Transaction",
    "TurnState",
    "VictoryCondition",
    "new_game",
]
