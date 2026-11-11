"""Topology loading, validation, and graph helpers.

Loads topology.json, validates with pydantic, builds a networkx.DiGraph
where edge A->B means A depends on B.  A failure at B can propagate to A.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import networkx as nx
from pydantic import BaseModel, Field, field_validator

from app.config import TOPOLOGY_PATH

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models for validation
# ---------------------------------------------------------------------------

class NodeModel(BaseModel):
    """A node in the UPI dependency graph."""

    id: str
    display_name: str
    type: str
    region: str
    criticality: int = Field(ge=1, le=5)

    @field_validator("id")
    @classmethod
    def id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("id must not be empty")
        return v.strip()


class EdgeModel(BaseModel):
    """An edge in the UPI dependency graph.

    source depends_on target.
    """

    source: str
    target: str
    relation: str = "depends_on"
    dependency_type: str = Field(pattern=r"^(hard|soft)$")
    propagation_prob: float = Field(ge=0.0, le=1.0)
    delay_min_mean: float = Field(gt=0.0)
    retry_sensitive: bool = False
    basis: str = ""


class TopologyModel(BaseModel):
    """Validated topology container."""

    nodes: list[NodeModel]
    edges: list[EdgeModel]

    @field_validator("nodes")
    @classmethod
    def unique_ids(cls, v: list[NodeModel]) -> list[NodeModel]:
        ids = [n.id for n in v]
        if len(ids) != len(set(ids)):
            raise ValueError("node ids must be unique")
        return v

    def validate_references(self, edges: list[EdgeModel], node_ids: set[str]) -> None:
        """Raise if any edge references a non-existent node."""
        for e in edges:
            if e.source not in node_ids:
                raise ValueError(f"edge references unknown source node: {e.source}")
            if e.target not in node_ids:
                raise ValueError(f"edge references unknown target node: {e.target}")


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def load_topology(path: Path | str | None = None) -> TopologyModel:
    """Load and validate topology.json.

    Returns a TopologyModel (pydantic) with validated nodes and edges.
    """
    p = Path(path) if path else TOPOLOGY_PATH
    if not p.exists():
        raise FileNotFoundError(f"topology file not found: {p}")
    raw: dict[str, Any] = {}
    with open(p) as f:
        raw = json.load(f)
    topo = TopologyModel(**raw)
    topo.validate_references(topo.edges, {n.id for n in topo.nodes})
    logger.info("Loaded topology: %d nodes, %d edges", len(topo.nodes), len(topo.edges))
    return topo


def build_graph(topo: TopologyModel | None = None) -> nx.DiGraph:
    """Build a networkx.DiGraph from a TopologyModel.

    Edge direction: source -> target means "source depends on target".
    A failure at target can propagate to source.
    """
    if topo is None:
        topo = load_topology()
    G = nx.DiGraph()
    for node in topo.nodes:
        G.add_node(
            node.id,
            display_name=node.display_name,
            type=node.type,
            region=node.region,
            criticality=node.criticality,
        )
    for edge in topo.edges:
        G.add_edge(
            edge.source,
            edge.target,
            relation=edge.relation,
            dependency_type=edge.dependency_type,
            propagation_prob=edge.propagation_prob,
            delay_min_mean=edge.delay_min_mean,
            retry_sensitive=edge.retry_sensitive,
            basis=edge.basis,
        )
    return G


def dependants(G: nx.DiGraph, node: str, max_depth: int = 8) -> list[tuple[str, int]]:
    """Return nodes that transitively depend on *node* (ancestors).

    Returns list of (node_id, hop_distance) sorted by hop distance.
    These are the nodes that could be affected if *node* fails.
    """
    if node not in G:
        return []
    result: dict[str, int] = {}
    queue: list[tuple[str, int]] = [(node, 0)]
    visited = {node}
    while queue:
        current, depth = queue.pop(0)
        for pred in G.predecessors(current):
            if pred not in visited and depth + 1 <= max_depth:
                visited.add(pred)
                result[pred] = depth + 1
                queue.append((pred, depth + 1))
    return sorted(result.items(), key=lambda x: x[1])


def dependencies(G: nx.DiGraph, node: str, max_depth: int = 8) -> list[tuple[str, int]]:
    """Return nodes that *node* transitively depends on (descendants).

    Returns list of (node_id, hop_distance) sorted by hop distance.
    These are the nodes whose failure could affect *node*.
    """
    if node not in G:
        return []
    result: dict[str, int] = {}
    queue: list[tuple[str, int]] = [(node, 0)]
    visited = {node}
    while queue:
        current, depth = queue.pop(0)
        for succ in G.successors(current):
            if succ not in visited and depth + 1 <= max_depth:
                visited.add(succ)
                result[succ] = depth + 1
                queue.append((succ, depth + 1))
    return sorted(result.items(), key=lambda x: x[1])


def get_node_info(G: nx.DiGraph, node: str) -> dict[str, Any] | None:
    """Return node attributes or None if not found."""
    if node not in G:
        return None
    data = dict(G.nodes[node])
    data["id"] = node
    return data


def get_edge_info(G: nx.DiGraph, source: str, target: str) -> dict[str, Any] | None:
    """Return edge attributes or None if not found."""
    if not G.has_edge(source, target):
        return None
    data = dict(G.edges[source, target])
    data["source"] = source
    data["target"] = target
    return data


def topology_to_dict(G: nx.DiGraph) -> dict[str, Any]:
    """Serialise graph to the API response format (nodes + edges)."""
    nodes = []
    for nid, attrs in G.nodes(data=True):
        entry = {"id": nid}
        entry.update(attrs)
        nodes.append(entry)
    edges = []
    for u, v, attrs in G.edges(data=True):
        entry = {"source": u, "target": v}
        entry.update(attrs)
        edges.append(entry)
    return {"nodes": nodes, "edges": edges}