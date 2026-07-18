"""Buying property and paying rent on landing.

``resolve_landing`` is the internal step the reducer runs right after movement:
if the player landed on someone else's property, rent is charged here (which may
push them into insolvency, handled downstream by the margin module). Buying is a
separate, explicit player action (``BUY``) so the player chooses when to spend.
"""

from __future__ import annotations

from typing import Optional

from ..board import TileType
from ..errors import RuleError, RuleErrorCode
from ..state import GameState, Transaction
from .. import valuation


def resolve_landing(state: GameState) -> None:
    """Apply the effect of the tile the active player just landed on.

    Only rent is auto-applied here. TAX tiles charge a flat fee. Buying an
    unowned property and drawing EVENT cards are handled elsewhere (BUY action /
    shock arming) so this stays side-effect-light and predictable.
    """
    player = state.active_player()
    tile = state.board[player.position]

    if tile.type == TileType.TAX:
        _charge_tax(state, tile.tax_amount)
        return

    if tile.type == TileType.PROPERTY:
        _charge_rent(state, tile.index)
        return

    # GO / CORNER / EVENT: no immediate mandatory charge in v1.


def _charge_tax(state: GameState, amount: int) -> None:
    """Charge a flat tax to the active player (cash may go negative -> liquidation)."""
    if amount <= 0:
        return
    player = state.active_player()
    player.cash -= amount
    state.market.money_supply -= amount  # tax is money leaving circulation
    state.record(
        Transaction(
            round_number=state.turn.round_number,
            player_id=player.id,
            kind="tax",
            amount=-amount,
            note="Landed on tax tile",
        )
    )


def _charge_rent(state: GameState, tile_index: int) -> None:
    """Charge rent for landing on a property and distribute it to its owners.

    Rent is charged only on the portion owned by *other* players (a player never
    pays rent to themselves, and the securitized-away 'market' portion earns no
    rent -- that lost income is the price of having IPO'd it). Mortgaged
    properties charge nothing.

    A sole owner who holds the whole city (monopoly) charges a multiplied rent:
    2x undeveloped, escalating with each building up to the skyscraper.
    """
    from ..board import RENT_MULTIPLIERS

    tile = state.board[tile_index]
    if tile.mortgaged or tile.is_unowned():
        return

    payer = state.active_player()
    full_rent = tile.base_rent * state.market.price_index

    # Monopoly + development multiplier (only a sole owner of the full city).
    sole = tile.sole_owner()
    if sole is not None and valuation.has_monopoly(state, sole, tile.group):
        full_rent *= RENT_MULTIPLIERS[min(tile.buildings, len(RENT_MULTIPLIERS) - 1)]

    # Only the share held by players *other than the payer* generates rent owed.
    payable_share = tile.total_owned() - tile.owned_share(payer.id)
    if payable_share <= 1e-9:
        return

    total_paid = 0
    # Distribute to each other owner pro-rata by their share of the property.
    for owner_id, share in list(tile.shares.items()):
        if owner_id == payer.id:
            continue
        owner = state.player_by_id(owner_id)
        if owner is None:
            continue
        owed = int(round(full_rent * share))
        if owed <= 0:
            continue
        owner.cash += owed
        total_paid += owed
        state.record(
            Transaction(
                round_number=state.turn.round_number,
                player_id=owner_id,
                kind="rent",
                amount=owed,
                note=f"Rent from player {payer.id} on {tile.name}",
            )
        )

    if total_paid > 0:
        payer.cash -= total_paid
        state.record(
            Transaction(
                round_number=state.turn.round_number,
                player_id=payer.id,
                kind="rent",
                amount=-total_paid,
                note=f"Rent paid on {tile.name}",
            )
        )


def buy_tile(state: GameState, player_id: int, tile_index: int) -> Optional[RuleError]:
    """Handle a BUY action: purchase the unowned property the player stands on.

    Bought at the fixed sticker ``price`` (not the inflated market value), so
    buying early and letting inflation lift the asset is a real, intended edge
    for asset-holders over cash-holders.
    """
    if tile_index < 0 or tile_index >= len(state.board):
        return RuleError(RuleErrorCode.INVALID_TARGET, "Tile index out of range")

    tile = state.board[tile_index]
    player = state.player_by_id(player_id)
    if player is None:
        return RuleError(RuleErrorCode.INVALID_TARGET, "Unknown player")

    if not tile.is_property():
        return RuleError(RuleErrorCode.TILE_NOT_PURCHASABLE, "Tile is not a property")
    if player.position != tile_index:
        return RuleError(
            RuleErrorCode.INVALID_TARGET, "Can only buy the tile you are standing on"
        )
    if not tile.is_unowned():
        return RuleError(RuleErrorCode.TILE_ALREADY_OWNED, "Property already owned")

    cost = tile.price
    if player.cash < cost:
        return RuleError(
            RuleErrorCode.INSUFFICIENT_CASH,
            f"Need {cost} cash to buy {tile.name}, have {player.cash}",
        )

    player.cash -= cost
    tile.shares = {player_id: 1.0}
    state.record(
        Transaction(
            round_number=state.turn.round_number,
            player_id=player_id,
            kind="buy",
            amount=-cost,
            note=f"Bought {tile.name}",
        )
    )
    return None
