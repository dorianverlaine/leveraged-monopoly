"""Tests for the deterministic engine: reducer contract and core mechanics."""

from __future__ import annotations

import copy

import pytest

from monopoly.engine import actions, valuation
from monopoly.engine.player import Player, PlayerStatus
from monopoly.engine.reducer import reduce
from monopoly.engine.state import GameConfig, GamePhase, new_game
from monopoly.engine.errors import RuleError, RuleErrorCode
from monopoly.engine.mechanics import inflation, margin, securitization, shock, trading


def two_player_game(seed: int = 1, **config_overrides) -> "object":
    """A minimal 2-human game on the 24-tile ring for targeted tests."""
    config = GameConfig(max_players=2, map_size=24, **config_overrides)
    roster = [Player(id=0, name="P0", cash=0), Player(id=1, name="P1", cash=0)]
    return new_game(config, seed, roster)


# --- Factory ---------------------------------------------------------------

def test_new_game_initial_conditions():
    state = two_player_game(starting_cash=1500)
    assert len(state.board) == 24
    assert all(p.cash == 1500 for p in state.players)
    assert all(p.position == 0 for p in state.players)
    assert state.turn.phase == GamePhase.AWAIT_ROLL
    assert state.turn.round_number == 1


# --- Reducer contract ------------------------------------------------------

def test_reduce_does_not_mutate_input():
    state = two_player_game()
    before = state.to_dict()
    reduce(state, actions.roll_dice(0))
    assert state.to_dict() == before  # input untouched; result is a new object


def test_reduce_rejects_wrong_turn():
    state = two_player_game()
    result = reduce(state, actions.roll_dice(1))  # P1 acting on P0's turn
    assert isinstance(result, RuleError)
    assert result.code == RuleErrorCode.NOT_YOUR_TURN


def test_reduce_rejects_wrong_phase():
    state = two_player_game()
    # Cannot buy before rolling.
    result = reduce(state, actions.buy(0, 1))
    assert isinstance(result, RuleError)
    assert result.code == RuleErrorCode.WRONG_PHASE


def test_unknown_action_rejected():
    state = two_player_game()
    bad = actions.Action(type="teleport", player_id=0)
    result = reduce(state, bad)
    assert isinstance(result, RuleError)
    assert result.code == RuleErrorCode.UNKNOWN_ACTION


def test_roll_advances_and_opens_action_phase():
    state = two_player_game()
    result = reduce(state, actions.roll_dice(0))
    assert not isinstance(result, RuleError)
    assert result.turn.phase == GamePhase.AWAIT_ACTION
    assert result.turn.last_roll is not None
    assert result.players[0].position != 0  # moved somewhere on the ring


# --- Buying ----------------------------------------------------------------

def test_buy_property_transfers_ownership_and_cash():
    state = two_player_game(starting_cash=1500)
    state.turn.phase = GamePhase.AWAIT_ACTION
    state.players[0].position = 1  # tile 1 is a property on the 24-ring
    price = state.board[1].price

    result = reduce(state, actions.buy(0, 1))
    assert not isinstance(result, RuleError)
    assert result.board[1].owned_share(0) == pytest.approx(1.0)
    assert result.players[0].cash == 1500 - price


def test_cannot_buy_already_owned():
    state = two_player_game()
    state.turn.phase = GamePhase.AWAIT_ACTION
    state.players[0].position = 1
    state.board[1].shares = {1: 1.0}  # owned by P1
    result = reduce(state, actions.buy(0, 1))
    assert isinstance(result, RuleError)
    assert result.code == RuleErrorCode.TILE_ALREADY_OWNED


def test_cannot_buy_without_cash():
    state = two_player_game(starting_cash=10)
    state.turn.phase = GamePhase.AWAIT_ACTION
    state.players[0].position = 1
    result = reduce(state, actions.buy(0, 1))
    assert isinstance(result, RuleError)
    assert result.code == RuleErrorCode.INSUFFICIENT_CASH


# --- Rent (mechanic-level) -------------------------------------------------

def test_rent_charged_on_landing():
    state = two_player_game(starting_cash=1000, inflation_rate=0.0)
    state.board[1].shares = {1: 1.0}       # P1 owns tile 1
    state.turn.active_player = 0
    state.players[0].position = 1          # P0 has landed on it
    rent = state.board[1].base_rent

    trading.resolve_landing(state)
    assert state.players[0].cash == 1000 - rent
    assert state.players[1].cash == 1000 + rent


def test_no_rent_on_mortgaged_property():
    state = two_player_game(starting_cash=1000)
    state.board[1].shares = {1: 1.0}
    state.board[1].mortgaged = True
    state.players[0].position = 1
    state.turn.active_player = 0
    trading.resolve_landing(state)
    assert state.players[0].cash == 1000  # nothing charged


# --- Leverage & margin -----------------------------------------------------

def test_leverage_borrow_and_over_borrow_guard():
    state = two_player_game(starting_cash=1000, max_leverage_ratio=0.5)
    state.turn.phase = GamePhase.AWAIT_ACTION
    state.board[1].shares = {0: 1.0}       # P0 owns a property as collateral
    value = valuation.property_value(state, 1)
    ceiling = int(value * 0.5)

    ok = reduce(state, actions.leverage(0, ceiling))
    assert not isinstance(ok, RuleError)
    assert ok.players[0].debt == ceiling
    assert ok.players[0].cash == 1000 + ceiling

    too_much = reduce(state, actions.leverage(0, ceiling + 100))
    assert isinstance(too_much, RuleError)
    assert too_much.code == RuleErrorCode.OVER_BORROW


def test_margin_call_liquidates_on_shock():
    # P0 is heavily leveraged; a shock crushes collateral and forces liquidation.
    state = two_player_game(
        starting_cash=0,
        maintenance_ratio=1.30,
        max_leverage_ratio=0.75,
        shock_magnitude=0.50,
        inflation_rate=0.0,
        interest_rate=0.0,
    )
    state.board[1].shares = {0: 1.0}
    state.players[0].debt = int(valuation.property_value(state, 1) * 0.75)

    # Before the shock the position is within tolerance.
    assert valuation.margin_ratio(state, 0) >= state.config.maintenance_ratio

    shock._fire_shock(state)
    margin.enforce_solvency(state)

    # The collateral collapsed; the player was liquidated (lost the property)
    # and, being unable to cover, went bankrupt.
    assert state.board[1].owned_share(0) == 0.0
    assert state.players[0].status == PlayerStatus.BANKRUPT


def test_repay_debt_reduces_debt():
    # maintenance_ratio=0 disables the margin sweep so we isolate the repay logic
    # (otherwise the engine correctly clears uncollateralized debt with spare cash).
    state = two_player_game(starting_cash=500, maintenance_ratio=0.0)
    state.turn.phase = GamePhase.AWAIT_ACTION
    state.players[0].debt = 300
    result = reduce(state, actions.repay_debt(0, 200))
    assert not isinstance(result, RuleError)
    assert result.players[0].debt == 100
    assert result.players[0].cash == 300


# --- Mortgage --------------------------------------------------------------

def test_mortgage_is_net_worth_neutral_then_costs_to_redeem():
    state = two_player_game(starting_cash=1000, inflation_rate=0.0)
    state.turn.phase = GamePhase.AWAIT_ACTION
    state.board[1].shares = {0: 1.0}
    nw_before = valuation.net_worth(state, 0)

    mortgaged = reduce(state, actions.mortgage(0, 1))
    assert not isinstance(mortgaged, RuleError)
    assert mortgaged.board[1].mortgaged is True
    # Cash up, debt up by the same principal -> net worth unchanged.
    assert valuation.net_worth(mortgaged, 0) == pytest.approx(nw_before, abs=1.0)

    redeemed = reduce(mortgaged, actions.unmortgage(0, 1))
    assert not isinstance(redeemed, RuleError)
    assert redeemed.board[1].mortgaged is False
    # Redemption fee makes the round-trip slightly net-worth-negative.
    assert valuation.net_worth(redeemed, 0) < nw_before


# --- Securitization --------------------------------------------------------

def test_securitize_sells_a_slice_for_cash():
    state = two_player_game(starting_cash=0, securitization_haircut=0.10, inflation_rate=0.0)
    state.board[1].shares = {0: 1.0}
    value = valuation.property_value(state, 1)

    err = securitization.securitize(state, 0, 1, 0.4)
    assert err is None
    assert state.board[1].owned_share(0) == pytest.approx(0.6)
    assert state.players[0].cash == pytest.approx(int(0.4 * value * 0.9), abs=1)


# --- Inflation -------------------------------------------------------------

def test_inflation_grows_price_index_and_accrues_interest():
    state = two_player_game(inflation_rate=0.10, interest_rate=0.10)
    state.players[0].debt = 100
    inflation.apply_round_economics(state)
    assert state.market.price_index == pytest.approx(1.10)
    assert state.players[0].debt == 110  # 10% interest compounded on debt
