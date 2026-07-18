from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "analysis" / "sweep.py"


def _run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd or ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_help_runs() -> None:
    result = _run([sys.executable, str(SCRIPT), "--help"])
    assert "Run deterministic balance sweeps" in result.stdout
    assert "--output-dir" in result.stdout


def test_small_sweep_writes_csv_and_report(tmp_path: Path) -> None:
    output_dir = tmp_path / "analysis-output"
    result = _run(
        [
            sys.executable,
            str(SCRIPT),
            "--preset",
            "quick",
            "--max-players",
            "2",
            "--seed-start",
            "3",
            "--seed-count",
            "2",
            "--inflation-rate",
            "0.02",
            "--maintenance-ratio",
            "1.30",
            "--shock-interval-rounds",
            "6",
            "--shock-magnitude",
            "0.20",
            "--policies",
            "conservative",
            "degen",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert "Rows: 2" in result.stdout

    csv_path = output_dir / "results.csv"
    report_path = output_dir / "report.md"
    assert csv_path.exists()
    assert report_path.exists()

    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 2
    assert {row["policy"] for row in rows} == {"conservative", "degen"}
    assert all(row["games"] == "2" for row in rows)
    assert all(float(row["avg_rounds"]) > 0 for row in rows)
    assert all(0.0 <= float(row["bankruptcy_rate"]) <= 1.0 for row in rows)

    report_text = report_path.read_text(encoding="utf-8")
    assert "Leveraged Monopoly Balance Sweep" in report_text
    assert "| `conservative` |" in report_text
    assert "| `degen` |" in report_text


def test_win_rates_come_from_head_to_head_games_not_self_play(tmp_path: Path) -> None:
    """Regression test: policies must compete against each other in the same
    games. The original implementation gave every policy its own roster of
    identical bots (self-play), so whichever bot happened to win a game was
    trivially "the" policy present -- every row reported win_rate == 1.0
    regardless of policy or config. With head-to-head games, at most one
    policy can win a given game, so the win rates across all policies sharing
    a config can never all be 1.0 and must sum to at most 1.0.
    """
    output_dir = tmp_path / "analysis-output"
    policies = ["conservative", "degen", "cashflow", "contrarian"]
    _run(
        [
            sys.executable,
            str(SCRIPT),
            "--preset",
            "quick",
            "--max-players",
            "4",
            "--seed-start",
            "0",
            "--seed-count",
            "20",
            "--inflation-rate",
            "0.05",
            "--maintenance-ratio",
            "1.20",
            "--shock-interval-rounds",
            "6",
            "--shock-magnitude",
            "0.25",
            "--policies",
            *policies,
            "--output-dir",
            str(output_dir),
        ]
    )

    with (output_dir / "results.csv").open(newline="", encoding="utf-8") as handle:
        rows = {row["policy"]: row for row in csv.DictReader(handle)}

    win_rates = {policy: float(rows[policy]["win_rate"]) for policy in policies}
    assert not all(rate == 1.0 for rate in win_rates.values())
    assert sum(win_rates.values()) <= 1.0 + 1e-9
