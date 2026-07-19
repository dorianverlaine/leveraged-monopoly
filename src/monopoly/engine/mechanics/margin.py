"""Solvency enforcement: margin calls, forced liquidation, and bankruptcy.

This module turns "a slow grind to bankruptcy" into "a one-second collapse"
(architecture 4.1). It runs after any event that can hurt a player's balance
sheet -- paying rent, a tax, interest accrual, or a systemic shock -- and does
two jobs at once:

* **Cover negative cash.** A player who couldn't afford rent has their assets
  fire-sold to fill the hole.
* **Restore the margin ratio.** A player whose collateral/debt has fallen below
  ``maintenance_ratio`` is force-liquidated, whole property at a time, until they
  are solvent again or they run out of assets and go bankrupt.

Because a systemic shock hits every player's collateral simultaneously, calling
this once after a shock can domino several players at once -- 2008 in the living
room.
"""

from __future__ import annotations

from typing import List

from ..board import Tile
from ..player import Player, PlayerStatus
from ..state import GameState, Transaction
from .. import valuation

# Fire-sale penalty when the *engine* liquidates you (worse than a voluntary
# securitization, because you have no choice and no time).
LIQUIDATION_HAIRCUT = 0.20


def enforce_solvency(state: GameState) -> None:
    """Bring every in-play player back to solvency, liquidating as needed.

    Idempotent: calling it on an already-solvent game changes nothing. Players
    are processed independently -- forced sales go to "the market", so one
    player's liquidation never moves another player's cash.
    """
    for player in state.players:
        if player.status == PlayerStatus.BANKRUPT:
            continue
        _resolve_player(state, player)


def _resolve_player(state: GameState, player: Player) -> None:
    """Liquidate one player's holdings until solvent, or declare bankruptcy."""
    called = False

    while True:
        under_water_cash = player.cash < 0
        under_margin = (
            player.debt > 0
            and valuation.margin_ratio(state, player.id) < state.config.maintenance_ratio
        )

        if not under_water_cash and not under_margin:
            break

        # First try to cure a margin breach with spare cash (cheaper than selling).
        if not under_water_cash and under_margin and player.cash > 0:
            repay = min(player.debt, player.cash)
            if repay > 0:
                player.cash -= repay
                player.debt -= repay
                _record_liquidation(state, player, -repay, "Cash swept to cover margin")
                called = True
                continue

        # Otherwise sell a whole property (dominoes, one tile at a time).
        tile = _next_liquidatable_tile(state, player)
        if tile is None:
            break  # nothing left to sell -> resolved below as bankruptcy

        _liquidate_tile(state, player, tile)
        called = True

    # Final verdict: a player is bankrupt only if they owe more than they own
    # (negative net worth). By the time the loop above exits, a player who still
    # has negative cash has already run out of assets to sell, so their net worth
    # is negative too -- this single check captures both failure modes and,
    # crucially, does NOT bankrupt someone who can still cover their debt in cash.
    if valuation.net_worth(state, player.id) < -1e-6:
        bankrupt_player(state, player)
    elif called:
        # Survived a margin call this pass; make sure status is clean.
        player.status = PlayerStatus.ACTIVE


def _next_liquidatable_tile(state: GameState, player: Player):
    """Return the next property (in deterministic board order) the player can sell."""
    for tile in state.board:
        if tile.is_property() and tile.owned_share(player.id) > 0.0:
            return tile
    return None


def _liquidate_tile(state: GameState, player: Player, tile: Tile) -> None:
    """Force-sell the player's entire stake in ``tile`` to the market.

    Proceeds (after the fire-sale haircut, and after settling any mortgage on the
    tile) go to cash if cash is negative, otherwise straight to paying down debt.
    """
    share = tile.owned_share(player.id)
    gross = share * valuation.property_value(state, tile.index)
    proceeds = int(round(gross * (1.0 - LIQUIDATION_HAIRCUT)))

    # Settle any mortgage on this tile first (the loan is secured by it).
    if tile.mortgaged:
        principal = tile.mortgage_principal
        player.debt = max(0, player.debt - principal)
        proceeds = max(0, proceeds - principal)
        tile.mortgaged = False
        tile.mortgage_principal = 0

    # Any buildings are sold with the tile (their value is already in ``proceeds``
    # via property_value); the fire sale demolishes them.
    tile.buildings = 0

    # Remove the player's stake; the share reverts to "the market" (unowned).
    tile.shares.pop(player.id, None)

    if player.cash < 0:
        # Use proceeds to fill the cash hole first.
        player.cash += proceeds
    else:
        # Solvent on cash but under margin: pay proceeds straight onto the debt.
        repay = min(player.debt, proceeds)
        player.debt -= repay
        leftover = proceeds - repay
        player.cash += leftover

    _record_liquidation(
        state, player, proceeds, f"Forced liquidation of {tile.name}"
    )


def bankrupt_player(state: GameState, player: Player) -> None:
    """Take a player out of the game: forfeit holdings, write off debt.

    Public so the reducer can use it for a voluntary CONCEDE as well as for the
    involuntary end of a failed liquidation.
    """
    for tile in state.board:
        if tile.is_property() and player.id in tile.shares:
            tile.shares.pop(player.id, None)
            if tile.sole_owner() is None and tile.total_owned() <= 1e-9:
                tile.mortgaged = False
                tile.mortgage_principal = 0
                tile.buildings = 0

    forfeited_debt = player.debt
    player.debt = 0
    player.cash = 0
    player.status = PlayerStatus.BANKRUPT

    # A bankrupt player can no longer honor any trade they proposed or were
    # offered; drop those pending offers rather than leave them dangling.
    state.trades = [
        t for t in state.trades if player.id not in (t.proposer_id, t.recipient_id)
    ]

    state.record(
        Transaction(
            round_number=state.turn.round_number,
            player_id=player.id,
            kind="bankruptcy",
            amount=-forfeited_debt,
            note="Bankrupted -- assets forfeited, debt written off",
        )
    )


def _record_liquidation(
    state: GameState, player: Player, amount: int, note: str
) -> None:
    state.record(
        Transaction(
            round_number=state.turn.round_number,
            player_id=player.id,
            kind="liquidation",
            amount=amount,
            note=note,
        )
    )
