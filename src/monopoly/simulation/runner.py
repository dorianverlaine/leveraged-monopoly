"""Local authoritative game loop and replay -- the same code path, twice.

Because the engine is deterministic and seeded, four things collapse into one
loop over ``reduce``:

* the MVP "play it locally with bots" loop (architecture 12),
* the AWS Monte-Carlo backtest driver (5.2),
* replay / "watch last game" (9),
* the anti-cheat audit (11).

``play_game`` drives every seat with a :class:`~monopoly.bots.policy.Policy` and
records the ordered action log. ``replay`` re-runs a ``seed + action_log`` and
returns the final state -- proving determinism and powering audits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..bots.policy import Policy
from ..bots.registry import make_policy
from ..engine import valuation
from ..engine.actions import Action, end_turn
from ..engine.errors import RuleError
from ..engine.player import Player, PlayerStatus
from ..engine.reducer import reduce, winner
from ..engine.state import GameConfig, GameState, new_game

# Safety valves so a misbehaving policy can never hang the loop.
_MAX_TOTAL_ACTIONS = 200_000
_MAX_MANAGEMENT_STREAK = 80  # consecutive management actions in one turn


@dataclass
class GameResult:
    """The outcome of a simulated game, plus the replayable action log."""

    seed: int
    config: GameConfig
    winner_id: Optional[int]
    winner_name: Optional[str]
    rounds_played: int
    shocks_fired: int
    num_actions: int
    truncated: bool                      # True if a safety valve stopped the game
    final_players: List[dict]            # id, name, policy, status, net_worth
    action_log: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "seed": self.seed,
            "config": self.config.to_dict(),
            "winner_id": self.winner_id,
            "winner_name": self.winner_name,
            "rounds_played": self.rounds_played,
            "shocks_fired": self.shocks_fired,
            "num_actions": self.num_actions,
            "truncated": self.truncated,
            "final_players": self.final_players,
            "action_log": self.action_log,
        }


def _build_policy_map(
    roster: List[Player],
    overrides: Optional[Dict[int, Policy]],
    default_policy: str,
) -> Dict[int, Policy]:
    """Assign a policy to every seat: explicit override, bot policy, or default."""
    overrides = overrides or {}
    policies: Dict[int, Policy] = {}
    for player in roster:
        if player.id in overrides:
            policies[player.id] = overrides[player.id]
        elif player.is_bot and player.policy:
            policies[player.id] = make_policy(player.policy)
        else:
            # A human seat in a headless sim is driven by a default policy.
            policies[player.id] = make_policy(default_policy)
    return policies


def play_game(
    config: GameConfig,
    seed: int,
    roster: List[Player],
    policies: Optional[Dict[int, Policy]] = None,
    default_policy: str = "conservative",
) -> GameResult:
    """Play one full game headlessly and return its result + action log.

    Every seat is driven by a policy (explicit ``policies`` override, the seat's
    own bot policy, or ``default_policy``). The action log is exactly what you
    would persist to R2 as the replay -- ``seed + action_log`` *is* the game.
    """
    state = new_game(config, seed, roster)
    policy_map = _build_policy_map(state.players, policies, default_policy)

    action_log: List[Action] = []
    truncated = False
    management_streak = 0
    last_active = state.turn.active_player

    while not state.is_over():
        if len(action_log) >= _MAX_TOTAL_ACTIONS:
            truncated = True
            break

        # Trading is not turn-gated: let recipients answer pending offers before
        # the active player acts (mirrors how the real-time server behaves).
        state = _resolve_pending_trades(state, policy_map, action_log)

        active = state.active_player()

        # Reset the per-turn streak counter whenever the active seat changes.
        if state.turn.active_player != last_active:
            management_streak = 0
            last_active = state.turn.active_player

        # Force the turn to end if a policy churns without progressing.
        if management_streak >= _MAX_MANAGEMENT_STREAK:
            action = end_turn(active.id)
        else:
            action = policy_map[active.id].decide(state, active.id)

        outcome = reduce(state, action)

        if isinstance(outcome, RuleError):
            # A policy proposed something illegal; fall back to ending the turn.
            forced = end_turn(active.id)
            outcome = reduce(state, forced)
            if isinstance(outcome, RuleError):
                # Cannot even end the turn -> abort rather than spin forever.
                truncated = True
                break
            action = forced

        state = outcome
        action_log.append(action)
        management_streak += 1

    return summarize_game(state, seed, config, action_log, truncated)


def _resolve_pending_trades(
    state: GameState, policy_map: Dict[int, Policy], action_log: List[Action]
) -> GameState:
    """Ask each pending offer's recipient to respond, applying their decision.

    Deterministic (offers processed in list order). A recipient that leaves an
    offer pending (``None``) simply keeps it for a future step; anything that
    resolves an offer is logged so the replay stays exact. Bounded: every
    accept/reject removes one offer, and ``None`` breaks the loop.
    """
    from ..engine.actions import accept_trade, reject_trade

    progressed = True
    while progressed and state.trades:
        progressed = False
        for offer in list(state.trades):
            recipient = offer.recipient_id
            decision = policy_map[recipient].respond_to_trade(state, recipient, offer)
            if decision is None:
                continue
            action = accept_trade(recipient, offer.id) if decision else reject_trade(recipient, offer.id)
            outcome = reduce(state, action)
            if isinstance(outcome, RuleError):
                # A stale/illegal accept -> clear the offer with a reject instead.
                outcome = reduce(state, reject_trade(recipient, offer.id))
                if isinstance(outcome, RuleError):
                    state.trades.remove(offer)  # defensive: never spin on a bad offer
                    continue
                action = reject_trade(recipient, offer.id)
            state = outcome
            action_log.append(action)
            progressed = True

    return state


def summarize_game(
    state: GameState,
    seed: int,
    config: GameConfig,
    action_log: List[Action],
    truncated: bool,
) -> GameResult:
    """Package a finished (or in-progress) game into a serializable result.

    Public so callers other than ``play_game`` -- notably the live multiplayer
    room in :mod:`monopoly.realtime.room` -- can build the exact same
    ``GameResult`` shape when a real-time game ends, keeping headless
    simulation, replay, and live-game persistence on one code path.
    """
    win = winner(state)
    final_players = [
        {
            "id": p.id,
            "name": p.name,
            "is_bot": p.is_bot,
            "policy": p.policy,
            "status": p.status,
            "net_worth": round(valuation.net_worth(state, p.id), 2),
        }
        for p in state.players
    ]
    return GameResult(
        seed=seed,
        config=config,
        winner_id=win.id if win else None,
        winner_name=win.name if win else None,
        rounds_played=state.turn.round_number,
        shocks_fired=state.market.shocks_fired,
        num_actions=len(action_log),
        truncated=truncated,
        final_players=final_players,
        action_log=[a.to_dict() for a in action_log],
    )


def replay(config: GameConfig, seed: int, roster: List[Player], action_log: List[dict]) -> GameState:
    """Re-run a recorded game from ``seed + action_log`` and return the final state.

    This is the deterministic audit / "watch last game" path. Any action that the
    engine now rejects means the log is corrupt or the rules drifted -- we raise
    so that never passes silently.
    """
    state = new_game(config, seed, roster)
    for i, entry in enumerate(action_log):
        outcome = reduce(state, Action.from_dict(entry))
        if isinstance(outcome, RuleError):
            raise ValueError(
                f"Replay diverged at action {i} ({entry}): {outcome}"
            )
        state = outcome
    return state
