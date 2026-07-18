"""Development: building houses and a skyscraper on a monopoly.

The classic strategic layer that the capital-market mechanics sit on top of.
Once you sole-own a whole city (a monopoly), you may invest cash to develop its
landmarks -- each building level multiplies the rent you charge (see
``board.RENT_MULTIPLIERS``). This is the reward for completing a set, and the
thing a systemic shock or a margin call can wipe out in one turn.

Guards keep it consistent with the rest of the engine:
* you must sole-own the whole city (monopoly) and the tile must be unmortgaged;
* a developed tile cannot be mortgaged or securitized until its buildings are
  sold (enforced in those modules) -- so buildings only ever exist on a clean,
  fully-owned monopoly.
"""

from __future__ import annotations

from typing import Optional

from ..board import MAX_BUILDINGS, SELL_REFUND_RATIO
from ..errors import RuleError, RuleErrorCode
from ..state import GameState, Transaction
from .. import valuation


def build(state: GameState, player_id: int, tile_index: int) -> Optional[RuleError]:
    """Handle a BUILD action: add one development level to a monopoly landmark."""
    err = _validate_developable(state, player_id, tile_index)
    if err is not None:
        return err

    tile = state.board[tile_index]
    if tile.buildings >= MAX_BUILDINGS:
        return RuleError(
            RuleErrorCode.INVALID_TARGET, f"{tile.name} is already fully developed"
        )

    player = state.player_by_id(player_id)
    cost = tile.building_cost()
    if player.cash < cost:
        return RuleError(
            RuleErrorCode.INSUFFICIENT_CASH,
            f"Need {cost} cash to build on {tile.name}, have {player.cash}",
        )

    player.cash -= cost
    tile.buildings += 1
    label = "skyscraper" if tile.buildings == MAX_BUILDINGS else f"house {tile.buildings}"
    state.record(
        Transaction(
            round_number=state.turn.round_number,
            player_id=player_id,
            kind="build",
            amount=-cost,
            note=f"Built {label} on {tile.name}",
        )
    )
    return None


def sell_building(state: GameState, player_id: int, tile_index: int) -> Optional[RuleError]:
    """Handle a SELL_BUILDING action: remove one level, refunding part of its cost."""
    if tile_index is None or tile_index < 0 or tile_index >= len(state.board):
        return RuleError(RuleErrorCode.INVALID_TARGET, "Tile index out of range")
    tile = state.board[tile_index]
    if not tile.is_property():
        return RuleError(RuleErrorCode.INVALID_TARGET, "Tile is not a property")
    if tile.owned_share(player_id) <= 0.0 or tile.sole_owner() != player_id:
        return RuleError(RuleErrorCode.NOT_TILE_OWNER, "You do not own this property")
    if tile.buildings <= 0:
        return RuleError(RuleErrorCode.INVALID_TARGET, f"{tile.name} has no buildings to sell")

    refund = round(tile.building_cost() * SELL_REFUND_RATIO)
    player = state.player_by_id(player_id)
    player.cash += refund
    tile.buildings -= 1
    state.record(
        Transaction(
            round_number=state.turn.round_number,
            player_id=player_id,
            kind="sell_building",
            amount=refund,
            note=f"Sold a building on {tile.name}",
        )
    )
    return None


def _validate_developable(
    state: GameState, player_id: int, tile_index: int
) -> Optional[RuleError]:
    """Shared build validation: a monopoly landmark you sole-own, unmortgaged."""
    if tile_index is None or tile_index < 0 or tile_index >= len(state.board):
        return RuleError(RuleErrorCode.INVALID_TARGET, "Tile index out of range")
    tile = state.board[tile_index]
    if not tile.is_property():
        return RuleError(RuleErrorCode.INVALID_TARGET, "Tile is not a property")
    if tile.sole_owner() != player_id:
        return RuleError(RuleErrorCode.NOT_TILE_OWNER, "You must sole-own this property")
    if tile.mortgaged:
        return RuleError(
            RuleErrorCode.TILE_ALREADY_MORTGAGED, "Redeem the mortgage before developing"
        )
    if not valuation.has_monopoly(state, player_id, tile.group):
        return RuleError(
            RuleErrorCode.INSUFFICIENT_COLLATERAL,
            "You must own the whole city (a monopoly) to develop it",
        )
    return None
