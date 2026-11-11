"""Detector worker - consumes events, computes features, scores with IsolationForest."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

import pandas as pd

from app.config import DATA_DIR, INGEST_MODE
from app.data.loader import DataLoader
from app.detection.alerting import AlertManager
from app.detection.features import compute_features
from app.detection.model import DetectorModel
from app.ingest.controller import ReplayController
from app.monitoring.prom import update_anomaly_score, set_active_alerts

logger = logging.getLogger(__name__)


class DetectorWorker:
    """Background worker that runs detection on incoming events."""

    def __init__(self, replay_controller: ReplayController | None = None):
        self._replay = replay_controller
        self._detector: DetectorModel | None = None
        self._alert_manager: AlertManager | None = None
        self._telemetry_df: pd.DataFrame | None = None
        self._running = False
        self._thread: threading.Thread | None = None

    def initialize(self) -> None:
        """Load data and train detector."""
        logger.info("DetectorWorker initializing...")
        self._telemetry_df = DataLoader.load()
        self._detector = DetectorModel()
        feature_df = compute_features(self._telemetry_df)
        feature_df["node_id"] = self._telemetry_df["node_id"]
        feature_df["timestamp"] = self._telemetry_df["timestamp"]
        self._detector.fit(feature_df)
        self._detector.save_all()
        self._alert_manager = AlertManager()
        logger.info("DetectorWorker initialized with %d node models",
                     len(self._detector.models))

    def process_batch(self, df: pd.DataFrame) -> tuple[list, dict]:
        """Process a batch of telemetry data. Returns (new_alerts, health)."""
        if not self._detector or not self._alert_manager:
            return [], {}
        feature_df = compute_features(df)
        feature_df["node_id"] = df["node_id"]
        feature_df["timestamp"] = df["timestamp"]
        scored = self._detector.score(feature_df)
        if scored.empty:
            return [], {}
        new_alerts = self._alert_manager.process_scores(scored)
        health = self._alert_manager.get_node_health()
        # Update Prometheus gauges
        for _, row in scored.iterrows():
            update_anomaly_score(row["node_id"], row["anomaly_score"])
        set_active_alerts(len(self._alert_manager.active_alerts))
        return new_alerts, health

    def run(self, stop_event: threading.Event | None = None) -> None:
        """Run the worker loop. Used when INGEST_MODE=kafka."""
        self._running = True
        logger.info("DetectorWorker running in Kafka mode")
        while not (stop_event and stop_event.is_set()):
            time.sleep(1)
        self._running = False

    def get_active_alerts(self) -> list:
        if self._alert_manager:
            return self._alert_manager.get_active_alerts()
        return []

    def get_health(self) -> dict:
        if self._alert_manager:
            return self._alert_manager.get_node_health()
        return {}
