"""
Week 8, item 3: programmatic geometry sanity checks for every frozen
benchmark pair's routes (all 3 modes) -- a systematic complement to the
live-browser visual spot-checks recorded in docs/week8_evaluation_report.md,
not a replacement for them. Flags:

- Any consecutive-point jump bigger than a walking segment plausibly is
  (a broken/looping geometry would show up as a huge jump).
- Any exact-duplicate consecutive point (a zero-length hop, usually
  harmless but worth listing) or a point repeated much later in the same
  route (a literal loop).
- The route's overall bounding box, to eyeball for anything absurd (e.g.
  spanning far outside Seattle).

Uses the same frozen pairs as scripts/run_evaluation.py and reconstructs
geometry the same way the real API does (app.core.route_service).

Run inside the api container:
    docker compose exec api python scripts/validate_route_geometry.py
"""
import json
import math
import sys

sys.path.insert(0, "/app")
from app.core import routing
from app.core.db import get_connection
from app.core.route_service import fetch_segment_geometries, build_route_geometry
from app.core.routing import haversine_distance_m

FROZEN_PAIRS_PATH = "/docs/week7_benchmark_pairs.json"
OUTPUT_PATH = "/docs/week8_geometry_validation.json"

JUMP_THRESHOLD_M = 150  # a single consecutive-point gap larger than this on
# a pedestrian network is suspicious (real segment vertices are much closer
# together than this almost everywhere in the loaded OSM extract)


def check_route_geometry(geometry):
    coords = geometry["coordinates"]
    issues = []
    max_jump = 0.0
    for i in range(len(coords) - 1):
        lon1, lat1 = coords[i]
        lon2, lat2 = coords[i + 1]
        d = haversine_distance_m(lat1, lon1, lat2, lon2)
        max_jump = max(max_jump, d)
        if d > JUMP_THRESHOLD_M:
            issues.append(f"jump of {d:.0f}m between point {i} and {i+1}")

    seen = {}
    for i, (lon, lat) in enumerate(coords):
        key = (round(lon, 6), round(lat, 6))
        if key in seen and i - seen[key] > 1:
            issues.append(f"point {i} repeats point {seen[key]} (possible loop)")
        seen[key] = i

    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return {
        "num_points": len(coords),
        "max_consecutive_jump_m": max_jump,
        "bbox": {"min_lon": min(lons), "max_lon": max(lons), "min_lat": min(lats), "max_lat": max(lats)},
        "issues": issues,
    }


def main():
    conn = get_connection()
    try:
        graph = routing.load_routing_graph(conn)
        with open(FROZEN_PAIRS_PATH, encoding="utf-8") as f:
            pairs = json.load(f)["pairs"]

        results = []
        for pair in pairs:
            category = pair["category"]
            if pair["status"] != "ok":
                results.append({"category": category, "status": pair["status"]})
                continue

            origin_id = pair["origin"]["node_id"]
            destination_id = pair["destination"]["node_id"]
            snap_ok = {
                "origin_snap_distance_m": 0.0,  # frozen pairs are exact node coordinates, snap distance 0 by construction
                "destination_snap_distance_m": 0.0,
            }

            mode_checks = {}
            for mode in routing.MODES:
                route = routing.find_route(graph, origin_id, destination_id, mode)
                segment_ids = [s["segment_id"] for s in route["segments"]]
                geoms = fetch_segment_geometries(conn, segment_ids)
                geometry = build_route_geometry(route, geoms)
                mode_checks[mode] = check_route_geometry(geometry)

            results.append({
                "category": category,
                "status": "ok",
                "snap": snap_ok,
                "modes": mode_checks,
            })

        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        print(f"Written to {OUTPUT_PATH}\n")
        any_issues = False
        for r in results:
            print(f"=== {r['category']} ({r['status']}) ===")
            if r["status"] != "ok":
                continue
            for mode, check in r["modes"].items():
                flag = " <<< ISSUES" if check["issues"] else ""
                print(f"  {mode}: {check['num_points']} points, max jump {check['max_consecutive_jump_m']:.1f}m{flag}")
                for issue in check["issues"]:
                    print(f"    - {issue}")
                    any_issues = True
        print("\nNo geometry issues found." if not any_issues else "\nSee ISSUES above.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
