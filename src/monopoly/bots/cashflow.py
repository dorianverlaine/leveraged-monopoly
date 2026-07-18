"""Cash-flow policy: prioritizes rent yield and securitization income.

Accumulates rent-earning property and taps the equity market for liquidity
instead of borrowing heavily. Sells slices of holdings (securitization) when cash
runs low, and keeps a little debt discipline so a shock does not wipe it out.
"""

from __future__ import annotations

from typing import Optional

from ..engine.actions import Action, buy, end_turn, repay_debt, securitize
from ..engine.board import Tile
from ..engine.state import GameState
from . import policy
from .policy import Policy

# Below this cash level the policy raises liquidity by securitizing a holding.
_LOW_CASH = 200
# Fraction of a holding sold per securitization step.
_SELL_FRACTION = 0.25
# Repay debt when the margin ratio sits this close to the maintenance floor.
_MARGIN_SAFETY = 0.25


class CashflowPolicy(Policy):
    name = "cashflow"

    def manage(self, state: GameState, player_id: int) -> Action:
        player = state.player_by_id(player_id)

        # De-risk: if margin is tight and we have spare cash, pay down debt.
        if (
            player.debt > 0
            and player.cash > _LOW_CASH
            and policy.margin_headroom(state, player_id) < _MARGIN_SAFETY
        ):
            return repay_debt(player_id, min(player.debt, player.cash - _LOW_CASH))

        # Grow the rent base whenever we can pay cash and stay above the floor.
        if policy.can_buy_here(state, player_id):
            cost = policy.buy_cost_here(state, player_id)
            if player.cash - cost >= _LOW_CASH:
                return buy(player_id, player.position)

        # Short on cash -> IPO a slice of a holding rather than borrow.
        if player.cash < _LOW_CASH:
            tile = self._securitizable_tile(state, player_id)
            if tile is not None:
                return securitize(player_id, tile.index, _SELL_FRACTION)

        return end_turn(player_id)

    @staticmethod
    def _securitizable_tile(state: GameState, player_id: int) -> Optional[Tile]:
        """Return an owned, un-mortgaged property to sell a slice of, if any."""
        for tile in state.board:
            if tile.is_property() and not tile.mortgaged and tile.owned_share(player_id) > 0.0:
                return tile
        return None
