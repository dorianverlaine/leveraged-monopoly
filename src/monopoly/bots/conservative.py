"""Conservative policy: low leverage, hoards cash.

Buys only when it can pay in cash while keeping a healthy buffer, never borrows,
and pays down any debt it somehow acquires. The quiet loser to inflation
(architecture 5.1) -- a useful baseline for the backtest and a calm opponent for
new human players.
"""

from __future__ import annotations

from ..engine.actions import Action, buy, end_turn, repay_debt
from ..engine.state import GameState
from . import policy
from .policy import Policy

# Keep at least this many multiples of the purchase in reserve before buying.
_CASH_BUFFER = 300


class ConservativePolicy(Policy):
    name = "conservative"

    def manage(self, state: GameState, player_id: int) -> Action:
        player = state.player_by_id(player_id)

        # Always retire debt first if we can afford it -- avoid any margin risk.
        if player.debt > 0 and player.cash > _CASH_BUFFER:
            return repay_debt(player_id, min(player.debt, player.cash - _CASH_BUFFER))

        # Buy only in cash and only while keeping a comfortable reserve.
        if policy.can_buy_here(state, player_id):
            cost = policy.buy_cost_here(state, player_id)
            if player.cash - cost >= _CASH_BUFFER:
                return buy(player_id, player.position)

        return end_turn(player_id)
