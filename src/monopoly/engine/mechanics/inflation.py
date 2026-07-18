"""Inflation and interest -- the slow, grinding macro pressure.

Applied once per full round (see the reducer's turn-advance logic). Two effects:

* **Price-index growth.** Every property's value and rent scale with
  ``market.price_index``, which grows by ``inflation_rate`` each round. Assets
  appreciate; cash quietly loses purchasing power. This is the mechanic that
  re-teaches "why savers lose to buyers" (architecture 4.4).
* **Interest accrual.** Outstanding debt compounds by ``interest_rate`` each
  round, so leverage that looked safe gets heavier over time and eventually
  forces a margin decision.
"""

from __future__ import annotations

from ..player import PlayerStatus
from ..state import GameState, Transaction


def apply_round_economics(state: GameState) -> None:
    """Advance inflation and accrue interest for one completed round."""
    _grow_price_index(state)
    _accrue_interest(state)


def _grow_price_index(state: GameState) -> None:
    """Lift the market price index by the configured inflation rate."""
    rate = state.config.inflation_rate
    if rate == 0.0:
        return
    state.market.price_index *= (1.0 + rate)


def _accrue_interest(state: GameState) -> None:
    """Compound interest onto every player's outstanding debt."""
    rate = state.config.interest_rate
    if rate <= 0.0:
        return
    for player in state.players:
        if player.status == PlayerStatus.BANKRUPT or player.debt <= 0:
            continue
        interest = int(round(player.debt * rate))
        if interest <= 0:
            continue
        player.debt += interest
        state.record(
            Transaction(
                round_number=state.turn.round_number,
                player_id=player.id,
                kind="interest",
                amount=-interest,
                note="Interest accrued on debt",
            )
        )
