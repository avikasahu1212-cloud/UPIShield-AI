"""Event schema for Kafka ingestion."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class TelemetryMetrics(BaseModel):
    """Per-minute metrics for a single node."""
    requests: int = Field(ge=0)
    success_rate: float = Field(ge=0.0, le=1.0)
    timeout_ratio: float = Field(ge=0.0, le=1.0)
    p95_latency_ms: float = Field(ge=0.0)
    retry_ratio: float = Field(ge=0.0, le=1.0)
    pending_txns: float = Field(ge=0.0)


class TelemetryEvent(BaseModel):
    """A single telemetry event for Kafka ingestion."""
    schema_version: int = 1
    event_id: str = ""
    ts: str = ""  # ISO 8601 timestamp
    node_id: str
    metrics: TelemetryMetrics
    data_source: str = "synthetic"

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "TelemetryEvent":
        """Create event from a telemetry CSV row."""
        ts = row.get("timestamp", "")
        node_id = row.get("node_id", "")
        event_id = hashlib.sha256(f"{node_id}:{ts}".encode()).hexdigest()[:12]
        return cls(
            event_id=event_id,
            ts=ts,
            node_id=node_id,
            metrics=TelemetryMetrics(
                requests=int(row.get("requests", 0)),
                success_rate=float(row.get("success_rate", 0)),
                timeout_ratio=float(row.get("timeout_ratio", 0)),
                p95_latency_ms=float(row.get("p95_latency_ms", 0)),
                retry_ratio=float(row.get("retry_ratio", 0)),
                pending_txns=float(row.get("pending_txns", 0)),
            ),
        )

    def to_dict(self) -> dict:
        """Serialise to dict for Kafka serialization."""
        return self.model_dump()
