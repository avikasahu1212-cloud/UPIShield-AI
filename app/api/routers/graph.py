"""Graph API router."""

import logging

from fastapi import APIRouter, HTTPException

from app.cascade.engine import NodeNotFoundError, simulate_cascade
from app.config import DEFAULT_CASCADE_TRIALS, DEFAULT_HORIZONS_MIN
from app.graph.topology import build_graph, dependants, get_node_info, topology_to_dict

logger = logging.getLogger(__name__)
router = APIRouter(tags=["graph"])


@router.get("/topology")
def get_topology():
    """Get the dependency topology (nodes + edges)."""
    G = build_graph()
    return topology_to_dict(G)


@router.post("/simulate-cascade")
def run_cascade(request: dict):
    """Run Monte Carlo cascade simulation.

    Request body: {failed_node, trials, seed, horizons_min}
    """
    failed_node = request.get("failed_node")
    if not failed_node:
        raise HTTPException(status_code=400, detail="failed_node is required")

    trials = request.get("trials", DEFAULT_CASCADE_TRIALS)
    trials = max(100, min(50000, int(trials)))
    seed = request.get("seed")
    horizons = request.get("horizons_min", DEFAULT_HORIZONS_MIN)

    try:
        result = simulate_cascade(failed_node, trials=trials, seed=seed, horizons_min=horizons)
        return result.to_dict()
    except NodeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/impact/{node_id}")
def get_impact(node_id: str):
    """Get nodes that depend on *node_id* (light S5 impact analysis)."""
    G = build_graph()
    info = get_node_info(G, node_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")
    deps = dependants(G, node_id)
    return {
        "node": info,
        "dependants": [{"node_id": n, "hop_distance": d} for n, d in deps],
    }