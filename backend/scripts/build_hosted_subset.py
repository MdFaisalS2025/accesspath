"""
Builds a graph-aware geographic subset of the AccessPath database for the
free-tier hosted demo (Neon + Render). This is a deliberate, reviewed,
manually-run step -- never run automatically, never part of the normal
local pipeline, and its output is never committed (see docs/deployment.md).

Subset selection, and why it is NOT one rectangle spanning both demo areas:
`modes_diverge` (Rainier Beach <-> Central Seattle) and `medium` (a separate,
~9km-away pair) are geographically distant from each other. A single
bounding rectangle covering both would include a large swath of irrelevant
area in between, wasting most of the space budget on data nobody will ever
route through in the hosted demo. Instead: compute all 3 routing modes for
BOTH frozen pairs against the FULL local graph (so whichever segments any
mode actually chooses are captured), union those 6 route geometries, and
buffer that union by BUFFER_RADIUS_M. Buffering (not just the bare route
lines) is what satisfies "enough surrounding network for meaningful
alternatives" -- without it, accessible/confidence_aware would have no
nearby parallel streets to choose from in the subset, artificially
collapsing whatever mode divergence the full dataset shows.

This script only READS from the source database and WRITES a portable JSON
file (data/hosted_subset/subset.json, gitignored). It never modifies the
source database, never fabricates or edits evidence, and never touches
scoring: segment_scores rows are copied verbatim from what
compute_scores.py already computed against the full dataset, not
recalculated -- the subset changes which segments are included, not how
any segment's score was derived.

Run inside the api container (needs the full local DB):
    docker compose exec api python scripts/build_hosted_subset.py
"""
import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app")
import networkx as nx

from app.core import routing
from app.core.db import get_connection
from app.core.route_service import fetch_segment_geometries

FROZEN_PAIRS_PATH = "/docs/week7_benchmark_pairs.json"
# Under /app (bind-mounted read-write from ./backend), not /data (mounted
# read-only in docker-compose.yml) -- this is a generated build artifact,
# gitignored (see backend/generated/ in .gitignore), never committed.
OUTPUT_DIR = "/app/generated/hosted_subset"
OUTPUT_PATH = f"{OUTPUT_DIR}/subset.json"

DEMO_CATEGORIES = ("modes_diverge", "medium")

# Wide enough to include a real parallel-street alternative near almost any
# point in Seattle's grid (typical block spacing is well under this), so
# accessible/confidence_aware retain a genuine choice in the subset, not
# just the exact segments the full-dataset routes happened to use.
BUFFER_RADIUS_M = 450


def load_frozen_pairs():
    with open(FROZEN_PAIRS_PATH, encoding="utf-8") as f:
        return json.load(f)["pairs"]


def collect_demo_route_segment_ids(conn, graph, pairs):
    """Runs all 3 modes for both demo pairs against the FULL graph and
    returns the union of every segment id any mode actually used."""
    segment_ids = set()
    routes_by_pair = {}
    for pair in pairs:
        if pair["category"] not in DEMO_CATEGORIES:
            continue
        origin_id = pair["origin"]["node_id"]
        destination_id = pair["destination"]["node_id"]
        routes_by_pair[pair["category"]] = {}
        for mode in routing.MODES:
            result = routing.find_route(graph, origin_id, destination_id, mode)
            routes_by_pair[pair["category"]][mode] = result
            for edge in result["segments"]:
                segment_ids.add(edge["segment_id"])
    return segment_ids, routes_by_pair


def buffered_union_wkt(conn, segment_ids, radius_m):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ST_AsText(
                ST_Buffer(
                    ST_Union(geom)::geography,
                    %s
                )::geometry
            )
            FROM segments WHERE id = ANY(%s)
            """,
            (radius_m, list(segment_ids)),
        )
        return cur.fetchone()[0]


def simplified_boundary_geojson(conn, buffer_wkt):
    """A coarser version of the same buffer polygon, for the frontend's
    coverage-boundary layer -- doesn't need survey precision, just needs to
    show roughly where the hosted subset's real data is. Simplified to keep
    this committed config file small (it ships in the repo, unlike the
    subset data dump itself)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ST_AsGeoJSON(ST_SimplifyPreserveTopology(ST_GeomFromText(%s, 4326), 0.0005))",
            (buffer_wkt,),
        )
        return json.loads(cur.fetchone()[0])


def select_subset_segment_ids(conn, buffer_wkt):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM segments WHERE ST_Intersects(geom, ST_GeomFromText(%s, 4326))",
            (buffer_wkt,),
        )
        return {row[0] for row in cur.fetchall()}


def fetch_subset_rows(conn, segment_ids):
    segment_ids = list(segment_ids)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, osm_way_id, from_node_id, to_node_id, ST_AsGeoJSON(geom),
                   length_m, highway_type, surface_tag, source, last_osm_edit
            FROM segments WHERE id = ANY(%s)
            """,
            (segment_ids,),
        )
        segments = [
            {
                "id": r[0], "osm_way_id": r[1], "from_node_id": r[2], "to_node_id": r[3],
                "geom_geojson": r[4], "length_m": r[5], "highway_type": r[6],
                "surface_tag": r[7], "source": r[8],
                "last_osm_edit": r[9].isoformat() if r[9] else None,
            }
            for r in cur.fetchall()
        ]

        node_ids = sorted({s["from_node_id"] for s in segments} | {s["to_node_id"] for s in segments})
        cur.execute(
            "SELECT id, osm_node_id, ST_AsGeoJSON(geom), is_crossing, kerb_type FROM nodes WHERE id = ANY(%s)",
            (node_ids,),
        )
        nodes = [
            {"id": r[0], "osm_node_id": r[1], "geom_geojson": r[2], "is_crossing": r[3], "kerb_type": r[4]}
            for r in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT id, ps_label_id, segment_id, ST_AsGeoJSON(geom), label_type, severity,
                   agree_count, disagree_count, unsure_count, region_name, label_date,
                   osm_way_id_hint, match_method, match_distance_m,
                   second_match_segment_id, second_match_distance_m, ambiguous_match,
                   pano_id, ps_user_id
            FROM accessibility_labels WHERE segment_id = ANY(%s)
            """,
            (segment_ids,),
        )
        subset_segment_id_set = set(segment_ids)
        labels = []
        for r in cur.fetchall():
            second_match_segment_id = r[14] if r[14] in subset_segment_id_set else None
            labels.append({
                "id": r[0], "ps_label_id": r[1], "segment_id": r[2], "geom_geojson": r[3],
                "label_type": r[4], "severity": r[5], "agree_count": r[6], "disagree_count": r[7],
                "unsure_count": r[8], "region_name": r[9],
                "label_date": r[10].isoformat() if r[10] else None,
                "osm_way_id_hint": r[11], "match_method": r[12], "match_distance_m": r[13],
                # nulled if the second-nearest candidate falls outside the subset --
                # it's a diagnostic ambiguity trace, not load-bearing for scoring or
                # routing, and pointing at a segment absent from this subset's
                # database would violate the FK it's declared with in schema.sql.
                "second_match_segment_id": second_match_segment_id,
                "second_match_distance_m": r[15] if second_match_segment_id is not None else None,
                "ambiguous_match": r[16], "pano_id": r[17], "ps_user_id": r[18],
            })

        cur.execute(
            """
            SELECT segment_id, accessibility_score, confidence_score, coverage_status,
                   label_count, staleness_days, positive_evidence, negative_evidence,
                   evidence_consistency, dominant_hazard_type, dominant_hazard_ps_label_id
            FROM segment_scores WHERE segment_id = ANY(%s)
            """,
            (segment_ids,),
        )
        scores = [
            {
                "segment_id": r[0], "accessibility_score": r[1], "confidence_score": r[2],
                "coverage_status": r[3], "label_count": r[4], "staleness_days": r[5],
                "positive_evidence": r[6], "negative_evidence": r[7], "evidence_consistency": r[8],
                "dominant_hazard_type": r[9], "dominant_hazard_ps_label_id": r[10],
            }
            for r in cur.fetchall()
        ]

    return nodes, segments, labels, scores


def recompute_component_ids(nodes, segments):
    """Same algorithm as scripts/build_graph.py's verify_connectivity(), run
    against only the subset's own nodes/edges -- cutting most of Seattle away
    necessarily splits some full-dataset components further, so component_id
    must be recomputed for the subset, not copied from the full dataset."""
    g = nx.Graph()
    g.add_nodes_from(n["id"] for n in nodes)
    for s in segments:
        g.add_edge(s["from_node_id"], s["to_node_id"], weight=s["length_m"])

    components = sorted(nx.connected_components(g), key=len, reverse=True)
    component_of = {node_id: cid for cid, comp in enumerate(components) for node_id in comp}
    for n in nodes:
        n["component_id"] = component_of.get(n["id"])
    return len(components), components[0] if components else set()


def build_subset_graph(nodes, segments, scores):
    """Reconstructs an in-memory graph identical in shape to
    routing.load_routing_graph()'s output, but from the exported subset
    rows directly -- no DB round trip -- so the subset can be validated
    (this script) with the exact same routing.find_route() the real API
    uses, before anything is imported anywhere."""
    scores_by_segment = {s["segment_id"]: s for s in scores}
    g = nx.Graph()
    for n in nodes:
        lon, lat = json.loads(n["geom_geojson"])["coordinates"]
        g.add_node(n["id"], component_id=n["component_id"], lat=lat, lon=lon)
    for s in segments:
        sc = scores_by_segment.get(s["id"])
        if sc is None:
            continue
        g.add_edge(
            s["from_node_id"], s["to_node_id"],
            segment_id=s["id"], length_m=s["length_m"], highway_type=s["highway_type"],
            accessibility_score=sc["accessibility_score"], confidence_score=sc["confidence_score"],
            coverage_status=sc["coverage_status"], dominant_hazard_type=sc["dominant_hazard_type"],
            evidence_consistency=sc["evidence_consistency"],
        )
    return g


def validate_subset(subset_graph, pairs):
    """Confirms, using the SAME routing.find_route() the API uses (not a
    hand-rolled check), that: both demo pairs still resolve to a real route
    for all 3 modes, and modes_diverge still shows real mode divergence
    (not collapsed to identical paths by the subset cut)."""
    report = {}
    for pair in pairs:
        if pair["category"] not in DEMO_CATEGORIES:
            continue
        origin_id = pair["origin"]["node_id"]
        destination_id = pair["destination"]["node_id"]
        results = {}
        for mode in routing.MODES:
            result = routing.find_route(subset_graph, origin_id, destination_id, mode)
            results[mode] = result
        distinct_paths = len({tuple(r["path_node_ids"]) for r in results.values()})
        report[pair["category"]] = {
            "status": "ok",
            "distances_m": {m: r["total_length_m"] for m, r in results.items()},
            "modes_all_identical": distinct_paths == 1,
        }
    return report


def main():
    conn = get_connection()
    try:
        print("Loading FULL routing graph (source database)...")
        full_graph = routing.load_routing_graph(conn)
        pairs = load_frozen_pairs()

        print(f"Computing all 3 modes for {DEMO_CATEGORIES} against the full graph...")
        route_segment_ids, _ = collect_demo_route_segment_ids(conn, full_graph, pairs)
        print(f"  {len(route_segment_ids)} distinct segments used across both pairs' 3 modes each")

        print(f"Buffering union of those routes by {BUFFER_RADIUS_M}m...")
        buffer_wkt = buffered_union_wkt(conn, route_segment_ids, BUFFER_RADIUS_M)

        print("Selecting all segments intersecting the buffer...")
        subset_segment_ids = select_subset_segment_ids(conn, buffer_wkt)
        print(f"  {len(subset_segment_ids)} segments in subset (of {full_graph.number_of_edges()} total)")

        boundary_geojson = simplified_boundary_geojson(conn, buffer_wkt)

        print("Fetching subset rows (nodes, segments, labels, scores)...")
        nodes, segments, labels, scores = fetch_subset_rows(conn, subset_segment_ids)
        print(f"  nodes={len(nodes)} segments={len(segments)} labels={len(labels)} scores={len(scores)}")

        print("Recomputing component_id for the subset...")
        num_components, largest = recompute_component_ids(nodes, segments)
        print(f"  {num_components} components in subset; largest has {len(largest)} nodes "
              f"({len(largest) / len(nodes) * 100:.1f}% of subset nodes)")

        print("Validating subset routing (same routing.find_route() the API uses)...")
        subset_graph = build_subset_graph(nodes, segments, scores)
        validation = validate_subset(subset_graph, pairs)
        for category, result in validation.items():
            divergence_note = "DIVERGES across modes" if not result["modes_all_identical"] else "all 3 modes identical"
            print(f"  {category}: OK, {divergence_note}, distances={result['distances_m']}")

        modes_diverge_ok = not validation.get("modes_diverge", {}).get("modes_all_identical", True)
        if not modes_diverge_ok:
            print("\nWARNING: modes_diverge no longer shows mode divergence in the subset.")
            print("Per this task's instructions, this should be reported as a blocker, not")
            print("silently deployed. Consider increasing BUFFER_RADIUS_M and re-running.")

        import os
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        # Small, committed config (boundary polygon + disclosure text only --
        # no label/segment/score data) that app.main reads at startup when
        # DEPLOYMENT_MODE=hosted_subset, to serve GET /deployment-info for
        # the frontend's coverage banner and boundary layer. Separate from
        # the big gitignored subset.json dump above on purpose.
        coverage_config_path = "/app/app/deployment_config/hosted_subset_coverage.json"
        os.makedirs(os.path.dirname(coverage_config_path), exist_ok=True)
        with open(coverage_config_path, "w", encoding="utf-8") as f:
            json.dump({
                "mode": "hosted_subset",
                "message": (
                    "Hosted demo coverage is limited to selected Seattle areas. "
                    "The local project supports the full Seattle dataset."
                ),
                "coverage_boundary": boundary_geojson,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "demo_categories": list(DEMO_CATEGORIES),
            }, f, indent=2)
        print(f"Coverage config (committed, small) written to {coverage_config_path}")

        output = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "AccessPath full local database (not committed; regenerate via this script)",
            "buffer_radius_m": BUFFER_RADIUS_M,
            "demo_categories": list(DEMO_CATEGORIES),
            "counts": {"nodes": len(nodes), "segments": len(segments), "labels": len(labels), "scores": len(scores)},
            "num_components": num_components,
            "largest_component_size": len(largest),
            "validation": validation,
            "nodes": nodes,
            "segments": segments,
            "labels": labels,
            "scores": scores,
        }
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(output, f)
        import os as _os
        size_mb = _os.path.getsize(OUTPUT_PATH) / (1024 * 1024)
        print(f"\nWritten to {OUTPUT_PATH} ({size_mb:.1f} MB)")

        if not modes_diverge_ok:
            sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
