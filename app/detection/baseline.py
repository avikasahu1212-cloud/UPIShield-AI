"""Static-threshold baseline detector.

Alerts when timeout_ratio > 0.02 OR p95 latency > 2x node baseline
for 3 consecutive minutes. Used for honest comparison against the ML detector.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.config import BASELINES

logger = logging.getLogger(__name__)


@dataclass
class StaticAlert:
    id: str
    node_id: str
    first_violation_time: str
    alert_time: str
    status: str = "active"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "node_id": self.node_id,
            "first_violation_time": self.first_violation_time,
            "alert_time": self.alert_time,
            "status": self.status,
            "data_source": "synthetic",
            "method": "static_threshold",
        }


class StaticBaselineDetector:
    """Simple rule-based detector for comparison."""

    TIMEOUT_THRESHOLD = 0.02
    LATENCY_MULTIPLIER = 2.0
    CONSECUTIVE_MINUTES = 3

    def __init__(self):
        self.active_alerts: list[StaticAlert] = []
        self.all_alerts: list[StaticAlert] = []
        self._tracking: dict[str, dict] = {}

    def check(self, df: pd.DataFrame) -> list[StaticAlert]:
        """Check a batch of telemetry rows. Returns new alerts."""
        new_alerts: list[StaticAlert] = []
        # Group by node and timestamp
        for (node_id, ts), group in df.groupby(["node_id", "timestamp"]):
            if node_id not in BASELINES:
                continue
            bl = BASELINES[node_id]
            lat_range = bl["p95_latency_ms"]
            lat_threshold = lat_range[1] * self.LATENCY_MULTIPLIER

            timeout_violation = group["timeout_ratio"].values[0] > self.TIMEOUT_THRESHOLD
            latency_violation = group["p95_latency_ms"].values[0] > lat_threshold

            if not (timeout_violation or latency_violation):
                # Reset tracking
                if node_id in self._tracking:
                    self._tracking[node_id]["consecutive"] = 0
                continue

            if node_id not in self._tracking:
                self._tracking[node_id] = {"consecutive": 0, "first_time": ts}

            self._tracking[node_id]["consecutive"] += 1
            if self._tracking[node_id]["consecutive"] >= self.CONSECUTIVE_MINUTES:
                alert_id = f"STATIC-{node_id[:4]}-{ts}"
                alert = StaticAlert(
                    id=alert_id,
                    node_id=node_id,
                    first_violation_time=self._tracking[node_id]["first_time"],
                    alert_time=ts,
                )
                new_alerts.append(alert)
                self.active_alerts.append(alert)
                self.all_alerts.append(alert)

        return new_alerts

    def get_active_alerts(self) -> list[dict[str, Any]]:
        return [a.to_dict() for a in self.active_alerts]