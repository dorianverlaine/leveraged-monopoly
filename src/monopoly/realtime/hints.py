"""Best-effort "which buttons can I press right now" hints for the client.

This is a convenience for the control-panel UI (architecture 6.2), *not* an
authority: the reducer still validates every action. Being wrong here can only
grey out a button that would have worked, or offer one the server then rejects --
never a correctness issue. Kept out of the engine so the kernel stays minimal.
"""

from __future__ import annotations

from typing import List

from ..engine import valuation
from ..engine.actions import ActionType
from ..engine.state import GamePhase, GameState


def available_action_types(state: GameState, seat: int) -> List[str]:
    """Return the action types that look legal for ``seat`` right now."""
    if state.is_over():
        return []

    player = state.player_by_id(seat)
    if player is None or player.status == "bankrupt":
        return []

    # Conceding is allowed at any time while you are still in the game.
    options: List[str] = [ActionType.CONCEDE]

    # Everything else requires it to be your turn.
    if state.active_player().id != seat:
        return options

    if state.turn.phase == GamePhase.AWAIT_ROLL:
        options.insert(0, ActionType.ROLL_DICE)
        return options

    if state.turn.phase != GamePhase.AWAIT_ACTION:
        return options

    # --- Management phase: enumerate the currently-plausible tools ---------
    options.insert(0, ActionType.END_TURN)

    tile = state.board[player.position]
    if tile.is_property() and tile.is_unowned() and player.cash >= tile.price:
        options.append(ActionType.BUY)

    if valuation.max_borrowable(state, seat) > 0:
        options.append(ActionType.LEVERAGE)

    if player.debt > 0 and player.cash > 0:
        options.append(ActionType.REPAY_DEBT)

    # Property-specific tools: scan holdings once.
    owns_soleable = False
    owns_mortgaged = False
    owns_securitizable = False
    for t in state.board:
        if not t.is_property():
            continue
        share = t.owned_share(seat)
        if share <= 0.0:
            continue
        if t.mortgaged:
            owns_mortgaged = True
        else:
            owns_securitizable = True
            if t.sole_owner() == seat:
                owns_soleable = True

    if owns_soleable:
        options.append(ActionType.MORTGAGE)
    if owns_mortgaged:
        options.append(ActionType.UNMORTGAGE)
    if owns_securitizable:
        options.append(ActionType.SECURITIZE)

    return options
