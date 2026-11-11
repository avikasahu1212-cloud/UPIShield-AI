"""Tests for the data generator."""

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

GENERATE_SCRIPT = Path(__file__).parent.parent / "scripts" / "generate_data.py"
DATA_DIR = Path(__file__).parent.parent / "data"


@pytest.fixture(scope="module")
def generated_data():
    """Run the generator once for all tests."""
    result = subprocess.run(
        [sys.executable, str(GENERATE_SCRIPT), "--seed", "42", "--out", str(DATA_DIR)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Generator failed: {result.stderr}"
    return True


class TestGenerator:
    """Test data generation."""

    def test_files_created(self, generated_data):
        assert (DATA_DIR / "telemetry.csv").exists()
        assert (DATA_DIR / "incidents.csv").exists()

    def test_telemetry_row_count(self, generated_data):
        df = pd.read_csv(DATA_DIR / "telemetry.csv")
        # 12 nodes x 7 days x 1440 minutes = 120,960
        assert len(df) == 12 * 7 * 1440, f"Expected 120960 rows, got {len(df)}"

    def test_telemetry_schema(self, generated_data):
        df = pd.read_csv(DATA_DIR / "telemetry.csv")
        expected_cols = {
            "timestamp", "node_id", "requests", "success_rate",
            "timeout_ratio", "p95_latency_ms", "retry_ratio", "pending_txns",
        }
        assert set(df.columns) == expected_cols, f"Unexpected columns: {set(df.columns) - expected_cols}"

    def test_no_nans(self, generated_data):
        df = pd.read_csv(DATA_DIR / "telemetry.csv")
        assert df.isnull().sum().sum() == 0, "DataFrame contains NaNs"

    def test_no_label_columns(self, generated_data):
        df = pd.read_csv(DATA_DIR / "telemetry.csv")
        label_cols = {"is_incident", "root_node", "scenario", "label"}
        assert not (set(df.columns) & label_cols), "Telemetry should not contain label columns"

    def test_invariants(self, generated_data):
        df = pd.read_csv(DATA_DIR / "telemetry.csv")
        # timeout_ratio <= 1 - success_rate
        violations = df[df["timeout_ratio"] > 1.0 - df["success_rate"] + 1e-9]
        assert violations.empty, f"{len(violations)} rows violate timeout_ratio invariant"
        # All ratios in [0, 1]
        assert (df["success_rate"] >= 0).all() and (df["success_rate"] <= 1).all()
        assert (df["timeout_ratio"] >= 0).all() and (df["timeout_ratio"] <= 1).all()
        assert (df["retry_ratio"] >= 0).all() and (df["retry_ratio"] <= 1).all()

    def test_incidents_non_overlapping(self, generated_data):
        inc_df = pd.read_csv(DATA_DIR / "incidents.csv")
        inc_df = inc_df[inc_df["is_incident"] == True].sort_values("start")
        for i in range(len(inc_df) - 1):
            end_i = pd.Timestamp(inc_df.iloc[i]["end"])
            start_next = pd.Timestamp(inc_df.iloc[i + 1]["start"])
            # Allow 60-min gap
            assert (start_next - end_i).total_seconds() >= 3600 or inc_df.iloc[i]["day"] != inc_df.iloc[i + 1]["day"], \
                f"Incidents overlap: {inc_df.iloc[i]['incident_id']} and {inc_df.iloc[i+1]['incident_id']}"

    def test_determinism(self, generated_data):
        """Running with the same seed produces the same output."""
        import tempfile
        df1 = pd.read_csv(DATA_DIR / "telemetry.csv")
        # Generate again to a temp dir
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_out = Path(tmpdir)
            result = subprocess.run(
                [sys.executable, str(GENERATE_SCRIPT), "--seed", "42", "--out", str(tmp_out)],
                capture_output=True, text=True,
            )
            assert result.returncode == 0, f"Second generation failed: {result.stderr}"
            df2 = pd.read_csv(tmp_out / "telemetry.csv")
        pd.testing.assert_frame_equal(df1, df2, check_dtype=False)