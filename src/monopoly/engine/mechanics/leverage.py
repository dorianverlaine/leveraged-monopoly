"""Leverage: borrowing, repaying, and mortgaging.

This is the soul of the game (architecture 4.1). Property is not cash-only: a
player can borrow against their portfolio to buy more, but a falling collateral
ratio triggers forced liquidation (see the margin module). Two borrowing tools:

* **Leverage** -- portfolio-wide margin loan against total unmortgaged collateral,
  capped by ``max_leverage_ratio``.
* **Mortgage** -- a specific-property secured loan (50% of value). The property
  stops earning rent and stops counting as fresh collateral until redeemed.

Both add to ``player.debt``; mortgages additionally record their principal on the
tile so redemption reconciles exactly.
"""

from __future__ import annotations

from typing import Optional

from ..errors import RuleError, RuleErrorCode
from ..state import GameState, Transaction
from .. import valuation

# Fraction of a property's market value advanced when it is mortgaged.
MORTGAGE_LTV = 0.50
# Extra fraction of principal charged as an interest fee to redeem a mortgage.
UNMORTGAGE_FEE = 0.10


def borrow(state: GameState, player_id: int, amount: int) -> Optional[RuleError]:
    """Handle a LEVERAGE action: draw ``amount`` cash as new margin debt."""
    player = state.player_by_id(player_id)
    if player is None:
        return RuleError(RuleErrorCode.INVALID_TARGET, "Unknown player")
    if amount is None or amount <= 0:
        return RuleError(RuleErrorCode.INVALID_AMOUNT, "Borrow amount must be positive")

    ceiling = valuation.max_borrowable(state, player_id)
    if amount > ceiling:
        return RuleError(
            RuleErrorCode.OVER_BORROW,
            f"Can borrow at most {ceiling} against collateral, requested {amount}",
        )

    player.cash += amount
    player.debt += amount
    state.record(
        Transaction(
            round_number=state.turn.round_number,
            player_id=player_id,
            kind="leverage",
            amount=amount,
            note="Borrowed against portfolio",
        )
    )
    return None


def repay(state: GameState, player_id: int, amount: int) -> Optional[RuleError]:
    """Handle a REPAY_DEBT action: pay down margin debt with cash.

    The repayment is capped at both the player's cash and their outstanding debt,
    so callers can safely pass a large number to mean "repay as much as I can".
    """
    player = state.player_by_id(player_id)
    if player is None:
        return RuleError(RuleErrorCode.INVALID_TARGET, "Unknown player")
    if amount is None or amount <= 0:
        return RuleError(RuleErrorCode.INVALID_AMOUNT, "Repay amount must be positive")
    if player.debt <= 0:
        return RuleError(RuleErrorCode.NOTHING_TO_REPAY, "No outstanding debt")

    paid = min(amount, player.debt, player.cash)
    if paid <= 0:
        return RuleError(RuleErrorCode.INSUFFICIENT_CASH, "No cash available to repay")

    player.cash -= paid
    player.debt -= paid
    state.record(
        Transaction(
            round_number=state.turn.round_number,
            player_id=player_id,
            kind="repay",
            amount=-paid,
            note="Repaid debt",
        )
    )
    return None


def mortgage(state: GameState, player_id: int, tile_index: int) -> Optional[RuleError]:
    """Handle a MORTGAGE action: raise cash against a fully-owned property.

    Advances ``MORTGAGE_LTV`` of the property's current market value as cash and
    records the matching principal as debt. Net worth is unchanged at the moment
    of mortgaging (cash up, debt up); the property just stops earning rent and
    stops backing further leverage until redeemed.
    """
    err = _validate_owned_tile(state, player_id, tile_index)
    if err is not None:
        return err

    tile = state.board[tile_index]
    if tile.mortgaged:
        return RuleError(
            RuleErrorCode.TILE_ALREADY_MORTGAGED, f"{tile.name} is already mortgaged"
        )
    if tile.sole_owner() != player_id:
        return RuleError(
            RuleErrorCode.NOT_TILE_OWNER,
            "Only a sole owner can mortgage a property (securitized shares block it)",
        )
    if tile.buildings > 0:
        return RuleError(
            RuleErrorCode.INVALID_TARGET,
            "Sell this property's buildings before mortgaging it",
        )

    principal = int(round(valuation.property_value(state, tile_index) * MORTGAGE_LTV))
    if principal <= 0:
        return RuleError(RuleErrorCode.INVALID_AMOUNT, "Property has no mortgage value")

    player = state.player_by_id(player_id)
    player.cash += principal
    player.debt += principal
    tile.mortgaged = True
    tile.mortgage_principal = principal
    state.record(
        Transaction(
            round_number=state.turn.round_number,
            player_id=player_id,
            kind="mortgage",
            amount=principal,
            note=f"Mortgaged {tile.name}",
        )
    )
    return None


def unmortgage(state: GameState, player_id: int, tile_index: int) -> Optional[RuleError]:
    """Handle an UNMORTGAGE action: redeem a mortgaged property.

    Repays the recorded principal plus an ``UNMORTGAGE_FEE`` interest charge,
    restoring the property's rent and collateral value.
    """
    err = _validate_owned_tile(state, player_id, tile_index)
    if err is not None:
        return err

    tile = state.board[tile_index]
    if not tile.mortgaged:
        return RuleError(
            RuleErrorCode.TILE_NOT_MORTGAGED, f"{tile.name} is not mortgaged"
        )

    principal = tile.mortgage_principal
    cost = int(round(principal * (1.0 + UNMORTGAGE_FEE)))
    player = state.player_by_id(player_id)
    if player.cash < cost:
        return RuleError(
            RuleErrorCode.INSUFFICIENT_CASH,
            f"Need {cost} cash to redeem {tile.name}, have {player.cash}",
        )

    player.cash -= cost
    player.debt = max(0, player.debt - principal)
    tile.mortgaged = False
    tile.mortgage_principal = 0
    state.record(
        Transaction(
            round_number=state.turn.round_number,
            player_id=player_id,
            kind="unmortgage",
            amount=-cost,
            note=f"Redeemed {tile.name}",
        )
    )
    return None


def _validate_owned_tile(
    state: GameState, player_id: int, tile_index: int
) -> Optional[RuleError]:
    """Shared validation: the index is a property in which the player has a share."""
    if tile_index is None or tile_index < 0 or tile_index >= len(state.board):
        return RuleError(RuleErrorCode.INVALID_TARGET, "Tile index out of range")
    tile = state.board[tile_index]
    if not tile.is_property():
        return RuleError(RuleErrorCode.INVALID_TARGET, "Tile is not a property")
    if tile.owned_share(player_id) <= 0.0:
        return RuleError(RuleErrorCode.NOT_TILE_OWNER, "You do not own this property")
    return None
