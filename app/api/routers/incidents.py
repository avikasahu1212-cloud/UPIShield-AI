"""Incidents and alerts API router."""

import logging
from typing import Any

from fastapi import APIRouter, Query

from app.cascade.engine import simulate_cascade
from app.config import DATA_DIR
from app.data.loader import DataLoader
from app.rca.root_cause import analyze

logger = logging.getLogger(__name__)
router = APIRouter(tags=["incidents"])

_incidents_cache: list[dict[str, Any]] | None = None
_alerts_cache: list[dict[str, Any]] | None = None


def _load_incidents():
    global _incidents_cache
    if _incidents_cache is None:
        df = DataLoader.load()
        # Load from incidents.csv
        import pandas as pd
        inc_df = pd.read_csv(DATA_DIR / "incidents.csv")
        _incidents_cache = inc_df.to_dict("records")
    return _incidents_cache


@router.get("/alerts")
def get_alerts(status: str = Query("all", regex="^(active|all)$")):
    """Get alerts. In a full implementation, these come from the AlertManager."""
    # For now, return empty (alerts are managed by the replay/detection pipeline)
    return {"alerts": [], "data_source": "synthetic", "status": status}


@router.get("/incidents")
def get_incidents():
    """Get all incidents from incidents.csv."""
    return {"incidents": _load_incidents(), "data_source": "synthetic"}


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: str, include_forecast: bool = Query(False)):
    """Get a specific incident, optionally with cascade forecast."""
    incidents = _load_incidents()
    incident = next((i for i in incidents if i.get("incident_id") == incident_id), None)
    if incident is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    result = dict(incident)

    if include_forecast:
        root = incident.get("root_node", "")
        if root and root != "none":
            try:
                forecast = simulate_cascade(root, trials=2000, seed=42)
                result["cascade_forecast"] = forecast.to_dict()
            except Exception as e:
                result["cascade_forecast"] = {"error": str(e)}

    return {"incident": result, "data_source": "synthetic"}