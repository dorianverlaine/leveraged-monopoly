"""The action space -- every intent a client can send.

Design principle #1 (server-authoritative, dumb clients): clients never compute
game logic. They send an :class:`Action` describing *intent* ("mortgage tile X",
"borrow Y"), and the server-side reducer validates and applies it. Each action is
an explicit, validated, serializable value object.

Actions round-trip to/from plain ``dict`` (``to_dict`` / ``from_dict``) so they
can travel over the WebSocket wire and be stored in the replay log
(``seed + action_log`` *is* the whole game).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class ActionType:
    """String tags for the action discriminated union."""

    ROLL_DICE = "roll_dice"
    BUY = "buy"
    MORTGAGE = "mortgage"
    UNMORTGAGE = "unmortgage"
    LEVERAGE = "leverage"        # borrow cash against collateral
    REPAY_DEBT = "repay_debt"
    SECURITIZE = "securitize"    # IPO a slice of a property for cash
    END_TURN = "end_turn"
    CONCEDE = "concede"


@dataclass(frozen=True)
class Action:
    """A single validated intent from one player.

    ``player_id`` identifies the sender; the reducer checks it against the active
    player where turn-ownership matters. ``type`` selects the handler. The
    remaining optional fields are the per-action arguments -- only the ones
    relevant to ``type`` are read, so this stays a flat, wire-friendly shape.
    """

    type: str
    player_id: int

    # Optional arguments (interpreted per ``type``):
    tile_index: Optional[int] = None   # BUY / MORTGAGE / UNMORTGAGE / SECURITIZE
    amount: Optional[int] = None       # LEVERAGE (borrow) / REPAY_DEBT (repay)
    percent: Optional[float] = None    # SECURITIZE: fraction of shares to sell (0..1)

    # --- Serialization -----------------------------------------------------
    def to_dict(self) -> dict:
        """Serialize to a compact wire dict, omitting unused argument fields."""
        data: dict = {"type": self.type, "player_id": self.player_id}
        if self.tile_index is not None:
            data["tile_index"] = self.tile_index
        if self.amount is not None:
            data["amount"] = self.amount
        if self.percent is not None:
            data["percent"] = self.percent
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Action":
        """Rebuild an action from its wire dict (used when replaying logs)."""
        return cls(
            type=data["type"],
            player_id=data["player_id"],
            tile_index=data.get("tile_index"),
            amount=data.get("amount"),
            percent=data.get("percent"),
        )


# --- Ergonomic constructors ------------------------------------------------
# Thin helpers so callers (bots, tests, the future Worker) read clearly instead
# of juggling keyword arguments. They all return the same frozen Action type.

def roll_dice(player_id: int) -> Action:
    return Action(ActionType.ROLL_DICE, player_id)


def buy(player_id: int, tile_index: int) -> Action:
    return Action(ActionType.BUY, player_id, tile_index=tile_index)


def mortgage(player_id: int, tile_index: int) -> Action:
    return Action(ActionType.MORTGAGE, player_id, tile_index=tile_index)


def unmortgage(player_id: int, tile_index: int) -> Action:
    return Action(ActionType.UNMORTGAGE, player_id, tile_index=tile_index)


def leverage(player_id: int, amount: int) -> Action:
    return Action(ActionType.LEVERAGE, player_id, amount=amount)


def repay_debt(player_id: int, amount: int) -> Action:
    return Action(ActionType.REPAY_DEBT, player_id, amount=amount)


def securitize(player_id: int, tile_index: int, percent: float) -> Action:
    return Action(ActionType.SECURITIZE, player_id, tile_index=tile_index, percent=percent)


def end_turn(player_id: int) -> Action:
    return Action(ActionType.END_TURN, player_id)


def concede(player_id: int) -> Action:
    return Action(ActionType.CONCEDE, player_id)
