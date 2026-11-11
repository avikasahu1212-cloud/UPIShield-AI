"""UPIShield - AI-powered resilience platform for UPI payments.

Detect, Predict, Recover. Sits BESIDE the payment path.

Usage:
    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    data_router,
    graph_router,
    incidents_router,
    replay_router,
    rca_router,
)
from app.config import INGEST_MODE

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown hooks."""
    logger.info("UPIShield starting (ingest_mode=%s)", INGEST_MODE)
    # Initialize Kafka producer/consumer here when INGEST_MODE=kafka
    # Initialize Neo4j graph store here
    yield
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


@app.get("/")
async def root():
    return {
        "message": "UPIShield API",
        "version": "0.1.0",
        "ingest_mode": INGEST_MODE,
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "ingest_mode": INGEST_MODE,
        "data_source": "synthetic",
        "kafka": "configured" if INGEST_MODE == "kafka" else "not_active",
        "neo4j": "configured" if INGEST_MODE == "kafka" else "not_active",
    }