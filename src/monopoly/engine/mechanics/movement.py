"""Movement around the ring: rolling dice, advancing, and the GO salary.

This is an internal step driven by the reducer's ``ROLL_DICE`` handler, not a
directly callable action beyond the roll itself. Passing GO injects money into
the economy -- the source of the inflation the whole game is built around.
"""

from __future__ import annotations

from ..player import Player
from ..state import GameState, Transaction


def roll_and_move(state: GameState) -> None:
    """Roll two dice for the active player, move them, and pay GO if passed.

    Randomness is drawn from ``state.rng`` so the move is fully determined by the
    seed and the action history. The two dice are stored on ``turn.last_roll`` so
    the client can animate them.
    """
    player = state.active_player()

    d1 = state.rng.roll_die(6)
    d2 = state.rng.roll_die(6)
    state.turn.last_roll = [d1, d2]
    steps = d1 + d2

    board_len = len(state.board)
    new_position = player.position + steps

    # If the move wraps past the end of the ring, the player passed GO.
    passed_go = new_position >= board_len
    player.position = new_position % board_len

    if passed_go:
        _pay_go_salary(state, player)


def _pay_go_salary(state: GameState, player: Player) -> None:
    """Pay the inflation-indexed salary for passing GO and expand money supply.

    The salary scales with the market price index: as the bank prints, nominal
    income rises, but so do asset prices -- cash still bleeds in real terms.
    """
    salary = int(round(state.config.go_salary * state.market.price_index))
    player.cash += salary
    state.market.money_supply += salary
    state.record(
        Transaction(
            round_number=state.turn.round_number,
            player_id=player.id,
            kind="salary",
            amount=salary,
            note="Passed GO",
        )
    )
