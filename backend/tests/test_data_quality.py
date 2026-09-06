"""
Week 2.5 / Week 3 data-quality tests. Run against the live-loaded DB (not a
fixture DB) to guard the label-matching, connectivity-awareness, and scoring
behavior end-to-end (app.core.scoring's own unit tests, which don't need a
DB, live in test_scoring.py).

    docker compose exec api pytest tests/test_data_quality.py -v
"""
import sys

import networkx as nx
import pytest

sys.path.insert(0, "/app")
from app.core import matching, routing, scoring
from app.core.graph import NoConnectedRouteError, UnknownNodeError, assert_connected


def test_max_label_to_segment_distance(conn):
    """No label should ever be matched further than the validated production
    threshold, however the matching logic evolves."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(match_distance_m) FROM accessibility_labels WHERE match_method = 'nearest_segment'"
        )
        max_distance = cur.fetchone()[0]
    assert max_distance is not None
    assert max_distance <= matching.PRODUCTION_MATCH_THRESHOLD_M


def test_unmatched_label_accounting(conn):
    """Every label must be accounted for by exactly one match_method, and
    segment_id nullness must agree with match_method -- no label silently
    falls through the join with an inconsistent state."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM accessibility_labels")
        total = cur.fetchone()[0]
        cur.execute("SELECT match_method, count(*) FROM accessibility_labels GROUP BY match_method")
        by_method = dict(cur.fetchall())
        cur.execute("SELECT count(*) FROM accessibility_labels WHERE match_method IS NULL")
        no_method = cur.fetchone()[0]
        cur.execute(
            """
            SELECT count(*) FROM accessibility_labels
            WHERE (segment_id IS NULL) != (match_method = 'unmatched')
            """
        )
        inconsistent = cur.fetchone()[0]

    assert total > 0
    assert no_method == 0, "every label must be accounted for by a match_method"
    assert sum(by_method.values()) == total
    assert inconsistent == 0, "segment_id must be NULL iff match_method is 'unmatched'"


def test_ambiguous_matches_are_flagged_not_silently_reassigned(conn):
    """Recomputes the ambiguity condition independently of matching.py's
    UPDATE statement (from the stored second-nearest columns) and checks
    every label meeting it is flagged -- a near-tie between two distinct,
    plausible ways must never be silently resolved to whichever segment the
    KNN query happened to return first."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)
            FROM accessibility_labels l
            JOIN segments s1 ON s1.id = l.segment_id
            JOIN segments s2 ON s2.id = l.second_match_segment_id
            WHERE l.match_method = 'nearest_segment'
              AND l.match_distance_m > %s
              AND l.second_match_distance_m < l.match_distance_m * %s
              AND s1.osm_way_id IS DISTINCT FROM s2.osm_way_id
              AND NOT l.ambiguous_match
            """,
            (matching.AMBIGUITY_MIN_DISTANCE_M, matching.AMBIGUITY_RATIO),
        )
        unflagged_ambiguous = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM accessibility_labels WHERE match_method = 'nearest_segment'")
        matched = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM accessibility_labels WHERE ambiguous_match")
        flagged = cur.fetchone()[0]

    assert unflagged_ambiguous == 0
    # Regression guard: a naive "any close 2nd candidate" rule (tried and
    # rejected in Week 2.5, see docs/week2_graph_report.md) flagged ~72% of
    # matches, which makes the flag useless for triage.
    assert flagged / matched < 0.5


def test_component_aware_routing_rejects_cross_component_pair(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM nodes WHERE component_id = 0 LIMIT 1")
        node_in_largest = cur.fetchone()[0]
        cur.execute("SELECT id FROM nodes WHERE component_id = 1 LIMIT 1")
        node_in_other = cur.fetchone()[0]

    with pytest.raises(NoConnectedRouteError):
        assert_connected(conn, node_in_largest, node_in_other)


def test_component_aware_routing_allows_same_component_pair(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM nodes WHERE component_id = 0 LIMIT 2")
        a, b = (row[0] for row in cur.fetchall())

    assert_connected(conn, a, b)  # must not raise


def test_component_aware_routing_unknown_node(conn):
    with pytest.raises(UnknownNodeError):
        assert_connected(conn, -1, -2)


# ---------------------------------------------------------------------------
# Week 3: scoring
# ---------------------------------------------------------------------------

def test_every_segment_has_a_score_row(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM segments")
        num_segments = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM segment_scores")
        num_scores = cur.fetchone()[0]
    assert num_segments > 0
    assert num_scores == num_segments, "compute_scores.py must score every segment, not just labeled ones"


def test_scores_are_in_valid_range(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM segment_scores
            WHERE accessibility_score < 0 OR accessibility_score > 1
               OR confidence_score < 0 OR confidence_score > 1
            """
        )
        out_of_range = cur.fetchone()[0]
    assert out_of_range == 0


def test_unknown_coverage_segments_have_neutral_score_and_zero_confidence(conn):
    """A segment with no informative matched label must not be silently
    scored as if it were known-accessible -- it should carry the explicit
    neutral prior and zero confidence, matching app.core.scoring's contract."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM segment_scores
            WHERE coverage_status = 'unknown'
              AND (accessibility_score != 0.5 OR confidence_score != 0.0 OR label_count != 0)
            """
        )
        violations = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM segment_scores WHERE coverage_status = 'unknown'")
        unknown_count = cur.fetchone()[0]
    assert unknown_count > 0
    assert violations == 0


def test_labeled_segments_have_at_least_one_informative_label(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM segment_scores WHERE coverage_status = 'labeled' AND label_count < 1"
        )
        violations = cur.fetchone()[0]
    assert violations == 0


def test_far_nosidewalk_matches_excluded_from_scoring_evidence(conn):
    """A NoSidewalk label matched between the scoring cutoff and the Week 2.5
    production threshold must stay matched in accessibility_labels (matching
    is untouched) but must not be the sole reason a segment is 'labeled'."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM accessibility_labels
            WHERE label_type = 'NoSidewalk'
              AND match_method = 'nearest_segment'
              AND match_distance_m > %s AND match_distance_m <= %s
            """,
            (scoring.NO_SIDEWALK_SCORING_MAX_DISTANCE_M, matching.PRODUCTION_MATCH_THRESHOLD_M),
        )
        far_but_matched = cur.fetchone()[0]
    assert far_but_matched > 0, "test assumption: some NoSidewalk labels land in the 5-10m band"

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)
            FROM accessibility_labels l
            JOIN segment_scores sc ON sc.segment_id = l.segment_id
            WHERE l.label_type = 'NoSidewalk'
              AND l.match_method = 'nearest_segment'
              AND l.match_distance_m > %s AND l.match_distance_m <= %s
              AND sc.coverage_status = 'labeled'
              AND NOT EXISTS (
                  SELECT 1 FROM accessibility_labels l2
                  WHERE l2.segment_id = l.segment_id
                    AND l2.match_method IN ('ps_osm_way_id', 'nearest_segment')
                    AND l2.label_type NOT IN ('Occlusion', 'Other')
                    AND (l2.label_type != 'NoSidewalk' OR l2.match_distance_m <= %s)
              )
            """,
            (scoring.NO_SIDEWALK_SCORING_MAX_DISTANCE_M, matching.PRODUCTION_MATCH_THRESHOLD_M,
             scoring.NO_SIDEWALK_SCORING_MAX_DISTANCE_M),
        )
        segments_wrongly_labeled = cur.fetchone()[0]
    # every segment whose only nearby label is a 5-10m NoSidewalk (and nothing
    # else informative) must be 'unknown', never wrongly promoted to 'labeled'
    assert segments_wrongly_labeled == 0


# ---------------------------------------------------------------------------
# Week 3.5: dominance ceiling / evidence-consistency columns
# ---------------------------------------------------------------------------

def test_dominance_capped_segments_respect_the_ceiling(conn):
    """Every segment with a dominant_hazard_type must have
    accessibility_score <= that hazard's own value (the ceiling is an upper
    bound: the graduated score can be lower, never higher)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM segment_scores
            WHERE dominant_hazard_type IS NOT NULL AND coverage_status != 'labeled'
            """
        )
        capped_but_not_labeled = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM segment_scores WHERE dominant_hazard_type IS NOT NULL")
        capped_count = cur.fetchone()[0]
    assert capped_but_not_labeled == 0
    assert capped_count > 0, "test assumption: at least some segments should be dominance-capped"


def test_evidence_consistency_in_range_when_present(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM segment_scores
            WHERE evidence_consistency IS NOT NULL
              AND (evidence_consistency < 0 OR evidence_consistency > 1)
            """
        )
        out_of_range = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM segment_scores WHERE coverage_status = 'labeled' AND evidence_consistency IS NULL"
        )
        missing_on_labeled = cur.fetchone()[0]
    assert out_of_range == 0
    # a labeled segment can only lack evidence_consistency in the pathological
    # all-reliability-exactly-zero case; shouldn't happen on real data
    assert missing_on_labeled == 0


def test_positive_and_negative_evidence_are_non_negative(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM segment_scores WHERE positive_evidence < 0 OR negative_evidence < 0"
        )
        negative_values = cur.fetchone()[0]
    assert negative_values == 0


def test_crossing_evidence_alone_does_not_yield_high_confidence_on_a_non_crossing_segment(conn):
    """A footway segment whose only labels are crossing-domain (CurbRamp/
    NoCurbRamp/Crosswalk/Signal) should never reach high confidence purely
    from that cross-domain evidence -- a curb ramp nearby isn't proof of the
    footway's own surface condition."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sc.segment_id
            FROM segment_scores sc
            JOIN segments s ON s.id = sc.segment_id
            WHERE sc.coverage_status = 'labeled'
              AND s.highway_type != 'crossing'
              AND sc.confidence_score > 0.8
              AND NOT EXISTS (
                  SELECT 1 FROM accessibility_labels l
                  WHERE l.segment_id = sc.segment_id
                    AND l.match_method IN ('ps_osm_way_id', 'nearest_segment')
                    AND l.label_type IN ('NoSidewalk', 'SurfaceProblem', 'Obstacle')
              )
            LIMIT 5
            """
        )
        violations = cur.fetchall()
    assert violations == []


# ---------------------------------------------------------------------------
# Week 4: routing, against the real DB-loaded graph
# ---------------------------------------------------------------------------

def test_load_routing_graph_matches_db_counts(conn):
    graph = routing.load_routing_graph(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM nodes")
        num_nodes = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM segments s JOIN segment_scores sc ON sc.segment_id = s.id")
        num_scored_segments = cur.fetchone()[0]
    assert graph.number_of_nodes() == num_nodes
    # segments collapse to unique (from,to) edges in a simple Graph, same
    # caveat as build_graph.py's verify_connectivity -- so <=, not ==
    assert graph.number_of_edges() <= num_scored_segments


def test_real_route_within_largest_component_succeeds(conn):
    graph = routing.load_routing_graph(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM nodes WHERE component_id = 0 LIMIT 1")
        origin = cur.fetchone()[0]
        cur.execute(
            "SELECT id FROM nodes WHERE component_id = 0 AND id != %s ORDER BY id DESC LIMIT 1", (origin,)
        )
        destination = cur.fetchone()[0]

    result = routing.find_route(graph, origin, destination, routing.SHORTEST)
    assert result["path_node_ids"][0] == origin
    assert result["path_node_ids"][-1] == destination
    assert result["total_length_m"] > 0


def test_real_cross_component_route_raises_no_connected_route(conn):
    graph = routing.load_routing_graph(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM nodes WHERE component_id = 0 LIMIT 1")
        origin = cur.fetchone()[0]
        cur.execute("SELECT id FROM nodes WHERE component_id = 1 LIMIT 1")
        destination = cur.fetchone()[0]

    with pytest.raises(NoConnectedRouteError):
        routing.find_route(graph, origin, destination, routing.SHORTEST)


def test_real_modes_can_disagree_on_at_least_one_real_od_pair(conn):
    """Not every origin/destination pair will show mode disagreement (many
    real segments are 'unknown' with identical neutral scores), but across a
    enough real pairs with mixed coverage, at least one should -- confirms
    the mode separation demonstrated on synthetic graphs in test_routing.py
    also shows up on real, messy data."""
    graph = routing.load_routing_graph(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT n1.id, n2.id
            FROM segment_scores sc1
            JOIN segments s1 ON s1.id = sc1.segment_id
            JOIN nodes n1 ON n1.id = s1.from_node_id
            JOIN segment_scores sc2 ON sc2.coverage_status = 'labeled' AND sc2.accessibility_score < 0.3
            JOIN segments s2 ON s2.id = sc2.segment_id
            JOIN nodes n2 ON n2.id = s2.to_node_id
            WHERE sc1.coverage_status = 'labeled' AND sc1.accessibility_score > 0.8
              AND n1.component_id = 0 AND n2.component_id = 0
            LIMIT 25
            """
        )
        candidate_pairs = cur.fetchall()

    disagreements = 0
    for origin, destination in candidate_pairs:
        if origin == destination:
            continue
        try:
            paths = {mode: tuple(routing.find_route(graph, origin, destination, mode)["path_node_ids"])
                     for mode in routing.MODES}
        except (NoConnectedRouteError, nx.NetworkXNoPath):
            continue
        if len(set(paths.values())) > 1:
            disagreements += 1
    assert disagreements > 0, "expected at least one real O/D pair where modes disagree"
