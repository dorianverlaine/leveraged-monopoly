"""Tests for the account system: progression maths, store, and progression apply."""

from __future__ import annotations

import pytest

from monopoly.accounts import progression
from monopoly.accounts.models import GameOutcome
from monopoly.accounts.service import record_finished_game
from monopoly.accounts.store import AccountStore, normalize_locale
from monopoly.config import build_roster, quick_match
from monopoly.persistence import db
from monopoly.persistence.store import GameStore
from monopoly.simulation import play_game


@pytest.fixture
def conn():
    return db.connect(":memory:")


@pytest.fixture
def accounts(conn) -> AccountStore:
    return AccountStore(conn)


# --- Pure progression maths ------------------------------------------------

def test_xp_rewards_winning_and_surviving():
    winner = progression.xp_for_game(rank=0, num_players=4, bankrupt=False)
    loser = progression.xp_for_game(rank=3, num_players=4, bankrupt=True)
    assert winner > loser
    # Every game earns something (Duolingo-style always-progress).
    assert loser >= progression.XP_FOR_PLAYING


def test_level_curve_is_monotonic_and_inverts():
    assert progression.level_for_xp(0) == 1
    prev = 0
    for level in range(1, 10):
        floor = progression.cumulative_xp_for_level(level)
        assert floor >= prev
        # A total exactly at the floor is that level; one below is the previous.
        assert progression.level_for_xp(floor) == level
        if floor > 0:
            assert progression.level_for_xp(floor - 1) == level - 1
        prev = floor


def test_level_progress_fraction_within_unit_interval():
    prog = progression.level_progress(progression.cumulative_xp_for_level(3) + 10)
    assert prog.level == 3
    assert 0.0 <= prog.fraction() < 1.0


def test_elo_winner_gains_loser_loses_zero_sum_ish():
    ratings = [1000, 1000]
    new = progression.update_ratings(ratings, ranks=[0, 1])
    assert new[0] > 1000 and new[1] < 1000
    # Two equal-rated players: symmetric swing.
    assert (new[0] - 1000) == (1000 - new[1])


def test_elo_single_player_is_noop():
    assert progression.update_ratings([1200], [0]) == [1200]


def test_ranks_from_standings_ranks_solvent_above_bankrupt():
    # (is_bankrupt, net_worth) for three players.
    standings = [(False, 100.0), (True, 0.0), (False, 300.0)]
    ranks = progression.ranks_from_standings(standings)
    # Player 2 (300, solvent) is best, then player 0 (100), then bankrupt player 1.
    assert ranks[2] == 0
    assert ranks[0] == 1
    assert ranks[1] == 2


# --- Guest identity & sessions ---------------------------------------------

def test_create_guest_returns_account_device_key_and_session(accounts: AccountStore):
    account, device_key, token = accounts.create_guest(display_name="Alice", locale="fr")
    assert account.display_name == "Alice"
    assert account.locale == "fr"
    assert account.level == 1 and account.rating == progression.DEFAULT_RATING
    assert device_key and token

    # The session token resolves back to the same account.
    resolved = accounts.account_for_session(token)
    assert resolved is not None and resolved.id == account.id


def test_login_guest_reclaims_same_account(accounts: AccountStore):
    account, device_key, _ = accounts.create_guest(display_name="Bob")
    again = accounts.login_guest(device_key)
    assert again is not None
    reclaimed, new_token = again
    assert reclaimed.id == account.id
    assert accounts.account_for_session(new_token).id == account.id


def test_bad_session_and_device_key_return_none(accounts: AccountStore):
    assert accounts.account_for_session("nope") is None
    assert accounts.login_guest("nope") is None


def test_update_profile_and_locale(accounts: AccountStore):
    account, _, _ = accounts.create_guest()
    updated = accounts.update_profile(account.id, display_name="Renamed", avatar="🦊")
    assert updated.display_name == "Renamed" and updated.avatar == "🦊"
    localed = accounts.set_locale(account.id, "zh-Hant")
    assert localed.locale == "zh-Hant"


def test_normalize_locale_falls_back_to_default():
    assert normalize_locale("fr") == "fr"
    assert normalize_locale("zh-Hant") == "zh-Hant"
    assert normalize_locale("klingon") == "en"
    assert normalize_locale(None) == "en"


# --- Progression application -----------------------------------------------

def test_record_game_results_updates_xp_rating_and_streak(accounts: AccountStore):
    a, _, _ = accounts.create_guest(display_name="A")
    b, _, _ = accounts.create_guest(display_name="B")

    accounts.record_game_results([
        GameOutcome(account_id=a.id, rank=0, num_players=2, bankrupt=False),
        GameOutcome(account_id=b.id, rank=1, num_players=2, bankrupt=True),
    ])

    a2 = accounts.get_account(a.id)
    b2 = accounts.get_account(b.id)
    assert a2.games_played == 1 and a2.games_won == 1
    assert a2.current_win_streak == 1 and a2.best_win_streak == 1
    assert a2.xp > 0 and a2.rating > progression.DEFAULT_RATING
    assert b2.games_won == 0 and b2.current_win_streak == 0
    assert b2.rating < progression.DEFAULT_RATING


def test_solo_human_gains_xp_but_no_rating_change(accounts: AccountStore):
    a, _, _ = accounts.create_guest()
    accounts.record_game_results([
        GameOutcome(account_id=a.id, rank=0, num_players=4, bankrupt=False),
    ])
    a2 = accounts.get_account(a.id)
    assert a2.xp > 0
    assert a2.rating == progression.DEFAULT_RATING  # no ladder movement vs bots


def test_leaderboard_orders_by_requested_metric(accounts: AccountStore):
    a, _, _ = accounts.create_guest(display_name="A")
    b, _, _ = accounts.create_guest(display_name="B")
    # A wins twice, B loses twice -> A should top a rating/wins leaderboard.
    for _ in range(2):
        accounts.record_game_results([
            GameOutcome(a.id, rank=0, num_players=2, bankrupt=False),
            GameOutcome(b.id, rank=1, num_players=2, bankrupt=True),
        ])
    board = accounts.leaderboard(by="rating")
    assert board[0]["display_name"] == "A"
    assert board[0]["games_won"] == 2


# --- Service coordinator (game record + progression together) ---------------

def test_record_finished_game_persists_and_updates_accounts(conn):
    game_store = GameStore(conn)
    account_store = AccountStore(conn)
    alice, _, _ = account_store.create_guest(display_name="Alice")

    config = quick_match(max_players=3)
    result = play_game(config, seed=1, roster=build_roster(config))

    game_id = record_finished_game(
        game_store,
        account_store,
        result,
        account_ids_by_seat={0: alice.id},  # seat 0 is Alice; the rest are bots
        room_code="LIVE",
    )

    # Game recorded with the account linked...
    record = game_store.get_game(game_id)
    assert record["participants"][0]["account_id"] == alice.id
    # ...and Alice's stats advanced.
    alice2 = account_store.get_account(alice.id)
    assert alice2.games_played == 1
    assert alice2.xp > 0
    # Her match history is queryable.
    assert len(game_store.games_for_account(alice.id)) == 1
