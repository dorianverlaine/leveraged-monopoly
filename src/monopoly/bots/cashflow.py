"""Cash-flow policy: prioritizes rent yield and securitization income.

Accumulates rent-earning property and, when margin pressure threatens, raises
cash by securitizing slices of holdings rather than being liquidated. In calm
conditions it grows its rent base and develops monopolies; it only taps the
equity market for a *purpose* (funding debt repayment under pressure), never just
to sit on idle cash.
"""

from __future__ import annotations

from typing import Optional

from ..engine.actions import Action, build, buy, end_turn, repay_debt, securitize
from ..engine.board import Tile
from ..engine.state import GameState
from . import policy
from .policy import Policy

# Keep at least this much cash in reserve when buying, in a calm market.
_LOW_CASH = 100
# Fraction of a holding sold per securitization step (large enough to make real
# progress in one action -- avoids re-securitizing the same turn).
_SELL_FRACTION = 0.5
# Treat margin as "tight" (act to de-risk) once headroom drops below this.
_MARGIN_SAFETY = 0.25


class CashflowPolicy(Policy):
    name = "cashflow"

    def manage(self, state: GameState, player_id: int) -> Action:
        player = state.player_by_id(player_id)
        tight = (
            player.debt > 0
            and policy.margin_headroom(state, player_id) < _MARGIN_SAFETY
        )

        # Under margin pressure: pay down debt, raising cash by securitizing a
        # slice first if we have none. This converges (repay shrinks debt,
        # securitize shrinks holdings) rather than spinning on idle liquidity.
        if tight:
            if player.cash > 0:
                return repay_debt(player_id, min(player.debt, player.cash))
            tile = self._securitizable_tile(state, player_id)
            if tile is not None:
                return securitize(player_id, tile.index, _SELL_FRACTION)
            return end_turn(player_id)  # nothing left to sell; ride it out

        # Calm market: grow the rent base whenever we can pay cash and keep a
        # small reserve, then develop monopolies (this policy lives on rent).
        if policy.can_buy_here(state, player_id):
            cost = policy.buy_cost_here(state, player_id)
            if player.cash - cost >= _LOW_CASH:
                return buy(player_id, player.position)

        tile = policy.buildable_tile(state, player_id, cash_buffer=_LOW_CASH)
        if tile is not None:
            return build(player_id, tile.index)

        return end_turn(player_id)

    @staticmethod
    def _securitizable_tile(state: GameState, player_id: int) -> Optional[Tile]:
        """Return an owned, un-mortgaged property to sell a slice of, if any."""
        for tile in state.board:
            if tile.is_property() and not tile.mortgaged and tile.owned_share(player_id) > 0.0:
                return tile
        return None
