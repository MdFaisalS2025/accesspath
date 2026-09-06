"""
Week 5 read-only map endpoints. All three take the same `bbox` query param
(`min_lon,min_lat,max_lon,max_lat`, matching GeoJSON's bbox convention) and
enforce the same size/result caps so a client cannot pull the entire
Seattle dataset in one request:

- MAX_BBOX_LAT_SPAN_DEG / MAX_BBOX_LON_SPAN_DEG (~3.3km x 3.3km at Seattle's
  latitude) -- a generous single map-viewport size, not the whole city
  (Seattle itself spans roughly 0.25 deg lat x 0.22 deg lon).
- MAX_RESULTS (2000 features) for /segments and /labels, with a
  `truncated` flag when hit rather than silently dropping the cap
  information. /coverage-summary is a GROUP BY aggregate (a handful of
  numbers regardless of bbox), so it has no result cap, but still enforces
  the bbox size cap for consistent, bounded query cost.
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_conn

router = APIRouter()

MAX_BBOX_LAT_SPAN_DEG = 0.03    # ~3.3km
MAX_BBOX_LON_SPAN_DEG = 0.045   # ~3.3km at Seattle's ~47.6N latitude
MAX_RESULTS = 2000


def parse_bbox(bbox: str):
    parts = bbox.split(",")
    if len(parts) != 4:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_bbox", "message": "bbox must be 'min_lon,min_lat,max_lon,max_lat'"},
        )
    try:
        min_lon, min_lat, max_lon, max_lat = (float(p) for p in parts)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_bbox", "message": "bbox values must be numbers"},
        )
    if min_lon >= max_lon or min_lat >= max_lat:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_bbox", "message": "bbox min must be less than max on both axes"},
        )
    if (max_lat - min_lat) > MAX_BBOX_LAT_SPAN_DEG or (max_lon - min_lon) > MAX_BBOX_LON_SPAN_DEG:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "bbox_too_large",
                "message": (
                    f"bbox exceeds the maximum supported size "
                    f"({MAX_BBOX_LAT_SPAN_DEG} deg lat x {MAX_BBOX_LON_SPAN_DEG} deg lon, ~3.3km x 3.3km)"
                ),
                "max_lat_span_deg": MAX_BBOX_LAT_SPAN_DEG,
                "max_lon_span_deg": MAX_BBOX_LON_SPAN_DEG,
            },
        )
    return min_lon, min_lat, max_lon, max_lat


@router.get("/segments")
def get_segments(bbox: str = Query(..., description="min_lon,min_lat,max_lon,max_lat"), conn=Depends(get_conn)):
    min_lon, min_lat, max_lon, max_lat = parse_bbox(bbox)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.id, s.osm_way_id, s.highway_type, s.length_m, ST_AsGeoJSON(s.geom),
                   sc.coverage_status, sc.accessibility_score, sc.confidence_score,
                   sc.evidence_consistency, sc.dominant_hazard_type
            FROM segments s
            LEFT JOIN segment_scores sc ON sc.segment_id = s.id
            WHERE s.geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
            ORDER BY s.id
            LIMIT %s
            """,
            (min_lon, min_lat, max_lon, max_lat, MAX_RESULTS + 1),
        )
        rows = cur.fetchall()

    truncated = len(rows) > MAX_RESULTS
    rows = rows[:MAX_RESULTS]
    features = [
        {
            "type": "Feature",
            "geometry": json.loads(geojson),
            "properties": {
                "segment_id": seg_id, "osm_way_id": osm_way_id,
                "highway_type": highway_type, "length_m": length_m,
                # Week 6 addition: coverage fields for the frontend's coverage
                # map layer (labeled / unknown / low-confidence / disputed /
                # dominant hazard) -- a LEFT JOIN, since segment_scores should
                # cover every segment once compute_scores.py has run, but a
                # missing row (stale DB) degrades to nulls, not a 500.
                "coverage_status": coverage_status,
                "accessibility_score": accessibility_score,
                "confidence_score": confidence_score,
                "evidence_consistency": evidence_consistency,
                "dominant_hazard_type": dominant_hazard_type,
            },
        }
        for (seg_id, osm_way_id, highway_type, length_m, geojson,
             coverage_status, accessibility_score, confidence_score,
             evidence_consistency, dominant_hazard_type) in rows
    ]
    return {"type": "FeatureCollection", "features": features, "count": len(features), "truncated": truncated}


@router.get("/labels")
def get_labels(bbox: str = Query(..., description="min_lon,min_lat,max_lon,max_lat"), conn=Depends(get_conn)):
    min_lon, min_lat, max_lon, max_lat = parse_bbox(bbox)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ps_label_id, label_type, severity, match_method, segment_id,
                   ambiguous_match, ST_AsGeoJSON(geom)
            FROM accessibility_labels
            WHERE geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
            ORDER BY ps_label_id
            LIMIT %s
            """,
            (min_lon, min_lat, max_lon, max_lat, MAX_RESULTS + 1),
        )
        rows = cur.fetchall()

    truncated = len(rows) > MAX_RESULTS
    rows = rows[:MAX_RESULTS]
    features = [
        {
            "type": "Feature",
            "geometry": json.loads(geojson),
            "properties": {
                "ps_label_id": ps_label_id, "label_type": label_type, "severity": severity,
                "match_method": match_method, "segment_id": segment_id, "ambiguous_match": ambiguous_match,
            },
        }
        for ps_label_id, label_type, severity, match_method, segment_id, ambiguous_match, geojson in rows
    ]
    return {"type": "FeatureCollection", "features": features, "count": len(features), "truncated": truncated}


@router.get("/segments/{segment_id}")
def get_segment_by_id(segment_id: int, conn=Depends(get_conn)):
    """Week 6 addition: a single-segment geometry lookup, used by the
    frontend to focus the map on a hazard/segment referenced in a route
    explanation. Read-only, not part of the routing algorithm."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, osm_way_id, highway_type, length_m, ST_AsGeoJSON(geom) FROM segments WHERE id = %s",
            (segment_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "segment_not_found", "message": f"No segment with id {segment_id}"},
        )
    seg_id, osm_way_id, highway_type, length_m, geojson = row
    return {
        "type": "Feature",
        "geometry": json.loads(geojson),
        "properties": {"segment_id": seg_id, "osm_way_id": osm_way_id, "highway_type": highway_type, "length_m": length_m},
    }


@router.get("/coverage-summary")
def get_coverage_summary(bbox: str = Query(..., description="min_lon,min_lat,max_lon,max_lat"), conn=Depends(get_conn)):
    min_lon, min_lat, max_lon, max_lat = parse_bbox(bbox)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sc.coverage_status, count(*),
                   avg(sc.accessibility_score), avg(sc.confidence_score),
                   count(*) FILTER (WHERE sc.dominant_hazard_type IS NOT NULL)
            FROM segment_scores sc
            JOIN segments s ON s.id = sc.segment_id
            WHERE s.geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
            GROUP BY sc.coverage_status
            """,
            (min_lon, min_lat, max_lon, max_lat),
        )
        rows = cur.fetchall()

    by_status = {}
    total = 0
    dominance_capped = 0
    for status, count, mean_acc, mean_conf, capped in rows:
        by_status[status] = {
            "segment_count": count,
            "mean_accessibility_score": mean_acc,
            "mean_confidence_score": mean_conf,
            "dominance_capped_count": capped,
        }
        total += count
        dominance_capped += capped

    return {
        "bbox": {"min_lon": min_lon, "min_lat": min_lat, "max_lon": max_lon, "max_lat": max_lat},
        "total_segments": total,
        "dominance_capped_segments": dominance_capped,
        "by_coverage_status": by_status,
    }
