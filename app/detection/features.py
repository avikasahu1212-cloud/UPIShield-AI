"""Causal feature engineering for anomaly detection.

All features are computed without look-ahead: only data up to and including
the current minute is used.
"""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Rolling window sizes
ROLLING_WIN = 5        # 5-minute rolling stats
DELTA_WIN = 3          # 3-minute delta


def compute_features(df: pd.DataFrame, fit_on_train: bool = False) -> pd.DataFrame:
    """Compute causal features per node.

    Parameters
    ----------
    df : pd.DataFrame
        Must have columns: timestamp, node_id, requests, success_rate,
        timeout_ratio, p95_latency_ms, retry_ratio, pending_txns.
    fit_on_train : bool
        If True, compute and store the train-period volume profile.

    Returns
    -------
    pd.DataFrame with added feature columns.
    """
    df = df.copy()
    df = df.sort_values(["node_id", "timestamp"]).reset_index(drop=True)

    # Log latency
    df["log_latency"] = np.log1p(df["p95_latency_ms"])

    # Pending/requests ratio
    df["pending_ratio"] = df["pending_txns"] / df["requests"].clip(lower=1)

    # Per-node rolling stats (causal: only past data)
    for col in ["p95_latency_ms", "timeout_ratio", "success_rate"]:
        df[f"rolling_mean_{col}_{ROLLING_WIN}"] = (
            df.groupby("node_id")[col]
            .transform(lambda x: x.rolling(ROLLING_WIN, min_periods=1).mean())
        )
        df[f"rolling_std_{col}_{ROLLING_WIN}"] = (
            df.groupby("node_id")[col]
            .transform(lambda x: x.rolling(ROLLING_WIN, min_periods=1).std().fillna(0))
        )

    # 3-minute deltas
    for col in ["p95_latency_ms", "timeout_ratio", "success_rate"]:
        df[f"delta_{col}_{DELTA_WIN}"] = (
            df.groupby("node_id")[col]
            .diff(DELTA_WIN)
        )

    # Minute-of-day sin/cos (cyclical encoding)
    df["timestamp_dt"] = pd.to_datetime(df["timestamp"], utc=True)
    minutes_since_midnight = (
        df["timestamp_dt"].dt.hour * 60 + df["timestamp_dt"].dt.minute
    )
    df["mood_sin"] = np.sin(2 * np.pi * minutes_since_midnight / 1440)
    df["mood_cos"] = np.cos(2 * np.pi * minutes_since_midnight / 1440)

    # Is weekend
    df["is_weekend"] = (df["timestamp_dt"].dt.dayofweek >= 5).astype(int)

    # Volume ratio: requests vs expected for this minute-of-day and weekday
    # For now, use a simple baseline; tune.py will refine this
    df["volume_ratio"] = 1.0  # placeholder, refined in baseline

    # Robust z-scores vs train median/MAD (computed later)
    # These are placeholders filled by compute_robust_zscores

    feature_cols = [
        "log_latency", "pending_ratio",
        "rolling_mean_p95_latency_ms_5", "rolling_std_p95_latency_ms_5",
        "rolling_mean_timeout_ratio_5", "rolling_std_timeout_ratio_5",
        "rolling_mean_success_rate_5", "rolling_std_success_rate_5",
        "delta_p95_latency_ms_3", "delta_timeout_ratio_3", "delta_success_rate_3",
        "mood_sin", "mood_cos", "is_weekend", "volume_ratio",
    ]

    return df[feature_cols]


def compute_robust_zscores(df: pd.DataFrame, train_df: pd.DataFrame) -> pd.DataFrame:
    """Compute robust z-scores (median/MAD) using train statistics.

    Returns df with added robust_z_* columns.
    """
    df = df.copy()
    cols = ["p95_latency_ms", "timeout_ratio", "success_rate", "retry_ratio"]

    # Compute train stats
    train_stats: dict[str, dict[str, float]] = {}
    for col in cols:
        median = train_df[col].median()
        mad = (train_df[col] - median).abs().median()
        mad = mad if mad > 0 else 1.0
        train_stats[col] = {"median": median, "mad": mad}

    # Apply to full df
    for col in cols:
        s = train_stats[col]
        df[f"robust_z_{col}"] = (df[col] - s["median"]) / s["mad"]

    return df, train_stats


def get_feature_columns() -> list[str]:
    """Return the list of feature column names."""
    return [
        "log_latency", "pending_ratio",
        "rolling_mean_p95_latency_ms_5", "rolling_std_p95_latency_ms_5",
        "rolling_mean_timeout_ratio_5", "rolling_std_timeout_ratio_5",
        "rolling_mean_success_rate_5", "rolling_std_success_rate_5",
        "delta_p95_latency_ms_3", "delta_timeout_ratio_3", "delta_success_rate_3",
        "mood_sin", "mood_cos", "is_weekend", "volume_ratio",
    ]