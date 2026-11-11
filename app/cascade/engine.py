"""Monte Carlo independent-cascade engine.

Simulates failure propagation from a failed node through the dependency
graph.  Each trial activates nodes probabilistically using edge
propagation_prob.  A min-heap tracks the earliest failure time per node.

All random processes take a seed and use numpy's Generator (never the
global RNG).
"""

from __future__ import annotations

import heapq
import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.config import DEFAULT_CASCADE_TRIALS, DEFAULT_HORIZONS_MIN
from app.graph.topology import build_graph

logger = logging.getLogger(__name__)


@dataclass
class CascadeResult:
    """Result of a Monte Carlo cascade simulation."""

    failed_node: str
    trials: int
    cascade_probabilities: dict[str, float] = field(default_factory=dict)
    time_to_failure: dict[str, float] = field(default_factory=dict)
    by_horizon: dict[str, dict[int, float]] = field(default_factory=dict)
    expected_affected: float = 0.0
    assumptions: list[str] = field(default_factory=lambda: [
        "Propagation probabilities are assumptions, not measured values.",
        "Delay distribution is exponential with mean = delay_min_mean per edge.",
        "Effects attenuate by 0.5 per hop in the generator; cascade uses raw probs.",
    ])

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for JSON API responses."""
        return {
            "failed_node": self.failed_node,
            "trials": self.trials,
            "cascade_probabilities": self.cascade_probabilities,
            "time_to_failure": self.time_to_failure,
            "by_horizon": self.by_horizon,
            "expected_affected": round(self.expected_affected, 2),
            "assumptions": self.assumptions,
        }


class NodeNotFoundError(ValueError):
    """Raised when a requested node is not in the topology."""
    pass


def simulate_cascade(
    failed_node: str,
    trials: int = DEFAULT_CASCADE_TRIALS,
    seed: int | None = None,
    horizons_min: list[int] | None = None,
) -> CascadeResult:
    """Run Monte Carlo independent-cascade simulation.

    Parameters
    ----------
    failed_node : str
        The node that fails at time 0.
    trials : int
        Number of Monte Carlo trials (100-50000).
    seed : int or None
        Random seed for reproducibility.
    horizons_min : list[int] or None
        Time horizons (in minutes) to compute P(failed by t).

    Returns
    -------
    CascadeResult
    """
    if horizons_min is None:
        horizons_min = DEFAULT_HORIZONS_MIN

    G = build_graph()
    if failed_node not in G:
        raise NodeNotFoundError(f"Node '{failed_node}' not found in topology graph.")

    rng = np.random.default_rng(seed)
    n_nodes = len(G.nodes())

    # Counters
    failure_counts: dict[str, int] = {n: 0 for n in G.nodes()}
    failure_times: dict[str, list[float]] = {n: [] for n in G.nodes()}
    horizon_counts: dict[str, dict[int, int]] = {
        n: {h: 0 for h in horizons_min} for n in G.nodes()
    }
    affected_counts: list[int] = []

    # Pre-fetch edge data for speed
    edge_data: dict[tuple[str, str], dict] = {
        (u, v): d for u, v, d in G.edges(data=True)
    }

    for _ in range(trials):
        # Each trial: simulate cascade from failed_node
        # Use a min-heap: (time, node)
        heap: list[tuple[float, str]] = [(0.0, failed_node)]
        activated: dict[str, float] = {failed_node: 0.0}
        activated_set = {failed_node}

        while heap:
            t, current = heapq.heappop(heap)
            # Propagate to predecessors (dependants)
            for pred in G.predecessors(current):
                if pred in activated_set:
                    continue
                edge = edge_data.get((current, pred))
                if edge is None:
                    continue
                prob = edge["propagation_prob"]
                # Bernoulli trial
                if rng.random() < prob:
                    # Sample delay from exponential distribution
                    delay = max(1.0, rng.exponential(edge["delay_min_mean"]))
                    fail_time = t + delay
                    activated[pred] = fail_time
                    activated_set.add(pred)
                    heapq.heappush(heap, (fail_time, pred))

        # Record results for this trial
        for node, fail_time in activated.items():
            if node == failed_node:
                continue
            failure_counts[node] += 1
            failure_times[node].append(fail_time)
            for h in horizons_min:
                if fail_time <= h:
                    horizon_counts[node][h] += 1

        affected_counts.append(len(activated) - 1)

    # Build result
    cascade_probs: dict[str, float] = {}
    time_to_fail: dict[str, float] = {}
    by_horizon: dict[str, dict[int, float]] = {}

    for node in G.nodes():
        if node == failed_node:
            continue
        cnt = failure_counts[node]
        cascade_probs[node] = round((cnt / trials) * 100, 2)

        if failure_times[node]:
            time_to_fail[node] = round(float(np.median(failure_times[node])), 2)

        by_horizon[node] = {}
        for h in horizons_min:
            by_horizon[node][h] = round(
                (horizon_counts[node][h] / trials) * 100, 2
            )

    return CascadeResult(
        failed_node=failed_node,
        trials=trials,
        cascade_probabilities=cascade_probs,
        time_to_failure=time_to_fail,
        by_horizon=by_horizon,
        expected_affected=float(np.mean(affected_counts)),
    )