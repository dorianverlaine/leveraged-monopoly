"""The reducer -- the one pure function every action flows through.

Contract (architecture 3.1):

    reduce(state, action) -> GameState | RuleError

* **No side effects.** No network, clock, or ambient RNG; all randomness comes
  from ``state.rng``.
* **Total & validated.** An illegal action returns a typed ``RuleError`` and the
  input state is never mutated. The reducer deep-copies the state up front and
  only ever returns that copy on success, so a rejected action leaves the caller's
  state untouched.
* **Serializable in, serializable out.** The result round-trips to JSON/msgpack.

Everything downstream (reconnect = resync, replay = re-run, anti-cheat audit,
backtest) is just this function called in a loop.
"""

from __future__ import annotations

import copy
from typing import Union

from .actions import Action, ActionType
from .errors import RuleError, RuleErrorCode
from .player import PlayerStatus
from .state import GameState, GamePhase, VictoryCondition
from . import valuation
from .mechanics import (
    building,
    inflation,
    leverage,
    margin,
    movement,
    securitization,
    shock,
    trading,
)

# Result type of the public reducer.
ReduceResult = Union[GameState, RuleError]


def reduce(state: GameState, action: Action) -> ReduceResult:
    """Validate and apply ``action`` to ``state``, returning a new state or error.

    The input ``state`` is treated as immutable: we clone it, mutate the clone,
    and return either the clone (success) or a ``RuleError`` (the clone is
    discarded, so no partial mutation escapes).
    """
    if state.turn.phase == GamePhase.GAME_OVER:
        return RuleError(RuleErrorCode.GAME_OVER, "The game is already over")

    working = copy.deepcopy(state)
    outcome = _dispatch(working, action)
    if isinstance(outcome, RuleError):
        return outcome
    return working


# --- Dispatch --------------------------------------------------------------

def _dispatch(state: GameState, action: Action) -> Union[None, RuleError]:
    """Route an action to its handler after common validation."""
    handlers = {
        ActionType.ROLL_DICE: _handle_roll,
        ActionType.BUY: _handle_buy,
        ActionType.MORTGAGE: _handle_mortgage,
        ActionType.UNMORTGAGE: _handle_unmortgage,
        ActionType.LEVERAGE: _handle_leverage,
        ActionType.REPAY_DEBT: _handle_repay,
        ActionType.SECURITIZE: _handle_securitize,
        ActionType.BUILD: _handle_build,
        ActionType.SELL_BUILDING: _handle_sell_building,
        ActionType.END_TURN: _handle_end_turn,
        ActionType.CONCEDE: _handle_concede,
    }
    handler = handlers.get(action.type)
    if handler is None:
        return RuleError(RuleErrorCode.UNKNOWN_ACTION, f"Unknown action '{action.type}'")
    return handler(state, action)


# --- Turn-ownership guards -------------------------------------------------

def _require_turn(state: GameState, action: Action) -> Union[None, RuleError]:
    """Ensure the sender is the active player and still in the game."""
    active = state.active_player()
    if active.id != action.player_id:
        return RuleError(RuleErrorCode.NOT_YOUR_TURN, "It is not your turn")
    if active.status == PlayerStatus.BANKRUPT:
        return RuleError(RuleErrorCode.PLAYER_BANKRUPT, "You are bankrupt")
    return None


def _require_phase(state: GameState, phase: str) -> Union[None, RuleError]:
    """Ensure the game is in the expected phase for this action."""
    if state.turn.phase != phase:
        return RuleError(
            RuleErrorCode.WRONG_PHASE,
            f"Action requires phase '{phase}', currently '{state.turn.phase}'",
        )
    return None


def _guard_management(state: GameState, action: Action) -> Union[None, RuleError]:
    """Common guard for financial-management actions (your turn, action phase)."""
    err = _require_turn(state, action) or _require_phase(state, GamePhase.AWAIT_ACTION)
    return err


# --- Action handlers -------------------------------------------------------

def _handle_roll(state: GameState, action: Action) -> Union[None, RuleError]:
    """Roll, move, resolve the landing, then open the management phase."""
    err = _require_turn(state, action) or _require_phase(state, GamePhase.AWAIT_ROLL)
    if err is not None:
        return err

    movement.roll_and_move(state)
    trading.resolve_landing(state)
    margin.enforce_solvency(state)

    # Landing (rent/tax) can bankrupt the active player; if so, their turn ends.
    if state.active_player().status == PlayerStatus.BANKRUPT:
        _advance_turn(state)
    else:
        state.turn.phase = GamePhase.AWAIT_ACTION
        _check_victory(state)
    return None


def _handle_buy(state: GameState, action: Action) -> Union[None, RuleError]:
    err = _guard_management(state, action)
    if err is not None:
        return err
    result = trading.buy_tile(state, action.player_id, action.tile_index)
    if result is not None:
        return result
    margin.enforce_solvency(state)
    return None


def _handle_mortgage(state: GameState, action: Action) -> Union[None, RuleError]:
    err = _guard_management(state, action)
    if err is not None:
        return err
    result = leverage.mortgage(state, action.player_id, action.tile_index)
    if result is not None:
        return result
    margin.enforce_solvency(state)
    return None


def _handle_unmortgage(state: GameState, action: Action) -> Union[None, RuleError]:
    err = _guard_management(state, action)
    if err is not None:
        return err
    result = leverage.unmortgage(state, action.player_id, action.tile_index)
    if result is not None:
        return result
    margin.enforce_solvency(state)
    return None


def _handle_leverage(state: GameState, action: Action) -> Union[None, RuleError]:
    err = _guard_management(state, action)
    if err is not None:
        return err
    result = leverage.borrow(state, action.player_id, action.amount)
    if result is not None:
        return result
    margin.enforce_solvency(state)
    return None


def _handle_repay(state: GameState, action: Action) -> Union[None, RuleError]:
    err = _guard_management(state, action)
    if err is not None:
        return err
    result = leverage.repay(state, action.player_id, action.amount)
    if result is not None:
        return result
    margin.enforce_solvency(state)
    return None


def _handle_securitize(state: GameState, action: Action) -> Union[None, RuleError]:
    err = _guard_management(state, action)
    if err is not None:
        return err
    result = securitization.securitize(
        state, action.player_id, action.tile_index, action.percent
    )
    if result is not None:
        return result
    margin.enforce_solvency(state)
    return None


def _handle_build(state: GameState, action: Action) -> Union[None, RuleError]:
    err = _guard_management(state, action)
    if err is not None:
        return err
    result = building.build(state, action.player_id, action.tile_index)
    if result is not None:
        return result
    margin.enforce_solvency(state)
    return None


def _handle_sell_building(state: GameState, action: Action) -> Union[None, RuleError]:
    err = _guard_management(state, action)
    if err is not None:
        return err
    result = building.sell_building(state, action.player_id, action.tile_index)
    if result is not None:
        return result
    margin.enforce_solvency(state)
    return None


def _handle_end_turn(state: GameState, action: Action) -> Union[None, RuleError]:
    err = _require_turn(state, action) or _require_phase(state, GamePhase.AWAIT_ACTION)
    if err is not None:
        return err
    _advance_turn(state)
    return None


def _handle_concede(state: GameState, action: Action) -> Union[None, RuleError]:
    player = state.player_by_id(action.player_id)
    if player is None:
        return RuleError(RuleErrorCode.INVALID_TARGET, "Unknown player")
    if player.status == PlayerStatus.BANKRUPT:
        return RuleError(RuleErrorCode.PLAYER_BANKRUPT, "You are already out")

    was_active = state.active_player().id == action.player_id
    margin.bankrupt_player(state, player)
    _check_victory(state)
    if not state.is_over() and was_active:
        _advance_turn(state)
    return None


# --- Turn cycle ------------------------------------------------------------

def _advance_turn(state: GameState) -> None:
    """Hand play to the next solvent player, applying round economics on wrap.

    Ordering matters: a round-boundary shock can bankrupt players, *including the
    seat we would otherwise hand the turn to*. So we detect the wrap, run the
    round boundary first, and only then pick the next active seat from whoever is
    still solvent -- never leaving a bankrupt player holding the turn.
    """
    start = state.turn.active_player

    # First pass (pre-boundary): find the next solvent seat only to detect whether
    # play wraps past the last seat, which is what marks a completed round.
    first_next, steps = _next_solvent_seat(state, start)
    if first_next is None:
        _check_victory(state)
        return

    if (start + steps) >= len(state.players):
        state.turn.round_number += 1
        _apply_round_boundary(state)  # inflation, interest, shock -> may bankrupt
        _check_victory(state)
        if state.is_over():
            return

    # Re-select the active seat *after* the boundary, since solvency may have
    # changed. If nobody solvent remains, the victory check above/below ends it.
    next_idx, _ = _next_solvent_seat(state, start)
    if next_idx is None:
        _check_victory(state)
        return

    state.turn.active_player = next_idx
    state.turn.last_roll = None
    state.turn.phase = GamePhase.AWAIT_ROLL


def _next_solvent_seat(state: GameState, start: int):
    """Return ``(index, steps)`` of the first non-bankrupt seat after ``start``.

    Scans cyclically; ``steps`` is how many seats forward it is (used to detect a
    round wrap). Returns ``(None, 0)`` if no other solvent seat exists.
    """
    n = len(state.players)
    for step in range(1, n + 1):
        cand = (start + step) % n
        if state.players[cand].status != PlayerStatus.BANKRUPT:
            return cand, step
    return None, 0


def _apply_round_boundary(state: GameState) -> None:
    """Run the per-round macro pass: inflation, interest, shock, then solvency."""
    inflation.apply_round_economics(state)
    shock.tick_and_maybe_fire(state)
    # Inflation, interest, and any shock can all break margins simultaneously.
    margin.enforce_solvency(state)


# --- Victory ---------------------------------------------------------------

def _check_victory(state: GameState) -> None:
    """Set ``GAME_OVER`` if a victory condition is met."""
    if state.is_over():
        return

    solvent = state.solvent_players()
    cfg = state.config

    over = False
    if len(solvent) <= 1:
        # Universal terminal condition: a game cannot continue with <=1 player.
        over = True
    elif state.turn.round_number > cfg.round_limit:
        # Universal hard cap: every game must terminate. Even a LAST_SOLVENT game
        # in which nobody ever goes bankrupt ends here (winner = highest net
        # worth). Without this an online room could run forever.
        over = True
    elif cfg.victory_condition == VictoryCondition.NET_WORTH_TARGET:
        over = any(valuation.net_worth(state, p.id) >= cfg.net_worth_target for p in solvent)

    if over:
        state.turn.phase = GamePhase.GAME_OVER


def winner(state: GameState):
    """Return the winning player (highest net worth among the solvent), or None.

    Only meaningful once the game is over. Ties break toward the lowest seat id
    for determinism.
    """
    solvent = state.solvent_players()
    if not solvent:
        return None
    return max(solvent, key=lambda p: (valuation.net_worth(state, p.id), -p.id))
