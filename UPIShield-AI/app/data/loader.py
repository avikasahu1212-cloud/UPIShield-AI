"""Data loading and replay source."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Protocol

import pandas as pd

from app.config import DATA_DIR

logger = logging.getLogger(__name__)


class EventSource(Protocol):
    """Protocol for event ingestion sources."""

    def next_batch(self, minutes: int) -> pd.DataFrame: ...
    def reset(self, start: str | None = None) -> None: ...


class DataLoader:
    """Load and validate telemetry.csv."""

    REQUIRED_COLUMNS = [
        "timestamp", "node_id", "requests", "success_rate",
        "timeout_ratio", "p95_latency_ms", "retry_ratio", "pending_txns",
    ]

    @classmethod
    def load(cls, path: str | None = None) -> pd.DataFrame:
        p = path or str(DATA_DIR / "telemetry.csv")
        df = pd.read_csv(p)
        cls._validate(df)
        logger.info("Loaded telemetry: %d rows, %d columns", len(df), len(df.columns))
        return df

    @staticmethod
    def _validate(df: pd.DataFrame) -> None:
        for col in DataLoader.REQUIRED_COLUMNS:
            assert col in df.columns, f"Missing column: {col}"
        assert df.isnull().sum().sum() == 0, "DataFrame contains NaNs"
        assert (df["timeout_ratio"] >= 0).all()
        assert (df["success_rate"] >= 0).all()
        assert (df["success_rate"] <= 1).all()
        # Invariant: timeout_ratio <= 1 - success_rate
        violations = df[df["timeout_ratio"] > 1.0 - df["success_rate"] + 1e-9]
        assert violations.empty, f"Invariant violated in {len(violations)} rows"


class ReplaySource:
    """ReplaySource over the telemetry DataFrame with a simulated clock."""

    def __init__(self, df: pd.DataFrame):
        self.df = df.sort_values(["timestamp", "node_id"]).reset_index(drop=True)
        self._clock = 0  # current minute offset
        self._all_timestamps = sorted(self.df["timestamp"].unique())

    def reset(self, start: str | None = None) -> None:
        """Reset clock. If start is given, find the closest timestamp >= start."""
        if start is None:
            self._clock = 0
        else:
            idx = self._find_closest(start)
            self._clock = idx
        logger.info("ReplaySource reset to minute %d", self._clock)

    def advance(self, minutes: int) -> pd.DataFrame:
        """Advance the simulated clock by *minutes* and return the new data."""
        old_clock = self._clock
        self._clock = min(self._clock + minutes, len(self._all_timestamps) - 1)
        new_timestamps = self._all_timestamps[old_clock:self._clock + 1]
        if not new_timestamps:
            return pd.DataFrame()
        return self.df[self.df["timestamp"].isin(new_timestamps)].copy()

    def window(self, node_id: str, minutes: int) -> pd.DataFrame:
        """Return the last *minutes* rows for *node_id* from the current clock."""
        if self._clock < 0 or self._clock >= len(self._all_timestamps):
            return pd.DataFrame()
        end_ts = self._all_timestamps[self._clock]
        start_idx = max(0, self._clock - minutes)
        start_ts = self._all_timestamps[start_idx]
        return self.df[
            (self.df["node_id"] == node_id)
            & (self.df["timestamp"] >= start_ts)
            & (self.df["timestamp"] <= end_ts)
        ]

    def status(self) -> dict:
        return {
            "clock_minute": self._clock,
            "total_minutes": len(self._all_timestamps),
            "current_timestamp": (
                self._all_timestamps[self._clock] if self._clock < len(self._all_timestamps) else None
            ),
        }

    def _find_closest(self, timestamp: str) -> int:
        """Find the index of the closest timestamp >= the given one."""
        for i, ts in enumerate(self._all_timestamps):
            if ts >= timestamp:
                return i
        return len(self._all_timestamps) - 1