"""Tests for player-to-player trading: propose, accept, reject, cancel.

Covers the parts of trading that are architecturally unusual for this engine:
it is not turn-gated, offers are re-validated (not just re-executed) at accept
time, and -- critically -- trade ids must be deterministic so replay works.
"""

from __future__ import annotations

import pytest

from monopoly.engine import actions, valuation
from monopoly.engine.board import city_tiles
from monopoly.engine.errors import RuleError, RuleErrorCode
from monopoly.engine.player import Player, PlayerStatus
from monopoly.engine.reducer import reduce
from monopoly.engine.state import GameConfig, GamePhase, new_game
from monopoly.engine.mechanics import margin, trade


def _game(seed: int = 1, players: int = 3, **cfg):
    cfg.setdefault("starting_cash", 0)
    config = GameConfig(max_players=players, map_size=24, inflation_rate=0.0, **cfg)
    roster = [Player(id=i, name=f"P{i}", cash=0) for i in range(players)]
    return new_game(config, seed, roster)


# --- Propose -----------------------------------------------------------

def test_propose_creates_a_pending_offer_with_deterministic_id():
    state = _game()
    state.players[0].cash = 500
    tile = city_tiles(state.board, "hong_kong")[0]
    tile.shares = {0: 1.0}

    result = reduce(
        state,
        actions.propose_trade(0, 1, offer_cash=100, request_tiles=None),
    )
    assert not isinstance(result, RuleError)
    assert len(result.trades) == 1
    assert result.trades[0].id == 0  # deterministic counter, not a UUID
    assert result.next_trade_id == 1


def test_propose_not_turn_gated():
    # Player 1 is NOT the active player (active_player defaults to seat 0), but
    # trading must still work -- this is the whole point of the feature.
    state = _game()
    state.players[1].cash = 200
    assert state.turn.active_player == 0
    result = reduce(state, actions.propose_trade(1, 0, offer_cash=50))
    assert not isinstance(result, RuleError)


def test_cannot_propose_to_self():
    state = _game()
    result = reduce(state, actions.propose_trade(0, 0, offer_cash=10))
    assert isinstance(result, RuleError)
    assert result.code == RuleErrorCode.INVALID_TARGET


def test_cannot_propose_empty_trade():
    state = _game()
    result = reduce(state, actions.propose_trade(0, 1))
    assert isinstance(result, RuleError)
    assert result.code == RuleErrorCode.EMPTY_TRADE


def test_cannot_offer_cash_you_dont_have():
    state = _game()
    state.players[0].cash = 10
    result = reduce(state, actions.propose_trade(0, 1, offer_cash=1000))
    assert isinstance(result, RuleError)
    assert result.code == RuleErrorCode.INSUFFICIENT_CASH


def test_cannot_offer_a_tile_you_dont_own():
    state = _game()
    tile = city_tiles(state.board, "paris")[0]
    result = reduce(state, actions.propose_trade(0, 1, offer_tiles={tile.index: 1.0}))
    assert isinstance(result, RuleError)
    assert result.code == RuleErrorCode.INSUFFICIENT_COLLATERAL


def test_cannot_trade_a_mortgaged_or_developed_tile():
    state = _game()
    tile = city_tiles(state.board, "new_york")[0]
    tile.shares = {0: 1.0}
    tile.mortgaged = True
    result = reduce(state, actions.propose_trade(0, 1, offer_tiles={tile.index: 1.0}))
    assert isinstance(result, RuleError)
    assert result.code == RuleErrorCode.TILE_ALREADY_MORTGAGED

    tile.mortgaged = False
    tile.buildings = 1
    state2 = _game()
    state2.board[tile.index].shares = {0: 1.0}
    state2.board[tile.index].buildings = 1
    result2 = reduce(state2, actions.propose_trade(0, 1, offer_tiles={tile.index: 1.0}))
    assert isinstance(result2, RuleError)
    assert result2.code == RuleErrorCode.INVALID_TARGET


def test_cannot_trade_same_tile_both_sides():
    state = _game()
    tile = city_tiles(state.board, "hong_kong")[0]
    tile.shares = {0: 0.5, 1: 0.5}
    result = reduce(
        state,
        actions.propose_trade(0, 1, offer_tiles={tile.index: 0.5}, request_tiles={tile.index: 0.5}),
    )
    assert isinstance(result, RuleError)
    assert result.code == RuleErrorCode.INVALID_TARGET


def test_cannot_propose_to_bankrupt_player():
    state = _game()
    state.players[1].status = PlayerStatus.BANKRUPT
    result = reduce(state, actions.propose_trade(0, 1, offer_cash=10))
    assert isinstance(result, RuleError)
    assert result.code == RuleErrorCode.INVALID_TARGET


# --- Accept --------------------------------------------------------------

def test_accept_swaps_cash_and_tiles():
    state = _game()
    state.players[0].cash = 500
    state.players[1].cash = 300
    tile = city_tiles(state.board, "hong_kong")[0]
    tile.shares = {1: 1.0}

    proposed = reduce(
        state,
        actions.propose_trade(0, 1, offer_cash=200, request_tiles={tile.index: 1.0}),
    )
    assert not isinstance(proposed, RuleError)
    trade_id = proposed.trades[0].id

    result = reduce(proposed, actions.accept_trade(1, trade_id))
    assert not isinstance(result, RuleError)
    assert result.players[0].cash == 300   # 500 - 200
    assert result.players[1].cash == 500   # 300 + 200
    assert result.board[tile.index].owned_share(0) == pytest.approx(1.0)
    assert result.board[tile.index].owned_share(1) == 0.0
    assert result.trades == []  # resolved offers don't linger


def test_only_recipient_can_accept():
    state = _game(players=3)
    state.players[0].cash = 100
    proposed = reduce(state, actions.propose_trade(0, 1, offer_cash=50))
    trade_id = proposed.trades[0].id

    # Player 2 is a bystander, not the recipient (player 1).
    result = reduce(proposed, actions.accept_trade(2, trade_id))
    assert isinstance(result, RuleError)
    assert result.code == RuleErrorCode.NOT_TRADE_PARTICIPANT


def test_accept_unknown_trade_id_rejected():
    state = _game()
    result = reduce(state, actions.accept_trade(1, 999))
    assert isinstance(result, RuleError)
    assert result.code == RuleErrorCode.TRADE_NOT_FOUND


def test_accept_revalidates_and_rejects_stale_offer():
    # Proposer offers cash they no longer have by the time of acceptance.
    state = _game()
    state.players[0].cash = 100
    proposed = reduce(state, actions.propose_trade(0, 1, offer_cash=100))
    trade_id = proposed.trades[0].id

    # Proposer's cash changes between propose and accept (e.g. spent it).
    proposed.players[0].cash = 0

    result = reduce(proposed, actions.accept_trade(1, trade_id))
    assert isinstance(result, RuleError)
    assert result.code == RuleErrorCode.TRADE_NO_LONGER_VALID


def test_accept_can_trigger_a_margin_call():
    # Give player 0 a monopoly, borrow heavily against it, then trade the
    # collateral away -- the recipient's accept should immediately trip the
    # proposer's margin ratio and liquidate/bankrupt them.
    state = _game(maintenance_ratio=1.30, max_leverage_ratio=0.75)
    hk = city_tiles(state.board, "hong_kong")
    for t in hk:
        t.shares = {0: 1.0}
    collateral = sum(valuation.property_value(state, t.index) for t in hk)
    state.players[0].debt = int(collateral * 0.75)  # right at the leverage ceiling
    state.players[0].cash = 0
    state.players[1].cash = 0

    # Trade away one landmark for nothing -- shrinks collateral, not debt.
    give_away = hk[-1]
    proposed = reduce(state, actions.propose_trade(0, 1, offer_tiles={give_away.index: 1.0}))
    trade_id = proposed.trades[0].id

    result = reduce(proposed, actions.accept_trade(1, trade_id))
    assert not isinstance(result, RuleError)
    # Either liquidated further or bankrupted -- either way, no longer holding
    # 0.75x collateral in cash-free safety; assert the margin engine actually ran.
    assert result.players[0].debt < proposed.players[0].debt or \
        result.players[0].status == PlayerStatus.BANKRUPT


# --- Reject / cancel -------------------------------------------------------

def test_reject_removes_offer_without_moving_anything():
    state = _game()
    state.players[0].cash = 100
    proposed = reduce(state, actions.propose_trade(0, 1, offer_cash=100))
    trade_id = proposed.trades[0].id

    result = reduce(proposed, actions.reject_trade(1, trade_id))
    assert not isinstance(result, RuleError)
    assert result.trades == []
    assert result.players[0].cash == 100  # untouched


def test_only_recipient_can_reject():
    state = _game()
    state.players[0].cash = 100
    proposed = reduce(state, actions.propose_trade(0, 1, offer_cash=50))
    trade_id = proposed.trades[0].id
    result = reduce(proposed, actions.reject_trade(0, trade_id))  # proposer, not recipient
    assert isinstance(result, RuleError)
    assert result.code == RuleErrorCode.NOT_TRADE_PARTICIPANT


def test_only_proposer_can_cancel():
    state = _game()
    state.players[0].cash = 100
    proposed = reduce(state, actions.propose_trade(0, 1, offer_cash=50))
    trade_id = proposed.trades[0].id
    result = reduce(proposed, actions.cancel_trade(1, trade_id))  # recipient, not proposer
    assert isinstance(result, RuleError)
    assert result.code == RuleErrorCode.NOT_TRADE_PARTICIPANT


def test_cancel_removes_offer():
    state = _game()
    state.players[0].cash = 100
    proposed = reduce(state, actions.propose_trade(0, 1, offer_cash=50))
    trade_id = proposed.trades[0].id
    result = reduce(proposed, actions.cancel_trade(0, trade_id))
    assert not isinstance(result, RuleError)
    assert result.trades == []


# --- Bankruptcy interaction -------------------------------------------------

def test_bankruptcy_voids_pending_trades_involving_that_player():
    state = _game(players=3)
    state.players[0].cash = 100
    proposed = reduce(state, actions.propose_trade(0, 1, offer_cash=50))
    assert len(proposed.trades) == 1

    margin.bankrupt_player(proposed, proposed.players[0])
    assert proposed.trades == []


# --- Replay determinism (the reason trade ids must not be random) ----------

def test_trade_ids_replay_deterministically():
    """Two independent propose+accept sequences from the same seed must assign
    the exact same trade id, or a replayed accept_trade would fail to find its
    trade. This is the property that rules out random UUIDs for TradeOffer.id.
    """
    def run():
        state = _game(seed=42, players=3)
        state.players[0].cash = 500
        state = reduce(state, actions.propose_trade(0, 1, offer_cash=100))
        tid = state.trades[0].id
        state = reduce(state, actions.accept_trade(1, tid))
        return state, tid

    state_a, tid_a = run()
    state_b, tid_b = run()
    assert tid_a == tid_b == 0
    assert state_a.players[0].cash == state_b.players[0].cash
    assert state_a.trades == state_b.trades == []
