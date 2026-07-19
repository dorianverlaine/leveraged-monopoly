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
from typing import Optional

from ..engine import valuation
from ..engine.actions import Action, end_turn, roll_dice
from ..engine.board import Tile
from ..engine.state import GamePhase, GameState, TradeOffer


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

    def respond_to_trade(
        self, state: GameState, player_id: int, offer: TradeOffer
    ) -> Optional[bool]:
        """Decide how to answer a trade offer addressed to this player.

        ``True`` accepts, ``False`` rejects, ``None`` leaves it pending. Called
        by the simulation runner for any offer whose recipient is ``player_id``
        (trading is not turn-gated). The default is a plain fair-value check:
        accept only if the value received is at least the value given. A smart
        policy overrides this to also weigh what a tile does to a *monopoly*
        (worth overpaying to complete one, worth refusing to hand one to a
        rival).
        """
        received = trade_value(state, offer.offer_cash, offer.offer_tiles)
        given = trade_value(state, offer.request_cash, offer.request_tiles)
        return received >= given


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


def buildable_tile(state: GameState, player_id: int, cash_buffer: int = 0):
    """Return a landmark the player can develop right now, or ``None``.

    A tile qualifies when the player sole-owns the whole city (a monopoly), the
    tile is unmortgaged and not yet a skyscraper, and the player keeps at least
    ``cash_buffer`` after paying the build cost. Cheapest tile first, to spread
    development the way a sensible player would.
    """
    from ..engine.board import MAX_BUILDINGS

    player = state.player_by_id(player_id)
    candidates = []
    for tile in state.board:
        if not tile.is_property() or tile.mortgaged or tile.buildings >= MAX_BUILDINGS:
            continue
        if tile.sole_owner() != player_id:
            continue
        if not valuation.has_monopoly(state, player_id, tile.group):
            continue
        if player.cash - tile.building_cost() < cash_buffer:
            continue
        candidates.append(tile)
    if not candidates:
        return None
    return min(candidates, key=lambda t: (t.buildings, t.price))


def margin_headroom(state: GameState, player_id: int) -> float:
    """How far the player's margin ratio sits above the maintenance floor.

    Large / infinite = safe; near zero = one shock from a margin call; negative
    would already have triggered liquidation.
    """
    ratio = valuation.margin_ratio(state, player_id)
    return ratio - state.config.maintenance_ratio


def trade_value(state: GameState, cash: int, tiles: dict) -> float:
    """Plain market value of one side of a trade: cash plus tile shares at value."""
    total = float(cash or 0)
    for tile_index, share in (tiles or {}).items():
        total += share * valuation.property_value(state, tile_index)
    return total


def city_progress(state: GameState, player_id: int, group: str):
    """Return ``(owned, total)`` landmark counts for a player in one city."""
    tiles = [t for t in state.board if t.is_property() and t.group == group]
    owned = sum(1 for t in tiles if t.sole_owner() == player_id)
    return owned, len(tiles)


def shock_is_imminent(state: GameState) -> bool:
    """True if a systemic shock fires at the very next round boundary.

    The shock clock is public state, so a shrewd policy can de-risk *before* the
    crash instead of being margin-called by it -- the single sharpest edge a bot
    has over a naive one.
    """
    return state.market.shock_clock <= 1
