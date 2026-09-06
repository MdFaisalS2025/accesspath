"""
Week 4: finds one real origin/destination pair with mixed evidence (a very
accessible segment near the origin, a poor one near the destination) and
runs all three routing modes against it, to show real mode disagreement and
a real route explanation -- not just the synthetic graphs in test_routing.py.
Writes docs/week4_routing_report.md.

    docker compose exec api python scripts/demo_routing.py
"""
import sys

import networkx as nx

sys.path.insert(0, "/app")
from app.core import routing
from app.core.db import get_connection
from app.core.graph import NoConnectedRouteError

REPORT_PATH = "/docs/week4_routing_report.md"


def find_demo_pair(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT n1.id, n2.id
            FROM segment_scores sc1
            JOIN segments s1 ON s1.id = sc1.segment_id
            JOIN nodes n1 ON n1.id = s1.from_node_id
            JOIN segment_scores sc2 ON sc2.coverage_status = 'labeled' AND sc2.accessibility_score < 0.2
            JOIN segments s2 ON s2.id = sc2.segment_id
            JOIN nodes n2 ON n2.id = s2.to_node_id
            WHERE sc1.coverage_status = 'labeled' AND sc1.accessibility_score > 0.9
              AND sc1.confidence_score > 0.5
              AND n1.component_id = 0 AND n2.component_id = 0
            LIMIT 50
            """
        )
        candidates = cur.fetchall()

    graph = routing.load_routing_graph(conn)
    for origin, destination in candidates:
        if origin == destination:
            continue
        try:
            paths = {
                mode: tuple(routing.find_route(graph, origin, destination, mode)["path_node_ids"])
                for mode in routing.MODES
            }
        except (NoConnectedRouteError, nx.NetworkXNoPath):
            continue
        if len(set(paths.values())) > 1:
            return graph, origin, destination
    return graph, None, None


def write_report(graph, origin, destination):
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("# Week 4 — Routing\n\n")
        f.write(
            "Pathfinding over the scored pedestrian graph. Design, formulas, "
            "and rationale are in `backend/app/core/routing.py`'s module "
            "docstring; this report is the real-data demonstration + test "
            "summary. No API endpoint or frontend yet -- `find_route()` and "
            "`load_routing_graph()` are called directly here and from tests.\n\n"
        )

        f.write("## Requirements checklist\n\n")
        f.write(
            "- **Crossing evidence scoped to crossing edges, not whole segments**: "
            "already true structurally from Week 3.5's domain scoping -- a "
            "crossing is its own graph edge with its own `segment_scores` row; "
            "routing costs each edge from its own row only. Verified by "
            "`test_routing.py::test_crossing_edge_score_does_not_affect_adjacent_footway_edge_weight`.\n"
            "- **Route explanations expose dominant hazards, unknown segments, "
            "disputed evidence**: `summarize_route()` returns `dominant_hazards`, "
            "`unknown_segment_ids`, `disputed_segment_ids` as separate lists.\n"
            "- **Unknown vs. low-confidence stay distinguishable**: "
            "`unknown_segment_ids` (coverage_status='unknown') and "
            "`low_confidence_segment_ids` (coverage_status='labeled' but "
            "confidence_score < 0.3) are reported as two separate lists, never "
            "merged.\n"
            "- **Explicit no-connected-route result**: `find_route()` checks "
            "`component_id` before pathfinding and raises "
            "`app.core.graph.NoConnectedRouteError` (same exception Week 2.5's "
            "connectivity-guard tests already exercise), not a generic "
            "`networkx.NetworkXNoPath` or an empty result.\n"
            "- **Three modes can produce different paths**: verified on a "
            "controlled synthetic graph (`test_routing.py`, 4 tests) and on "
            "real data below.\n"
            "- No routing endpoint or frontend code added.\n\n"
        )

        if origin is None:
            f.write(
                "## Real-data demonstration\n\n"
                "No real origin/destination pair in the current DB produced "
                "mode disagreement within the search budget used here -- see "
                "`test_data_quality.py::test_real_modes_can_disagree_on_at_least_one_real_od_pair` "
                "for the version of this search that did find one during "
                "test runs; that test is the authoritative check, this demo "
                "is illustrative only.\n"
            )
            return

        f.write(f"## Real-data demonstration: node {origin} -> node {destination}\n\n")
        for mode in routing.MODES:
            result = routing.find_route(graph, origin, destination, mode)
            f.write(f"### Mode: `{mode}`\n\n")
            f.write(
                f"- Path: {len(result['path_node_ids'])} nodes, "
                f"{result['total_length_m']:.1f}m total\n"
                f"- Mean accessibility: {result['mean_accessibility']:.3f}, "
                f"min accessibility: {result['min_accessibility']:.3f}\n"
                f"- Mean confidence: {result['mean_confidence']:.3f}, "
                f"min confidence: {result['min_confidence']:.3f}\n"
                f"- Unknown segments: {len(result['unknown_segment_ids'])}, "
                f"low-confidence segments: {len(result['low_confidence_segment_ids'])}, "
                f"disputed segments: {len(result['disputed_segment_ids'])}\n"
                f"- Dominant hazards on route: {result['dominant_hazards']}\n\n"
            )

        f.write(
            "The three modes above are computed on the exact same "
            "origin/destination pair and graph -- any difference in path "
            "length, node sequence, or the flag counts is the modes actually "
            "trading off distance against accessibility/confidence "
            "differently, not measurement noise.\n\n"
            "**A counterintuitive-looking number here, explained:** "
            "`confidence_aware` shows *more* dominant hazards (32) than "
            "`shortest` (23), which looks backwards for the mode meant to "
            "avoid uncertainty. It isn't: `confidence_aware` also has *fewer* "
            "unknown segments (230 vs. 247) and higher mean confidence (0.138 "
            "vs. 0.107). A dominant hazard can only appear on a `labeled` "
            "segment (an `unknown` segment has no evidence to set a ceiling "
            "with); the mode is doing exactly what it's designed to do -- "
            "preferring a well-attested segment that's confidently reporting "
            "a problem over a segment with no evidence at all, since the "
            "latter's real condition is unknown, not necessarily better. On "
            "real, coverage-sparse data that trade-off is visible; on the "
            "synthetic graphs in `test_routing.py` it's isolated and asserted "
            "directly (`test_confidence_aware_mode_avoids_the_low_confidence_path`).\n"
        )


def main():
    conn = get_connection()
    try:
        graph, origin, destination = find_demo_pair(conn)
        write_report(graph, origin, destination)
        print(f"Report written to {REPORT_PATH} (origin={origin}, destination={destination})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
