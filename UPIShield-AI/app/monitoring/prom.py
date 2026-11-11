"""Prometheus metrics exposition for UPIShield.

Provides per-node gauges and global counters in Prometheus exposition format.
Values follow the simulated clock, not wall-clock scrape time.
"""

from __future__ import annotations

import logging

from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

logger = logging.getLogger(__name__)

# Per-node gauges (created lazily)
_success_rate_gauges: dict[str, Gauge] = {}
_p95_latency_gauges: dict[str, Gauge] = {}
_timeout_ratio_gauges: dict[str, Gauge] = {}
_anomaly_score_gauges: dict[str, Gauge] = {}

# Global counters
_events_consumed = Counter(
    "upishield_events_consumed_total",
    "Total events consumed by group",
    ["group"],
)
_consumer_lag = Counter(
    "upishield_consumer_lag",
    "Consumer lag in minutes",
    ["group"],
)
_detection_seconds = Histogram(
    "upishield_detection_seconds",
    "Time spent running detection per batch",
)

# Global gauges
_active_alerts = Gauge("upishield_active_alerts", "Number of active alerts")


def get_or_create_gauge(node_id: str, prefix: str) -> Gauge:
    """Get or create a per-node gauge."""
    if node_id not in _success_rate_gauges:
        _success_rate_gauges[node_id] = Gauge(
            f"upishield_success_rate_{node_id.replace('-', '_')}",
            f"Success rate for {node_id}",
        )
        _p95_latency_gauges[node_id] = Gauge(
            f"upishield_p95_latency_ms_{node_id.replace('-', '_')}",
            f"P95 latency for {node_id}",
        )
        _timeout_ratio_gauges[node_id] = Gauge(
            f"upishield_timeout_ratio_{node_id.replace('-', '_')}",
            f"Timeout ratio for {node_id}",
        )
        _anomaly_score_gauges[node_id] = Gauge(
            f"upishield_anomaly_score_{node_id.replace('-', '_')}",
            f"Anomaly score for {node_id}",
        )
    return getattr(globals(), f"_{prefix}_gauges", {})[node_id]


def update_node_metrics(node_id: str, success_rate: float,
                        p95_latency_ms: float, timeout_ratio: float) -> None:
    """Update per-node Prometheus gauges."""
    try:
        _success_rate_gauges.get(node_id, Gauge("", "")).set(success_rate)
        _p95_latency_gauges.get(node_id, Gauge("", "")).set(p95_latency_ms)
        _timeout_ratio_gauges.get(node_id, Gauge("", "")).set(timeout_ratio)
    except Exception:
        pass  # Don't crash on Prometheus errors


def update_anomaly_score(node_id: str, score: float) -> None:
    """Update anomaly score gauge."""
    try:
        _anomaly_score_gauges.get(node_id, Gauge("", "")).set(score)
    except Exception:
        pass


def set_active_alerts(count: int) -> None:
    """Set the active alerts gauge."""
    _active_alerts.set(count)


def record_consumed(group: str, count: int = 1) -> None:
    """Record consumed events."""
    _events_consumed.labels(group=group).inc(count)


def expose_metrics() -> bytes:
    """Return Prometheus exposition format metrics."""
    return generate_latest(CONTENT_TYPE_LATEST)
