"""The aggregate game state and its factory.

``GameState`` is the single source of truth. It is fully serializable and, being
the sole input/output of ``reduce``, defines the entire observable game. All the
pacing knobs (player count, map size, inflation rate, maintenance ratio, shock
cadence, victory condition) live in :class:`GameConfig` as *data*, so a "quick
match: 4 players, 24 tiles" is just a different config -- never a code change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .board import Tile, build_board
from .market import Market
from .player import Player, PlayerStatus
from .rng import SeededRng


class GamePhase:
    """Where we are within a turn."""

    AWAIT_ROLL = "await_roll"      # active player must roll the dice
    AWAIT_ACTION = "await_action"  # active player may manage finances, then end turn
    GAME_OVER = "game_over"        # a victory condition has been met


class VictoryCondition:
    """How a game ends."""

    LAST_SOLVENT = "last_solvent"        # everyone else bankrupt
    NET_WORTH_TARGET = "net_worth_target"  # first to reach a net-worth goal
    ROUND_LIMIT = "round_limit"          # highest net worth when round cap hits


@dataclass
class GameConfig:
    """All tunable knobs. Backtests sweep these; they never live in code."""

    max_players: int = 6
    map_size: int = 24
    victory_condition: str = VictoryCondition.LAST_SOLVENT
    net_worth_target: int = 5000          # used by NET_WORTH_TARGET
    # Universal hard cap: every game ends once this round is exceeded, regardless
    # of victory_condition (guarantees termination). It is also the win trigger
    # for the ROUND_LIMIT condition (highest net worth wins at the cap).
    round_limit: int = 40

    starting_cash: int = 1500

    # --- Capital-market knobs (the reason this isn't just Monopoly) ------
    # Inflation: fraction the price index grows each full round.
    inflation_rate: float = 0.02
    # GO salary at reference index; scaled by the price index when paid.
    go_salary: int = 200
    # Leverage: how much you may borrow per unit of collateral value.
    max_leverage_ratio: float = 0.75      # borrow up to 75% of collateral value
    # Margin: forced liquidation when collateral/debt drops below this.
    maintenance_ratio: float = 1.30
    # Interest accrued on outstanding debt each full round.
    interest_rate: float = 0.05
    # Systemic shock: rounds between shocks, and the price-index drop it inflicts.
    shock_interval_rounds: int = 8
    shock_magnitude: float = 0.30         # property values fall 30% on a shock
    # Securitization: haircut the market takes when it buys your IPO'd shares.
    securitization_haircut: float = 0.10

    def to_dict(self) -> dict:
        """Serialize for the wire / persistence."""
        return {
            "max_players": self.max_players,
            "map_size": self.map_size,
            "victory_condition": self.victory_condition,
            "net_worth_target": self.net_worth_target,
            "round_limit": self.round_limit,
            "starting_cash": self.starting_cash,
            "inflation_rate": self.inflation_rate,
            "go_salary": self.go_salary,
            "max_leverage_ratio": self.max_leverage_ratio,
            "maintenance_ratio": self.maintenance_ratio,
            "interest_rate": self.interest_rate,
            "shock_interval_rounds": self.shock_interval_rounds,
            "shock_magnitude": self.shock_magnitude,
            "securitization_haircut": self.securitization_haircut,
        }


@dataclass
class TurnState:
    """Whose turn it is and where we are in it."""

    active_player: int = 0        # index into ``GameState.players``
    phase: str = GamePhase.AWAIT_ROLL
    round_number: int = 1         # increments when the turn wraps back to seat 0
    last_roll: Optional[List[int]] = None  # the two dice of the most recent roll

    def to_dict(self) -> dict:
        return {
            "active_player": self.active_player,
            "phase": self.phase,
            "round_number": self.round_number,
            "last_roll": list(self.last_roll) if self.last_roll else None,
        }


@dataclass
class Transaction:
    """One append-only ledger entry.

    The ledger drives the live UI history *and* the post-game audit. It is
    append-only: mechanics record money movements here, never rewrite them.
    """

    round_number: int
    player_id: int
    kind: str            # e.g. "buy", "rent", "salary", "interest", "liquidation"
    amount: int          # signed: positive = player gained cash, negative = paid
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "round_number": self.round_number,
            "player_id": self.player_id,
            "kind": self.kind,
            "amount": self.amount,
            "note": self.note,
        }


@dataclass
class GameState:
    """The complete, serializable game world.

    This is the *only* argument to and result of ``reduce``. Everything a client
    could need is reachable from here; nothing the engine needs lives outside it
    (no clock, no globals, no I/O).
    """

    config: GameConfig
    rng: SeededRng
    turn: TurnState
    board: List[Tile]
    players: List[Player]
    market: Market
    ledger: List[Transaction] = field(default_factory=list)

    # --- Convenience accessors ------------------------------------------
    def active_player(self) -> Player:
        """Return the player whose turn it currently is."""
        return self.players[self.turn.active_player]

    def player_by_id(self, player_id: int) -> Optional[Player]:
        """Return the player with ``player_id``, or ``None`` if not found."""
        for p in self.players:
            if p.id == player_id:
                return p
        return None

    def solvent_players(self) -> List[Player]:
        """Players who are not bankrupt (still in the game)."""
        return [p for p in self.players if p.status != PlayerStatus.BANKRUPT]

    def is_over(self) -> bool:
        return self.turn.phase == GamePhase.GAME_OVER

    def record(self, txn: Transaction) -> None:
        """Append a transaction to the ledger (the append-only audit trail)."""
        self.ledger.append(txn)

    def to_dict(self) -> dict:
        """Serialize the full state for wire / persistence.

        Derived per-player metrics (net worth, collateral, margin ratio) are
        computed here so clients never have to. Kept import-local to avoid a
        circular import with the valuation module.
        """
        from . import valuation

        players_out = []
        for p in self.players:
            entry = p.to_dict()
            entry["net_worth"] = valuation.net_worth(self, p.id)
            entry["collateral_value"] = valuation.collateral_value(self, p.id)
            entry["margin_ratio"] = valuation.margin_ratio(self, p.id)
            players_out.append(entry)

        return {
            "config": self.config.to_dict(),
            "rng": {"state": self.rng.state},
            "turn": self.turn.to_dict(),
            "board": [t.to_dict() for t in self.board],
            "players": players_out,
            "market": self.market.to_dict(),
            "ledger": [t.to_dict() for t in self.ledger],
        }

    def to_public_dict(self) -> dict:
        """Serialize for sending to clients -- the same as :meth:`to_dict` but
        with the RNG internal state removed.

        The seeded PRNG state fully determines every future dice roll and shock.
        Broadcasting it would let a client predict the future and cheat, so it is
        stripped from anything that crosses to the client. Persistence and replay
        use :meth:`to_dict` (which keeps the RNG) instead.
        """
        data = self.to_dict()
        data.pop("rng", None)
        return data


# --- Factory ---------------------------------------------------------------

def new_game(
    config: GameConfig,
    seed: int,
    players: List[Player],
) -> GameState:
    """Create a fresh game from a config, a seed, and a roster of players.

    The seed fully determines the RNG stream, so ``new_game`` + the same action
    log reproduces the game exactly (this is what makes replays and backtests a
    single code path).
    """
    if not players:
        raise ValueError("new_game requires at least one player")
    if len(players) > config.max_players:
        raise ValueError(
            f"{len(players)} players exceeds max_players={config.max_players}"
        )

    # Give everyone the starting cash and place them on GO.
    for p in players:
        p.cash = config.starting_cash
        p.position = 0
        p.debt = 0
        p.status = PlayerStatus.ACTIVE

    market = Market(
        price_index=1.0,
        money_supply=0,
        shock_clock=config.shock_interval_rounds,
    )

    return GameState(
        config=config,
        rng=SeededRng.from_seed(seed),
        turn=TurnState(active_player=0, phase=GamePhase.AWAIT_ROLL, round_number=1),
        board=build_board(config.map_size),
        players=list(players),
        market=market,
        ledger=[],
    )
