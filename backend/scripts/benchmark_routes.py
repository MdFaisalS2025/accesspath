"""
Week 7: reproducible benchmark set + in-process performance measurement.

Selects 8 origin/destination pairs by category (documented rationale in
each `select_*` function, not chosen after seeing results), resolves them
to real coordinates, and measures each of the three modes' routing
computation time, weight-function-call count (a proxy for search-space
size -- see routing.find_route's docstring), path distance, and
accessibility/confidence summary, run in-process against the same graph
`load_routing_graph()` builds for the real API (not a toy graph).

This script measures *routing computation* only (in-process, no HTTP, no
DB round-trip per request). Total API latency, process memory, and
cold-vs-warm behavior are measured separately by
scripts/benchmark_http.sh against the live server, since those require an
actual running process and container restarts. See
docs/week7_hardening_report.md for the combined results.

Run inside the api container:
    docker compose exec api python scripts/benchmark_routes.py
"""
import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app")
from app.core import routing
from app.core.db import get_connection
from app.core.graph import NoConnectedRouteError

OUTPUT_PATH = "/docs/week7_benchmark_pairs.json"


def fetch_coords(conn, node_id):
    with conn.cursor() as cur:
        cur.execute("SELECT ST_Y(geom), ST_X(geom) FROM nodes WHERE id = %s", (node_id,))
        lat, lon = cur.fetchone()
        return {"node_id": node_id, "lat": lat, "lon": lon}


def _select_by_geographic_distance(conn, target_m, tolerance_m):
    """Picks a fixed anchor node (first component-0 node by id, for
    reproducibility) and a second node at approximately target_m from it
    (+-tolerance_m), using real geography, not id-order proximity -- an
    earlier version of this script used id-order gaps as a distance proxy
    and it was wrong: two nodes at opposite ends of the id range turned out
    to be 5m apart geographically. Distance is the only thing that defines
    "short"/"medium"/"long" here, so it must be measured directly."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, geom FROM nodes WHERE component_id = 0 ORDER BY id LIMIT 1")
        anchor_id, anchor_geom = cur.fetchone()
        cur.execute(
            """
            SELECT id FROM nodes
            WHERE component_id = 0
              AND ST_Distance(geom::geography, %s::geography) BETWEEN %s AND %s
            ORDER BY id
            LIMIT 1
            """,
            (anchor_geom, target_m - tolerance_m, target_m + tolerance_m),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"no node found within {target_m}+-{tolerance_m}m of anchor {anchor_id}")
        return anchor_id, row[0]


def select_short(conn):
    """~300m apart by real geography -- a short, local hop."""
    return _select_by_geographic_distance(conn, target_m=300, tolerance_m=100)


def select_medium(conn):
    """~3km apart by real geography."""
    return _select_by_geographic_distance(conn, target_m=3000, tolerance_m=500)


def select_long(conn):
    """~12km apart by real geography -- close to Seattle's own diagonal
    extent, a genuinely long cross-city trip."""
    return _select_by_geographic_distance(conn, target_m=12000, tolerance_m=1500)


def select_well_labeled(conn):
    """Endpoints of two segments that both have many matched labels
    (label_count-like: many rows in accessibility_labels) -- an area with
    substantial real evidence, not sparse/unknown coverage."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.from_node_id, s.to_node_id, count(*) AS n
            FROM accessibility_labels l
            JOIN segments s ON s.id = l.segment_id
            JOIN nodes n1 ON n1.id = s.from_node_id
            WHERE n1.component_id = 0
            GROUP BY s.id, s.from_node_id, s.to_node_id
            ORDER BY n DESC
            LIMIT 2
            """
        )
        rows = cur.fetchall()
    return rows[0][0], rows[1][1]


def select_heavy_unknown(conn):
    """Endpoints of two segments with coverage_status='unknown' -- a route
    through an area with little to no accessibility evidence."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.from_node_id, s.to_node_id
            FROM segment_scores sc
            JOIN segments s ON s.id = sc.segment_id
            JOIN nodes n1 ON n1.id = s.from_node_id
            WHERE sc.coverage_status = 'unknown' AND n1.component_id = 0
            ORDER BY s.id
            LIMIT 2
            """
        )
        rows = cur.fetchall()
    return rows[0][0], rows[1][1]


def select_cross_component(conn):
    """One node in the largest component, one in the second-largest --
    expected to produce an explicit no_connected_route result, not a path."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM nodes WHERE component_id = 0 ORDER BY id LIMIT 1")
        origin = cur.fetchone()[0]
        cur.execute("SELECT id FROM nodes WHERE component_id = 1 ORDER BY id LIMIT 1")
        destination = cur.fetchone()[0]
    return origin, destination


def select_modes_agree_candidates(conn):
    """Several short-range candidates (same fixed anchor node, several
    nearby destinations at increasing small radii) to search for one where
    all three modes genuinely produce the identical path -- short distance
    alone doesn't guarantee this (a single hazard on an otherwise-short hop
    is enough to make accessible/confidence_aware detour), so this has to
    be verified, not assumed, same as modes_diverge below."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, geom FROM nodes WHERE component_id = 0 ORDER BY id LIMIT 1")
        anchor_id, anchor_geom = cur.fetchone()
        cur.execute(
            """
            SELECT id FROM nodes
            WHERE component_id = 0 AND id != %s
              AND ST_Distance(geom::geography, %s::geography) BETWEEN 20 AND 400
            ORDER BY ST_Distance(geom::geography, %s::geography)
            LIMIT 30
            """,
            (anchor_id, anchor_geom, anchor_geom),
        )
        return [(anchor_id, row[0]) for row in cur.fetchall()]


def select_modes_diverge_candidate(conn):
    """A node near a very accessible, confident segment paired with a node
    near a poor-accessibility segment -- the same pattern that produced
    real mode disagreement in the Week 4/5 demos (docs/week4_routing_report.md)."""
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
        return cur.fetchall()


def build_pairs(conn, graph):
    pairs = {}
    pairs["short"] = select_short(conn)
    pairs["medium"] = select_medium(conn)
    pairs["long"] = select_long(conn)
    pairs["well_labeled_area"] = select_well_labeled(conn)
    pairs["heavy_unknown_coverage"] = select_heavy_unknown(conn)
    pairs["cross_component"] = select_cross_component(conn)

    # modes_agree / modes_diverge are qualified empirically: candidates are
    # selected by a structural rule (above), then checked against the real
    # graph for the property that defines the category (all 3 paths equal,
    # or not) -- a factual check of the category's own definition, not a
    # result-quality filter chosen after seeing accessibility/confidence
    # numbers. First candidate meeting the structural criteria is used; not
    # cherry-picked among many for a flattering outcome.
    pairs["modes_agree"] = None
    for origin, destination in select_modes_agree_candidates(conn):
        try:
            agree_paths = {m: tuple(routing.find_route(graph, origin, destination, m)["path_node_ids"]) for m in routing.MODES}
        except NoConnectedRouteError:
            continue
        if len(set(agree_paths.values())) == 1:
            pairs["modes_agree"] = (origin, destination)
            break
    if pairs["modes_agree"] is None:
        raise RuntimeError("no modes_agree candidate found within search radius -- widen select_modes_agree_candidates")

    candidates = select_modes_diverge_candidate(conn)
    pairs["modes_diverge"] = None
    for origin, destination in candidates:
        if origin == destination:
            continue
        try:
            results = {m: routing.find_route(graph, origin, destination, m) for m in routing.MODES}
        except (NoConnectedRouteError, Exception):
            continue
        geoms = {m: tuple(r["path_node_ids"]) for m, r in results.items()}
        if len(set(geoms.values())) > 1:
            pairs["modes_diverge"] = (origin, destination)
            break
    if pairs["modes_diverge"] is None:
        pairs["modes_diverge"] = pairs["long"]

    return pairs


def measure_pair(conn, graph, category, origin_id, destination_id):
    origin = fetch_coords(conn, origin_id)
    destination = fetch_coords(conn, destination_id)
    result = {"category": category, "origin": origin, "destination": destination, "modes": {}}

    try:
        origin_component = graph.nodes[origin_id]["component_id"]
        destination_component = graph.nodes[destination_id]["component_id"]
    except KeyError:
        origin_component = destination_component = None

    if origin_component != destination_component:
        result["status"] = "no_connected_route"
        result["origin_component_id"] = origin_component
        result["destination_component_id"] = destination_component
        return result

    result["status"] = "ok"
    path_signatures = {}
    for mode in routing.MODES:
        stats = {}
        route = routing.find_route(graph, origin_id, destination_id, mode, stats=stats)
        path_signatures[mode] = tuple(route["path_node_ids"])
        result["modes"][mode] = {
            "elapsed_s": stats["elapsed_s"],
            "weight_evaluations": stats["weight_evaluations"],
            "distance_m": route["total_length_m"],
            "mean_accessibility": route["mean_accessibility"],
            "mean_confidence": route["mean_confidence"],
            "segment_count": len(route["segments"]),
            "unknown_segments": len(route["unknown_segment_ids"]),
            "dominant_hazards": len(route["dominant_hazards"]),
        }
    result["modes_all_identical"] = len(set(path_signatures.values())) == 1
    return result


def main():
    conn = get_connection()
    try:
        print("Loading routing graph...")
        graph = routing.load_routing_graph(conn)
        print(f"  {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")

        print("Selecting benchmark pairs...")
        pairs = build_pairs(conn, graph)

        results = []
        for category, (origin_id, destination_id) in pairs.items():
            print(f"Measuring {category}: {origin_id} -> {destination_id}")
            results.append(measure_pair(conn, graph, category, origin_id, destination_id))

        output = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "graph_nodes": graph.number_of_nodes(),
            "graph_edges": graph.number_of_edges(),
            "pairs": results,
        }
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
        print(f"Written to {OUTPUT_PATH}")

        for r in results:
            print(f"\n{r['category']}: status={r['status']}")
            if r["status"] == "ok":
                for mode, m in r["modes"].items():
                    print(f"  {mode}: {m['elapsed_s']*1000:.2f}ms, {m['weight_evaluations']} weight evals, "
                          f"{m['distance_m']:.0f}m, acc={m['mean_accessibility']}, conf={m['mean_confidence']}")
                print(f"  modes_all_identical={r['modes_all_identical']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
