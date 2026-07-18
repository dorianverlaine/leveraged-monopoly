"""Systemic shock / black swan -- the correlated crash.

The point is *correlation* (architecture 4.2). A classic chance card is an
independent draw affecting one player; a systemic shock fires for *everyone at
once*: property values drop by ``shock_magnitude``, so every over-leveraged
player gets margin-called simultaneously. The finest social damage is "it wasn't
me, it was the market."

The shock is armed by a countdown (``market.shock_clock``) so it is deterministic
and predictable to the engine (though dramatic to the players). The reducer ticks
the clock once per round and calls :func:`maybe_fire` at the round boundary.
"""

from __future__ import annotations

from ..state import GameState, Transaction


def tick_and_maybe_fire(state: GameState) -> bool:
    """Advance the shock clock by one round and fire a shock if it hits zero.

    Returns ``True`` if a shock fired (so the reducer knows to re-run solvency
    enforcement and the client knows to shake the screen).
    """
    market = state.market
    market.shock_clock -= 1
    if market.shock_clock > 0:
        return False

    _fire_shock(state)
    # Re-arm for the next cycle.
    market.shock_clock = state.config.shock_interval_rounds
    return True


def _fire_shock(state: GameState) -> None:
    """Apply the correlated price drop to the whole market."""
    magnitude = state.config.shock_magnitude
    before = state.market.price_index
    state.market.price_index *= (1.0 - magnitude)
    state.market.shocks_fired += 1

    # A market-wide ledger note (player_id -1 == "the market/bank").
    state.record(
        Transaction(
            round_number=state.turn.round_number,
            player_id=-1,
            kind="shock",
            amount=0,
            note=(
                f"Systemic shock: property values -{magnitude:.0%} "
                f"(index {before:.2f} -> {state.market.price_index:.2f})"
            ),
        )
    )
