"""Per-node Isolation Forest models and score calibration.

One IsolationForest per node, fit on train data. Scores are converted to
[0,1] via the empirical train-score CDF (higher = more anomalous).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from app.config import (
    ARTIFACTS_DIR,
    DETECTOR_SEED,
    ISOLATION_FOREST_N_ESTIMATORS,
    NODE_IDS,
)
from app.detection.features import get_feature_columns

logger = logging.getLogger(__name__)


class NodeModel:
    """Wraps an IsolationForest and its score CDF for a single node."""

    def __init__(self, node_id: str, model: IsolationForest,
                 cdf_bins: np.ndarray, cdf_probs: np.ndarray):
        self.node_id = node_id
        self.model = model
        self.cdf_bins = cdf_bins
        self.cdf_probs = cdf_probs

    def score(self, features: pd.DataFrame) -> pd.Series:
        """Convert raw model scores to [0,1] anomaly probabilities."""
        raw = self.model.score_samples(features)
        inverted = -raw  # higher = more anomalous
        probs = np.interp(inverted, self.cdf_bins, self.cdf_probs)
        return pd.Series(probs, index=features.index)

    def save(self, path: Path) -> None:
        """Save model and CDF to disk."""
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "node_id": self.node_id,
            "model": self.model,
            "cdf_bins": self.cdf_bins,
            "cdf_probs": self.cdf_probs,
        }, path)

    @classmethod
    def load(cls, path: Path) -> "NodeModel":
        """Load model from disk."""
        data = joblib.load(path)
        return cls(data["node_id"], data["model"], data["cdf_bins"], data["cdf_probs"])


class DetectorModel:
    """Manages per-node IsolationForest models."""

    def __init__(self, seed: int = DETECTOR_SEED):
        self.seed = seed
        self.models: dict[str, NodeModel] = {}
        self.thresholds: dict[str, float] = {}

    def fit(self, train_df: pd.DataFrame) -> None:
        """Fit one IsolationForest per node on train data."""
        feature_cols = get_feature_columns()
        missing = set(feature_cols) - set(train_df.columns)
        if missing:
            raise ValueError(f"Missing feature columns: {missing}")

        for node_id in NODE_IDS:
            node_data = train_df[train_df["node_id"] == node_id][feature_cols]
            if node_data.empty:
                logger.warning("No train data for node %s; skipping", node_id)
                continue

            rng = np.random.default_rng(self.seed)
            model = IsolationForest(
                n_estimators=ISOLATION_FOREST_N_ESTIMATORS,
                random_state=int(rng.integers(0, 2**31)),
                contamination="auto",
                n_jobs=-1,
            )
            model.fit(node_data)

            raw_scores = -model.score_samples(node_data)
            cdf_bins = np.percentile(raw_scores, np.linspace(0, 100, 200))
            cdf_probs = np.linspace(0, 1, 200)

            self.models[node_id] = NodeModel(node_id, model, cdf_bins, cdf_probs)
            logger.info("Fitted model for node %s (%d samples)", node_id, len(node_data))

    def score(self, df: pd.DataFrame) -> pd.DataFrame:
        """Score all nodes. Returns DataFrame with node_id, timestamp, score."""
        feature_cols = get_feature_columns()
        results: list[dict[str, Any]] = []

        for _, row in df.iterrows():
            node_id = row["node_id"]
            if node_id not in self.models:
                continue
            features = row[feature_cols].values.reshape(1, -1)
            score_df = pd.DataFrame(features, columns=feature_cols)
            score_val = float(self.models[node_id].score(score_df).iloc[0])
            results.append({
                "node_id": node_id,
                "timestamp": row["timestamp"],
                "anomaly_score": score_val,
            })

        return pd.DataFrame(results)

    def save_all(self) -> None:
        """Save all models to artifacts/."""
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        for node_id, model in self.models.items():
            path = ARTIFACTS_DIR / f"model_{node_id}.joblib"
            model.save(path)
            logger.info("Saved model for %s to %s", node_id, path)

    def load_all(self) -> None:
        """Load all models from artifacts/."""
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        for node_id in NODE_IDS:
            path = ARTIFACTS_DIR / f"model_{node_id}.joblib"
            if path.exists():
                self.models[node_id] = NodeModel.load(path)
                logger.info("Loaded model for %s from %s", node_id, path)