"""SQLite runtime store for metrics and alerts."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from app.config import BASE_DIR

logger = logging.getLogger(__name__)

RUNTIME_DB = BASE_DIR / "data" / "runtime.db"


class MetricStore:
    """Lightweight SQLite store for node_metrics, alerts, incidents."""

    def __init__(self, path: Path | None = None):
        self._path = path or RUNTIME_DB
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(str(self._path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS node_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    requests INTEGER, success_rate REAL, timeout_ratio REAL,
                    p95_latency_ms REAL, retry_ratio REAL, pending_txns REAL,
                    anomaly_score REAL, health_state TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_metrics_ts_node ON node_metrics(ts, node_id);

                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    first_anomaly_time TEXT,
                    alert_time TEXT,
                    peak_score REAL,
                    status TEXT DEFAULT 'active',
                    top_features TEXT,
                    data_source TEXT DEFAULT 'synthetic'
                );
                CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);

                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    scenario TEXT,
                    root_node TEXT,
                    start TEXT,
                    end TEXT,
                    severity REAL,
                    affected_nodes TEXT,
                    split TEXT,
                    is_incident INTEGER
                );
            """)
            logger.info("Initialized SQLite store at %s", self._path)

    def append_metrics(self, rows: list[dict[str, Any]]) -> None:
        """Append node metrics rows."""
        if not rows:
            return
        with sqlite3.connect(str(self._path)) as conn:
            conn.executemany(
                "INSERT INTO node_metrics (ts, node_id, requests, success_rate, "
                "timeout_ratio, p95_latency_ms, retry_ratio, pending_txns, "
                "anomaly_score, health_state) "
                "VALUES (:ts, :node_id, :requests, :success_rate, "
                ":timeout_ratio, :p95_latency_ms, :retry_ratio, :pending_txns, "
                ":anomaly_score, :health_state)",
                rows,
            )

    def append_alert(self, alert: dict[str, Any]) -> None:
        """Append an alert."""
        with sqlite3.connect(str(self._path)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO alerts (id, node_id, first_anomaly_time, "
                "alert_time, peak_score, status, top_features, data_source) "
                "VALUES (:id, :node_id, :first_anomaly_time, :alert_time, "
                ":peak_score, :status, :top_features, :data_source)",
                alert,
            )

    def get_active_alerts(self) -> list[dict[str, Any]]:
        """Get all active alerts."""
        with sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM alerts WHERE status = 'active' ORDER BY alert_time DESC"
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_metrics_series(
        self, node_id: str | None = None, metric: str | None = None,
        from_ts: str | None = None, to_ts: str | None = None,
        step_min: int = 1,
    ) -> list[dict[str, Any]]:
        """Get downsampled metrics series for charting."""
        query = "SELECT ts, node_id, requests, success_rate, timeout_ratio, " \
                "p95_latency_ms, retry_ratio, pending_txns, anomaly_score, health_state " \
                "FROM node_metrics WHERE 1=1"
        params: dict = {}
        if node_id:
            query += " AND node_id = :node_id"
            params["node_id"] = node_id
        if from_ts:
            query += " AND ts >= :from_ts"
            params["from_ts"] = from_ts
        if to_ts:
            query += " AND ts <= :to_ts"
            params["to_ts"] = to_ts
        query += " ORDER BY ts LIMIT 10000"
        with sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_health_summary(self) -> dict[str, Any]:
        """Get current health per node and active alert count."""
        with sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            latest = conn.execute(
                "SELECT node_id, health_state, anomaly_score, ts "
                "FROM node_metrics nm1 "
                "WHERE ts = (SELECT MAX(ts) FROM node_metrics nm2 WHERE nm2.node_id = nm1.node_id)"
            ).fetchall()
            health = {row["node_id"]: {"health_state": row["health_state"],
                                        "anomaly_score": row["anomaly_score"]}
                      for row in latest}
            active = conn.execute(
                "SELECT COUNT(*) as cnt FROM alerts WHERE status = 'active'"
            ).fetchone()["cnt"]
            return {"nodes": health, "active_alerts": active}
