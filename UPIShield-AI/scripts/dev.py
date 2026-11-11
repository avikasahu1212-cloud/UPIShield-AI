"""UPIShield dev CLI - cross-platform (Windows, macOS, Linux).

Usage:
    python scripts/dev.py up            Start Kafka + Neo4j containers
    python scripts/dev.py status        Show health of all services
    python scripts/dev.py seed          Load topology into Neo4j
    python scripts/dev.py reset         Clear runtime state
    python scripts/dev.py down          Stop containers
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INFRA_DIR = BASE_DIR / "infra"
COMPOSE_FILE = INFRA_DIR / "docker-compose.yml"
ENV_FILE = INFRA_DIR / ".env.example"


def _run(cmd, **kwargs):
    """Run a shell command and return its result."""
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kwargs)


def _wait_for(url, name, timeout=60):
    """Block until HTTP URL responds or timeout."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = urllib.request.urlopen(url, timeout=3)
            if resp.status < 500:
                print(f"  {name} is healthy.")
                return True
        except Exception:
            pass
        time.sleep(2)
    print(f"  ERROR: {name} did not become healthy within {timeout}s.")
    return False


def cmd_up(args):
    """Start infrastructure containers."""
    print("Starting UPIShield infrastructure...")
    cmd = f'docker compose -f "{COMPOSE_FILE}" up -d'
    if args.monitoring:
        cmd += " --profile monitoring"
    result = _run(cmd, cwd=str(INFRA_DIR))
    if result.returncode != 0:
        print(f"ERROR: docker compose up failed:\n{result.stderr}")
        sys.exit(1)
    print("Containers starting. Waiting for health checks...")
    if not _wait_for("http://localhost:7474", "Neo4j"):
        print("WARNING: Neo4j health check timed out.")
    print("Infrastructure is up.")


def cmd_down(args):
    """Stop infrastructure containers."""
    print("Stopping UPIShield infrastructure...")
    cmd = f'docker compose -f "{COMPOSE_FILE}" down'
    if args.monitoring:
        cmd += " --profile monitoring"
    result = _run(cmd, cwd=str(INFRA_DIR))
    if result.returncode != 0:
        print(f"ERROR: docker compose down failed:\n{result.stderr}")
    else:
        print("Infrastructure stopped.")


def cmd_status(args):
    """Show health of all services."""
    print("Checking service health...")
    print()
    for name, container in [("Kafka", "upishield-kafka"), ("Neo4j", "upishield-neo4j"),
                             ("Prometheus", "upishield-prometheus"), ("Grafana", "upishield-grafana")]:
        result = _run(f'docker inspect --format="{{{{.State.Health.Status}}}}" {container} 2>/dev/null')
        if result.returncode == 0:
            print(f"  {name}: {result.stdout.strip()}")
        else:
            print(f"  {name}: not running")


def cmd_seed(args):
    """Load topology.json into Neo4j via app API."""
    import urllib.request
    topo_path = BASE_DIR / "data" / "topology.json"
    if not topo_path.exists():
        print("ERROR: data/topology.json not found. Run generate_data.py first.")
        sys.exit(1)
    with open(topo_path) as f:
        topo = json.load(f)
    url = "http://localhost:8000/api/graph/seed"
    data = json.dumps(topo).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        print(f"Seeded Neo4j: {resp.read().decode()}")
    except Exception as e:
        print(f"ERROR seeding Neo4j: {e}")
        print("  Make sure the app is running (uvicorn app.main:app).")


def cmd_reset(args):
    """Clear runtime state."""
    runtime_db = BASE_DIR / "data" / "runtime.db"
    artifacts_dir = BASE_DIR / "artifacts"
    reports_dir = BASE_DIR / "reports"
    for path in [runtime_db,
                 artifacts_dir / "detector_config.json"]:
        if path.exists():
            path.unlink()
            print(f"  Removed: {path}")
    if runtime_db.exists():
        import sqlite3
        conn = sqlite3.connect(str(runtime_db))
        for tbl in ["node_metrics", "alerts", "incidents"]:
            conn.execute(f"DELETE FROM {tbl}")
        conn.commit()
        conn.close()
        print(f"  Cleared tables in {runtime_db}")
    print("Runtime state cleared.")


def main():
    parser = argparse.ArgumentParser(description="UPIShield dev CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("up", help="Start Kafka + Neo4j containers")
    p_down = sub.add_parser("down", help="Stop containers")
    p_down.add_argument("--monitoring", action="store_true", help="Also stop monitoring profile")
    sub.add_parser("status", help="Show health of all services")
    sub.add_parser("seed", help="Load topology into Neo4j")
    sub.add_parser("reset", help="Clear runtime state")
    args = parser.parse_args()
    cmd_map = {"up": cmd_up, "down": cmd_down, "status": cmd_status, "seed": cmd_seed, "reset": cmd_reset}
    cmd_map[args.command](args)


if __name__ == "__main__":
    main()