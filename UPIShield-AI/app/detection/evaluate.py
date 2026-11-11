"""Evaluation of detection on a given split.

Computes event-level metrics for the ML detector and static baseline.
Writes reports to reports/detection_eval_<split>.json and .md.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from app.config import DATA_DIR, REPORTS_DIR
from app.detection.alerting import AlertManager
from app.detection.baseline import StaticBaselineDetector
from app.detection.features import compute_features

logger = logging.getLogger(__name__)


def evaluate(split: str = "test") -> dict:
    """Evaluate detection on a split. Returns metrics dict."""
    df = pd.read_csv(DATA_DIR / "telemetry.csv")
    inc_df = pd.read_csv(DATA_DIR / "incidents.csv")

    split_incs = inc_df[inc_df["split"] == split]
    if split_incs.empty:
        logger.warning("No incidents in split %s", split)
        return {"error": f"No incidents in split {split}"}

    feature_df = compute_features(df)
    if "node_id" not in feature_df.columns:
        feature_df["node_id"] = df["node_id"]
        feature_df["timestamp"] = df["timestamp"]

    ml_manager = AlertManager()
    thresholds = {node_id: 0.995 for node_id in df["node_id"].unique()}
    ml_alerts = ml_manager.process_scores(feature_df, thresholds)

    static_detector = StaticBaselineDetector()
    static_alerts = static_detector.check(df[["node_id", "timestamp", "timeout_ratio", "p95_latency_ms"]])

    metrics = _compute_event_metrics(ml_alerts, static_alerts, split_incs, df)
    return metrics


def _compute_event_metrics(ml_alerts, static_alerts, inc_df, telemetry_df):
    """Compute event-level detection metrics."""
    results = {}
    for name, alerts in [("ml_detector", ml_alerts), ("static_baseline", static_alerts)]:
        detected_incidents = 0
        false_alerts = 0
        detection_delays: list[float] = []
        per_scenario: dict = {}

        for _, inc in inc_df.iterrows():
            inc_start = pd.Timestamp(inc["start"])
            inc_end = pd.Timestamp(inc["end"])
            window_end = inc_end + pd.Timedelta(10, "min")
            root = inc["root_node"]
            affected = inc.get("affected_nodes", "")
            if isinstance(affected, str):
                affected_nodes = [n.strip() for n in affected.split(";") if n.strip()]
            else:
                affected_nodes = []
            relevant_nodes = set([root] + affected_nodes) if root != "none" else set()

            incident_detected = False
            for alert in alerts:
                if alert.node_id not in relevant_nodes:
                    continue
                alert_time = pd.Timestamp(alert.alert_time)
                if inc_start <= alert_time <= window_end:
                    incident_detected = True
                    delay = (alert_time - inc_start).total_seconds() / 60
                    detection_delays.append(delay)
                    break

            scenario = inc["scenario"]
            if scenario not in per_scenario:
                per_scenario[scenario] = {"total": 0, "detected": 0}
            per_scenario[scenario]["total"] += 1
            if incident_detected:
                detected_incidents += 1
                per_scenario[scenario]["detected"] += 1

        total_incidents = len(inc_df[inc_df["is_incident"] == True])
        precision = detected_incidents / (detected_incidents + false_alerts + 1e-10)
        recall = detected_incidents / total_incidents if total_incidents > 0 else 0
        f1 = 2 * precision * recall / (precision + recall + 1e-10)

        benign_fps = 0
        benign_incs = inc_df[inc_df["is_incident"] == False]
        for alert in alerts:
            for _, inc in benign_incs.iterrows():
                at = pd.Timestamp(alert.alert_time)
                if pd.Timestamp(inc["start"]) <= at <= pd.Timestamp(inc["end"]):
                    benign_fps += 1
                    break

        results[name] = {
            "total_incidents": total_incidents,
            "detected": detected_incidents,
            "false_alerts": false_alerts,
            "benign_false_positives": benign_fps,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "median_delay_min": round(float(pd.Series(detection_delays).median()), 2) if detection_delays else 0,
            "p90_delay_min": round(float(pd.Series(detection_delays).quantile(0.9)), 2) if detection_delays else 0,
            "per_scenario": per_scenario,
        }

    results["disclaimer"] = (
        "This evaluation validates the pipeline on SYNTHETIC data only. "
        "Results do not reflect real-world accuracy. "
        "The data generator uses assumed propagation probabilities and incident magnitudes."
    )
    return results