"""Player-to-player trading: propose, accept, reject, cancel.

This is the deliberate exception to "only the active player may act": real
trade talk happens *anytime*, not just on your turn (the reducer does not
turn-gate these four actions -- see the ``_guard_in_play`` guard, distinct from
``_guard_management``). It is also what makes completing a city monopoly
realistic -- landing alone on all six landmarks of a city is rare (see
board.py); trading lets players negotiate to complete a set, which is the
classic Monopoly social/betrayal layer, and it manufactures the leverage this
game's capital-market mechanics are built to detonate: complete a monopoly via
trade, over-develop it on borrowed cash, and a systemic shock (or a rival's
well-timed counter-trade) can margin-call you in the same turn.

A proposal only creates a pending :class:`~monopoly.engine.state.TradeOffer`;
nothing moves until the recipient accepts. Both sides are **re-validated at
accept time**, not just at proposal time, because state can drift between the
two (the proposer might have spent the cash, mortgaged the tile, or gone
bankrupt in the meantime) -- a proposal is an offer, not a reservation.
"""

from __future__ import annotations

from typing import Dict, Optional

from ..board import Tile
from ..errors import RuleError, RuleErrorCode
from ..player import PlayerStatus
from ..state import GameState, Transaction, TradeOffer
from .. import valuation

_EPSILON = 1e-9


def propose(
    state: GameState,
    proposer_id: int,
    recipient_id: int,
    offer_cash: int,
    offer_tiles: Dict[int, float],
    request_cash: int,
    request_tiles: Dict[int, float],
) -> Optional[RuleError]:
    """Handle a PROPOSE_TRADE action: create a pending offer.

    Validates the shape of the offer and that the proposer currently plausibly
    can honor their side (a fast-fail courtesy; the authoritative check happens
    again at accept). Assigns the offer a deterministic id from
    ``state.next_trade_id`` -- see :class:`TradeOffer` for why this must never
    be a random UUID.
    """
    if proposer_id == recipient_id:
        return RuleError(RuleErrorCode.INVALID_TARGET, "Cannot trade with yourself")

    recipient = state.player_by_id(recipient_id)
    if recipient is None or recipient.status == PlayerStatus.BANKRUPT:
        return RuleError(RuleErrorCode.INVALID_TARGET, "Invalid trade target")

    if offer_cash < 0 or request_cash < 0:
        return RuleError(RuleErrorCode.INVALID_AMOUNT, "Cash amounts cannot be negative")

    if not offer_cash and not request_cash and not offer_tiles and not request_tiles:
        return RuleError(RuleErrorCode.EMPTY_TRADE, "A trade must offer or request something")

    if set(offer_tiles) & set(request_tiles):
        return RuleError(RuleErrorCode.INVALID_TARGET, "A tile cannot be on both sides of a trade")

    err = _validate_tile_shares(state, offer_tiles, holder_id=proposer_id)
    if err is not None:
        return err
    err = _validate_tile_shares(state, request_tiles, holder_id=recipient_id)
    if err is not None:
        return err

    proposer = state.player_by_id(proposer_id)
    if proposer.cash < offer_cash:
        return RuleError(
            RuleErrorCode.INSUFFICIENT_CASH, "You cannot offer more cash than you have"
        )

    trade = TradeOffer(
        id=state.next_trade_id,
        proposer_id=proposer_id,
        recipient_id=recipient_id,
        offer_cash=offer_cash,
        offer_tiles=dict(offer_tiles),
        request_cash=request_cash,
        request_tiles=dict(request_tiles),
        created_round=state.turn.round_number,
    )
    state.next_trade_id += 1
    state.trades.append(trade)
    return None


def accept(state: GameState, recipient_id: int, trade_id: Optional[int]) -> Optional[RuleError]:
    """Handle an ACCEPT_TRADE action: re-validate and execute the swap."""
    trade = _find_trade(state, trade_id)
    if trade is None:
        return RuleError(RuleErrorCode.TRADE_NOT_FOUND, "No such pending trade")
    if trade.recipient_id != recipient_id:
        return RuleError(RuleErrorCode.NOT_TRADE_PARTICIPANT, "You are not this trade's recipient")

    err = _revalidate(state, trade)
    if err is not None:
        state.trades.remove(trade)  # the offer is stale; drop it rather than leave it dangling
        return err

    _execute(state, trade)
    state.trades.remove(trade)
    return None


def reject(state: GameState, recipient_id: int, trade_id: Optional[int]) -> Optional[RuleError]:
    """Handle a REJECT_TRADE action: the recipient declines the offer."""
    trade = _find_trade(state, trade_id)
    if trade is None:
        return RuleError(RuleErrorCode.TRADE_NOT_FOUND, "No such pending trade")
    if trade.recipient_id != recipient_id:
        return RuleError(RuleErrorCode.NOT_TRADE_PARTICIPANT, "You are not this trade's recipient")
    state.trades.remove(trade)
    return None


def cancel(state: GameState, proposer_id: int, trade_id: Optional[int]) -> Optional[RuleError]:
    """Handle a CANCEL_TRADE action: the proposer withdraws their own offer."""
    trade = _find_trade(state, trade_id)
    if trade is None:
        return RuleError(RuleErrorCode.TRADE_NOT_FOUND, "No such pending trade")
    if trade.proposer_id != proposer_id:
        return RuleError(RuleErrorCode.NOT_TRADE_PARTICIPANT, "You are not this trade's proposer")
    state.trades.remove(trade)
    return None


# --- Internals ---------------------------------------------------------

def _find_trade(state: GameState, trade_id: Optional[int]) -> Optional[TradeOffer]:
    if trade_id is None:
        return None
    for trade in state.trades:
        if trade.id == trade_id:
            return trade
    return None


def _validate_tile_shares(
    state: GameState, tiles: Dict[int, float], holder_id: int
) -> Optional[RuleError]:
    """Check that ``holder_id`` currently owns >= each requested share, on a
    clean (unmortgaged, undeveloped) property -- the same constraint mortgage
    and securitize apply, kept consistent so a traded tile never carries debt or
    building state that would need to follow it to a new owner."""
    for tile_index, share in tiles.items():
        if tile_index < 0 or tile_index >= len(state.board):
            return RuleError(RuleErrorCode.INVALID_TARGET, "Tile index out of range")
        tile = state.board[tile_index]
        if not tile.is_property():
            return RuleError(RuleErrorCode.INVALID_TARGET, "Tile is not a property")
        if share <= 0.0 or share > 1.0:
            return RuleError(RuleErrorCode.INVALID_PERCENT, "Trade share must be in (0, 1]")
        if tile.mortgaged:
            return RuleError(
                RuleErrorCode.TILE_ALREADY_MORTGAGED,
                f"{tile.name} is mortgaged; redeem it before trading",
            )
        if tile.buildings > 0:
            return RuleError(
                RuleErrorCode.INVALID_TARGET,
                f"Sell {tile.name}'s buildings before trading it",
            )
        if tile.owned_share(holder_id) + _EPSILON < share:
            return RuleError(
                RuleErrorCode.INSUFFICIENT_COLLATERAL,
                f"Holder does not own {share:.0%} of {tile.name}",
            )
    return None


def _revalidate(state: GameState, trade: TradeOffer) -> Optional[RuleError]:
    """Authoritative re-check at accept time: state may have drifted since the
    proposal (spent cash, mortgaged/developed/sold the tile, gone bankrupt)."""
    proposer = state.player_by_id(trade.proposer_id)
    recipient = state.player_by_id(trade.recipient_id)
    if proposer is None or recipient is None:
        return RuleError(RuleErrorCode.TRADE_NO_LONGER_VALID, "A trade participant no longer exists")
    if proposer.status == PlayerStatus.BANKRUPT or recipient.status == PlayerStatus.BANKRUPT:
        return RuleError(RuleErrorCode.TRADE_NO_LONGER_VALID, "A trade participant went bankrupt")
    if proposer.cash < trade.offer_cash:
        return RuleError(RuleErrorCode.TRADE_NO_LONGER_VALID, "Proposer can no longer afford this trade")
    if recipient.cash < trade.request_cash:
        return RuleError(RuleErrorCode.TRADE_NO_LONGER_VALID, "You can no longer afford this trade")

    err = _validate_tile_shares(state, trade.offer_tiles, holder_id=trade.proposer_id)
    if err is not None:
        return RuleError(RuleErrorCode.TRADE_NO_LONGER_VALID, "Offered property is no longer available")
    err = _validate_tile_shares(state, trade.request_tiles, holder_id=trade.recipient_id)
    if err is not None:
        return RuleError(RuleErrorCode.TRADE_NO_LONGER_VALID, "Requested property is no longer available")
    return None


def _execute(state: GameState, trade: TradeOffer) -> None:
    """Move cash and shares both directions atomically, then ledger it.

    Giving away a tile can shrink the giver's collateral (if it backed a margin
    loan) just as easily as it can shrink the receiver's -- this is deliberate:
    the reducer runs ``enforce_solvency`` after every trade, so a trade can
    trigger a margin call on either side (see reducer._handle_accept_trade).
    """
    proposer = state.player_by_id(trade.proposer_id)
    recipient = state.player_by_id(trade.recipient_id)

    proposer.cash += trade.request_cash - trade.offer_cash
    recipient.cash += trade.offer_cash - trade.request_cash

    for tile_index, share in trade.offer_tiles.items():
        _transfer_share(state.board[tile_index], trade.proposer_id, trade.recipient_id, share)
    for tile_index, share in trade.request_tiles.items():
        _transfer_share(state.board[tile_index], trade.recipient_id, trade.proposer_id, share)

    state.record(
        Transaction(
            round_number=state.turn.round_number,
            player_id=trade.proposer_id,
            kind="trade",
            amount=trade.request_cash - trade.offer_cash,
            note=f"Trade with player {trade.recipient_id} accepted",
        )
    )
    state.record(
        Transaction(
            round_number=state.turn.round_number,
            player_id=trade.recipient_id,
            kind="trade",
            amount=trade.offer_cash - trade.request_cash,
            note=f"Trade with player {trade.proposer_id} accepted",
        )
    )


def _transfer_share(tile: Tile, from_id: int, to_id: int, share: float) -> None:
    """Move ``share`` of ``tile`` from one player's holding to another's."""
    remaining = tile.shares.get(from_id, 0.0) - share
    if remaining <= _EPSILON:
        tile.shares.pop(from_id, None)
    else:
        tile.shares[from_id] = remaining
    tile.shares[to_id] = tile.shares.get(to_id, 0.0) + share
