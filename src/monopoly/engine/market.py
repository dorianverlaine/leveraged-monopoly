"""Market state -- the macroeconomic backdrop shared by all players.

Two forces live here:

* **Inflation** (``price_index`` / ``money_supply``): the bank prints money over
  time, lifting asset prices and thinning cash (see mechanics/inflation).
* **Systemic shock** (``shock_clock``): a countdown that, when it fires, moves
  asset values *for everyone at once* -- the correlated draw that margin-calls
  every over-leveraged player simultaneously (see mechanics/shock).

Both are parameters of the running game, not hardcoded behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Market:
    """Macro state affecting every property valuation on the board."""

    # Multiplier applied to every property's reference price/rent. Starts at 1.0
    # and drifts up with inflation; a systemic shock can jolt it down sharply.
    price_index: float = 1.0

    # Total money the bank has injected (via GO salaries etc.). Drives inflation.
    money_supply: int = 0

    # Rounds remaining until the next systemic shock fires. Re-armed after each
    # shock. ``<= 0`` while disarmed.
    shock_clock: int = 0

    # How many shocks have fired so far (useful for analytics / escalation).
    shocks_fired: int = 0

    def to_dict(self) -> dict:
        """Serialize for the wire / persistence."""
        return {
            "price_index": self.price_index,
            "money_supply": self.money_supply,
            "shock_clock": self.shock_clock,
            "shocks_fired": self.shocks_fired,
        }
