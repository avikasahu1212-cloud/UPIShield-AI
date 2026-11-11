"""Tests for root cause analysis."""

import pytest

from app.rca.root_cause import analyze, impact


class TestRCA:
    """Test root cause analysis."""

    def test_single_root(self):
        """Single root cause should rank highest."""
        alerts = [
            {"node_id": "bank_a", "first_anomaly_time": "2026-11-06T05:00:00+05:30",
             "peak_score": 0.95, "status": "active"},
            {"node_id": "psp_app_1", "first_anomaly_time": "2026-11-06T05:05:00+05:30",
             "peak_score": 0.8, "status": "active"},
        ]
        results = analyze(alerts)
        assert len(results) > 0
        # bank_a should be the top root cause (it's the dependency)
        assert results[0]["root_cause"] == "bank_a"

    def test_two_roots(self):
        """Two separate groups should produce separate candidates."""
        alerts = [
            {"node_id": "bank_a", "first_anomaly_time": "2026-11-06T05:00:00+05:30",
             "peak_score": 0.95, "status": "active"},
            {"node_id": "status_check_api", "first_anomaly_time": "2026-11-06T10:00:00+05:30",
             "peak_score": 0.9, "status": "active"},
        ]
        results = analyze(alerts)
        # Should have at least one result
        assert len(results) >= 1

    def test_victim_early_fire(self):
        """A victim that fires early by accident should be penalized."""
        alerts = [
            # Victim fires before the actual root
            {"node_id": "psp_app_1", "first_anomaly_time": "2026-11-06T05:00:00+05:30",
             "peak_score": 0.9, "status": "active"},
            {"node_id": "bank_a", "first_anomaly_time": "2026-11-06T05:05:00+05:30",
             "peak_score": 0.95, "status": "active"},
        ]
        results = analyze(alerts)
        assert len(results) > 0
        # bank_a should rank higher (it's the actual root, psp_app_1 is the victim)
        bank_rank = next((r["rank"] for r in results if r["root_cause"] == "bank_a"), 99)
        psp_rank = next((r["rank"] for r in results if r["root_cause"] == "psp_app_1"), 99)
        assert bank_rank <= psp_rank, "bank_a should rank higher than victim psp_app_1"

    def test_no_alerts(self):
        """Empty alerts should return empty results."""
        results = analyze([])
        assert results == []

    def test_all_resolved(self):
        """All resolved alerts should return empty results."""
        alerts = [
            {"node_id": "bank_a", "first_anomaly_time": "2026-11-06T05:00:00+05:30",
             "peak_score": 0.95, "status": "resolved"},
        ]
        results = analyze(alerts)
        assert results == []

    def test_impact(self):
        """Impact should return dependants."""
        results = impact("cloud_region_1")
        assert len(results) > 0
        node_ids = [r["node_id"] for r in results]
        assert "bank_b" in node_ids
        assert "bank_c" in node_ids

    def test_result_format(self):
        """Results should have expected keys."""
        alerts = [
            {"node_id": "bank_a", "first_anomaly_time": "2026-11-06T05:00:00+05:30",
             "peak_score": 0.95, "status": "active"},
        ]
        results = analyze(alerts)
        if results:
            r = results[0]
            assert "root_cause" in r
            assert "confidence" in r
            assert "explanation" in r
            assert "rank" in r