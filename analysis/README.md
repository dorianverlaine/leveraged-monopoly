# Offline Balance Analysis

This directory contains the offline sweep tool for the deterministic Leveraged
Monopoly engine.

The tool stays on the public package API only:

- `monopoly.config`: `quick_match`, `standard_match`, `long_match`, `build_roster`
- `monopoly.simulation`: `play_game`, `replay`, `run_batch`
- `monopoly.engine`: `GameConfig`, `valuation`
- `monopoly.bots`: `register_policy`, `Policy`

It does not import `monopoly.realtime.*` and does not modify any package code.

## Files

- `analysis/sweep.py` - CLI for deterministic parameter sweeps.
- `analysis/tests/` - pytest coverage for the CLI and generated outputs.

## How to run

From the repository root:

```bash
python analysis/sweep.py --help
python analysis/sweep.py \
  --preset quick \
  --seed-count 5 \
  --inflation-rate 0.02 0.05 \
  --maintenance-ratio 1.20 1.30 \
  --shock-interval-rounds 6 8 \
  --shock-magnitude 0.20 0.30
```

By default the script writes `results.csv` and `report.md` into `analysis/`.
Use `--output-dir` to place the files somewhere else.

## Parameters

- `--preset`: base pacing bundle. `quick` is the default for short runs.
- `--max-players`: player cap for the base config before sweeping.
- `--seed-start` / `--seed-count`: deterministic seed range.
- `--inflation-rate`, `--maintenance-ratio`, `--shock-interval-rounds`, `--shock-magnitude`: grid values.
- `--policies`: bot policy names to compare. The default set compares the built-in strategies.

Each configuration is evaluated with **one batch of mixed-policy games**: every
listed `--policies` value gets a seat in the *same* games (rotated across seats
by `build_roster`), so win-rate is a genuine head-to-head comparison rather than
a policy playing only against copies of itself. `run_batch(...)` supplies
win-rate, average rounds, average shocks, and truncated-game count from that
batch; bankruptcy rate is measured from the same seeds/roster via
`play_game(...).final_players`, using the final `status` field per seat.

Because every game in a config's batch has at most one winner, the win rates
reported for the policies sharing that config always sum to at most `1.0` (a
useful sanity check when reading `results.csv`).

## Outputs

### `results.csv`

One row per configuration-policy pair. Columns:

- `preset`
- `max_players`
- `map_size`
- `victory_condition`
- `round_limit`
- `starting_cash`
- `inflation_rate`
- `maintenance_ratio`
- `shock_interval_rounds`
- `shock_magnitude`
- `policy`
- `seed_start`
- `seed_count`
- `games`
- `win_rate`
- `avg_rounds`
- `avg_shocks`
- `bankruptcy_rate`
- `truncated_games`

### `report.md`

A Markdown summary with one table per swept configuration, plus a short
headline summary.

## Optional experimental policies

If you later add `analysis/experimental_bots.py`, the sweep script will try to
import it on startup. That module can call `monopoly.bots.register_policy(...)`
to add extra policies without touching the package source tree.
