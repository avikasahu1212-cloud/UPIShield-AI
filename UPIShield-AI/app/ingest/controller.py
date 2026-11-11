"""ReplayController - thread-safe controller for replay playback."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.config import DATA_DIR
from app.data.loader import ReplaySource
from app.ingest.producer import KafkaProducerWrapper
from app.ingest.schemas import TelemetryEvent

logger = logging.getLogger(__name__)


class ReplayController:
    """Single-instance, thread-safe replay controller."""

    def __init__(self, telemetry_df: pd.DataFrame | None = None,
                 producer: KafkaProducerWrapper | None = None):
        self._df = telemetry_df
        self._replay = ReplaySource(telemetry_df) if telemetry_df is not None else None
        self._producer = producer
        self._lock = threading.Lock()
        self._speed: float = 1.0  # simulated minutes per real second
        self._paused = False
        self._session_id = f"session-{int(time.time())}"

    def reset(self, start_ts: str | None = None) -> dict:
        """Reset replay to start or a specific timestamp."""
        with self._lock:
            if self._replay:
                self._replay.reset(start_ts)
            logger.info("ReplayController reset%s", f" to {start_ts}" if start_ts else "")
            return self.status()

    def advance(self, minutes: int) -> dict:
        """Advance by *minutes*, produce events, return status + new events."""
        with self._lock:
            if not self._replay:
                return {"error": "No telemetry data loaded"}
            new_data = self._replay.advance(minutes)
            if new_data.empty:
                return {"clock": self.status(), "produced": 0}

            produced = 0
            events = []
            for _, row in new_data.iterrows():
                event = TelemetryEvent.from_row(row.to_dict())
                events.append(event.to_dict())
                if self._producer:
                    self._producer.produce(event)
                produced += 1

            if self._producer:
                self._producer.flush()

            logger.info("ReplayController advanced %d minutes, produced %d events",
                        minutes, produced)
            return {"clock": self.status(), "produced": produced, "events": events[:100]}

    def set_speed(self, sim_minutes_per_second: float) -> None:
        """Set playback speed."""
        self._speed = max(0.1, sim_minutes_per_second)

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def status(self) -> dict:
        if not self._replay:
            return {"error": "No data loaded"}
        s = self._replay.status()
        s["session_id"] = self._session_id
        s["speed"] = self._speed
        s["paused"] = self._paused
        return s
