"""API smoke tests using FastAPI TestClient."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

CLIENT = TestClient(app)
DATA_DIR = Path(__file__).parent.parent / "data"


@pytest.fixture(scope="session", autouse=True)
def generate_data():
    """Generate test data once."""
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent.parent / "scripts" / "generate_data.py"),
         "--seed", "42", "--out", str(DATA_DIR)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Generator failed: {result.stderr}"


class TestAPI:
    """Smoke tests for the API."""

    def test_root(self):
        resp = CLIENT.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data
        assert data["data_source"] == "synthetic" or "UPIShield" in data["message"]

    def test_health(self):
        resp = CLIENT.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["data_source"] == "synthetic"

    def test_topology(self):
        resp = CLIENT.get("/api/graph/topology")
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) == 12
        assert len(data["edges"]) == 19

    def test_simulate_cascade(self):
        resp = CLIENT.post("/api/graph/simulate-cascade",
                           json={"failed_node": "bank_a", "trials": 100, "seed": 42})
        assert resp.status_code == 200
        data = resp.json()
        assert data["failed_node"] == "bank_a"
        assert data["trials"] == 100
        assert "cascade_probabilities" in data
        assert "assumptions" in data

    def test_simulate_cascade_unknown_node(self):
        resp = CLIENT.post("/api/graph/simulate-cascade",
                           json={"failed_node": "nonexistent", "trials": 100})
        assert resp.status_code == 404

    def test_simulate_cascade_old_format(self):
        """Backwards compat: old format {failed_node, trials} should work."""
        resp = CLIENT.post("/api/graph/simulate-cascade",
                           json={"failed_node": "cloud_region_1", "trials": 500})
        assert resp.status_code == 200

    def test_impact(self):
        resp = CLIENT.get("/api/graph/impact/cloud_region_1")
        assert resp.status_code == 200
        data = resp.json()
        assert "dependants" in data
        dep_ids = [d["node_id"] for d in data["dependants"]]
        assert "bank_b" in dep_ids

    def test_impact_unknown_node(self):
        resp = CLIENT.get("/api/graph/impact/nonexistent")
        assert resp.status_code == 404

    def test_data_metrics(self):
        resp = CLIENT.get("/api/data/metrics?node_id=bank_a&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert "metrics" in data
        assert len(data["metrics"]) <= 10
        assert data["data_source"] == "synthetic"

    def test_replay_reset(self):
        resp = CLIENT.post("/api/replay/reset", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "clock" in data
        assert data["data_source"] == "synthetic"

    def test_replay_status(self):
        # Reset first
        CLIENT.post("/api/replay/reset", json={})
        resp = CLIENT.get("/api/replay/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "clock_minute" in data

    def test_replay_advance(self):
        CLIENT.post("/api/replay/reset", json={})
        resp = CLIENT.post("/api/replay/advance", json={"minutes": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert "new_alerts" in data
        assert "node_health" in data
        assert data["data_source"] == "synthetic"

    def test_incidents(self):
        resp = CLIENT.get("/api/incidents")
        assert resp.status_code == 200
        data = resp.json()
        assert "incidents" in data
        assert data["data_source"] == "synthetic"

    def test_incidents_by_id(self):
        resp = CLIENT.get("/api/incidents/INC-0001")
        assert resp.status_code == 200
        data = resp.json()
        assert "incident" in data

    def test_incidents_with_forecast(self):
        resp = CLIENT.get("/api/incidents/INC-0001?include_forecast=true")
        assert resp.status_code == 200
        data = resp.json()
        assert "incident" in data
        # Forecast may or may not be present depending on root node
        if data["incident"].get("root_node") and data["incident"]["root_node"] != "none":
            assert "cascade_forecast" in data

    def test_alerts(self):
        resp = CLIENT.get("/api/alerts?status=all")
        assert resp.status_code == 200
        data = resp.json()
        assert "alerts" in data
        assert data["data_source"] == "synthetic"

    def test_rca_root_causes(self):
        alerts = json.dumps([
            {"node_id": "bank_a", "first_anomaly_time": "2026-11-06T05:00:00+05:30",
             "peak_score": 0.95, "status": "active"},
            {"node_id": "psp_app_1", "first_anomaly_time": "2026-11-06T05:05:00+05:30",
             "peak_score": 0.8, "status": "active"},
        ])
        resp = CLIENT.get(f"/api/rca/root-causes?alerts={alerts}")
        assert resp.status_code == 200
        data = resp.json()
        assert "root_causes" in data

    def test_rca_impact(self):
        resp = CLIENT.get("/api/rca/impact/cloud_region_1")
        assert resp.status_code == 200
        data = resp.json()
        assert "impact" in data