"""RCA API router."""

import logging

from fastapi import APIRouter, Query

from app.rca.root_cause import analyze, impact

logger = logging.getLogger(__name__)
router = APIRouter(tags=["rca"])


@router.get("/root-causes")
def get_root_causes(alerts: str = Query("", description="JSON array of alert dicts")):
    """Run RCA on provided alerts."""
    import json
    alert_list = json.loads(alerts) if alerts else []
    results = analyze(alert_list)
    return {"root_causes": results, "data_source": "synthetic"}


@router.get("/impact/{node_id}")
def get_impact_rca(node_id: str):
    """Get impact analysis for a node."""
    results = impact(node_id)
    return {"node_id": node_id, "impact": results, "data_source": "synthetic"}