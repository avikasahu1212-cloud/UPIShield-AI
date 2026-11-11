"""Alerting logic with persistence rule.

Alert when at least K of the last N windows exceed the threshold.
Resolve after M consecutive normal windows.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.config import (
    ALERT_PERSISTENCE_K,
    ALERT_PERSISTENCE_N,
    ALERT_RESOLVE_M,
)

logger = logging.getLogger(__name__)


@dataclass
class Alert:
    """A detected alert."""

    id: str
    node_id: str
    first_anomaly_time: str
    alert_time: str
    peak_score: float
    status: str = "active"
    top_features: list[str] = field(default_factory=list)
    data_source: str = "synthetic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "node_id": self.node_id,
            "first_anomaly_time": self.first_anomaly_time,
            "alert_time": self.alert_time,
            "peak_score": round(self.peak_score, 4),
            "status": self.status,
            "top_features": self.top_features,
            "data_source": self.data_source,
        }


@dataclass
class AlertState:
    """Per-node alert tracking state."""
    node_id: str
    is_alerting: bool = False
    first_anomaly_time: str = ""
    peak_score: float = 0.0
    recent_scores: list[tuple[str, float]] = field(default_factory=list)
    normal_count: int = 0

    def add_score(self, timestamp: str, score: float, threshold: float,
                  top_features: list[str], k: int = ALERT_PERSISTENCE_K,
                  n: int = ALERT_PERSISTENCE_N, m: int = ALERT_RESOLVE_M
                  ) -> Alert | None:
        """Process a new score. Returns an Alert if a new alert is fired."""
        self.recent_scores.append((timestamp, score))
        if len(self.recent_scores) > n:
            self.recent_scores = self.recent_scores[-n:]

        if score > threshold:
            if not self.is_alerting:
                self.normal_count = 0
                self.first_anomaly_time = timestamp
            self.peak_score = max(self.peak_score, score)
            self.recent_scores = [(t, s) for t, s in self.recent_scores if s > threshold]
            exceed_count = sum(1 for _, s in self.recent_scores if s > threshold)
            if exceed_count >= k and not self.is_alerting:
                self.is_alerting = True
                return Alert(
                    id=str(uuid.uuid4())[:8],
                    node_id=self.node_id,
                    first_anomaly_time=self.first_anomaly_time,
                    alert_time=timestamp,
                    peak_score=self.peak_score,
                    top_features=top_features,
                )
        else:
            if self.is_alerting:
                self.normal_count += 1
                if self.normal_count >= m:
                    self.is_alerting = False
                    self.normal_count = 0
                    self.peak_score = 0.0
                    self.recent_scores = []
        return None


class AlertManager:
    """Manages alerts across all nodes."""

    def __init__(self, k: int = ALERT_PERSISTENCE_K,
                 n: int = ALERT_PERSISTENCE_N,
                 m: int = ALERT_RESOLVE_M):
        self.k = k
        self.n = n
        self.m = m
        self.states: dict[str, AlertState] = {}
        self.active_alerts: list[Alert] = []
        self.resolved_alerts: list[Alert] = []
        self.all_alerts: list[Alert] = []

    def _get_state(self, node_id: str) -> AlertState:
        if node_id not in self.states:
            self.states[node_id] = AlertState(node_id=node_id)
        return self.states[node_id]

    def process_scores(self, scores_df: pd.DataFrame,
                       thresholds: dict[str, float] | None = None
                       ) -> list[Alert]:
        """Process scored data. Returns new alerts fired in this batch."""
        new_alerts: list[Alert] = []
        if thresholds is None:
            thresholds = {}

        for _, row in scores_df.iterrows():
            node_id = row["node_id"]
            timestamp = row["timestamp"]
            score = row["anomaly_score"]
            threshold = thresholds.get(node_id, 0.995)
            state = self._get_state(node_id)
            alert = state.add_score(timestamp, score, threshold, [])
            if alert:
                new_alerts.append(alert)
                self.active_alerts.append(alert)
                self.all_alerts.append(alert)

        # Resolve resolved alerts
        for node_id, state in self.states.items():
            if state.is_alerting:
                continue
            for alert in self.active_alerts:
                if alert.node_id == node_id and alert.status == "active":
                    alert.status = "resolved"
                    self.resolved_alerts.append(alert)
        return new_alerts

    def get_active_alerts(self) -> list[dict[str, Any]]:
        return [a.to_dict() for a in self.active_alerts if a.status == "active"]

    def get_all_alerts(self) -> list[dict[str, Any]]:
        return [a.to_dict() for a in self.all_alerts]

    def get_node_health(self) -> dict[str, str]:
        """Return health state per node: normal / degraded / anomalous."""
        health: dict[str, str] = {}
        for node_id, state in self.states.items():
            if state.is_alerting:
                health[node_id] = "anomalous"
            elif state.peak_score > 0:
                health[node_id] = "degraded"
            else:
                health[node_id] = "normal"
        return health