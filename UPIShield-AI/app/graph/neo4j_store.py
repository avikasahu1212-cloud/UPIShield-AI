"""Neo4j graph store implementation.

Provides Neo4j-backed graph storage with parameterized Cypher queries.
Falls back to NetworkXGraphStore when Neo4j is unavailable.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import networkx as nx

from app.config import NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
from app.graph.store import GraphStore

logger = logging.getLogger(__name__)

try:
    from neo4j import GraphDatabase
    _NEO4J_AVAILABLE = True
except ImportError:
    _NEO4J_AVAILABLE = False
    logger.warning("neo4j driver not available; Neo4jGraphStore will fall back to NetworkX")


class Neo4jGraphStore(GraphStore):
    """Neo4j-backed graph store."""

    def __init__(self, uri: str | None = None, username: str | None = None,
                 password: str | None = None):
        if not _NEO4J_AVAILABLE:
            from app.graph.store import NetworkXGraphStore
            self._delegate = NetworkXGraphStore()
            self._connected = False
            return

        self._uri = uri or NEO4J_URI
        self._username = username or NEO4J_USERNAME
        self._password = password or NEO4J_PASSWORD
        self._driver = None
        self._connected = False
        self._connect()

    def _connect(self) -> None:
        """Connect to Neo4j."""
        try:
            self._driver = GraphDatabase.driver(
                self._uri, auth=(self._username, self._password),
                max_connection_pool_size=5,
            )
            with self._driver.session() as session:
                session.run("RETURN 1")
            self._connected = True
            logger.info("Connected to Neo4j at %s", self._uri)
        except Exception as e:
            self._connected = False
            logger.warning("Neo4j connection failed: %s; falling back", e)
            from app.graph.store import NetworkXGraphStore
            self._delegate = NetworkXGraphStore()

    def seed(self, topology: dict) -> None:
        """Seed the graph with topology data (idempotent via MERGE)."""
        if not self._connected:
            self._delegate.seed(topology)
            return
        self._ensure_connected()
        with self._driver.session() as session:
            session.run("CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE")
            topo_json = str(topology)
            checksum = hashlib.sha256(topo_json.encode()).hexdigest()[:16]
            existing = session.run("MATCH (m:Meta) RETURN m.checksum AS checksum")
            record = existing.single()
            if record and record["checksum"] == checksum:
                logger.info("Topology checksum unchanged; skipping seed")
                return
            session.run("MATCH (n) DETACH DELETE n")
            for node in topology.get("nodes", []):
                session.execute_write(self._merge_node, node)
            for edge in topology.get("edges", []):
                session.execute_write(self._merge_edge, edge)
            session.execute_write(self._update_checksum, checksum)
        logger.info("Seeded Neo4j: %d nodes, %d edges",
                     len(topology.get("nodes", [])), len(topology.get("edges", [])))

    @staticmethod
    def _merge_node(tx, node: dict) -> None:
        props = {
            "display_name": node.get("display_name", node["id"]),
            "type": node.get("type", "unknown"),
            "region": node.get("region", ""),
            "criticality": node.get("criticality", 1),
            "health_state": "normal", "last_score": 0.0, "last_update": None,
        }
        tx.run("MERGE (n:Entity {id: $id}) SET n += $props", id=node["id"], props=props)

    @staticmethod
    def _merge_edge(tx, edge: dict) -> None:
        props = {
            "relation": edge.get("relation", "depends_on"),
            "dependency_type": edge.get("dependency_type", "soft"),
            "propagation_prob": edge.get("propagation_prob", 0.5),
            "delay_min_mean": edge.get("delay_min_mean", 1.0),
            "retry_sensitive": edge.get("retry_sensitive", False),
            "basis": edge.get("basis", ""),
        }
        tx.run(
            "MERGE (source:Entity {id: $source}) MERGE (target:Entity {id: $target}) "
            "MERGE (source)-[r:DEPENDS_ON]->(target) SET r += $props",
            source=edge["source"], target=edge["target"], props=props,
        )

    @staticmethod
    def _update_checksum(tx, checksum: str) -> None:
        tx.run("MERGE (m:Meta) SET m.checksum = $checksum", checksum=checksum)

    def get_topology(self) -> dict:
        if not self._connected:
            return self._delegate.get_topology()
        self._ensure_connected()
        with self._driver.session() as session:
            nodes = []
            for record in session.run("MATCH (n:Entity) RETURN n ORDER BY n.id"):
                n = dict(record["n"])
                nodes.append({"id": n.pop("id"), **n})
            edges = []
            for record in session.run(
                "MATCH (a:Entity)-[r:DEPENDS_ON]->(b:Entity) RETURN a.id AS source, b.id AS target, r"
            ):
                edge = {"source": record["source"], "target": record["target"]}
                edge.update(dict(record["r"]))
                edges.append(edge)
        return {"nodes": nodes, "edges": edges}

    def dependants(self, node_id: str, max_depth: int = 8) -> list[tuple[str, int]]:
        if not self._connected:
            return self._delegate.dependants(node_id, max_depth)
        self._ensure_connected()
        with self._driver.session() as session:
            result = session.run(
                "MATCH (start:Entity {id: $nid}) "
                "MATCH path = shortestPath((start)<-[:DEPENDS_ON*1..$md]-(dependant)) "
                "RETURN dependant.id AS node_id, length(path) AS hops ORDER BY hops",
                nid=node_id, md=max_depth,
            )
            return [(r["node_id"], r["hops"]) for r in result]

    def dependencies(self, node_id: str, max_depth: int = 8) -> list[tuple[str, int]]:
        if not self._connected:
            return self._delegate.dependencies(node_id, max_depth)
        self._ensure_connected()
        with self._driver.session() as session:
            result = session.run(
                "MATCH (start:Entity {id: $nid}) "
                "MATCH path = shortestPath((start)-[:DEPENDS_ON*1..$md]-(dep)) "
                "RETURN dep.id AS node_id, length(path) AS hops ORDER BY hops",
                nid=node_id, md=max_depth,
            )
            return [(r["node_id"], r["hops"]) for r in result]

    def update_health(self, rows: list[dict]) -> None:
        if not self._connected:
            self._delegate.update_health(rows)
            return
        self._ensure_connected()
        if not rows:
            return
        with self._driver.session() as session:
            session.execute_write(self._batch_update, rows)

    @staticmethod
    def _batch_update(tx, rows: list[dict]) -> None:
        tx.run(
            "UNWIND $rows AS row MERGE (n:Entity {id: row.node_id}) "
            "SET n.health_state = row.health_state, n.last_score = row.last_score, "
            "    n.last_update = row.last_update",
            rows=rows,
        )

    def load_subgraph(self, root_id: str) -> nx.DiGraph:
        if not self._connected:
            return self._delegate.load_subgraph(root_id)
        self._ensure_connected()
        G = nx.DiGraph()
        with self._driver.session() as session:
            for record in session.run("MATCH (n:Entity) RETURN n"):
                n = dict(record["n"])
                G.add_node(n.pop("id"), **n)
            for record in session.run(
                "MATCH (a:Entity)-[r:DEPENDS_ON]->(b:Entity) "
                "RETURN a.id AS source, b.id AS target, r"
            ):
                G.add_edge(record["source"], record["target"], **dict(record["r"]))
        return G

    def close(self) -> None:
        if self._driver and self._connected:
            self._driver.close()
            self._connected = False
