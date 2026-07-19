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
from typing import Dict, Optional


class ActionType:
    """String tags for the action discriminated union."""

    ROLL_DICE = "roll_dice"
    BUY = "buy"
    MORTGAGE = "mortgage"
    UNMORTGAGE = "unmortgage"
    LEVERAGE = "leverage"        # borrow cash against collateral
    REPAY_DEBT = "repay_debt"
    SECURITIZE = "securitize"    # IPO a slice of a property for cash
    BUILD = "build"              # add a building level to a monopoly landmark
    SELL_BUILDING = "sell_building"  # remove a building level for a partial refund
    PROPOSE_TRADE = "propose_trade"  # offer cash/tiles to another player
    ACCEPT_TRADE = "accept_trade"
    REJECT_TRADE = "reject_trade"
    CANCEL_TRADE = "cancel_trade"    # withdraw your own pending offer
    END_TURN = "end_turn"
    CONCEDE = "concede"


@dataclass(frozen=True)
class Action:
    """A single validated intent from one player.

    ``player_id`` identifies the sender; the reducer checks it against the active
    player where turn-ownership matters (trade actions are the deliberate
    exception -- see ``mechanics/trade.py``). ``type`` selects the handler. The
    remaining optional fields are the per-action arguments -- only the ones
    relevant to ``type`` are read, so this stays a flat, wire-friendly shape.
    """

    type: str
    player_id: int

    # Optional arguments (interpreted per ``type``):
    tile_index: Optional[int] = None   # BUY / MORTGAGE / UNMORTGAGE / SECURITIZE / BUILD / SELL_BUILDING
    amount: Optional[int] = None       # LEVERAGE (borrow) / REPAY_DEBT (repay)
    percent: Optional[float] = None    # SECURITIZE: fraction of shares to sell (0..1)

    # Trade arguments:
    target_player_id: Optional[int] = None            # PROPOSE_TRADE: the counterparty
    offer_cash: Optional[int] = None                   # PROPOSE_TRADE: cash you give
    offer_tiles: Optional[Dict[int, float]] = None     # PROPOSE_TRADE: tile_index -> share you give
    request_cash: Optional[int] = None                 # PROPOSE_TRADE: cash you want
    request_tiles: Optional[Dict[int, float]] = None   # PROPOSE_TRADE: tile_index -> share you want
    trade_id: Optional[int] = None                     # ACCEPT/REJECT/CANCEL_TRADE: which offer

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
        if self.target_player_id is not None:
            data["target_player_id"] = self.target_player_id
        if self.offer_cash is not None:
            data["offer_cash"] = self.offer_cash
        if self.offer_tiles is not None:
            data["offer_tiles"] = {str(k): v for k, v in self.offer_tiles.items()}
        if self.request_cash is not None:
            data["request_cash"] = self.request_cash
        if self.request_tiles is not None:
            data["request_tiles"] = {str(k): v for k, v in self.request_tiles.items()}
        if self.trade_id is not None:
            data["trade_id"] = self.trade_id
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Action":
        """Rebuild an action from its wire dict (used when replaying logs)."""
        offer_tiles = data.get("offer_tiles")
        request_tiles = data.get("request_tiles")
        return cls(
            type=data["type"],
            player_id=data["player_id"],
            tile_index=data.get("tile_index"),
            amount=data.get("amount"),
            percent=data.get("percent"),
            target_player_id=data.get("target_player_id"),
            offer_cash=data.get("offer_cash"),
            offer_tiles={int(k): v for k, v in offer_tiles.items()} if offer_tiles else None,
            request_cash=data.get("request_cash"),
            request_tiles={int(k): v for k, v in request_tiles.items()} if request_tiles else None,
            trade_id=data.get("trade_id"),
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


def build(player_id: int, tile_index: int) -> Action:
    return Action(ActionType.BUILD, player_id, tile_index=tile_index)


def sell_building(player_id: int, tile_index: int) -> Action:
    return Action(ActionType.SELL_BUILDING, player_id, tile_index=tile_index)


def propose_trade(
    player_id: int,
    target_player_id: int,
    offer_cash: int = 0,
    offer_tiles: Optional[Dict[int, float]] = None,
    request_cash: int = 0,
    request_tiles: Optional[Dict[int, float]] = None,
) -> Action:
    return Action(
        ActionType.PROPOSE_TRADE,
        player_id,
        target_player_id=target_player_id,
        offer_cash=offer_cash,
        offer_tiles=offer_tiles or {},
        request_cash=request_cash,
        request_tiles=request_tiles or {},
    )


def accept_trade(player_id: int, trade_id: int) -> Action:
    return Action(ActionType.ACCEPT_TRADE, player_id, trade_id=trade_id)


def reject_trade(player_id: int, trade_id: int) -> Action:
    return Action(ActionType.REJECT_TRADE, player_id, trade_id=trade_id)


def cancel_trade(player_id: int, trade_id: int) -> Action:
    return Action(ActionType.CANCEL_TRADE, player_id, trade_id=trade_id)


def end_turn(player_id: int) -> Action:
    return Action(ActionType.END_TURN, player_id)


def concede(player_id: int) -> Action:
    return Action(ActionType.CONCEDE, player_id)
