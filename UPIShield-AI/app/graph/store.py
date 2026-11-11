"""GraphStore protocol and implementations.

Provides a swappable graph backend: Neo4j (default) or NetworkX (tests/fallback).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import networkx as nx

logger = logging.getLogger(__name__)


class GraphStore(ABC):
    """Protocol for graph storage backends."""

    @abstractmethod
    def seed(self, topology: dict) -> None:
        """Seed the graph with topology data (idempotent)."""
        ...

    @abstractmethod
    def get_topology(self) -> dict:
        """Return the topology as a dict (nodes + edges)."""
        ...

    @abstractmethod
    def dependants(self, node_id: str, max_depth: int = 8) -> list[tuple[str, int]]:
        """Return nodes that transitively depend on *node_id* with hop distance."""
        ...

    @abstractmethod
    def dependencies(self, node_id: str, max_depth: int = 8) -> list[tuple[str, int]]:
        """Return nodes that *node_id* transitively depends on with hop distance."""
        ...

    @abstractmethod
    def update_health(self, rows: list[dict]) -> None:
        """Update health state for multiple nodes in one batch."""
        ...

    @abstractmethod
    def load_subgraph(self, root_id: str) -> nx.DiGraph:
        """Load a subgraph rooted at *root_id* as a networkx DiGraph."""
        ...


class NetworkXGraphStore(GraphStore):
    """NetworkX-based graph store (for tests and file-mode fallback)."""

    def __init__(self):
        self._graph: nx.DiGraph | None = None
        self._health: dict[str, dict] = {}

    def seed(self, topology: dict) -> None:
        """Seed from topology dict."""
        self._graph = nx.DiGraph()
        for node in topology.get("nodes", []):
            self._graph.add_node(
                node["id"],
                display_name=node.get("display_name", node["id"]),
                type=node.get("type", "unknown"),
                region=node.get("region", ""),
                criticality=node.get("criticality", 1),
                health_state="normal",
                last_score=0.0,
                last_update=None,
            )
        for edge in topology.get("edges", []):
            self._graph.add_edge(
                edge["source"],
                edge["target"],
                relation=edge.get("relation", "depends_on"),
                dependency_type=edge.get("dependency_type", "soft"),
                propagation_prob=edge.get("propagation_prob", 0.5),
                delay_min_mean=edge.get("delay_min_mean", 1.0),
                retry_sensitive=edge.get("retry_sensitive", False),
                basis=edge.get("basis", ""),
            )
        logger.info("Seeded NetworkXGraphStore: %d nodes, %d edges",
                     len(self._graph.nodes()), len(self._graph.edges()))

    def get_topology(self) -> dict:
        if self._graph is None:
            return {"nodes": [], "edges": []}
        nodes = []
        for nid, attrs in self._graph.nodes(data=True):
            entry = {"id": nid}
            entry.update(attrs)
            nodes.append(entry)
        edges = []
        for u, v, attrs in self._graph.edges(data=True):
            entry = {"source": u, "target": v}
            entry.update(attrs)
            edges.append(entry)
        return {"nodes": nodes, "edges": edges}

    def dependants(self, node_id: str, max_depth: int = 8) -> list[tuple[str, int]]:
        if self._graph is None or node_id not in self._graph:
            return []
        result: dict[str, int] = {}
        queue: list[tuple[str, int]] = [(node_id, 0)]
        visited = {node_id}
        while queue:
            current, depth = queue.pop(0)
            for pred in self._graph.predecessors(current):
                if pred not in visited and depth + 1 <= max_depth:
                    visited.add(pred)
                    result[pred] = depth + 1
                    queue.append((pred, depth + 1))
        return sorted(result.items(), key=lambda x: x[1])

    def dependencies(self, node_id: str, max_depth: int = 8) -> list[tuple[str, int]]:
        if self._graph is None or node_id not in self._graph:
            return []
        result: dict[str, int] = {}
        queue: list[tuple[str, int]] = [(node_id, 0)]
        visited = {node_id}
        while queue:
            current, depth = queue.pop(0)
            for succ in self._graph.successors(current):
                if succ not in visited and depth + 1 <= max_depth:
                    visited.add(succ)
                    result[succ] = depth + 1
                    queue.append((succ, depth + 1))
        return sorted(result.items(), key=lambda x: x[1])

    def update_health(self, rows: list[dict]) -> None:
        """Update health state for nodes."""
        for row in rows:
            node_id = row.get("node_id")
            if node_id and self._graph and node_id in self._graph:
                self._graph.nodes[node_id]["health_state"] = row.get("health_state", "normal")
                self._graph.nodes[node_id]["last_score"] = row.get("last_score", 0.0)
                self._graph.nodes[node_id]["last_update"] = row.get("last_update")

    def load_subgraph(self, root_id: str) -> nx.DiGraph:
        """Load subgraph rooted at root_id."""
        if self._graph is None or root_id not in self._graph:
            return nx.DiGraph()
        # Load the full graph (subgraph traversal happens in cascade/RCA)
        return self._graph.copy()

    @property
    def graph(self) -> nx.DiGraph | None:
        return self._graph
