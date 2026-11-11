"""Data metrics API router."""

import logging
from typing import Any

from fastapi import APIRouter, Query

from app.data.loader import DataLoader

logger = logging.getLogger(__name__)
router = APIRouter(tags=["data"])


@router.get("/metrics")
def get_metrics(
    node_id: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    limit: int = Query(1000, ge=1, le=10000),
):
    """Get telemetry metrics with optional filtering."""
    df = DataLoader.load()

    if node_id:
        df = df[df["node_id"] == node_id]
    if from_ts:
        df = df[df["timestamp"] >= from_ts]
    if to_ts:
        df = df[df["timestamp"] <= to_ts]

    df = df.head(limit)
    return {
        "metrics": df.to_dict("records"),
        "count": len(df),
        "data_source": "synthetic",
    }