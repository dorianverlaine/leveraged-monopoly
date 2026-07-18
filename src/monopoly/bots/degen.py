"""Degen policy: maximum leverage, buys everything it can reach.

Borrows against its portfolio to fund purchases whenever cash falls short. First
to die *or* first to dominate (architecture 5.1). This policy is the stress test
for the margin/shock machinery -- it is usually the one that dominoes.
"""

from __future__ import annotations

from ..engine import valuation
from ..engine.actions import Action, buy, end_turn, leverage
from ..engine.state import GameState
from . import policy
from .policy import Policy


class DegenPolicy(Policy):
    name = "degen"

    def manage(self, state: GameState, player_id: int) -> Action:
        player = state.player_by_id(player_id)

        if policy.can_buy_here(state, player_id):
            cost = policy.buy_cost_here(state, player_id)

            # Enough cash on hand -> just buy.
            if player.cash >= cost:
                return buy(player_id, player.position)

            # Short on cash -> borrow exactly the gap, if the collateral allows it.
            gap = cost - player.cash
            room = valuation.max_borrowable(state, player_id)
            if 0 < gap <= room:
                return leverage(player_id, gap)

        # Nothing worth leveraging into this turn.
        return end_turn(player_id)
