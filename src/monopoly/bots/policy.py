"""The bot policy interface.

A ``Policy`` maps the current game state to a single legal action for a given
player: ``decide(state, player_id) -> Action`` (architecture 5.1). The same
interface serves three roles: matchmaking backfill for empty seats, the backtest
driver, and (in v2) a slot for trained RL agents -- they are all drop-in
replacements.

Policies must return an action that is *legal right now*, and every management
turn must eventually return ``END_TURN`` so play progresses. The base class
handles the mechanical parts (rolling when required, ending the turn) so concrete
policies only implement :meth:`manage`, their financial decision for the action
phase.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..engine import valuation
from ..engine.actions import Action, end_turn, roll_dice
from ..engine.board import Tile
from ..engine.state import GamePhase, GameState


class Policy(ABC):
    """Base class for all bot strategies."""

    #: Human-readable policy name; recorded on the player for analytics.
    name: str = "policy"

    def decide(self, state: GameState, player_id: int) -> Action:
        """Return the next action for ``player_id`` given the current phase.

        Rolling and turn-ending are universal; the strategy-specific choices live
        in :meth:`manage`.
        """
        if state.turn.phase == GamePhase.AWAIT_ROLL:
            return roll_dice(player_id)
        if state.turn.phase == GamePhase.AWAIT_ACTION:
            return self.manage(state, player_id)
        # Nothing sensible to do in a terminal phase; end the turn defensively.
        return end_turn(player_id)

    @abstractmethod
    def manage(self, state: GameState, player_id: int) -> Action:
        """Return one financial-management action, or ``end_turn`` to pass."""
        raise NotImplementedError


# --- Shared decision helpers ----------------------------------------------
# Small, side-effect-free readers policies use to inspect the world. They never
# mutate state -- only the reducer does that.

def current_tile(state: GameState, player_id: int) -> Tile:
    """Return the tile the player is standing on."""
    player = state.player_by_id(player_id)
    return state.board[player.position]


def can_buy_here(state: GameState, player_id: int) -> bool:
    """True if the player is on an unowned property (purchase is legal)."""
    tile = current_tile(state, player_id)
    return tile.is_property() and tile.is_unowned() and player_at(state, player_id).position == tile.index


def buy_cost_here(state: GameState, player_id: int) -> int:
    """Sticker cost to buy the property the player is standing on."""
    return current_tile(state, player_id).price


def player_at(state: GameState, player_id: int):
    """Return the player object (convenience for readability in policies)."""
    return state.player_by_id(player_id)


def margin_headroom(state: GameState, player_id: int) -> float:
    """How far the player's margin ratio sits above the maintenance floor.

    Large / infinite = safe; near zero = one shock from a margin call; negative
    would already have triggered liquidation.
    """
    ratio = valuation.margin_ratio(state, player_id)
    return ratio - state.config.maintenance_ratio
