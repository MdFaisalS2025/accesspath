"""
Week 2: loads the Week 1 raw extracts (docs/data_verification.md) into
Postgres, joins Project Sidewalk labels to OSM segments, and verifies the
routing graph is connected.

Run inside the api container, where /data is the mounted data/ directory
and DATABASE_URL points at the db service:

    docker compose exec api python scripts/build_graph.py

Does not compute accessibility/confidence scores or anything CV/slope
related — that's later work. This is graph construction + label join +
connectivity verification only.
"""
import sys
from collections import defaultdict

import ijson
import networkx as nx
import psycopg2.extras

sys.path.insert(0, "/app")
from app.core import matching
from app.core.db import get_connection

OSM_PATH = "/data/raw/osm_seattle_pedestrian.json"
LABELS_PATH = "/data/raw/sidewalk_labels_seattle.json"
REPORT_PATH = "/docs/week2_graph_report.md"

PEDESTRIAN_HIGHWAYS = {"footway", "path", "pedestrian", "steps"}


def load_osm(path):
    """Streams the Overpass extract. Returns (tagged_nodes, ways).

    tagged_nodes: {osm_node_id: {"lat", "lon", "tags"}} for kerb=* / crossing nodes.
    ways: [{"id", "tags", "nodes": [osm_node_id...], "coords": [(lon, lat)...]}]
    """
    tagged_nodes = {}
    ways = []
    with open(path, "rb") as f:
        for el in ijson.items(f, "elements.item"):
            if el["type"] == "node":
                tags = el.get("tags", {})
                if "kerb" in tags or tags.get("highway") == "crossing":
                    tagged_nodes[el["id"]] = {
                        "lat": el["lat"],
                        "lon": el["lon"],
                        "tags": tags,
                    }
            elif el["type"] == "way":
                tags = el.get("tags", {})
                if tags.get("highway") in PEDESTRIAN_HIGHWAYS or tags.get("footway") == "crossing":
                    ways.append(
                        {
                            "id": el["id"],
                            "tags": tags,
                            "nodes": el["nodes"],
                            "coords": [(g["lon"], g["lat"]) for g in el["geometry"]],
                        }
                    )
    return tagged_nodes, ways


def compute_graph_node_ids(ways, tagged_nodes):
    """Vertices worth materializing: way endpoints, true intersections
    (nodes shared by 2+ ways), and any explicitly kerb/crossing-tagged node."""
    way_membership = defaultdict(int)
    for way in ways:
        for nid in set(way["nodes"]):
            way_membership[nid] += 1

    graph_node_ids = set(tagged_nodes)
    for way in ways:
        graph_node_ids.add(way["nodes"][0])
        graph_node_ids.add(way["nodes"][-1])
    for nid, count in way_membership.items():
        if count >= 2:
            graph_node_ids.add(nid)
    return graph_node_ids


def collect_node_coords(ways):
    coords = {}
    for way in ways:
        for nid, xy in zip(way["nodes"], way["coords"]):
            coords[nid] = xy
    return coords


def split_way_into_segments(way, graph_node_ids):
    nodes = way["nodes"]
    coords = way["coords"]
    split_idx = [i for i, nid in enumerate(nodes) if nid in graph_node_ids]

    highway_type = "crossing" if way["tags"].get("footway") == "crossing" else way["tags"].get("highway")
    surface = way["tags"].get("surface")

    segments = []
    for a, b in zip(split_idx, split_idx[1:]):
        seg_coords = coords[a : b + 1]
        if len(seg_coords) < 2:
            continue
        segments.append(
            {
                "way_id": way["id"],
                "from_osm_node": nodes[a],
                "to_osm_node": nodes[b],
                "coords": seg_coords,
                "highway_type": highway_type,
                "surface_tag": surface,
            }
        )
    return segments


def linestring_wkt(coords):
    return "LINESTRING(" + ",".join(f"{lon} {lat}" for lon, lat in coords) + ")"


def load_nodes(conn, graph_node_ids, node_coords, tagged_nodes):
    rows = []
    for nid in graph_node_ids:
        if nid in node_coords:
            lon, lat = node_coords[nid]
        elif nid in tagged_nodes:
            lon, lat = tagged_nodes[nid]["lon"], tagged_nodes[nid]["lat"]
        else:
            continue
        tags = tagged_nodes.get(nid, {}).get("tags", {})
        rows.append(
            (
                nid,
                f"POINT({lon} {lat})",
                tags.get("highway") == "crossing",
                tags.get("kerb"),
            )
        )

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO nodes (osm_node_id, geom, is_crossing, kerb_type)
            VALUES %s
            ON CONFLICT (osm_node_id) DO NOTHING
            """,
            rows,
            template="(%s, ST_SetSRID(ST_GeomFromText(%s), 4326), %s, %s)",
            page_size=5000,
        )
        cur.execute("SELECT osm_node_id, id FROM nodes")
        osm_to_db = dict(cur.fetchall())
    conn.commit()
    return osm_to_db


def load_segments(conn, ways, graph_node_ids, osm_to_db):
    rows = []
    skipped_missing_node = 0
    for way in ways:
        for seg in split_way_into_segments(way, graph_node_ids):
            from_id = osm_to_db.get(seg["from_osm_node"])
            to_id = osm_to_db.get(seg["to_osm_node"])
            if from_id is None or to_id is None:
                skipped_missing_node += 1
                continue
            rows.append(
                (
                    seg["way_id"],
                    from_id,
                    to_id,
                    linestring_wkt(seg["coords"]),
                    seg["highway_type"],
                    seg["surface_tag"],
                )
            )

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO segments (osm_way_id, from_node_id, to_node_id, geom, length_m, highway_type, surface_tag)
            VALUES %s
            """,
            rows,
            template="(%s, %s, %s, ST_SetSRID(ST_GeomFromText(%s), 4326), 0, %s, %s)",
            page_size=5000,
        )
        cur.execute("UPDATE segments SET length_m = ST_Length(geom::geography)")
    conn.commit()
    return len(rows), skipped_missing_node


def load_labels(conn, path):
    rows = []
    with open(path, "rb") as f:
        for feat in ijson.items(f, "features.item"):
            props = feat["properties"]
            lon, lat = feat["geometry"]["coordinates"]
            rows.append(
                (
                    props["label_id"],
                    f"POINT({lon} {lat})",
                    props["label_type"],
                    props.get("severity"),
                    props.get("agree_count", 0),
                    props.get("disagree_count", 0),
                    props.get("unsure_count", 0),
                    props.get("region_name"),
                    props.get("time_created"),
                    props.get("osm_way_id"),
                )
            )

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO accessibility_labels
                (ps_label_id, geom, label_type, severity, agree_count, disagree_count,
                 unsure_count, region_name, label_date, osm_way_id_hint)
            VALUES %s
            ON CONFLICT (ps_label_id) DO NOTHING
            """,
            rows,
            template="(%s, ST_SetSRID(ST_GeomFromText(%s), 4326), %s, %s, %s, %s, %s, %s, %s, %s)",
            page_size=5000,
        )
    conn.commit()
    return len(rows)


def join_labels_to_segments(conn):
    with conn.cursor() as cur:
        # 1) Direct osm_way_id match (Section 9 of the planning doc): where the
        # way was split into multiple segments, pick the nearest one.
        cur.execute(
            """
            UPDATE accessibility_labels l
            SET segment_id = m.segment_id,
                match_method = 'ps_osm_way_id',
                match_distance_m = m.d
            FROM (
                SELECT DISTINCT ON (l2.id)
                    l2.id AS label_id, s.id AS segment_id,
                    ST_Distance(l2.geom::geography, s.geom::geography) AS d
                FROM accessibility_labels l2
                JOIN segments s ON s.osm_way_id = l2.osm_way_id_hint
                ORDER BY l2.id, d
            ) m
            WHERE l.id = m.label_id
            """
        )
        matched_by_id = cur.rowcount
    conn.commit()

    # 2) Nearest-segment spatial match for everything osm_way_id didn't
    # resolve, using the validated threshold/ambiguity logic from Week 2.5
    # (see app.core.matching and docs/week2_graph_report.md — a plain 30m
    # threshold was found to silently attach `NoSidewalk` labels to whatever
    # footway happened to be nearby, which is wrong by construction since
    # those labels mark the *absence* of a sidewalk).
    matching.build_nearest_candidates(conn)
    matched_by_nearest, unmatched = matching.apply_final_match(conn)
    return matched_by_id, matched_by_nearest, unmatched


def verify_connectivity(conn):
    g = nx.Graph()
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM nodes")
        g.add_nodes_from(row[0] for row in cur.fetchall())
        cur.execute("SELECT from_node_id, to_node_id, length_m FROM segments")
        for from_id, to_id, length_m in cur.fetchall():
            g.add_edge(from_id, to_id, weight=length_m)

    components = sorted(nx.connected_components(g), key=len, reverse=True)
    largest = components[0] if components else set()
    isolated = list(nx.isolates(g))

    # Persist an explicit component id per node (0 = largest) so routing can
    # reject a cross-component origin/destination pair with a clear error
    # instead of a silent pathfinding failure — see app.core.graph.
    with conn.cursor() as cur:
        rows = [(cid, node_id) for cid, comp in enumerate(components) for node_id in comp]
        psycopg2.extras.execute_values(
            cur,
            "UPDATE nodes AS n SET component_id = v.component_id FROM (VALUES %s) AS v(component_id, node_id) WHERE n.id = v.node_id",
            rows,
            page_size=5000,
        )
    conn.commit()

    return {
        "num_nodes": g.number_of_nodes(),
        "num_edges": g.number_of_edges(),
        "num_components": len(components),
        "largest_component_size": len(largest),
        "largest_component_fraction": len(largest) / g.number_of_nodes() if g.number_of_nodes() else 0,
        "component_sizes_top10": [len(c) for c in components[:10]],
        "num_isolated_nodes": len(isolated),
    }


def write_report(stats, label_stats):
    matched_by_id, matched_by_nearest, unmatched = label_stats
    total_labels = matched_by_id + matched_by_nearest + unmatched
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("# Week 2 — Graph Build & Label Join Report\n\n")
        f.write("## Graph connectivity\n\n")
        f.write(f"- Nodes: {stats['num_nodes']}\n")
        f.write(f"- Edges (segments): {stats['num_edges']}\n")
        f.write(f"- Connected components: {stats['num_components']}\n")
        f.write(
            f"- Largest component: {stats['largest_component_size']} nodes "
            f"({stats['largest_component_fraction']:.4%} of all nodes)\n"
        )
        f.write(f"- Top 10 component sizes: {stats['component_sizes_top10']}\n")
        f.write(f"- Isolated nodes (degree 0): {stats['num_isolated_nodes']}\n\n")
        f.write(
            "Edge count is deduplicated (networkx `Graph` collapses parallel edges "
            "between the same two nodes), so it can be slightly below the raw segment "
            "count. The ~18% of nodes outside the largest component are mostly small "
            "disconnected clusters (e.g. isolated courtyard paths, a footway that ends "
            "at a crossing node not shared with the road network) rather than one large "
            "second region — see the component-size list above. Each node's "
            "`component_id` (0 = largest) is persisted for routing to use. See "
            "the Week 2.5 section below for a deeper look at whether the smaller "
            "components are legitimate or data artifacts.\n\n"
        )
        f.write("## Project Sidewalk label join\n\n")
        f.write(f"- Total labels loaded: {total_labels}\n")
        f.write(f"- Matched via `osm_way_id` (Project Sidewalk's own join): {matched_by_id}\n")
        f.write(
            f"- Matched via nearest-segment fallback (<= {matching.PRODUCTION_MATCH_THRESHOLD_M:.0f}m, "
            f"validated in Week 2.5 below): {matched_by_nearest}\n"
        )
        f.write(f"- Unmatched: {unmatched}\n\n")
        f.write(
            "**Finding, contradicting the Week 1 plan (docs/data_verification.md):** "
            "`osm_way_id` on Project Sidewalk labels almost never matches a way in our "
            "pedestrian extract (footway/path/pedestrian/steps/footway=crossing) — only "
            f"{matched_by_id} of {total_labels} labels. Spot-checking confirms PS's "
            "`osm_way_id` is the *street* way each label's `street_edge_id` was derived "
            "from, not a dedicated sidewalk/footway way. The nearest-segment spatial join "
            "is therefore the primary matching method in practice, not a fallback for "
            "edge cases as the Week 1 doc assumed; the ID join is kept first since it is "
            "authoritative on the rare occasions it does resolve.\n"
        )


def main():
    print("Loading OSM extract...")
    tagged_nodes, ways = load_osm(OSM_PATH)
    print(f"  {len(tagged_nodes)} tagged nodes, {len(ways)} pedestrian ways")

    node_coords = collect_node_coords(ways)
    graph_node_ids = compute_graph_node_ids(ways, tagged_nodes)
    print(f"  {len(graph_node_ids)} graph vertices identified")

    conn = get_connection()
    try:
        print("Loading nodes...")
        osm_to_db = load_nodes(conn, graph_node_ids, node_coords, tagged_nodes)
        print(f"  {len(osm_to_db)} nodes in DB")

        print("Loading segments...")
        num_segments, skipped = load_segments(conn, ways, graph_node_ids, osm_to_db)
        print(f"  {num_segments} segments inserted ({skipped} skipped for missing node coords)")

        print("Loading Project Sidewalk labels...")
        num_labels = load_labels(conn, LABELS_PATH)
        print(f"  {num_labels} labels inserted")

        print("Joining labels to segments...")
        label_stats = join_labels_to_segments(conn)
        print(f"  matched by osm_way_id: {label_stats[0]}, nearest fallback: {label_stats[1]}, unmatched: {label_stats[2]}")

        print("Verifying graph connectivity...")
        stats = verify_connectivity(conn)
        print(f"  {stats['num_components']} connected components; largest = {stats['largest_component_fraction']:.4%} of nodes")

        write_report(stats, label_stats)
        print(f"Report written to {REPORT_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
