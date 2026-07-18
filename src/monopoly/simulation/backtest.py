"""Monte-Carlo backtest driver -- empirical balance tuning.

Because the engine is deterministic and seeded, balance is measured, not guessed
(architecture 5.2): fan out many ``(config, seed)`` games and read win-rate
distributions per policy. This is the embarrassingly-parallel workload that the
AWS Batch/Fargate plane will one day run at scale; here it runs in-process so the
same questions can be answered on a laptop during prototyping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List

from ..engine.player import Player
from ..engine.state import GameConfig
from .runner import GameResult, play_game

# A factory takes nothing and returns a fresh roster (new Player objects each
# call, since new_game mutates them).
RosterFactory = Callable[[], List[Player]]


@dataclass
class BacktestReport:
    """Aggregate statistics over a batch of simulated games."""

    games: int
    wins_by_policy: Dict[str, int] = field(default_factory=dict)
    avg_rounds: float = 0.0
    avg_shocks: float = 0.0
    truncated_games: int = 0

    def win_rate_by_policy(self) -> Dict[str, float]:
        """Fraction of games won, keyed by policy name."""
        if self.games == 0:
            return {}
        return {name: wins / self.games for name, wins in self.wins_by_policy.items()}

    def to_dict(self) -> dict:
        return {
            "games": self.games,
            "wins_by_policy": self.wins_by_policy,
            "win_rate_by_policy": self.win_rate_by_policy(),
            "avg_rounds": self.avg_rounds,
            "avg_shocks": self.avg_shocks,
            "truncated_games": self.truncated_games,
        }


def run_batch(
    config: GameConfig,
    seeds: List[int],
    roster_factory: RosterFactory,
    default_policy: str = "conservative",
) -> BacktestReport:
    """Run one game per seed and aggregate the outcomes.

    ``roster_factory`` must return a *fresh* roster each call, because
    ``new_game`` assigns starting cash and positions onto the Player objects.
    """
    results: List[GameResult] = []
    for seed in seeds:
        roster = roster_factory()
        results.append(play_game(config, seed, roster, default_policy=default_policy))

    return _aggregate(results)


def _aggregate(results: List[GameResult]) -> BacktestReport:
    """Fold a list of game results into a report."""
    report = BacktestReport(games=len(results))
    if not results:
        return report

    total_rounds = 0
    total_shocks = 0
    for res in results:
        total_rounds += res.rounds_played
        total_shocks += res.shocks_fired
        if res.truncated:
            report.truncated_games += 1
        # Attribute the win to the winning seat's policy (or "human" if unnamed).
        winner_policy = _winner_policy(res)
        if winner_policy is not None:
            report.wins_by_policy[winner_policy] = (
                report.wins_by_policy.get(winner_policy, 0) + 1
            )

    report.avg_rounds = total_rounds / len(results)
    report.avg_shocks = total_shocks / len(results)
    return report


def _winner_policy(result: GameResult) -> str:
    """Return the policy label of the winning seat (or 'human' / 'none')."""
    if result.winner_id is None:
        return "none"
    for player in result.final_players:
        if player["id"] == result.winner_id:
            return player["policy"] or "human"
    return "none"
