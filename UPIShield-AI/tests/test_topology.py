"""Tests for topology loading and validation."""

import pytest

from app.graph.topology import (
    build_graph,
    dependants,
    dependencies,
    get_node_info,
    load_topology,
    topology_to_dict,
)


class TestTopology:
    """Test topology loading and graph operations."""

    def test_load_topology(self):
        topo = load_topology()
        assert len(topo.nodes) == 12
        assert len(topo.edges) == 19

    def test_build_graph(self):
        G = build_graph()
        assert len(G.nodes()) == 12
        assert len(G.edges()) == 19

    def test_node_info(self):
        G = build_graph()
        info = get_node_info(G, "bank_a")
        assert info is not None
        assert info["id"] == "bank_a"
        assert info["type"] == "bank"

    def test_unknown_node(self):
        G = build_graph()
        assert get_node_info(G, "nonexistent") is None

    def test_dependants(self):
        G = build_graph()
        # cloud_region_1 is depended on by bank_b, bank_c, payment_gateway_1
        deps = dependants(G, "cloud_region_1")
        dep_ids = [d[0] for d in deps]
        assert "bank_b" in dep_ids
        assert "bank_c" in dep_ids
        assert "payment_gateway_1" in dep_ids

    def test_dependencies(self):
        G = build_graph()
        # psp_app_1 depends on sponsor_bank_1 and status_check_api
        deps = dependencies(G, "psp_app_1")
        dep_ids = [d[0] for d in deps]
        assert "sponsor_bank_1" in dep_ids
        assert "status_check_api" in dep_ids

    def test_topology_to_dict(self):
        G = build_graph()
        d = topology_to_dict(G)
        assert "nodes" in d
        assert "edges" in d
        assert len(d["nodes"]) == 12
        assert len(d["edges"]) == 19

    def test_edge_fields(self):
        """Edges should have all required fields."""
        G = build_graph()
        for u, v, data in G.edges(data=True):
            assert "propagation_prob" in data
            assert "delay_min_mean" in data
            assert "dependency_type" in data
            assert 0 <= data["propagation_prob"] <= 1

    def test_topology_preserves_old_keys(self):
        """API response should include 'nodes' and 'edges' keys for backwards compat."""
        G = build_graph()
        d = topology_to_dict(G)
        assert isinstance(d["nodes"], list)
        assert isinstance(d["edges"], list)
        # Each edge should have "source" and "target"
        for edge in d["edges"]:
            assert "source" in edge
            assert "target" in edge
            assert "probability" in edge or "propagation_prob" in edge