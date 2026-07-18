"""Securitization / REIT: IPO a slice of a property for immediate cash.

Cash-strapped players can package a property and sell equity in it to the market
(architecture 4.3). You get liquidity now, but you keep only the un-sold share of
its rent forever -- and the market takes a haircut on the sale. This manufactures
an in-game equity market and a lot of betrayal.

In P0 the buyer is "the market" (the bank), so sold shares simply leave player
ownership and their rent stops accruing to anyone. A future version can route the
sale to a specific rival player.
"""

from __future__ import annotations

from typing import Optional

from ..errors import RuleError, RuleErrorCode
from ..state import GameState, Transaction
from .. import valuation


def securitize(
    state: GameState, player_id: int, tile_index: int, percent: float
) -> Optional[RuleError]:
    """Handle a SECURITIZE action: sell ``percent`` of your stake in a property.

    ``percent`` is the fraction *of your current holding* to sell (0..1]. Proceeds
    are the sold value minus ``config.securitization_haircut``.
    """
    if tile_index is None or tile_index < 0 or tile_index >= len(state.board):
        return RuleError(RuleErrorCode.INVALID_TARGET, "Tile index out of range")
    tile = state.board[tile_index]
    if not tile.is_property():
        return RuleError(RuleErrorCode.INVALID_TARGET, "Tile is not a property")
    if tile.mortgaged:
        return RuleError(
            RuleErrorCode.TILE_ALREADY_MORTGAGED,
            "Cannot securitize a mortgaged property; redeem it first",
        )

    player = state.player_by_id(player_id)
    if player is None:
        return RuleError(RuleErrorCode.INVALID_TARGET, "Unknown player")

    current_share = tile.owned_share(player_id)
    if current_share <= 0.0:
        return RuleError(RuleErrorCode.NOT_TILE_OWNER, "You do not own this property")
    if percent is None or percent <= 0.0 or percent > 1.0:
        return RuleError(
            RuleErrorCode.INVALID_PERCENT, "percent must be in the range (0, 1]"
        )

    sold_share = current_share * percent
    gross = sold_share * valuation.property_value(state, tile_index)
    proceeds = int(round(gross * (1.0 - state.config.securitization_haircut)))

    remaining = current_share - sold_share
    if remaining <= 1e-9:
        tile.shares.pop(player_id, None)
    else:
        tile.shares[player_id] = remaining

    player.cash += proceeds
    state.record(
        Transaction(
            round_number=state.turn.round_number,
            player_id=player_id,
            kind="securitize",
            amount=proceeds,
            note=f"Securitized {percent:.0%} of stake in {tile.name}",
        )
    )
    return None
