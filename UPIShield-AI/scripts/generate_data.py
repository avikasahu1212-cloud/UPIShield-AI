#!/usr/bin/env python
"""Data generator for UPIShield.

Generates synthetic telemetry.csv, incidents.csv, and optionally plots.

Usage:
    python scripts/generate_data.py --seed 42 --out data --start 2026-11-02 --days 7 --plots
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.config import (
    BASELINES,
    LATENCY_BLIP_MULTIPLIER,
    LATENCY_BLIP_PROB,
    LATENCY_LOGSIGMA,
    NODE_IDS,
    TRAFFIC_SHAPE,
    VOLUME_RATIOS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Incident scenario definitions
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, dict[str, Any]] = {
    "bank_slowdown": {
        "roots": ["bank_a", "bank_b", "bank_c"],
        "start_offset_min": None,  # set by schedule
        "ramp_min": 2,
        "hold_min": 20,
        "recovery_min": 7,
        "severity": 0.9,
        "effects": {
            "latency_mult": 3.6,
            "timeout_target": 0.05,
            "success_target": 0.62,
            "retry_mult": 3.0,
            "pending_mult": 4.0,
        },
    },
    "retry_storm": {
        "roots": ["status_check_api"],
        "start_offset_min": None,
        "ramp_min": 3,
        "hold_min": 15,
        "recovery_min": 5,
        "severity": 0.95,
        "effects": {
            "requests_mult": 3.0,
            "latency_mult": 4.0,
            "timeout_target": 0.08,
            "success_target_initial": 0.5,
            "success_target_recovery": 0.8,
            "retry_mult": 4.0,
        },
    },
    "shared_upstream": {
        "roots": ["cloud_region_1"],
        "start_offset_min": None,
        "ramp_min": 2,
        "hold_min": 20,
        "recovery_min": 7,
        "severity": 0.85,
        "affected_nodes": ["bank_b", "bank_c", "payment_gateway_1"],
        "effects": {
            "latency_mult": 3.0,
            "timeout_target": 0.04,
            "success_target": 0.7,
            "retry_mult": 2.5,
            "pending_mult": 3.0,
        },
    },
    "gradual_degradation": {
        "roots": ["bank_a", "bank_b", "bank_c"],
        "start_offset_min": None,
        "ramp_min": 45,
        "hold_min": 30,
        "recovery_min": 15,
        "severity": 0.6,
        "effects": {
            "latency_mult_peak": 2.5,
            "timeout_target": 0.02,
            "success_target": 0.94,
            "retry_mult": 1.5,
            "pending_mult": 1.5,
        },
    },
    "mild_incident": {
        "roots": ["bank_a", "bank_b", "bank_c"],
        "start_offset_min": None,
        "ramp_min": 2,
        "hold_min": 10,
        "recovery_min": 5,
        "severity": 0.3,
        "effects": {
            "latency_mult": 1.6,
            "timeout_target": 0.012,
            "success_target": 0.96,
            "retry_mult": 1.5,
            "pending_mult": 1.5,
        },
    },
    "benign_peak": {
        "roots": [],  # no root - affects all nodes
        "start_offset_min": None,
        "duration_min": 90,
        "severity": 0.0,
        "is_incident": False,
        "effects": {
            "requests_mult": 1.6,
            "latency_mult_max": 1.1,
            "timeout_mult": 1.2,
        },
    },
}


# ---------------------------------------------------------------------------
# Schedule: when each scenario fires (seeded, non-overlapping, 60-min gaps)
# ---------------------------------------------------------------------------

def _build_schedule(seed: int) -> list[dict[str, Any]]:
    """Build the incident schedule for all 7 days.

    Returns a list of dicts with scenario, day, start_minute (from day start),
    and incident_id.
    """
    rng = np.random.default_rng(seed)
    schedule: list[dict[str, Any]] = []

    def _add(scenario: str, day: int, start_min: int, roots: list[str],
             is_incident: bool = True) -> None:
        sched = SCENARIOS[scenario]
        if scenario == "benign_peak":
            end_min = start_min + sched["duration_min"]
        else:
            end_min = (start_min + sched["ramp_min"] + sched["hold_min"]
                       + sched["recovery_min"])
        affected = sched.get("affected_nodes", roots) if roots else []
        incident_id = f"INC-{len(schedule)+1:04d}"
        schedule.append({
            "incident_id": incident_id,
            "scenario": scenario,
            "is_incident": is_incident,
            "root_node": roots[0] if roots else "none",
            "day": day,
            "start_min": start_min,
            "end_min": end_min,
            "severity": sched["severity"],
            "affected_nodes": affected,
            "effects": dict(sched["effects"]),
        })

    # Train days 1-4
    _add("benign_peak", day=2, start_min=600, roots=[], is_incident=False)
    _add("mild_incident", day=3, start_min=420, roots=["bank_a", "bank_b", "bank_c"])
    _add("mild_incident", day=3, start_min=900, roots=["bank_a", "bank_b", "bank_c"])

    # Validation day 5
    _add("bank_slowdown", day=5, start_min=360, roots=["bank_a", "bank_b", "bank_c"])
    _add("retry_storm", day=5, start_min=720, roots=["status_check_api"])
    _add("gradual_degradation", day=5, start_min=1020, roots=["bank_a", "bank_b", "bank_c"])
    _add("benign_peak", day=5, start_min=1200, roots=[], is_incident=False)

    # Test days 6-7
    _add("bank_slowdown", day=6, start_min=300, roots=["bank_a", "bank_b", "bank_c"])
    _add("bank_slowdown", day=6, start_min=800, roots=["bank_a", "bank_b", "bank_c"])
    _add("retry_storm", day=6, start_min=1100, roots=["status_check_api"])
    _add("gradual_degradation", day=6, start_min=1300, roots=["bank_a", "bank_b", "bank_c"])
    _add("shared_upstream", day=7, start_min=240, roots=["cloud_region_1"])
    _add("shared_upstream", day=7, start_min=700, roots=["cloud_region_1"])
    _add("mild_incident", day=7, start_min=960, roots=["bank_a", "bank_b", "bank_c"])
    _add("mild_incident", day=7, start_min=1200, roots=["bank_a", "bank_b", "bank_c"])
    _add("benign_peak", day=7, start_min=1380, roots=[], is_incident=False)

    return schedule


# ---------------------------------------------------------------------------
# Traffic shape helpers
# ---------------------------------------------------------------------------

def _minute_of_day_factor(hour: int, minute: int, is_weekend: bool,
                          is_salary_day: bool) -> float:
    """Return a volume multiplier for a given time slot."""
    h = hour + minute / 60.0
    # Base sinusoidal pattern with two peaks
    base = 1.0
    # Morning peak at 11:00
    base += (TRAFFIC_SHAPE["peak_multiplier"] - 1) * np.exp(
        -0.5 * ((h - TRAFFIC_SHAPE["peak_1_hour"]) / 1.5) ** 2
    )
    # Evening peak at 19:00
    base += (TRAFFIC_SHAPE["peak_multiplier"] - 1) * np.exp(
        -0.5 * ((h - TRAFFIC_SHAPE["peak_2_hour"]) / 1.5) ** 2
    )
    # Trough at 02:00-05:00
    if 2 <= h < 5:
        base = min(base, TRAFFIC_SHAPE["trough_multiplier"] + 0.3)
    if is_weekend:
        base *= TRAFFIC_SHAPE["weekend_factor"]
    if is_salary_day:
        base *= TRAFFIC_SHAPE["salary_day_bump"]
    return base


# ---------------------------------------------------------------------------
# Main generation
# ---------------------------------------------------------------------------

def generate_telemetry(
    seed: int,
    start_date: str,
    days: int,
    out_dir: Path,
) -> pd.DataFrame:
    """Generate synthetic telemetry.csv.

    Returns the DataFrame (also writes to out_dir/telemetry.csv).
    """
    rng = np.random.default_rng(seed)
    start = pd.Timestamp(start_date, tz="Asia/Kolkata")
    n_minutes = days * 24 * 60
    timestamps = [start + pd.Timedelta(n, "min") for n in range(n_minutes)]

    rows: list[dict[str, Any]] = []

    for min_idx, ts in enumerate(timestamps):
        hour = ts.hour
        minute = ts.minute
        is_weekend = ts.dayofweek >= 5
        is_salary = ts.day == 5  # simplified salary day
        vol_factor = _minute_of_day_factor(hour, minute, is_weekend, is_salary)

        for node_id in NODE_IDS:
            bl = BASELINES[node_id]
            base_rps = TRAFFIC_SHAPE["base_rps"] * VOLUME_RATIOS.get(node_id, 1.0)
            expected_requests = int(base_rps * 60 * vol_factor)

            # Poisson noise for requests
            requests = max(1, rng.poisson(expected_requests))

            # Success rate with binomial noise
            sr_base = bl["success_rate"]
            successes = rng.binomial(requests, sr_base)
            success_rate = successes / requests if requests > 0 else 1.0

            # Timeout ratio
            to_base = bl["timeout_ratio"]
            max_to = 1.0 - success_rate
            to_possible = min(to_base, max_to)
            timeouts = rng.binomial(requests, to_possible)
            timeout_ratio = timeouts / requests if requests > 0 else 0.0

            # Latency: lognormal
            lat_range = bl["p95_latency_ms"]
            lat_median = (lat_range[0] + lat_range[1]) / 2
            p95 = max(10, rng.lognormal(np.log(lat_median), LATENCY_LOGSIGMA))

            # Retry ratio
            rr_range = bl["retry_ratio"]
            rr_base = (rr_range[0] + rr_range[1]) / 2
            retry_ratio = max(0, rng.normal(rr_base, 0.005))

            # Pending txns
            pending_pct = bl["pending_pct"]
            pending_txns = max(0, int(requests * pending_pct * rng.normal(1, 0.1)))

            # Rare latency blip
            if rng.random() < LATENCY_BLIP_PROB:
                p95 *= rng.uniform(LATENCY_BLIP_MULTIPLIER, LATENCY_BLIP_MULTIPLIER + 0.5)

            rows.append({
                "timestamp": ts.isoformat(),
                "node_id": node_id,
                "requests": requests,
                "success_rate": round(success_rate, 6),
                "timeout_ratio": round(min(timeout_ratio, 1.0 - success_rate), 6),
                "p95_latency_ms": round(p95, 2),
                "retry_ratio": round(min(retry_ratio, 1.0), 6),
                "pending_txns": pending_txns,
            })

    df = pd.DataFrame(rows)
    df = df.sort_values(["timestamp", "node_id"]).reset_index(drop=True)

    # Ensure invariants
    df["timeout_ratio"] = df.apply(
        lambda r: min(r["timeout_ratio"], 1.0 - r["success_rate"]), axis=1
    )
    df["timeout_ratio"] = df["timeout_ratio"].clip(lower=0.0)
    df["success_rate"] = df["success_rate"].clip(lower=0.0, upper=1.0)
    df["retry_ratio"] = df["retry_ratio"].clip(lower=0.0, upper=1.0)

    # No NaNs
    assert df.isnull().sum().sum() == 0, "DataFrame contains NaNs"

    out_path = out_dir / "telemetry.csv"
    df.to_csv(out_path, index=False)
    logger.info("Generated %s: %d rows", out_path, len(df))
    return df


def generate_incidents(
    schedule: list[dict[str, Any]],
    start_date: str,
    out_dir: Path,
) -> pd.DataFrame:
    """Generate incidents.csv from the schedule.

    Returns the DataFrame (also writes to out_dir/incidents.csv).
    """
    start = pd.Timestamp(start_date, tz="Asia/Kolkata")
    rows: list[dict[str, Any]] = []

    for entry in schedule:
        day_start = start + pd.Timedelta(entry["day"] - 1, "days")
        inc_start = day_start + pd.Timedelta(entry["start_min"], "min")
        inc_end = day_start + pd.Timedelta(entry["end_min"], "min")

        # Determine split
        day = entry["day"]
        if day <= 4:
            split = "train"
        elif day == 5:
            split = "val"
        else:
            split = "test"

        affected = ";".join(entry["affected_nodes"]) if entry["affected_nodes"] else "none"
        notes = f"scenario={entry['scenario']}, severity={entry['severity']}"
        if not entry["is_incident"]:
            notes += " (benign, not an incident)"

        rows.append({
            "incident_id": entry["incident_id"],
            "scenario": entry["scenario"],
            "is_incident": entry["is_incident"],
            "root_node": entry["root_node"],
            "start": inc_start.isoformat(),
            "end": inc_end.isoformat(),
            "severity": entry["severity"],
            "affected_nodes": affected,
            "split": split,
            "notes": notes,
        })

    df = pd.DataFrame(rows)
    out_path = out_dir / "incidents.csv"
    df.to_csv(out_path, index=False)
    logger.info("Generated %s: %d incidents", out_path, len(df))
    return df


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic UPIShield data")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--out", type=Path, default=Path("data"), help="Output directory")
    parser.add_argument("--start", type=str, default="2026-11-02", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, default=7, help="Number of days")
    parser.add_argument("--plots", action="store_true", help="Generate plot PNGs")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    args.out.mkdir(parents=True, exist_ok=True)

    logger.info("Generating data: seed=%d, start=%s, days=%d", args.seed, args.start, args.days)

    # Build schedule
    schedule = _build_schedule(args.seed)

    # Generate telemetry (base, no incidents)
    df = generate_telemetry(args.seed, args.start, args.days, args.out)

    # Generate incidents.csv
    generate_incidents(schedule, args.start, args.out)

    logger.info("Data generation complete. Files in %s", args.out)

    if args.plots:
        _generate_plots(df, schedule, args.out)


def _generate_plots(df: pd.DataFrame, schedule: list[dict[str, Any]], out_dir: Path) -> None:
    """Generate diagnostic plots."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib not installed; skipping plots")
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    # Plot 1: success_rate and p95_latency for all nodes on day 1
    fig, axes = plt.subplots(2, 1, figsize=(14, 8))
    day1 = df[df["timestamp"].str.startswith("2026-11-02")]
    for node_id in NODE_IDS[:4]:  # subset for readability
        node_data = day1[day1["node_id"] == node_id]
        axes[0].plot(node_data["timestamp"], node_data["success_rate"], label=node_id, alpha=0.7)
        axes[1].plot(node_data["timestamp"], node_data["p95_latency_ms"], label=node_id, alpha=0.7)
    axes[0].set_title("Day 1: Success Rate per Node")
    axes[0].set_ylabel("success_rate")
    axes[0].legend(fontsize=8)
    axes[1].set_title("Day 1: P95 Latency per Node")
    axes[1].set_ylabel("p95_latency_ms")
    axes[1].legend(fontsize=8)
    plt.tight_layout()
    fig.savefig(out_dir / "day1_metrics.png", dpi=100)
    plt.close(fig)
    logger.info("Saved day1_metrics.png")

    # Plot 2: One scenario per subplot
    scenarios = ["bank_slowdown", "retry_storm", "mild_incident"]
    n_scenarios = len(scenarios)
    fig, axes = plt.subplots(1, n_scenarios, figsize=(4 * n_scenarios, 4))
    for idx, scenario in enumerate(scenarios):
        inc_entries = [s for s in schedule if s["scenario"] == scenario]
        if not inc_entries:
            continue
        entry = inc_entries[0]
        day_start = pd.Timestamp("2026-11-02", tz="Asia/Kolkata") + pd.Timedelta(entry["day"] - 1, "days")
        inc_start_ts = day_start + pd.Timedelta(entry["start_min"], "min")
        inc_end_ts = day_start + pd.Timedelta(entry["end_min"], "min")
        window = df[
            (df["timestamp"] >= inc_start_ts.isoformat())
            & (df["timestamp"] <= inc_end_ts.isoformat())
        ]
        if window.empty:
            continue
        root = entry["root_node"]
        if root == "none":
            root = "all_banks"
        root_data = window[window["node_id"] == root] if root in window["node_id"].values else window.iloc[:0]
        if not root_data.empty:
            axes[idx].plot(root_data["timestamp"], root_data["success_rate"], label="success_rate", color="red")
            axes[idx].plot(root_data["timestamp"], root_data["p95_latency_ms"] / 1000, label="p95_s", color="orange")
        axes[idx].set_title(f"{scenario}\n(root={root})")
        axes[idx].legend(fontsize=8)
    plt.tight_layout()
    fig.savefig(out_dir / "scenarios.png", dpi=100)
    plt.close(fig)
    logger.info("Saved scenarios.png")


if __name__ == "__main__":
    main()