"""Player state.

A player holds cash and debt, sits on a board tile, and has a lifecycle status.
Note what is *not* here: net worth, collateral value, and margin ratio are all
*derived* quantities computed from the board in :mod:`monopoly.engine.valuation`.
Storing them would risk drift; they are always recomputed from the source of
truth (cash, debt, and the shares recorded on each tile).
"""

from __future__ import annotations

from dataclasses import dataclass


class PlayerStatus:
    """Lifecycle states for a player."""

    ACTIVE = "active"
    MARGIN_CALLED = "margin_called"   # transient: flagged this turn, being liquidated
    BANKRUPT = "bankrupt"             # out of the game
    DISCONNECTED = "disconnected"     # human dropped; turn may be skipped or handed to a bot


@dataclass
class Player:
    """One participant (human or bot)."""

    id: int
    name: str
    cash: int
    position: int = 0                 # current tile index on the ring
    debt: int = 0                     # outstanding borrowed principal owed to the bank
    status: str = PlayerStatus.ACTIVE

    # Backfill / matchmaking metadata. ``policy`` names a bot policy when
    # ``is_bot`` is true (see monopoly.bots). Humans leave it empty.
    is_bot: bool = False
    policy: str = ""

    def is_in_play(self) -> bool:
        """True if the player can still take actions (not bankrupt)."""
        return self.status not in (PlayerStatus.BANKRUPT,)

    def to_dict(self) -> dict:
        """Serialize the stored fields. Derived metrics are added by the state
        serializer, which has access to the board."""
        return {
            "id": self.id,
            "name": self.name,
            "cash": self.cash,
            "position": self.position,
            "debt": self.debt,
            "status": self.status,
            "is_bot": self.is_bot,
            "policy": self.policy,
        }
