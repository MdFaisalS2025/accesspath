"""
Week 5: orchestrates POST /route/compare. Kept separate from
app/routers/route.py so the HTTP layer stays a thin translation between
request/response bodies and this; this module is also what
tests/test_api.py exercises indirectly through the endpoint, and could be
called directly if a non-HTTP caller ever needed it.

Flow: validate/snap both coordinates (app.core.geo) -> for each of the
three modes, find_route() on the shared in-memory graph
(app.core.routing) -> reconstruct real LineString geometry from
segments.geom (routing's in-memory graph only carries length_m + scores,
not full geometry, to keep it light) -> build a deterministic per-mode
explanation plus cross-mode comparison notes.

A cross-component origin/destination is NOT raised as an HTTP error here:
it's a normal, valid outcome ("this graph has no path between these two
points right now"), returned as status="no_connected_route" in an
otherwise-200 response, same shape as a successful comparison minus the
`routes` field. Genuinely bad input (out of service area, no nearby
network at all) raises for the router to translate into 4xx.
"""
import json

from app.core import geo, routing
from app.core.graph import NoConnectedRouteError

ASSUMED_WALKING_SPEED_MPS = 1.2  # ~4.3 km/h -- a commonly used conservative
# pedestrian-speed assumption. NOT measured from any real trip data; purely
# a distance-to-time convenience conversion, documented as an estimate.

SCORE_DISCLAIMER = (
    "accessibility_score and confidence_score are relative decision-support "
    "indicators derived from crowdsourced Project Sidewalk reports and OSM "
    "tags, not probabilities or a safety guarantee. A high score does not "
    "certify a route is safe, and a low or unknown score does not mean it "
    "is impassable -- verify accessibility needs independently."
)


def fetch_segment_geometries(conn, segment_ids):
    if not segment_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, from_node_id, to_node_id, ST_AsGeoJSON(geom) FROM segments WHERE id = ANY(%s)",
            (list(segment_ids),),
        )
        return {
            seg_id: {"from_node_id": from_id, "to_node_id": to_id, "coordinates": json.loads(gj)["coordinates"]}
            for seg_id, from_id, to_id, gj in cur.fetchall()
        }


def build_route_geometry(route_summary, geoms):
    """Reconstructs a single GeoJSON LineString for the whole route, in
    traversal order, reversing each segment's stored coordinates when the
    path crosses it against its stored from->to direction. `geoms` is a
    pre-fetched {segment_id: {...}} dict (see compare_routes -- Week 7:
    fetched once for the union of all three modes' segments instead of once
    per mode, cutting geometry-fetch DB round trips from 3 to 1)."""
    coordinates = []
    for edge in route_summary["segments"]:
        seg = geoms.get(edge["segment_id"])
        if seg is None:
            continue
        coords = seg["coordinates"]
        if edge["from_node_id"] != seg["from_node_id"]:
            coords = list(reversed(coords))
        if coordinates and coordinates[-1] == coords[0]:
            coordinates.extend(coords[1:])
        else:
            coordinates.extend(coords)
    return {"type": "LineString", "coordinates": coordinates}


def build_mode_explanation(mode, summary):
    """Deterministic (same input -> same string, always): distinguishes
    known hazards, disputed evidence, low confidence, and missing evidence
    explicitly rather than folding them into one vague "some issues" line."""
    parts = [
        f"{mode} route: {summary['total_length_m']:.0f}m across {len(summary['segments'])} segments."
    ]

    if summary["dominant_hazards"]:
        counts = {}
        for h in summary["dominant_hazards"]:
            counts[h["hazard_type"]] = counts.get(h["hazard_type"], 0) + 1
        hazard_text = ", ".join(f"{count} {htype}" for htype, count in sorted(counts.items()))
        parts.append(f"Known hazards on this route (reliable reports that capped a segment's score): {hazard_text}.")
    else:
        parts.append("No segment on this route has a reliable, capping hazard report.")

    if summary["unknown_segment_ids"]:
        parts.append(
            f"{len(summary['unknown_segment_ids'])} segment(s) have no accessibility evidence at "
            "all (unknown, not verified either way)."
        )
    if summary["low_confidence_segment_ids"]:
        parts.append(
            f"{len(summary['low_confidence_segment_ids'])} segment(s) have some evidence but low confidence in it."
        )
    if summary["disputed_segment_ids"]:
        parts.append(
            f"{len(summary['disputed_segment_ids'])} segment(s) have conflicting (disputed) evidence."
        )
    if not (summary["unknown_segment_ids"] or summary["low_confidence_segment_ids"] or summary["disputed_segment_ids"]):
        parts.append("All segments on this route have well-attested evidence.")

    return " ".join(parts)


def build_comparison_notes(summaries):
    """Cross-mode notes -- specifically covers the case the review asked to
    be explained: confidence_aware trading known imperfections for fewer
    unknowns, relative to shortest and/or accessible."""
    notes = []
    ca = summaries.get(routing.CONFIDENCE_AWARE)
    if not ca:
        return notes
    for other_mode in (routing.SHORTEST, routing.ACCESSIBLE):
        other = summaries.get(other_mode)
        if not other:
            continue
        ca_unknown, other_unknown = len(ca["unknown_segment_ids"]), len(other["unknown_segment_ids"])
        ca_hazards, other_hazards = len(ca["dominant_hazards"]), len(other["dominant_hazards"])
        if ca_unknown < other_unknown and ca_hazards > other_hazards:
            notes.append(
                f"confidence_aware passes through more segments with a known, reliably-"
                f"reported issue than {other_mode} ({ca_hazards} vs {other_hazards}), but "
                f"fewer segments with no evidence at all ({ca_unknown} vs {other_unknown}) -- "
                "it prefers a documented imperfect path over an unverified one."
            )
    return notes


def snap_response(snap):
    return {
        "node_id": snap["node_id"],
        "snapped_lat": snap["snapped_lat"],
        "snapped_lon": snap["snapped_lon"],
        "snap_distance_m": snap["snap_distance_m"],
        "component_id": snap["component_id"],
        "adjusted_for_connectivity": snap["adjusted_for_connectivity"],
        "nearest_unconstrained_node_id": snap["nearest_unconstrained_node_id"],
        "nearest_unconstrained_distance_m": snap["nearest_unconstrained_distance_m"],
    }


def build_mode_response(result, mode, geoms):
    coverage_counts = {"labeled": 0, "unknown": 0}
    for s in result["segments"]:
        coverage_counts[s["coverage_status"]] = coverage_counts.get(s["coverage_status"], 0) + 1

    return {
        "mode": mode,
        "geometry": build_route_geometry(result, geoms),
        "distance_m": result["total_length_m"],
        "estimated_travel_time_s": result["total_length_m"] / ASSUMED_WALKING_SPEED_MPS,
        "accessibility_score": result["mean_accessibility"],
        "min_accessibility_score": result["min_accessibility"],
        "confidence_score": result["mean_confidence"],
        "min_confidence_score": result["min_confidence"],
        "coverage": {
            "total_segments": len(result["segments"]),
            "labeled_segments": coverage_counts.get("labeled", 0),
            "unknown_segments": coverage_counts.get("unknown", 0),
        },
        "hazards": result["dominant_hazards"],
        "unknown_segment_ids": result["unknown_segment_ids"],
        "low_confidence_segment_ids": result["low_confidence_segment_ids"],
        "disputed_segment_ids": result["disputed_segment_ids"],
        "explanation": build_mode_explanation(mode, result),
    }


def compare_routes(conn, graph, origin_lat, origin_lon, destination_lat, destination_lon):
    """Raises geo.OutOfServiceAreaError / geo.NoRoutableNetworkError for bad
    input; returns a dict for every other outcome, including
    status='no_connected_route'."""
    origin_snap = geo.snap_point(conn, origin_lat, origin_lon)
    destination_snap = geo.snap_point(conn, destination_lat, destination_lon, prefer_component_id=origin_snap["component_id"])

    response = {
        "origin": {"requested": {"lat": origin_lat, "lon": origin_lon}, "snap": snap_response(origin_snap)},
        "destination": {"requested": {"lat": destination_lat, "lon": destination_lon}, "snap": snap_response(destination_snap)},
        "disclaimer": SCORE_DISCLAIMER,
    }

    try:
        raw_results = {
            mode: routing.find_route(graph, origin_snap["node_id"], destination_snap["node_id"], mode)
            for mode in routing.MODES
        }
    except NoConnectedRouteError as e:
        response["status"] = "no_connected_route"
        response["reason"] = "origin_and_destination_in_different_connected_components"
        response["origin_component_id"] = e.from_component_id
        response["destination_component_id"] = e.to_component_id
        return response

    # Week 7: one geometry fetch for the union of every mode's segment ids,
    # instead of one fetch per mode -- three modes on a long route can
    # share most of their path, so this also avoids re-fetching the same
    # segment's geometry multiple times, not just cutting round trips.
    all_segment_ids = {
        s["segment_id"] for result in raw_results.values() for s in result["segments"]
    }
    geoms = fetch_segment_geometries(conn, all_segment_ids)

    response["status"] = "ok"
    response["routes"] = {mode: build_mode_response(result, mode, geoms) for mode, result in raw_results.items()}
    response["comparison_notes"] = build_comparison_notes(raw_results)
    return response
