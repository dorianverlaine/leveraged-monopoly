"""Coordinator: persist a finished game *and* update player progression.

Sits above the two repositories so neither has to know about the other:
:class:`~monopoly.persistence.store.GameStore` records the game, and
:class:`~monopoly.accounts.store.AccountStore` applies XP/level/rating/streak
changes to the human accounts that played. The real-time server calls this once
per finished game.
"""

from __future__ import annotations

from typing import Dict, Optional

from ..persistence.store import GameStore
from ..simulation.runner import GameResult
from .models import GameOutcome
from .progression import ranks_from_standings
from .store import AccountStore


def record_finished_game(
    game_store: GameStore,
    account_store: AccountStore,
    result: GameResult,
    account_ids_by_seat: Dict[int, Optional[str]],
    room_code: str,
    started_at: Optional[str] = None,
    ended_at: Optional[str] = None,
) -> str:
    """Persist ``result`` and update every account that held a seat.

    ``account_ids_by_seat`` maps seat index -> account id (or ``None`` for bots
    and anonymous guests). Returns the stored game id.
    """
    game_id = game_store.save_completed_game(
        result,
        room_code=room_code,
        account_ids_by_seat=account_ids_by_seat,
        started_at=started_at,
        ended_at=ended_at,
    )

    outcomes = _outcomes_for_accounts(result, account_ids_by_seat)
    if outcomes:
        account_store.record_game_results(outcomes)
    return game_id


def _outcomes_for_accounts(
    result: GameResult, account_ids_by_seat: Dict[int, Optional[str]]
) -> list[GameOutcome]:
    """Build per-account progression outcomes from a finished game's standings."""
    # Order players by seat so ranks line up with seat indices.
    players = sorted(result.final_players, key=lambda p: p["id"])
    standings = [(p["status"] == "bankrupt", float(p["net_worth"])) for p in players]
    ranks = ranks_from_standings(standings)
    num_players = len(players)

    outcomes: list[GameOutcome] = []
    for player in players:
        seat = player["id"]
        account_id = account_ids_by_seat.get(seat)
        if not account_id:
            continue  # bot or anonymous guest -> no progression
        outcomes.append(
            GameOutcome(
                account_id=account_id,
                rank=ranks[seat],
                num_players=num_players,
                bankrupt=player["status"] == "bankrupt",
            )
        )
    return outcomes
