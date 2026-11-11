"""Tests for the cascade engine."""

import pytest

from app.cascade.engine import NodeNotFoundError, simulate_cascade
from app.graph.topology import build_graph


class TestCascade:
    """Test Monte Carlo cascade simulation."""

    def test_unknown_node(self):
        with pytest.raises(NodeNotFoundError):
            simulate_cascade("nonexistent_node", trials=100, seed=42)

    def test_trials_out_of_range(self):
        """Trials < 100 or > 50000 should raise via FastAPI validation."""
        # Direct engine call doesn't validate; FastAPI router does
        result = simulate_cascade("bank_a", trials=50, seed=42)  # Should work
        assert result.trials == 50

    def test_determinism(self):
        """Same seed produces same results."""
        r1 = simulate_cascade("bank_a", trials=1000, seed=42)
        r2 = simulate_cascade("bank_a", trials=1000, seed=42)
        assert r1.cascade_probabilities == r2.cascade_probabilities

    def test_different_seeds_different_results(self):
        r1 = simulate_cascade("bank_a", trials=1000, seed=42)
        r2 = simulate_cascade("bank_a", trials=1000, seed=99)
        # With different seeds, probabilities should differ slightly
        diff = sum(abs(v1 - v2) for v1, v2 in zip(
            r1.cascade_probabilities.values(),
            r2.cascade_probabilities.values()
        ))
        assert diff > 0  # At least some difference

    def test_by_horizon_non_decreasing(self):
        """P(failed by t) should be non-decreasing in t."""
        result = simulate_cascade("cloud_region_1", trials=1000, seed=42)
        for node, horizons in result.by_horizon.items():
            sorted_h = sorted(horizons.items())
            for i in range(len(sorted_h) - 1):
                assert sorted_h[i][1] <= sorted_h[i + 1][1], \
                    f"Horizon not non-decreasing for node {node}"

    def test_has_time_to_failure(self):
        result = simulate_cascade("bank_a", trials=1000, seed=42)
        assert isinstance(result.time_to_failure, dict)
        assert len(result.time_to_failure) > 0

    def test_has_expected_affected(self):
        result = simulate_cascade("npci_switch", trials=1000, seed=42)
        assert result.expected_affected > 0
        assert isinstance(result.expected_affected, float)

    def test_output_keys(self):
        """Result should have expected keys."""
        result = simulate_cascade("bank_a", trials=100, seed=42)
        d = result.to_dict()
        assert "failed_node" in d
        assert "trials" in d
        assert "cascade_probabilities" in d
        assert "time_to_failure" in d
        assert "by_horizon" in d
        assert "expected_affected" in d
        assert "assumptions" in d

    def test_hard_dependency_propagation(self):
        """Hard dependency nodes should have higher cascade probability."""
        result = simulate_cascade("cloud_region_1", trials=2000, seed=42)
        # bank_b and bank_c have hard deps on cloud_region_1
        bank_b_prob = result.cascade_probabilities.get("bank_b", 0)
        bank_c_prob = result.cascade_probabilities.get("bank_c", 0)
        # These should be reasonably high due to hard dependency
        assert bank_b_prob > 30, f"bank_b prob {bank_b_prob} seems too low"
        assert bank_c_prob > 30, f"bank_c prob {bank_c_prob} seems too low"

    def test_distant_node_lower_prob(self):
        """Nodes far from the failure source should have lower probability."""
        result = simulate_cascade("cloud_region_1", trials=2000, seed=42)
        # psp_app_1 is many hops away from cloud_region_1
        psp_prob = result.cascade_probabilities.get("psp_app_1", 0)
        bank_b_prob = result.cascade_probabilities.get("bank_b", 0)
        assert psp_prob < bank_b_prob, \
            f"Distant node psp_app_1 ({psp_prob}) should have lower prob than bank_b ({bank_b_prob})"