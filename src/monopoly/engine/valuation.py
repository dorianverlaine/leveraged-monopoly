"""Derived economic quantities.

Nothing here is stored on the state -- everything is recomputed from the source
of truth (each player's cash/debt plus the shares recorded on each tile, scaled
by the market price index). Centralising these formulas means leverage, margin,
securitization, and the UI all agree on what a property is "worth" and when a
player is under-collateralised.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid a runtime circular import with state.py
    from .state import GameState


def property_value(state: "GameState", tile_index: int) -> float:
    """Market value of a whole property tile at the current price index.

    Includes the cash invested in any buildings on the tile, so a developed
    landmark is worth more (this feeds net worth, collateral, securitization
    pricing, and liquidation proceeds). A mortgaged property still reports its
    clean market value here; collateral is handled separately.
    """
    from .board import building_cost

    tile = state.board[tile_index]
    if not tile.is_property():
        return 0.0
    base = tile.price + tile.buildings * building_cost(tile.price)
    return base * state.market.price_index


def has_monopoly(state: "GameState", player_id: int, group: str) -> bool:
    """True if ``player_id`` is the sole owner of every landmark in ``group``.

    This is what grants the rent-doubling bonus and unlocks development.
    Securitizing away any share of any landmark in the city breaks it.
    """
    if not group:
        return False
    tiles = [t for t in state.board if t.is_property() and t.group == group]
    if not tiles:
        return False
    return all(t.sole_owner() == player_id for t in tiles)


def player_property_value(state: "GameState", player_id: int) -> float:
    """Total market value of the shares a player holds across all properties."""
    total = 0.0
    for tile in state.board:
        if tile.is_property():
            share = tile.owned_share(player_id)
            if share > 0.0:
                total += share * property_value(state, tile.index)
    return total


def collateral_value(state: "GameState", player_id: int) -> float:
    """Value of a player's holdings that can back debt.

    Mortgaged properties are already pledged, so they do not count toward fresh
    collateral. This is the denominator-side quantity for margin checks and the
    base for how much a player may borrow.
    """
    total = 0.0
    for tile in state.board:
        if tile.is_property() and not tile.mortgaged:
            share = tile.owned_share(player_id)
            if share > 0.0:
                total += share * property_value(state, tile.index)
    return total


def player_assets(state: "GameState", player_id: int) -> float:
    """Cash plus the market value of all property shares (ignores debt)."""
    player = state.player_by_id(player_id)
    cash = player.cash if player else 0
    return cash + player_property_value(state, player_id)


def net_worth(state: "GameState", player_id: int) -> float:
    """Assets minus debt -- the headline number the UI flashes."""
    player = state.player_by_id(player_id)
    debt = player.debt if player else 0
    return player_assets(state, player_id) - debt


def margin_ratio(state: "GameState", player_id: int) -> float:
    """Collateral coverage: collateral value / debt.

    Debt-free players are infinitely collateralised, reported as ``inf``. When
    this ratio falls below ``config.maintenance_ratio`` the player is
    margin-called and force-liquidated (see mechanics/margin).
    """
    player = state.player_by_id(player_id)
    debt = player.debt if player else 0
    if debt <= 0:
        return float("inf")
    return collateral_value(state, player_id) / debt


def max_borrowable(state: "GameState", player_id: int) -> int:
    """Additional cash a player may borrow right now.

    Capped so that total debt stays within ``max_leverage_ratio`` of unmortgaged
    collateral value. Never negative.
    """
    player = state.player_by_id(player_id)
    debt = player.debt if player else 0
    ceiling = collateral_value(state, player_id) * state.config.max_leverage_ratio
    room = ceiling - debt
    return int(room) if room > 0 else 0
