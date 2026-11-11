"""Hyperparameter tuning for the detector.

Grid search over threshold quantile and (K, N) on the VALIDATION split only.
Writes the best config to artifacts/detector_config.json.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from app.config import (
    ALERT_PERSISTENCE_K,
    ALERT_PERSISTENCE_N,
    ALERT_RESOLVE_M,
    ARTIFACTS_DIR,
    DATA_DIR,
    REPORTS_DIR,
)
from app.detection.alerting import AlertManager
from app.detection.model import DetectorModel
from app.detection.features import compute_features

logger = logging.getLogger(__name__)

THRESHOLDS = [0.99, 0.995, 0.999]
K_N_PAIRS = [(2, 3), (3, 5), (4, 6)]


def load_split(split: str) -> pd.DataFrame:
    """Load telemetry for a given split."""
    df = pd.read_csv(DATA_DIR / "telemetry.csv")
    inc_df = pd.read_csv(DATA_DIR / "incidents.csv")

    if split == "train":
        train_incs = inc_df[inc_df["split"] == "train"]
    elif split == "val":
        train_incs = inc_df[inc_df["split"] == "train"]
        val_incs = inc_df[inc_df["split"] == "val"]
    else:
        train_incs = inc_df[inc_df["split"].isin(["train", "val"])]
        val_incs = inc_df[inc_df["split"] == split]

    # For tuning, we need train data to fit and val data to evaluate
    if split == "val":
        train_rows = []
        for _, inc in train_incs.iterrows():
            train_rows.append({"start": inc["start"], "end": inc["end"]})
        # Use all train split data
        mask = pd.Series(False, index=df.index)
        for _, inc in train_incs.iterrows():
            mask |= df["timestamp"].between(inc["start"], inc["end"])
        train_df = df[~mask] if len(train_rows) > 0 else df.iloc[:0]
        eval_df = df
    else:
        train_df = df
        eval_df = df

    return train_df, eval_df, val_incs


def tune() -> dict:
    """Run grid search. Returns best config."""
    train_df, eval_df, val_incs = load_split("val")

    # Compute features
    feature_df = compute_features(eval_df)

    # Add node_id back (compute_features preserves it)
    if "node_id" not in eval_df.columns:
        feature_df["node_id"] = eval_df["node_id"]
        feature_df["timestamp"] = eval_df["timestamp"]

    best_config = {
        "threshold_quantile": 0.995,
        "k": ALERT_PERSISTENCE_K,
        "n": ALERT_PERSISTENCE_N,
        "m": ALERT_RESOLVE_M,
        "f1": 0.0,
        "false_alerts_per_day": float("inf"),
    }

    for quantile in THRESHOLDS:
        for k, n in K_N_PAIRS:
            manager = AlertManager(k=k, n=n, m=ALERT_RESOLVE_M)
            # Use a simple threshold based on quantile
            thresholds = {node_id: quantile for node_id in eval_df["node_id"].unique()}

            new_alerts = manager.process_scores(feature_df, thresholds)

            # Simple scoring: count alerts during val incidents
            val_incidents = val_incs[val_incs["is_incident"] == True]
            detected = 0
            false_alerts = 0

            for alert in new_alerts:
                alert_time = pd.Timestamp(alert["alert_time"])
                # Check if alert falls within any val incident
                for _, inc in val_incidents.iterrows():
                    inc_start = pd.Timestamp(inc["start"])
                    inc_end = pd.Timestamp(inc["end"])
                    if inc_start <= alert_time <= inc_end:
                        detected += 1
                        break
                else:
                    false_alerts += 1

            days = 1  # validation is 1 day
            f1 = 2 * detected / (2 * detected + false_alerts + 1e-10) if detected + false_alerts > 0 else 0

            logger.info("quantile=%.3f K=%d N=%d: detected=%d false=%d f1=%.3f",
                        quantile, k, n, detected, false_alerts, f1)

            if f1 > best_config["f1"] or (
                f1 == best_config["f1"] and false_alerts / days < best_config["false_alerts_per_day"]
            ):
                best_config = {
                    "threshold_quantile": quantile,
                    "k": k,
                    "n": n,
                    "m": ALERT_RESOLVE_M,
                    "f1": round(f1, 4),
                    "false_alerts_per_day": round(false_alerts / days, 2),
                    "detected": detected,
                    "false_alerts": false_alerts,
                }

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    config_path = ARTIFACTS_DIR / "detector_config.json"
    with open(config_path, "w") as f:
        json.dump(best_config, f, indent=2)
    logger.info("Best config saved to %s: %s", config_path, best_config)
    return best_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Tune detector hyperparameters")
    parser.add_argument("--split", type=str, default="val", help="Split to tune on")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    best = tune()
    print(f"Best config: {json.dumps(best, indent=2)}")


if __name__ == "__main__":
    main()