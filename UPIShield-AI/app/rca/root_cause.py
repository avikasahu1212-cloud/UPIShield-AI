"""Root cause analysis.

Groups alerts into incident candidates, ranks them, and returns top-3
with explanations.
"""

from __future__ import annotations

import logging
from typing import Any

import networkx as nx
import pandas as pd

from app.config import RCA_CORRELATION_WINDOW_MIN, RCA_WEIGHTS
from app.graph.topology import build_graph, dependants, dependencies

logger = logging.getLogger(__name__)


def analyze(alerts: list[dict[str, Any]],
            G: nx.DiGraph | None = None) -> list[dict[str, Any]]:
    """Analyze alerts and return ranked root cause candidates."""
    if G is None:
        G = build_graph()

    active = [a for a in alerts if a.get("status") == "active"]
    if not active:
        return []

    groups = _group_alerts(active, G)
    candidates: list[dict[str, Any]] = []
    for group_idx, group in enumerate(groups):
        ranking = _rank_group(group, G)
        for rank, score_tuple in enumerate(ranking[:3], 1):
            # score_tuple is (float_score, dict_result)
            candidate = dict(score_tuple[1])
            candidate["group"] = group_idx
            candidate["rank"] = rank
            candidates.append(candidate)

    candidates.sort(key=lambda x: (x["group"], x["rank"]))
    return candidates[:10]


def _group_alerts(alerts: list[dict], G: nx.DiGraph) -> list[list[dict]]:
    """Group alerts using correlation window and graph connectivity."""
    if not alerts:
        return []

    sorted_alerts = sorted(alerts, key=lambda a: a.get("first_anomaly_time", ""))
    undirected = G.to_undirected()
    groups: list[list[dict]] = []
    assigned: set[int] = set()

    for i, alert_i in enumerate(sorted_alerts):
        if i in assigned:
            continue
        group = [alert_i]
        assigned.add(i)

        for j, alert_j in enumerate(sorted_alerts):
            if j in assigned:
                continue
            time_i = pd.Timestamp(alert_i.get("first_anomaly_time", ""))
            time_j = pd.Timestamp(alert_j.get("first_anomaly_time", ""))
            if abs((time_j - time_i).total_seconds()) / 60 <= RCA_CORRELATION_WINDOW_MIN:
                connected = (
                    undirected.has_edge(alert_i["node_id"], alert_j["node_id"])
                    or any(
                        undirected.has_edge(alert_j["node_id"], g["node_id"])
                        for g in group
                    )
                )
                if connected:
                    group.append(alert_j)
                    assigned.add(j)

        if group:
            groups.append(group)

    return groups


def _rank_group(group: list[dict], G: nx.DiGraph) -> list[dict[str, Any]]:
    """Rank alerts in a group by root cause likelihood."""
    weights = RCA_WEIGHTS
    nodes_in_group = {a["node_id"] for a in group}
    group_size = len(group)
    scored: list[tuple[float, dict]] = []

    for alert in group:
        node = alert["node_id"]
        score = alert.get("peak_score", 0.5)

        # Earliness
        try:
            t = pd.Timestamp(alert.get("first_anomaly_time", ""))
            times = [pd.Timestamp(a.get("first_anomaly_time", "")) for a in group]
            earliest, latest = min(times), max(times)
            time_range = (latest - earliest).total_seconds() / 60 if latest != earliest else 1
            earliness = 1.0 - ((t - earliest).total_seconds() / 60) / time_range
        except Exception:
            earliness = 0.5

        # Explained fraction
        deps = dependants(G, node)
        dep_nodes = {d[0] for d in deps}
        explained = len(dep_nodes & nodes_in_group - {node}) / max(group_size - 1, 1)

        # Victim penalty
        my_deps = dependencies(G, node)
        dep_node_ids = {d[0] for d in my_deps}
        earlier_deps = total_deps = 0
        try:
            t_self = pd.Timestamp(alert.get("first_anomaly_time", ""))
            for other in group:
                if other["node_id"] in dep_node_ids and other["node_id"] != node:
                    total_deps += 1
                    if pd.Timestamp(other.get("first_anomaly_time", "")) < t_self:
                        earlier_deps += 1
        except Exception:
            pass
        victim_penalty = earlier_deps / max(total_deps, 1)

        combined = (
            weights["earliness"] * earliness
            + weights["explained_fraction"] * explained
            + weights["normalised_peak_score"] * score
            - weights["victim_penalty"] * victim_penalty
        )
        confidence = max(0, min(1, combined + 0.5))
        explains = len(dep_nodes & nodes_in_group - {node})
        explanation = (
            f"earliest anomaly at {alert.get('first_anomaly_time', 'N/A')[:16]}; "
            f"explains {explains} of {group_size - 1} anomalous nodes; "
            f"victim_penalty={victim_penalty:.2f}"
        )

        scored.append((combined, {
            "root_cause": node,
            "confidence": round(confidence, 4),
            "explanation": explanation,
            "alerts_count": group_size,
            "explained_fraction": round(explained, 4),
            "earliness": round(earliness, 4),
            "victim_penalty": round(victim_penalty, 4),
            "peak_score": round(score, 4),
            "first_anomaly_time": alert.get("first_anomaly_time", ""),
        }))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def impact(node_id: str, G: nx.DiGraph | None = None) -> list[dict[str, Any]]:
    """Return nodes that depend on *node_id* with hop distance (light S5)."""
    if G is None:
        G = build_graph()
    deps = dependants(G, node_id)
    return [{"node_id": n, "hop_distance": d} for n, d in deps]