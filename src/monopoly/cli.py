"""Command-line demo: play a headless game and print the drama.

Usage::

    python -m monopoly.cli --preset quick --seed 42
    monopoly-demo --preset standard --seed 7 --humans Alice Bob

This is a P0 "is the collapse satisfying?" tool -- it runs a full game driven by
bot policies and prints the key events (shocks, liquidations, bankruptcies) plus
the final standings. It exercises the whole engine end-to-end with no cloud.
"""

from __future__ import annotations

import argparse
from typing import List

from .config import build_roster, long_match, quick_match, standard_match
from .simulation import play_game

_PRESETS = {
    "quick": quick_match,
    "standard": standard_match,
    "long": long_match,
}


def _parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Play a headless Leveraged Monopoly game.")
    parser.add_argument(
        "--preset", choices=sorted(_PRESETS), default="quick", help="Game pacing preset."
    )
    parser.add_argument("--seed", type=int, default=42, help="RNG seed (game is fully determined by it).")
    parser.add_argument("--players", type=int, default=4, help="Total seats (humans + bot backfill).")
    parser.add_argument(
        "--humans", nargs="*", default=[], help="Names of human seats (driven by a default bot policy here)."
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = _parse_args(argv)
    config = _PRESETS[args.preset](max_players=args.players)
    roster = build_roster(config, human_names=args.humans)

    result = play_game(config, seed=args.seed, roster=roster)

    print(f"Leveraged Monopoly -- preset={args.preset} seed={args.seed}")
    print(f"Seats: {[p.name for p in roster]}")
    print("-" * 60)
    _print_drama(result)
    print("-" * 60)
    print(f"Rounds played : {result.rounds_played}")
    print(f"Shocks fired  : {result.shocks_fired}")
    print(f"Actions logged: {result.num_actions}")
    if result.truncated:
        print("(!) Game was truncated by a safety valve.")
    print("Final standings (by net worth):")
    for p in sorted(result.final_players, key=lambda x: x["net_worth"], reverse=True):
        marker = "  <-- WINNER" if p["id"] == result.winner_id else ""
        print(
            f"  {p['name']:<22} net_worth={p['net_worth']:>10.2f} "
            f"status={p['status']}{marker}"
        )
    return 0


def _print_drama(result) -> None:
    """Summarise the game's dramatic beats.

    The runner returns intents (the replayable action log) rather than the ledger,
    so we summarise from the aggregate counters. A richer event feed is a natural
    extension once the frontend needs per-event drama popups.
    """
    survivors = [p for p in result.final_players if p["status"] != "bankrupt"]
    casualties = len(result.final_players) - len(survivors)
    print(
        f"Systemic shocks fired: {result.shocks_fired}. "
        f"Bankruptcies: {casualties}. "
        "See final standings for who survived the margin calls."
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
