"""Contrarian policy: hoards cash in calm markets, buys into the crash.

The signal is whether prices are depressed relative to their expected inflation
drift. In a normal market the contrarian sits on cash and stays debt-light; when
a systemic shock has knocked the price index well below trend, it flips to
aggressive, leverage-funded buying -- accumulating cheap assets while the degens
are being liquidated.
"""

from __future__ import annotations

from ..engine import valuation
from ..engine.actions import Action, buy, end_turn, leverage, repay_debt
from ..engine.state import GameState
from . import policy
from .policy import Policy

# Buy aggressively once prices fall this far below their expected drift.
_CHEAP_DISCOUNT = 0.90


class ContrarianPolicy(Policy):
    name = "contrarian"

    def manage(self, state: GameState, player_id: int) -> Action:
        player = state.player_by_id(player_id)

        if self._market_is_cheap(state):
            # Crash mode: lever into discounted property, exactly like a degen.
            if policy.can_buy_here(state, player_id):
                cost = policy.buy_cost_here(state, player_id)
                if player.cash >= cost:
                    return buy(player_id, player.position)
                gap = cost - player.cash
                room = valuation.max_borrowable(state, player_id)
                if 0 < gap <= room:
                    return leverage(player_id, gap)
            return end_turn(player_id)

        # Calm market: stay liquid and debt-light; don't chase full-price assets.
        if player.debt > 0 and player.cash > 0:
            return repay_debt(player_id, min(player.debt, player.cash))
        return end_turn(player_id)

    @staticmethod
    def _market_is_cheap(state: GameState) -> bool:
        """True when the price index is well below its expected inflation drift."""
        expected = (1.0 + state.config.inflation_rate) ** (state.turn.round_number - 1)
        return state.market.price_index < _CHEAP_DISCOUNT * expected
