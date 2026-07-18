"""Headless simulation: the local game loop, replay, and the backtest driver."""

from __future__ import annotations

from .backtest import BacktestReport, run_batch
from .runner import GameResult, play_game, replay, summarize_game

__all__ = [
    "GameResult",
    "play_game",
    "replay",
    "summarize_game",
    "BacktestReport",
    "run_batch",
]
