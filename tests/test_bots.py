"""Tests for bot policies -- focused on the smart 'shark' and trade response."""

from __future__ import annotations

from monopoly.bots import SharkPolicy, make_policy
from monopoly.bots.registry import available_policies
from monopoly.config import build_roster, long_match
from monopoly.engine.actions import ActionType
from monopoly.engine.board import city_tiles
from monopoly.engine.player import Player
from monopoly.engine.state import GameConfig, GamePhase, TradeOffer, new_game
from monopoly.simulation import play_game


def _game(seed=1, players=3, **cfg):
    cfg.setdefault("starting_cash", 0)
    config = GameConfig(max_players=players, map_size=24, inflation_rate=0.0, **cfg)
    roster = [Player(id=i, name=f"P{i}", cash=0) for i in range(players)]
    state = new_game(config, seed, roster)
    state.turn.phase = GamePhase.AWAIT_ACTION
    state.turn.active_player = 0
    return state


def _give_city(state, player_id, group):
    for t in city_tiles(state.board, group):
        t.shares = {player_id: 1.0}


# --- Registration -----------------------------------------------------------

def test_shark_is_registered():
    assert "shark" in available_policies()
    assert make_policy("shark").name == "shark"


# --- Shock timing (the shark's core edge) -----------------------------------

def test_shark_derisks_when_shock_imminent():
    state = _game()
    # Give the shark collateral + debt, and put a shock one round away.
    _give_city(state, 0, "hong_kong")
    state.players[0].debt = 100
    state.players[0].cash = 300
    state.market.shock_clock = 1

    action = SharkPolicy().manage(state, 0)
    assert action.type == ActionType.REPAY_DEBT  # dump leverage before the crash


def test_shark_grows_in_calm_water():
    state = _game()
    state.market.shock_clock = 8  # no shock near
    # Stand the shark on an unowned, affordable landmark.
    tile = city_tiles(state.board, "hong_kong")[0]
    state.players[0].position = tile.index
    state.players[0].cash = tile.price + 50

    action = SharkPolicy().manage(state, 0)
    assert action.type == ActionType.BUY


def test_shark_does_not_buy_into_a_shock():
    state = _game()
    state.market.shock_clock = 1  # shock imminent
    tile = city_tiles(state.board, "hong_kong")[0]
    state.players[0].position = tile.index
    state.players[0].cash = tile.price + 50  # could afford it, but shouldn't buy now
    state.players[0].debt = 0

    action = SharkPolicy().manage(state, 0)
    assert action.type == ActionType.END_TURN


# --- Trade evaluation -------------------------------------------------------

def test_shark_accepts_a_monopoly_completing_offer():
    state = _game()
    hk = city_tiles(state.board, "hong_kong")
    # Shark owns all but the last landmark; the offer hands it over for a pittance.
    for t in hk[:-1]:
        t.shares = {0: 1.0}
    last = hk[-1]
    last.shares = {1: 1.0}
    offer = TradeOffer(
        id=0, proposer_id=1, recipient_id=0,
        offer_cash=0, offer_tiles={last.index: 1.0},
        request_cash=1, request_tiles={}, created_round=1,
    )
    assert SharkPolicy().respond_to_trade(state, 0, offer) is True


def test_shark_refuses_to_break_its_own_set():
    state = _game()
    hk = city_tiles(state.board, "hong_kong")
    for t in hk[:3]:  # shark holds several HK landmarks -> a set in progress
        t.shares = {0: 1.0}
    # A generous cash offer for one of them -- but it would break the set.
    offer = TradeOffer(
        id=0, proposer_id=1, recipient_id=0,
        offer_cash=100000, offer_tiles={},
        request_cash=0, request_tiles={hk[0].index: 1.0}, created_round=1,
    )
    assert SharkPolicy().respond_to_trade(state, 0, offer) is False


def test_default_policy_accepts_fair_trade_rejects_bad():
    from monopoly.bots import ConservativePolicy

    state = _game()
    tile = city_tiles(state.board, "paris")[0]
    tile.shares = {1: 1.0}
    value = tile.price  # index 1.0
    fair = TradeOffer(0, 0, 1, offer_cash=value + 10, offer_tiles={},
                      request_cash=0, request_tiles={tile.index: 1.0}, created_round=1)
    bad = TradeOffer(1, 0, 1, offer_cash=1, offer_tiles={},
                     request_cash=0, request_tiles={tile.index: 1.0}, created_round=1)
    pol = ConservativePolicy()
    assert pol.respond_to_trade(state, 1, fair) is True    # received cash >= tile value
    assert pol.respond_to_trade(state, 1, bad) is False


# --- Runner resolves trades -------------------------------------------------

def test_runner_resolves_a_pending_trade():
    from monopoly.simulation.runner import _resolve_pending_trades
    from monopoly.bots import make_policy

    state = _game(players=2)
    state.players[0].cash = 500
    tile = city_tiles(state.board, "hong_kong")[0]
    tile.shares = {1: 1.0}
    # Player 0 offers generous cash for player 1's landmark.
    state.trades.append(TradeOffer(
        id=0, proposer_id=0, recipient_id=1,
        offer_cash=tile.price + 50, offer_tiles={},
        request_cash=0, request_tiles={tile.index: 1.0}, created_round=1,
    ))
    state.next_trade_id = 1
    policies = {0: make_policy("conservative"), 1: make_policy("conservative")}

    log = []
    state = _resolve_pending_trades(state, policies, log)
    # Fair trade -> the default policy accepts; the offer is gone and the tile moved.
    assert state.trades == []
    assert state.board[tile.index].owned_share(0) > 0.99
    assert any(a.type == ActionType.ACCEPT_TRADE for a in log)


# --- The shark is actually strong ------------------------------------------

def test_shark_outperforms_degen_over_a_batch():
    # Over a batch, the disciplined shark should beat the reckless degen (which
    # stays levered into shocks). Long games make the difference clearest.
    config = long_match(max_players=5)
    roster = [
        Player(id=0, name="shark", cash=0, is_bot=True, policy="shark"),
        Player(id=1, name="degen", cash=0, is_bot=True, policy="degen"),
        Player(id=2, name="conservative", cash=0, is_bot=True, policy="conservative"),
        Player(id=3, name="cashflow", cash=0, is_bot=True, policy="cashflow"),
        Player(id=4, name="contrarian", cash=0, is_bot=True, policy="contrarian"),
    ]
    shark_wins = degen_wins = 0
    for seed in range(12):
        fresh = [Player(id=p.id, name=p.name, cash=0, is_bot=True, policy=p.policy) for p in roster]
        result = play_game(config, seed, fresh)
        winner_policy = next(
            (p["policy"] for p in result.final_players if p["id"] == result.winner_id), None
        )
        if winner_policy == "shark":
            shark_wins += 1
        elif winner_policy == "degen":
            degen_wins += 1
    assert shark_wins > degen_wins
