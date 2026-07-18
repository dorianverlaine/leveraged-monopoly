"""Grid-based offline balance analysis for Leveraged Monopoly.

The CLI keeps to the public package API and stays deterministic by design: the
same seed and config always produce the same game, so sweeps are fully
reproducible.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import sys
from dataclasses import replace
from itertools import product
from pathlib import Path
from typing import Iterable, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
SRC_DIR = REPO_ROOT / "src"

for path in (REPO_ROOT, SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _load_optional_modules() -> None:
    """Import optional analysis helpers if they exist."""
    try:
        importlib.import_module("analysis.experimental_bots")
    except ModuleNotFoundError as exc:
        if exc.name != "analysis.experimental_bots":
            raise


_load_optional_modules()

from monopoly.config import build_roster, long_match, quick_match, standard_match
from monopoly.engine import GameConfig
from monopoly.simulation import play_game, run_batch


DEFAULT_POLICIES: tuple[str, ...] = (
    "degen",
    "conservative",
    "cashflow",
    "contrarian",
)

PRESET_FACTORIES = {
    "quick": quick_match,
    "standard": standard_match,
    "long": long_match,
}

CSV_FIELDS = [
    "preset",
    "max_players",
    "map_size",
    "victory_condition",
    "round_limit",
    "starting_cash",
    "inflation_rate",
    "maintenance_ratio",
    "shock_interval_rounds",
    "shock_magnitude",
    "policy",
    "seed_start",
    "seed_count",
    "games",
    "win_rate",
    "avg_rounds",
    "avg_shocks",
    "bankruptcy_rate",
    "truncated_games",
]


def _parse_values(raw: Sequence[str], cast):
    values = []
    for item in raw:
        for part in item.split(","):
            part = part.strip()
            if part:
                values.append(cast(part))
    if not values:
        raise argparse.ArgumentTypeError("at least one value is required")
    return values


def _parse_float_values(raw: Sequence[str]) -> list[float]:
    return _parse_values(raw, float)


def _parse_int_values(raw: Sequence[str]) -> list[int]:
    return _parse_values(raw, int)


def _build_base_config(preset: str, max_players: int) -> GameConfig:
    try:
        factory = PRESET_FACTORIES[preset]
    except KeyError as exc:
        raise argparse.ArgumentTypeError(
            f"Unknown preset '{preset}'. Choose from: {', '.join(PRESET_FACTORIES)}"
        ) from exc
    return factory(max_players=max_players)


def _config_grid(
    base: GameConfig,
    inflation_rates: Iterable[float],
    maintenance_ratios: Iterable[float],
    shock_intervals: Iterable[int],
    shock_magnitudes: Iterable[float],
) -> list[GameConfig]:
    configs: list[GameConfig] = []
    for inflation_rate, maintenance_ratio, shock_interval, shock_magnitude in product(
        inflation_rates,
        maintenance_ratios,
        shock_intervals,
        shock_magnitudes,
    ):
        configs.append(
            replace(
                base,
                inflation_rate=inflation_rate,
                maintenance_ratio=maintenance_ratio,
                shock_interval_rounds=shock_interval,
                shock_magnitude=shock_magnitude,
            )
        )
    return configs


def _mixed_roster_factory(config: GameConfig, policies: Sequence[str]):
    """Build a roster where every listed policy gets a seat in the same game.

    This is what makes win_rate a genuine head-to-head comparison: all policies
    compete against each other in one batch of games, rotated across seats by
    ``build_roster``, instead of each policy only ever playing copies of itself
    (which trivially "wins" 100% of its own self-play games and tells you
    nothing about how it does against the others).
    """
    return lambda: build_roster(config, fill_with_bots=True, bot_rotation=list(policies))


def _bankruptcy_rates(
    config: GameConfig, seeds: Sequence[int], policies: Sequence[str]
) -> dict[str, float]:
    """Per-policy bankruptcy rate, measured from the same mixed-policy games
    used for the win-rate batch (not from isolated self-play)."""
    roster_factory = _mixed_roster_factory(config, policies)
    seats = {policy: 0 for policy in policies}
    bankrupt = {policy: 0 for policy in policies}
    for seed in seeds:
        result = play_game(config, seed, roster_factory())
        for player in result.final_players:
            policy = player["policy"]
            if policy not in seats:
                continue
            seats[policy] += 1
            if player["status"] == "bankrupt":
                bankrupt[policy] += 1
    return {
        policy: (bankrupt[policy] / seats[policy]) if seats[policy] else 0.0
        for policy in policies
    }


def _summarize_config(config: GameConfig, seeds: Sequence[int], policies: Sequence[str]) -> list[dict]:
    """One row per policy for this config, all measured from a single batch of
    mixed-policy games: every listed policy plays in the same games, rotated
    across seats, so win_rate reflects how each policy does against the others
    rather than against copies of itself.
    """
    roster_factory = _mixed_roster_factory(config, policies)
    report = run_batch(config, list(seeds), roster_factory)
    bankruptcy_rates = _bankruptcy_rates(config, seeds, policies)
    win_rates = report.win_rate_by_policy()

    rows = []
    for policy in policies:
        rows.append(
            {
                "max_players": config.max_players,
                "map_size": config.map_size,
                "victory_condition": config.victory_condition,
                "round_limit": config.round_limit,
                "starting_cash": config.starting_cash,
                "inflation_rate": config.inflation_rate,
                "maintenance_ratio": config.maintenance_ratio,
                "shock_interval_rounds": config.shock_interval_rounds,
                "shock_magnitude": config.shock_magnitude,
                "policy": policy,
                "games": report.games,
                "win_rate": win_rates.get(policy, 0.0),
                "avg_rounds": report.avg_rounds,
                "avg_shocks": report.avg_shocks,
                "bankruptcy_rate": bankruptcy_rates.get(policy, 0.0),
                "truncated_games": report.truncated_games,
            }
        )
    return rows


def _format_percent(value: float) -> str:
    return f"{value:.1%}"


def _format_float(value: float) -> str:
    return f"{value:.3f}"


def _write_csv(rows: Sequence[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_report(
    rows: Sequence[dict],
    output_path: Path,
    preset: str,
    seed_start: int,
    seed_count: int,
    policies: Sequence[str],
    grid_size: int,
) -> None:
    lines: list[str] = []
    lines.append("# Leveraged Monopoly Balance Sweep")
    lines.append("")
    lines.append(f"Preset: `{preset}`")
    lines.append(f"Seeds: `{seed_start}` to `{seed_start + seed_count - 1}` ({seed_count} total)")
    lines.append(f"Policies: {', '.join(f'`{policy}`' for policy in policies)}")
    lines.append(f"Config combinations: `{grid_size}`")
    lines.append("")
    lines.append("## Summary")
    if rows:
        best = max(rows, key=lambda row: (row["win_rate"], -row["bankruptcy_rate"], -row["avg_rounds"]))
        lines.append(
            f"- Best win rate: `{best['policy']}` at {_format_percent(best['win_rate'])}"
        )
        lines.append(
            f"- Lowest bankruptcy rate: `{min(rows, key=lambda row: row['bankruptcy_rate'])['policy']}`"
        )
    else:
        lines.append("- No rows were produced.")
    lines.append("")

    grouped: dict[tuple, list[dict]] = {}
    for row in rows:
        key = (
            row["max_players"],
            row["map_size"],
            row["inflation_rate"],
            row["maintenance_ratio"],
            row["shock_interval_rounds"],
            row["shock_magnitude"],
        )
        grouped.setdefault(key, []).append(row)

    for key in sorted(grouped):
        max_players, map_size, inflation_rate, maintenance_ratio, shock_interval, shock_magnitude = key
        lines.append("## Configuration")
        lines.append(
            f"- max_players: `{max_players}`, map_size: `{map_size}`, inflation_rate: `{_format_float(inflation_rate)}`, maintenance_ratio: `{_format_float(maintenance_ratio)}`, shock_interval_rounds: `{shock_interval}`, shock_magnitude: `{_format_float(shock_magnitude)}`"
        )
        lines.append("")
        lines.append("| policy | win rate | avg rounds | avg shocks | bankruptcy rate | truncated games |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
        for row in sorted(grouped[key], key=lambda item: item["policy"]):
            lines.append(
                f"| `{row['policy']}` | {_format_percent(row['win_rate'])} | {_format_float(row['avg_rounds'])} | {_format_float(row['avg_shocks'])} | {_format_percent(row['bankruptcy_rate'])} | {row['truncated_games']} |"
            )
        lines.append("")

    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic balance sweeps for Leveraged Monopoly.",
    )
    parser.add_argument(
        "--preset",
        choices=sorted(PRESET_FACTORIES),
        default="quick",
        help="Base pacing preset to sweep from.",
    )
    parser.add_argument(
        "--max-players",
        type=int,
        default=4,
        help="Maximum players for the base config.",
    )
    parser.add_argument(
        "--seed-start",
        type=int,
        default=0,
        help="First seed to run.",
    )
    parser.add_argument(
        "--seed-count",
        type=int,
        default=5,
        help="How many consecutive seeds to run.",
    )
    parser.add_argument(
        "--inflation-rate",
        nargs="+",
        default=["0.02", "0.05"],
        help="Comma-separated or space-separated inflation values.",
    )
    parser.add_argument(
        "--maintenance-ratio",
        nargs="+",
        default=["1.20", "1.30"],
        help="Comma-separated or space-separated maintenance ratios.",
    )
    parser.add_argument(
        "--shock-interval-rounds",
        nargs="+",
        default=["6", "8"],
        help="Comma-separated or space-separated shock intervals.",
    )
    parser.add_argument(
        "--shock-magnitude",
        nargs="+",
        default=["0.20", "0.30"],
        help="Comma-separated or space-separated shock magnitudes.",
    )
    parser.add_argument(
        "--policies",
        nargs="+",
        default=list(DEFAULT_POLICIES),
        help="Bot policy names to compare.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=SCRIPT_DIR,
        help="Directory that receives results.csv and report.md.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.seed_count <= 0:
        parser.error("--seed-count must be greater than zero")

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    inflation_rates = _parse_float_values(args.inflation_rate)
    maintenance_ratios = _parse_float_values(args.maintenance_ratio)
    shock_intervals = _parse_int_values(args.shock_interval_rounds)
    shock_magnitudes = _parse_float_values(args.shock_magnitude)
    seeds = list(range(args.seed_start, args.seed_start + args.seed_count))

    base_config = _build_base_config(args.preset, args.max_players)
    configs = _config_grid(
        base_config,
        inflation_rates,
        maintenance_ratios,
        shock_intervals,
        shock_magnitudes,
    )

    rows: list[dict] = []
    for config in configs:
        for row in _summarize_config(config, seeds, args.policies):
            row["preset"] = args.preset
            row["seed_start"] = args.seed_start
            row["seed_count"] = args.seed_count
            rows.append(row)

    rows.sort(
        key=lambda row: (
            row["max_players"],
            row["map_size"],
            row["inflation_rate"],
            row["maintenance_ratio"],
            row["shock_interval_rounds"],
            row["shock_magnitude"],
            row["policy"],
        )
    )

    csv_rows = [
        {field: row[field] for field in CSV_FIELDS}
        for row in rows
    ]

    csv_path = output_dir / "results.csv"
    report_path = output_dir / "report.md"
    _write_csv(csv_rows, csv_path)
    _write_report(
        rows,
        report_path,
        args.preset,
        args.seed_start,
        args.seed_count,
        args.policies,
        len(configs),
    )

    print(f"Wrote {csv_path}")
    print(f"Wrote {report_path}")
    print(f"Rows: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())