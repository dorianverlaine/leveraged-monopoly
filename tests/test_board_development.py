"""Tests for the themed 3-city board, monopoly bonus, and development."""

from __future__ import annotations

import pytest

from monopoly.engine import actions, valuation
from monopoly.engine.board import (
    CITY_ORDER,
    MAX_BUILDINGS,
    RENT_MULTIPLIERS,
    build_board,
    city_group_size,
    city_tiles,
)
from monopoly.engine.player import Player
from monopoly.engine.reducer import reduce
from monopoly.engine.state import GameConfig, GamePhase, new_game
from monopoly.engine.errors import RuleError, RuleErrorCode
from monopoly.engine.mechanics import trading


def _game(seed: int = 1, map_size: int = 24, **cfg):
    # starting_cash=0 so tests set exact balances (new_game overwrites Player.cash).
    cfg.setdefault("starting_cash", 0)
    config = GameConfig(max_players=2, map_size=map_size, inflation_rate=0.0, **cfg)
    roster = [Player(id=0, name="P0", cash=0), Player(id=1, name="P1", cash=0)]
    return new_game(config, seed, roster)


def _grant_city(state, player_id: int, group: str):
    """Give a player sole ownership of every landmark in a city."""
    for tile in city_tiles(state.board, group):
        tile.shares = {player_id: 1.0}


# --- Board layout ----------------------------------------------------------

def test_board_has_three_cities_with_equal_groups():
    board = build_board(24)
    assert set(CITY_ORDER) == {"hong_kong", "paris", "new_york"}
    for city in CITY_ORDER:
        tiles = city_tiles(board, city)
        assert len(tiles) == city_group_size(24) == 6
        # Every landmark carries a stable i18n key namespaced by its city.
        assert all(t.key.startswith(f"{city}:") for t in tiles)


def test_cities_are_price_symmetric():
    board = build_board(24)
    prices = {c: sorted(t.price for t in city_tiles(board, c)) for c in CITY_ORDER}
    # All three cities span the identical price tiers (balanced by theme only).
    assert prices["hong_kong"] == prices["paris"] == prices["new_york"]


@pytest.mark.parametrize("size", [24, 36, 44])
def test_board_sizes_are_exact(size):
    assert len(build_board(size)) == size


# --- Monopoly rent bonus ---------------------------------------------------

def test_monopoly_doubles_rent():
    state = _game()
    hk = city_tiles(state.board, "hong_kong")
    landmark = hk[0]

    # Baseline: P1 owns only this one landmark (no monopoly) -> plain rent.
    landmark.shares = {1: 1.0}
    state.players[0].cash = 1000
    state.players[1].cash = 0
    state.turn.active_player = 0
    state.players[0].position = landmark.index
    trading.resolve_landing(state)
    assert state.players[1].cash == landmark.base_rent  # x1

    # Now give P1 the whole city -> rent doubles (RENT_MULTIPLIERS[0] == 2).
    state2 = _game()
    _grant_city(state2, 1, "hong_kong")
    state2.players[0].cash = 1000
    state2.turn.active_player = 0
    state2.players[0].position = landmark.index
    trading.resolve_landing(state2)
    assert state2.players[1].cash == landmark.base_rent * RENT_MULTIPLIERS[0]


def test_buildings_escalate_rent():
    state = _game()
    _grant_city(state, 1, "paris")
    paris = city_tiles(state.board, "paris")
    target = paris[0]
    target.buildings = 3
    state.players[0].cash = 100000
    state.turn.active_player = 0
    state.players[0].position = target.index
    trading.resolve_landing(state)
    assert state.players[1].cash == target.base_rent * RENT_MULTIPLIERS[3]


# --- Development action -----------------------------------------------------

def test_build_requires_monopoly():
    state = _game()
    state.turn.phase = GamePhase.AWAIT_ACTION
    hk = city_tiles(state.board, "hong_kong")
    # Own only one landmark of the city -> no monopoly.
    hk[0].shares = {0: 1.0}
    state.players[0].cash = 100000
    result = reduce(state, actions.build(0, hk[0].index))
    assert isinstance(result, RuleError)
    assert result.code == RuleErrorCode.INSUFFICIENT_COLLATERAL


def test_build_succeeds_on_monopoly_and_costs_cash():
    state = _game()
    state.turn.phase = GamePhase.AWAIT_ACTION
    _grant_city(state, 0, "new_york")
    ny = city_tiles(state.board, "new_york")
    target = ny[0]
    state.players[0].cash = 100000
    cost = target.building_cost()

    result = reduce(state, actions.build(0, target.index))
    assert not isinstance(result, RuleError)
    built = result.board[target.index]
    assert built.buildings == 1
    assert result.players[0].cash == 100000 - cost


def test_cannot_build_past_max():
    state = _game()
    state.turn.phase = GamePhase.AWAIT_ACTION
    _grant_city(state, 0, "hong_kong")
    tile = city_tiles(state.board, "hong_kong")[0]
    tile.buildings = MAX_BUILDINGS
    state.players[0].cash = 100000
    result = reduce(state, actions.build(0, tile.index))
    assert isinstance(result, RuleError)


def test_sell_building_refunds_and_decrements():
    state = _game()
    state.turn.phase = GamePhase.AWAIT_ACTION
    _grant_city(state, 0, "paris")
    tile = city_tiles(state.board, "paris")[0]
    tile.buildings = 2
    state.players[0].cash = 0
    result = reduce(state, actions.sell_building(0, tile.index))
    assert not isinstance(result, RuleError)
    assert result.board[tile.index].buildings == 1
    assert result.players[0].cash > 0  # got a refund


# --- Interaction guards -----------------------------------------------------

def test_cannot_mortgage_or_securitize_developed_property():
    state = _game()
    state.turn.phase = GamePhase.AWAIT_ACTION
    _grant_city(state, 0, "hong_kong")
    tile = city_tiles(state.board, "hong_kong")[0]
    tile.buildings = 1
    state.players[0].cash = 100000

    m = reduce(state, actions.mortgage(0, tile.index))
    assert isinstance(m, RuleError) and m.code == RuleErrorCode.INVALID_TARGET
    s = reduce(state, actions.securitize(0, tile.index, 0.5))
    assert isinstance(s, RuleError) and s.code == RuleErrorCode.INVALID_TARGET


def test_cashflow_bot_develops_a_monopoly():
    # Verifies the bot wiring deterministically (emergent monopolies are rare
    # without trading, so we hand it one and check it chooses to build).
    from monopoly.bots.cashflow import CashflowPolicy

    state = _game()
    state.turn.phase = GamePhase.AWAIT_ACTION
    state.turn.active_player = 0
    _grant_city(state, 0, "hong_kong")
    state.players[0].cash = 100000
    state.players[0].position = 0  # on GO, so the "buy" path is skipped

    action = CashflowPolicy().manage(state, 0)
    assert action.type == actions.ActionType.BUILD


def test_developed_property_value_includes_buildings():
    state = _game()
    _grant_city(state, 0, "new_york")
    tile = city_tiles(state.board, "new_york")[0]
    value_before = valuation.property_value(state, tile.index)
    tile.buildings = 2
    value_after = valuation.property_value(state, tile.index)
    assert value_after > value_before
