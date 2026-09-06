"""
Week 4 routing tests: synthetic graphs only, no DB needed (mirrors how
test_scoring.py/test_scoring_v2.py stay DB-free). DB-integration routing
checks (load_routing_graph against the real DB) live in test_data_quality.py.

    docker compose exec api pytest tests/test_routing.py -v
"""
import sys

import networkx as nx
import pytest

sys.path.insert(0, "/app")
from app.core import routing
from app.core.graph import NoConnectedRouteError, UnknownNodeError


def make_edge_labeled(length_m, accessibility_score, confidence_score, **extra):
    return {
        "length_m": length_m,
        "accessibility_score": accessibility_score,
        "confidence_score": confidence_score,
        "coverage_status": "labeled",
        "dominant_hazard_type": None,
        "evidence_consistency": 1.0,
        **extra,
    }


def make_edge_unknown(length_m, **extra):
    return {
        "length_m": length_m,
        "accessibility_score": 0.5,
        "confidence_score": 0.0,
        "coverage_status": "unknown",
        "dominant_hazard_type": None,
        "evidence_consistency": None,
        **extra,
    }


def three_path_graph():
    """origin=0, destination=1, three alternate node-disjoint paths:
    A (via 'a'): short, unknown coverage.
    B (via 'b'): slightly longer, excellent accessibility, very low confidence.
    C (via 'c'): longest, good accessibility, high confidence.
    Split into two edges per path so they're distinct simple-graph paths."""
    g = nx.Graph()
    for node in (0, 1, "a", "b", "c"):
        g.add_node(node, component_id=0)

    for u, v in ((0, "a"), ("a", 1)):
        g.add_edge(u, v, segment_id=f"A-{u}-{v}", **make_edge_unknown(5.0))
    for u, v in ((0, "b"), ("b", 1)):
        g.add_edge(u, v, segment_id=f"B-{u}-{v}", **make_edge_labeled(5.5, 0.95, 0.05))
    for u, v in ((0, "c"), ("c", 1)):
        g.add_edge(u, v, segment_id=f"C-{u}-{v}", **make_edge_labeled(7.5, 0.85, 0.95))
    return g


def path_via(path_node_ids, waypoint):
    return waypoint in path_node_ids


# ---------------------------------------------------------------------------
# Three modes must be able to disagree
# ---------------------------------------------------------------------------

def test_shortest_mode_ignores_accessibility_and_confidence():
    g = three_path_graph()
    result = routing.find_route(g, 0, 1, routing.SHORTEST)
    assert path_via(result["path_node_ids"], "a")
    assert result["total_length_m"] == pytest.approx(10.0)


def test_accessible_mode_prefers_best_raw_accessibility_regardless_of_confidence():
    g = three_path_graph()
    result = routing.find_route(g, 0, 1, routing.ACCESSIBLE)
    assert path_via(result["path_node_ids"], "b")  # 0.95 accessibility, even though confidence is 0.05


def test_confidence_aware_mode_avoids_the_low_confidence_path():
    g = three_path_graph()
    result = routing.find_route(g, 0, 1, routing.CONFIDENCE_AWARE)
    assert path_via(result["path_node_ids"], "c")  # gives up B's raw score for C's certainty


def test_all_three_modes_produce_different_paths_on_the_same_graph():
    g = three_path_graph()
    winners = {mode: tuple(routing.find_route(g, 0, 1, mode)["path_node_ids"]) for mode in routing.MODES}
    assert len(set(winners.values())) == 3, winners


# ---------------------------------------------------------------------------
# No-connected-route
# ---------------------------------------------------------------------------

def disconnected_graph():
    g = nx.Graph()
    g.add_node(0, component_id=0)
    g.add_node(1, component_id=0)
    g.add_edge(0, 1, segment_id="s1", **make_edge_labeled(10.0, 0.8, 0.8))
    g.add_node(2, component_id=1)
    g.add_node(3, component_id=1)
    g.add_edge(2, 3, segment_id="s2", **make_edge_labeled(10.0, 0.8, 0.8))
    return g


def test_cross_component_request_raises_no_connected_route():
    g = disconnected_graph()
    with pytest.raises(NoConnectedRouteError):
        routing.find_route(g, 0, 2, routing.SHORTEST)


def test_same_component_request_succeeds():
    g = disconnected_graph()
    result = routing.find_route(g, 0, 1, routing.SHORTEST)
    assert result["path_node_ids"] == [0, 1]


def test_unknown_node_raises():
    g = disconnected_graph()
    with pytest.raises(UnknownNodeError):
        routing.find_route(g, 0, 999, routing.SHORTEST)


def test_invalid_mode_raises():
    g = disconnected_graph()
    with pytest.raises(routing.InvalidRouteModeError):
        routing.find_route(g, 0, 1, "fastest")


# ---------------------------------------------------------------------------
# Route explanations: unknown vs. low-confidence vs. disputed vs. dominant hazard
# ---------------------------------------------------------------------------

def test_unknown_and_low_confidence_segments_are_reported_separately():
    g = nx.Graph()
    for node in (0, 1, 2):
        g.add_node(node, component_id=0)
    g.add_edge(0, 1, segment_id="unknown-seg", **make_edge_unknown(10.0))
    g.add_edge(1, 2, segment_id="low-conf-seg", **make_edge_labeled(10.0, 0.6, 0.1))

    result = routing.summarize_route(g, [0, 1, 2], routing.SHORTEST)
    assert result["unknown_segment_ids"] == ["unknown-seg"]
    assert result["low_confidence_segment_ids"] == ["low-conf-seg"]
    # never counted as both
    assert set(result["unknown_segment_ids"]) & set(result["low_confidence_segment_ids"]) == set()


def test_dominant_hazard_exposed_in_route_summary():
    g = nx.Graph()
    for node in (0, 1):
        g.add_node(node, component_id=0)
    g.add_edge(0, 1, segment_id="capped-seg",
               **make_edge_labeled(10.0, 0.05, 0.8, dominant_hazard_type="NoSidewalk"))

    result = routing.summarize_route(g, [0, 1], routing.SHORTEST)
    assert result["dominant_hazards"] == [{"segment_id": "capped-seg", "hazard_type": "NoSidewalk"}]


def test_disputed_evidence_exposed_in_route_summary():
    g = nx.Graph()
    for node in (0, 1):
        g.add_node(node, component_id=0)
    g.add_edge(0, 1, segment_id="disputed-seg",
               **make_edge_labeled(10.0, 0.5, 0.0, evidence_consistency=0.02))

    result = routing.summarize_route(g, [0, 1], routing.SHORTEST)
    assert result["disputed_segment_ids"] == ["disputed-seg"]


def test_route_with_no_issues_reports_empty_flag_lists():
    g = nx.Graph()
    for node in (0, 1):
        g.add_node(node, component_id=0)
    g.add_edge(0, 1, segment_id="good-seg", **make_edge_labeled(10.0, 0.95, 0.95))

    result = routing.summarize_route(g, [0, 1], routing.SHORTEST)
    assert result["unknown_segment_ids"] == []
    assert result["low_confidence_segment_ids"] == []
    assert result["disputed_segment_ids"] == []
    assert result["dominant_hazards"] == []


# ---------------------------------------------------------------------------
# Crossing evidence scope: a good crossing edge doesn't launder an adjacent
# bad footway edge's cost (each edge is scored/weighted independently)
# ---------------------------------------------------------------------------

def test_crossing_edge_score_does_not_affect_adjacent_footway_edge_weight():
    g = nx.Graph()
    for node in (0, 1, 2):
        g.add_node(node, component_id=0)
    # footway with poor, confident evidence
    g.add_edge(0, 1, segment_id="bad-footway", highway_type="footway",
               **make_edge_labeled(10.0, 0.1, 0.9))
    # excellent, confident crossing right after it
    g.add_edge(1, 2, segment_id="great-crossing", highway_type="crossing",
               **make_edge_labeled(2.0, 0.95, 0.95))

    weight_before = routing.edge_weight(
        routing.ACCESSIBLE, g.edges[0, 1]["length_m"],
        g.edges[0, 1]["accessibility_score"], g.edges[0, 1]["confidence_score"],
    )
    # the footway edge's own weight is computed purely from its own attributes
    expected = 10.0 * (1 + routing.ACCESSIBILITY_PENALTY_WEIGHT * (1 - 0.1))
    assert weight_before == pytest.approx(expected)
    # traversing the route doesn't retroactively change that edge's data
    routing.find_route(g, 0, 2, routing.ACCESSIBLE)
    assert g.edges[0, 1]["accessibility_score"] == 0.1
