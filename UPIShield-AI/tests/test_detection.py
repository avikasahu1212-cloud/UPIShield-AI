"""Tests for detection features and model."""

import pandas as pd
import pytest

from app.config import DATA_DIR
from app.detection.features import compute_features, get_feature_columns
from app.detection.model import DetectorModel


class TestDetection:
    """Test detection pipeline."""

    @pytest.fixture
    def telemetry_df(self):
        return pd.read_csv(DATA_DIR / "telemetry.csv")

    def test_feature_columns(self):
        cols = get_feature_columns()
        assert len(cols) > 0
        assert "log_latency" in cols
        assert "is_weekend" in cols

    def test_compute_features(self, telemetry_df):
        feature_df = compute_features(telemetry_df)
        cols = get_feature_columns()
        for col in cols:
            assert col in feature_df.columns, f"Missing feature: {col}"
        assert len(feature_df) == len(telemetry_df)

    def test_no_nans_in_features(self, telemetry_df):
        feature_df = compute_features(telemetry_df)
        assert feature_df.isnull().sum().sum() == 0, "Features contain NaNs"

    def test_detector_model_fit(self, telemetry_df):
        """Detector should fit on feature data."""
        feature_df = compute_features(telemetry_df)
        model = DetectorModel(seed=42)
        # Need node_id and timestamp columns
        feature_df["node_id"] = telemetry_df["node_id"]
        feature_df["timestamp"] = telemetry_df["timestamp"]
        model.fit(feature_df)
        assert len(model.models) == 12  # All 12 nodes

    def test_detector_save_load(self, telemetry_df, tmp_path):
        """Model should save and load correctly."""
        import shutil
        from app.config import ARTIFACTS_DIR
        tmp_artifacts = tmp_path / "artifacts"
        shutil.copytree(ARTIFACTS_DIR, tmp_artifacts, dirs_exist_ok=True)

        feature_df = compute_features(telemetry_df)
        feature_df["node_id"] = telemetry_df["node_id"]
        feature_df["timestamp"] = telemetry_df["timestamp"]

        model = DetectorModel(seed=42)
        model.fit(feature_df)
        model.save_all()

        # Load
        model2 = DetectorModel()
        model2.load_all()
        assert len(model2.models) == len(model.models)