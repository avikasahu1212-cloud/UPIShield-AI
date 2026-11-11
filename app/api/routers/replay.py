"""Replay API router."""

import logging

import pandas as pd
from fastapi import APIRouter, HTTPException

from app.config import DATA_DIR
from app.data.loader import DataLoader, ReplaySource
from app.detection.alerting import AlertManager
from app.detection.features import compute_features
from app.detection.model import DetectorModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["replay"])

# Global state for replay
_replay: ReplaySource | None = None
_detector: DetectorModel | None = None
_alert_manager: AlertManager | None = None
_telemetry_df: pd.DataFrame | None = None


def _ensure_initialized():
    """Lazy-initialize replay, detector, and alert manager."""
    global _replay, _detector, _alert_manager, _telemetry_df
    if _replay is None:
        _telemetry_df = DataLoader.load()
        _replay = ReplaySource(_telemetry_df)

    if _detector is None:
        _detector = DetectorModel()
        # Try to load pre-trained models
        _detector.load_all()

    if _alert_manager is None:
        _alert_manager = AlertManager()


@router.post("/reset")
def replay_reset(request: dict | None = None):
    """Reset replay to the start or a specific timestamp."""
    _ensure_initialized()
    start = request.get("start") if request else None
    _replay.reset(start)
    _alert_manager = AlertManager()  # Reset alerts
    return {"status": "reset", "clock": _replay.status(), "data_source": "synthetic"}


@router.post("/advance")
def replay_advance(request: dict):
    """Advance the simulated clock by *minutes* and run detection."""
    _ensure_initialized()
    minutes = min(max(int(request.get("minutes", 1)), 1), 240)

    # Advance clock
    new_data = _replay.advance(minutes)
    if new_data.empty:
        return {
            "clock": _replay.status(),
            "new_alerts": [],
            "resolved_alerts": [],
            "node_health": {},
            "data_source": "synthetic",
        }

    # Compute features and score
    feature_df = compute_features(new_data)
    if "node_id" not in feature_df.columns:
        feature_df["node_id"] = new_data["node_id"]
        feature_df["timestamp"] = new_data["timestamp"]

    # Score if model is loaded
    new_alerts = []
    resolved_alerts = []
    if _detector and _detector.models:
        scored = _detector.score(feature_df)
        if not scored.empty:
            new_alerts_obj = _alert_manager.process_scores(scored)
            new_alerts = [a.to_dict() for a in new_alerts_obj]

    return {
        "clock": _replay.status(),
        "new_alerts": new_alerts,
        "resolved_alerts": resolved_alerts,
        "node_health": _alert_manager.get_node_health() if _alert_manager else {},
        "data_source": "synthetic",
    }


@router.get("/status")
def replay_status():
    """Get replay status."""
    _ensure_initialized()
    return _replay.status()