"""Command-line inspector for persisted accounts and game history.

Usage::

    monopoly-history recent [--limit N] [--db PATH]
    monopoly-history leaderboard [--by rating|xp|wins] [--limit N] [--db PATH]
    monopoly-history replay GAME_ID [--db PATH]

``replay`` re-runs a stored ``seed + action_log`` through the engine and prints
the recomputed winner -- a lightweight audit that the stored record matches what
the engine actually produces (architecture 9, 11).
"""

from __future__ import annotations

import argparse
from typing import List, Optional

from .accounts.store import AccountStore
from .engine import valuation
from .persistence import db as persistence_db
from .persistence.store import GameStore


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect Leveraged Monopoly accounts and history.")
    parser.add_argument(
        "--db", default=None, help=f"SQLite path (default: {persistence_db.DEFAULT_DB_PATH})"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    recent = sub.add_parser("recent", help="List the most recently finished games.")
    recent.add_argument("--limit", type=int, default=20)

    board = sub.add_parser("leaderboard", help="Rank accounts by rating, xp, or wins.")
    board.add_argument("--limit", type=int, default=20)
    board.add_argument("--by", choices=["rating", "xp", "wins"], default="rating")

    replay_cmd = sub.add_parser("replay", help="Re-run a stored game and print its winner.")
    replay_cmd.add_argument("game_id")

    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    conn = persistence_db.connect(args.db or persistence_db.DEFAULT_DB_PATH)
    game_store = GameStore(conn)
    account_store = AccountStore(conn)

    if args.command == "recent":
        _print_recent(game_store, args.limit)
    elif args.command == "leaderboard":
        _print_leaderboard(account_store, args.limit, args.by)
    elif args.command == "replay":
        _print_replay(game_store, args.game_id)
    return 0


def _print_recent(store: GameStore, limit: int) -> None:
    games = store.list_recent_games(limit)
    if not games:
        print("No games recorded yet.")
        return
    for g in games:
        print(
            f"{g['id']}  room={g['room_code']}  ended={g['ended_at']}  "
            f"winner={g['winner_name'] or '(none)'}  rounds={g['rounds_played']}  "
            f"shocks={g['shocks_fired']}"
        )


def _print_leaderboard(store: AccountStore, limit: int, by: str) -> None:
    rows = store.leaderboard(limit, by=by)
    if not rows:
        print("No accounts have played yet.")
        return
    print(f"{'name':<20}{'level':>6}{'rating':>8}{'played':>8}{'won':>6}{'streak':>8}")
    for r in rows:
        print(
            f"{r['display_name']:<20}{r['level']:>6}{r['rating']:>8}"
            f"{r['games_played']:>8}{r['games_won']:>6}{r['best_win_streak']:>8}"
        )


def _print_replay(store: GameStore, game_id: str) -> None:
    record = store.get_game(game_id)
    if record is None:
        print(f"No such game: {game_id}")
        return
    state = store.replay_game(game_id)
    print(f"Replayed game {game_id} ({len(record['action_log'])} actions)")
    print("Recomputed final standings:")
    for p in state.players:
        print(f"  seat {p.id:<3} {p.name:<20} net_worth={valuation.net_worth(state, p.id):>10.2f} status={p.status}")
    print(f"Stored winner: {record['winner_name']!r} (seat {record['winner_id']})")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
