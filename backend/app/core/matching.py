"""
Project Sidewalk label -> OSM segment matching.

Two-stage: (1) exact `osm_way_id` match (rare in practice — see
docs/week2_graph_report.md, most PS `osm_way_id` values point at the parallel
*street* way, not a footway/path way), then (2) nearest-segment spatial
match, computed here.

PRODUCTION_MATCH_THRESHOLD_M and AMBIGUITY_MARGIN_M were chosen empirically
in the Week 2.5 validation pass (docs/week2_graph_report.md) by comparing
5/10/15/30m thresholds against distance distributions and manual sampling —
do not change them without re-running scripts/validate_matching.py.
"""
PRODUCTION_MATCH_THRESHOLD_M = 10.0

# A label's 1st/2nd nearest segment being close together is usually *not*
# meaningful ambiguity here: the graph splits every way into short segments
# at each intersection/crossing, so at any corner several segments legitimately
# sit within a meter of each other by construction (median 2nd-vs-1st gap
# across all matches is ~0.6m). Flagging all of those would mark ~72% of
# matches "ambiguous" and make the flag useless for triage. Real ambiguity —
# a label that could plausibly belong to either of two *distinct* ways, not
# just an adjacent split of the same sidewalk polyline — requires: the match
# isn't a near-exact hit (d1 > AMBIGUITY_MIN_DISTANCE_M), the runner-up is
# within AMBIGUITY_RATIO of d1, and the runner-up is a different OSM way.
AMBIGUITY_MIN_DISTANCE_M = 2.0
AMBIGUITY_RATIO = 1.3


def build_nearest_candidates(conn):
    """(Re)builds a session-local temp table `label_nearest_candidates` with
    the 1st- and 2nd-nearest segment (by real-world geography distance) for
    every label not already matched by `osm_way_id`. Safe to call more than
    once per connection (drops and recreates)."""
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS label_nearest_candidates")
        cur.execute(
            """
            CREATE TEMP TABLE label_nearest_candidates AS
            SELECT
                l.id AS label_id,
                n1.id AS segment_id_1, n1.d AS d1,
                n2.id AS segment_id_2, n2.d AS d2
            FROM accessibility_labels l
            CROSS JOIN LATERAL (
                SELECT seg.id, ST_Distance(seg.geom::geography, l.geom::geography) AS d
                FROM segments seg
                ORDER BY l.geom <-> seg.geom
                LIMIT 1
            ) n1
            CROSS JOIN LATERAL (
                SELECT seg.id, ST_Distance(seg.geom::geography, l.geom::geography) AS d
                FROM segments seg
                WHERE seg.id != n1.id
                ORDER BY l.geom <-> seg.geom
                LIMIT 1
            ) n2
            WHERE l.match_method IS DISTINCT FROM 'ps_osm_way_id'
            """
        )
        cur.execute("CREATE INDEX ON label_nearest_candidates (label_id)")
    conn.commit()


def threshold_counts(conn, thresholds):
    """Returns {threshold: matched_count} for labels in the candidate table
    (i.e. excluding already-ID-matched labels)."""
    counts = {}
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM label_nearest_candidates")
        total = cur.fetchone()[0]
        for t in thresholds:
            cur.execute("SELECT count(*) FROM label_nearest_candidates WHERE d1 <= %s", (t,))
            counts[t] = cur.fetchone()[0]
    return total, counts


def threshold_counts_by_label_type(conn, thresholds):
    """{label_type: {threshold: matched_count, 'total': n}} — lets the report
    show whether raising the threshold mostly rescues legitimately-positioned
    labels or mostly pulls in one specific (likely spurious) label_type."""
    results = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT l.label_type, count(*)
            FROM label_nearest_candidates c
            JOIN accessibility_labels l ON l.id = c.label_id
            GROUP BY l.label_type
            """
        )
        totals = dict(cur.fetchall())
        for label_type, total in sorted(totals.items(), key=lambda kv: -kv[1]):
            results[label_type] = {"total": total}
            for t in thresholds:
                cur.execute(
                    """
                    SELECT count(*)
                    FROM label_nearest_candidates c
                    JOIN accessibility_labels l ON l.id = c.label_id
                    WHERE l.label_type = %s AND c.d1 <= %s
                    """,
                    (label_type, t),
                )
                results[label_type][t] = cur.fetchone()[0]
    return results


def distance_stats(conn, lo, hi):
    """Distance-distribution stats for candidates with lo < d1 <= hi."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                count(*),
                avg(d1),
                percentile_cont(0.5) WITHIN GROUP (ORDER BY d1),
                percentile_cont(0.9) WITHIN GROUP (ORDER BY d1),
                percentile_cont(0.99) WITHIN GROUP (ORDER BY d1),
                max(d1)
            FROM label_nearest_candidates
            WHERE d1 > %s AND d1 <= %s
            """,
            (lo, hi),
        )
        return cur.fetchone()


def sample_for_inspection(conn, lo, hi, limit=20):
    """Sample rows in the (lo, hi] distance band for manual inspection."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT l.ps_label_id, l.label_type, l.region_name, c.d1,
                   s.osm_way_id, s.highway_type,
                   ST_Y(l.geom) AS lat, ST_X(l.geom) AS lon
            FROM label_nearest_candidates c
            JOIN accessibility_labels l ON l.id = c.label_id
            JOIN segments s ON s.id = c.segment_id_1
            WHERE c.d1 > %s AND c.d1 <= %s
            ORDER BY c.d1 DESC
            LIMIT %s
            """,
            (lo, hi, limit),
        )
        return cur.fetchall()


def apply_final_match(
    conn,
    threshold=PRODUCTION_MATCH_THRESHOLD_M,
    ambiguity_min_distance=AMBIGUITY_MIN_DISTANCE_M,
    ambiguity_ratio=AMBIGUITY_RATIO,
):
    """Applies label_nearest_candidates to accessibility_labels using the
    given threshold. match_distance_m is preserved even for labels that end
    up unmatched (the nearest segment was simply too far), so the raw
    distance is never lost. Genuine ambiguity — a plausible match to two
    distinct ways, not just an adjacent split of the same one — is flagged,
    not silently resolved to whichever came first."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE accessibility_labels l
            SET segment_id = CASE WHEN c.d1 <= %(threshold)s THEN c.segment_id_1 ELSE NULL END,
                match_method = CASE WHEN c.d1 <= %(threshold)s THEN 'nearest_segment' ELSE 'unmatched' END,
                match_distance_m = c.d1,
                second_match_segment_id = c.segment_id_2,
                second_match_distance_m = c.d2,
                ambiguous_match = (
                    c.d1 <= %(threshold)s
                    AND c.d1 > %(min_dist)s
                    AND c.d2 < c.d1 * %(ratio)s
                    AND s1.osm_way_id IS DISTINCT FROM s2.osm_way_id
                )
            FROM label_nearest_candidates c
            JOIN segments s1 ON s1.id = c.segment_id_1
            JOIN segments s2 ON s2.id = c.segment_id_2
            WHERE l.id = c.label_id
            """,
            {"threshold": threshold, "min_dist": ambiguity_min_distance, "ratio": ambiguity_ratio},
        )
        matched = cur.rowcount
        cur.execute(
            "SELECT count(*) FROM accessibility_labels WHERE match_method = 'nearest_segment'"
        )
        matched_by_nearest = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM accessibility_labels WHERE match_method = 'unmatched'")
        unmatched = cur.fetchone()[0]
    conn.commit()
    return matched_by_nearest, unmatched
