"""UPIShield configuration and shared assumptions.

All constants live here so the generator, cascade engine, and detector
use identical numbers.  Every assumption is documented in a comment.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ARTIFACTS_DIR = BASE_DIR / "artifacts"
REPORTS_DIR = BASE_DIR / "reports"

# ---------------------------------------------------------------------------
# Ingestion mode: "kafka" (default) or "file" (ReplaySource fallback)
# ---------------------------------------------------------------------------
INGEST_MODE: str = "file"  # Change to "kafka" when Kafka is running
KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
NEO4J_URI: str = "bolt://localhost:7687"
NEO4J_USERNAME: str = "neo4j"
NEO4J_PASSWORD: str = "upishield_dev_password"

# ---------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------
TOPOLOGY_PATH = DATA_DIR / "topology.json"

# ---------------------------------------------------------------------------
# Baseline metrics (synthetic, documented assumptions)
# These represent "normal" operational metrics for each node type.
# Values are approximate ranges observed in typical UPI traffic.
# ---------------------------------------------------------------------------
BASELINES: dict[str, dict] = {
    "psp_app_1": {
        "p95_latency_ms": (120, 220),
        "timeout_ratio": 0.004,
        "success_rate": 0.985,
        "retry_ratio": (0.02, 0.04),
        "pending_pct": 0.002,
    },
    "psp_app_2": {
        "p95_latency_ms": (120, 220),
        "timeout_ratio": 0.004,
        "success_rate": 0.985,
        "retry_ratio": (0.02, 0.04),
        "pending_pct": 0.002,
    },
    "sponsor_bank_1": {
        "p95_latency_ms": (150, 250),
        "timeout_ratio": 0.004,
        "success_rate": 0.985,
        "retry_ratio": (0.02, 0.04),
        "pending_pct": 0.002,
    },
    "payment_gateway_1": {
        "p95_latency_ms": (100, 200),
        "timeout_ratio": 0.004,
        "success_rate": 0.985,
        "retry_ratio": (0.02, 0.04),
        "pending_pct": 0.002,
    },
    "npci_switch": {
        "p95_latency_ms": (80, 180),
        "timeout_ratio": 0.004,
        "success_rate": 0.985,
        "retry_ratio": (0.02, 0.04),
        "pending_pct": 0.002,
    },
    "bank_a": {
        "p95_latency_ms": (150, 220),
        "timeout_ratio": 0.004,
        "success_rate": 0.985,
        "retry_ratio": (0.02, 0.04),
        "pending_pct": 0.002,
    },
    "bank_b": {
        "p95_latency_ms": (160, 230),
        "timeout_ratio": 0.004,
        "success_rate": 0.985,
        "retry_ratio": (0.02, 0.04),
        "pending_pct": 0.002,
    },
    "bank_c": {
        "p95_latency_ms": (170, 240),
        "timeout_ratio": 0.004,
        "success_rate": 0.985,
        "retry_ratio": (0.02, 0.04),
        "pending_pct": 0.002,
    },
    "status_check_api": {
        "p95_latency_ms": (50, 150),
        "timeout_ratio": 0.004,
        "success_rate": 0.985,
        "retry_ratio": (0.02, 0.04),
        "pending_pct": 0.002,
    },
    "merchant_cluster_1": {
        "p95_latency_ms": (80, 180),
        "timeout_ratio": 0.004,
        "success_rate": 0.985,
        "retry_ratio": (0.02, 0.04),
        "pending_pct": 0.002,
    },
    "merchant_cluster_2": {
        "p95_latency_ms": (80, 180),
        "timeout_ratio": 0.004,
        "success_rate": 0.985,
        "retry_ratio": (0.02, 0.04),
        "pending_pct": 0.002,
    },
    "cloud_region_1": {
        "p95_latency_ms": (40, 100),
        "timeout_ratio": 0.004,
        "success_rate": 0.985,
        "retry_ratio": (0.02, 0.04),
        "pending_pct": 0.002,
    },
}

# Volume ratios relative to NPCI switch volume (assumption)
VOLUME_RATIOS: dict[str, float] = {
    "psp_app_1": 1.0,
    "psp_app_2": 1.0,
    "sponsor_bank_1": 1.0,
    "payment_gateway_1": 1.0,
    "npci_switch": 1.0,
    "bank_a": 0.5,
    "bank_b": 0.3,
    "bank_c": 0.2,
    "status_check_api": 0.15,
    "merchant_cluster_1": 0.5,
    "merchant_cluster_2": 0.5,
    "cloud_region_1": 1.0,
}

# Traffic shape parameters (assumptions based on typical UPI patterns)
TRAFFIC_SHAPE = {
    "base_rps": 500,
    "peak_1_hour": 11,
    "peak_2_hour": 19,
    "peak_multiplier": 2.5,
    "trough_multiplier": 0.3,
    "weekend_factor": 0.85,
    "salary_day_bump": 1.1,
}

# Detection parameters
DETECTOR_SEED: int = 42
ISOLATION_FOREST_N_ESTIMATORS: int = 200
ALERT_THRESHOLD_QUANTILE: float = 0.995
ALERT_PERSISTENCE_K: int = 3
ALERT_PERSISTENCE_N: int = 5
ALERT_RESOLVE_M: int = 5

# RCA parameters (weights)
RCA_WEIGHTS = {
    "earliness": 0.35,
    "explained_fraction": 0.35,
    "normalised_peak_score": 0.20,
    "victim_penalty": 0.30,
}
RCA_CORRELATION_WINDOW_MIN: int = 10

# Cascade parameters
DEFAULT_CASCADE_TRIALS: int = 5000
DEFAULT_HORIZONS_MIN: list[int] = [2, 5, 10, 15, 30]

# Data generation
NODE_IDS: list[str] = [
    "psp_app_1", "psp_app_2", "sponsor_bank_1", "payment_gateway_1",
    "npci_switch", "bank_a", "bank_b", "bank_c",
    "status_check_api", "merchant_cluster_1", "merchant_cluster_2",
    "cloud_region_1",
]

LATENCY_BLIP_PROB = 1 / 2000
LATENCY_BLIP_MULTIPLIER = 1.5
LATENCY_LOGSIGMA = 0.08