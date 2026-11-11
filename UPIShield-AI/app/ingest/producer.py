"""Kafka producer for telemetry ingestion."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.config import KAFKA_BOOTSTRAP_SERVERS
from app.ingest.schemas import TelemetryEvent

logger = logging.getLogger(__name__)

try:
    from confluent_kafka import Producer
    _KAFKA_AVAILABLE = True
except ImportError:
    _KAFKA_AVAILABLE = False
    logger.warning("confluent-kafka not available; KafkaProducer will be a no-op")


class KafkaProducerWrapper:
    """Kafka producer wrapper for telemetry events."""

    def __init__(self, bootstrap_servers: str | None = None):
        if not _KAFKA_AVAILABLE:
            self._producer = None
            return
        self._producer = Producer({
            "bootstrap.servers": bootstrap_servers or KAFKA_BOOTSTRAP_SERVERS,
            "enable.idempotence": True,
            "acks": "all",
            "retries": 5,
            "max.in.flight.requests.per.connection": 5,
        })
        logger.info("KafkaProducer initialised with %s",
                     bootstrap_servers or KAFKA_BOOTSTRAP_SERVERS)

    def produce(self, event: TelemetryEvent, topic: str = "upishield.telemetry") -> None:
        """Produce a single telemetry event."""
        if self._producer is None:
            return
        payload = json.dumps(event.to_dict()).encode("utf-8")
        key = event.node_id.encode("utf-8")
        try:
            self._producer.produce(
                topic, key=key, value=payload,
                timestamp=int(event.ts.replace("T", " ").replace(":", " ", 1).replace(":", "", 1).split(".")[-1]) if "T" in event.ts else int(time.time() * 1000),
            )
        except Exception as e:
            logger.warning("Failed to produce event %s: %s", event.event_id, e)

    def flush(self, timeout: float = 5.0) -> None:
        """Flush pending messages."""
        if self._producer:
            self._producer.flush(timeout)

    def poll(self, timeout: float = 0.1) -> None:
        """Poll for delivery reports."""
        if self._producer:
            self._producer.poll(timeout)
