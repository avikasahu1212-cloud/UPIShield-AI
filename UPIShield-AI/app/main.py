"""UPIShield - AI-powered resilience platform for UPI payments.

Detect, Predict, Recover. Sits BESIDE the payment path.

Usage:
    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    data_router,
    graph_router,
    incidents_router,
    replay_router,
    rca_router,
)
from app.config import INGEST_MODE, NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
from app.graph.neo4j_store import Neo4jGraphStore
from app.graph.store import NetworkXGraphStore

logger = logging.getLogger(__name__)

# Global graph store
_graph_store: Neo4jGraphStore | NetworkXGraphStore | None = None


def _get_graph_store():
    """Get or create the graph store."""
    global _graph_store
    if _graph_store is None:
        if INGEST_MODE == "kafka":
            try:
                _graph_store = Neo4jGraphStore(
                    uri=NEO4J_URI, username=NEO4J_USERNAME, password=NEO4J_PASSWORD
                )
            except Exception as e:
                logger.warning("Neo4j unavailable, using NetworkX fallback: %s", e)
                _graph_store = NetworkXGraphStore()
        else:
            _graph_store = NetworkXGraphStore()
    return _graph_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown hooks."""
    global _graph_store
    logger.info("UPIShield starting (ingest_mode=%s)", INGEST_MODE)

    # Initialize graph store
    store = _get_graph_store()

    # Seed from topology if empty
    from app.config import TOPOLOGY_PATH
    import json
    if TOPOLOGY_PATH.exists():
        with open(TOPOLOGY_PATH) as f:
            topology = json.load(f)
        try:
            store.seed(topology)
        except Exception as e:
            logger.warning("Failed to seed graph store: %s", e)

    # Start worker threads if in Kafka mode
    if INGEST_MODE == "kafka":
        try:
            from app.workers.runner import run_workers
            import threading
            _stop_event = threading.Event()
            worker_thread = threading.Thread(target=run_workers, args=(_stop_event,), daemon=True)
            worker_thread.start()
            logger.info("Worker thread started")
        except Exception as e:
            logger.warning("Failed to start workers: %s", e)

    yield

    # Shutdown
    if hasattr(store, "close"):
        store.close()
    logger.info("UPIShield shutting down")


app = FastAPI(
    title="UPIShield",
    description="AI-powered resilience platform for predictive outage prevention in UPI payments",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for localhost:3000 (Grafana) and :5173 (React dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(graph_router, prefix="/api/graph")
app.include_router(replay_router, prefix="/api/replay")
app.include_router(incidents_router, prefix="/api/incidents")
app.include_router(data_router, prefix="/api/data")
app.include_router(rca_router, prefix="/api/rca")

# Alerts router (top-level /api/alerts)
alerts_router = APIRouter(tags=["alerts"])


@alerts_router.get("/alerts")
def get_alerts(status: str = Query("all", pattern="^(active|all)$")):
    """Get alerts. In a full implementation, these come from the AlertManager."""
    return {"alerts": [], "data_source": "synthetic", "status": status}


app.include_router(alerts_router, prefix="/api")

# Prometheus metrics endpoint
@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus exposition format metrics."""
    from app.monitoring.prom import expose_metrics
    return Response(content=expose_metrics(), media_type="text/plain")


@app.get("/")
async def root():
    return {
        "message": "UPIShield API",
        "version": "0.1.0",
        "ingest_mode": INGEST_MODE,
        "data_source": "synthetic",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    store = _get_graph_store()
    neo4j_status = "not_configured"
    if INGEST_MODE == "kafka":
        if hasattr(store, "_connected") and store._connected:
            neo4j_status = "connected"
        elif hasattr(store, "_connected"):
            neo4j_status = "disconnected"
        else:
            neo4j_status = "fallback"

    return {
        "status": "ok",
        "ingest_mode": INGEST_MODE,
        "data_source": "synthetic",
        "kafka": "configured" if INGEST_MODE == "kafka" else "not_active",
        "neo4j": neo4j_status,
    }