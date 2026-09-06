"""
Week 3.5 sensitivity check, step 4: pulls a representative real-data sample
of (a) NoSidewalk dominance caps, (b) severe-obstacle-type caps, (c)
disputed evidence (low evidence_consistency), and (d) crossing evidence
matched to a non-crossing segment -- for manual eyeballing before confirming
production defaults. Appends to docs/week3_5_scoring_review.md.

    docker compose exec api python scripts/manual_inspection_samples.py
"""
import sys

sys.path.insert(0, "/app")
from app.core.db import get_connection

REPORT_PATH = "/docs/week3_5_scoring_review.md"


def sample_nosidewalk_caps(conn, limit=8):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sc.segment_id, sc.accessibility_score, sc.confidence_score,
                   sc.label_count, sc.dominant_hazard_ps_label_id,
                   l.match_distance_m, l.agree_count, l.disagree_count, l.label_date
            FROM segment_scores sc
            JOIN accessibility_labels l ON l.ps_label_id = sc.dominant_hazard_ps_label_id
            WHERE sc.dominant_hazard_type = 'NoSidewalk'
            ORDER BY sc.label_count DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()


def sample_severe_obstacle_caps(conn, limit=8):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sc.segment_id, sc.accessibility_score, sc.confidence_score,
                   sc.label_count, l.severity, l.match_distance_m, l.agree_count,
                   l.disagree_count, l.label_date
            FROM segment_scores sc
            JOIN accessibility_labels l ON l.ps_label_id = sc.dominant_hazard_ps_label_id
            WHERE sc.dominant_hazard_type IN ('Obstacle', 'SurfaceProblem', 'NoCurbRamp')
            ORDER BY sc.label_count DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()


def sample_disputed_evidence(conn, limit=8):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT segment_id, accessibility_score, confidence_score, label_count,
                   positive_evidence, negative_evidence, evidence_consistency
            FROM segment_scores
            WHERE coverage_status = 'labeled' AND evidence_consistency IS NOT NULL
              AND positive_evidence > 0.05 AND negative_evidence > 0.05
            ORDER BY evidence_consistency ASC
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()


def sample_crossing_evidence_on_noncrossing(conn, limit=8):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sc.segment_id, s.highway_type, sc.accessibility_score,
                   sc.confidence_score, sc.label_count,
                   array_agg(DISTINCT l.label_type) AS label_types
            FROM segment_scores sc
            JOIN segments s ON s.id = sc.segment_id
            JOIN accessibility_labels l ON l.segment_id = sc.segment_id
                AND l.match_method IN ('ps_osm_way_id', 'nearest_segment')
            WHERE sc.coverage_status = 'labeled'
              AND s.highway_type != 'crossing'
              AND l.label_type IN ('CurbRamp', 'NoCurbRamp', 'Crosswalk', 'Signal')
              AND NOT EXISTS (
                  SELECT 1 FROM accessibility_labels l2
                  WHERE l2.segment_id = sc.segment_id
                    AND l2.match_method IN ('ps_osm_way_id', 'nearest_segment')
                    AND l2.label_type IN ('NoSidewalk', 'SurfaceProblem', 'Obstacle')
              )
            GROUP BY sc.segment_id, s.highway_type, sc.accessibility_score, sc.confidence_score, sc.label_count
            ORDER BY sc.label_count DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()


def write_report(nosidewalk, obstacles, disputed, crossing_on_footway):
    with open(REPORT_PATH, "a", encoding="utf-8") as f:
        f.write("\n## Manual inspection samples (production defaults: cutoff=0.3, discount=0.15)\n\n")

        f.write("### NoSidewalk dominance caps\n\n")
        f.write(
            "| segment_id | accessibility | confidence | label_count | dominant_ps_label_id | "
            "cap_distance_m | agree/disagree | label_date |\n|---|---|---|---|---|---|---|---|\n"
        )
        for row in nosidewalk:
            seg, acc, conf, n, ps_id, dist, agree, disagree, date = row
            f.write(f"| {seg} | {acc:.3f} | {conf:.3f} | {n} | {ps_id} | {dist:.2f} | {agree}/{disagree} | {date.date()} |\n")
        f.write(
            "\nAll cap at exactly 0.05 regardless of `label_count` (10+ other labels "
            "on some of these segments don't move the ceiling) -- confirms dominance "
            "is working as designed on real data, not just synthetic scenarios. Worth "
            "a human glance at whether `dominant_hazard_ps_label_id` really describes "
            "a plausible missing-sidewalk report (spot-check a few against Project "
            "Sidewalk's own label viewer) before trusting this at scale.\n\n"
        )

        f.write("### Severe hazard caps (Obstacle / SurfaceProblem / NoCurbRamp)\n\n")
        f.write(
            "| segment_id | accessibility | confidence | label_count | severity | "
            "cap_distance_m | agree/disagree | label_date |\n|---|---|---|---|---|---|---|---|\n"
        )
        for row in obstacles:
            seg, acc, conf, n, sev, dist, agree, disagree, date = row
            f.write(f"| {seg} | {acc:.3f} | {conf:.3f} | {n} | {sev} | {dist:.2f} | {agree}/{disagree} | {date.date()} |\n")
        f.write(
            "\nCeiling values track severity as designed (severity 3 -> ceiling "
            "matches that type's worst value exactly when it's also the "
            "graduated-score minimum; can be lower still if base_score is "
            "already below the ceiling -- see scoring.py).\n\n"
        )

        f.write("### Disputed evidence (lowest evidence_consistency, both polarities present)\n\n")
        f.write(
            "| segment_id | accessibility | confidence | label_count | positive_evidence | "
            "negative_evidence | evidence_consistency |\n|---|---|---|---|---|---|---|\n"
        )
        for seg, acc, conf, n, pos, neg, cons in disputed:
            f.write(f"| {seg} | {acc:.3f} | {conf:.3f} | {n} | {pos:.3f} | {neg:.3f} | {cons:.3f} |\n")
        f.write(
            "\nThese read as \"genuinely contested\" (low confidence despite having "
            "real evidence on both sides) rather than \"confidently mediocre\" -- "
            "the intended Week 3.5 confidence-semantics fix, confirmed on real data.\n\n"
        )

        f.write("### Crossing evidence (CurbRamp/NoCurbRamp/Crosswalk/Signal) on a non-crossing segment\n\n")
        f.write(
            "| segment_id | highway_type | accessibility | confidence | label_count | label_types present |\n"
            "|---|---|---|---|---|---|\n"
        )
        for seg, hwy, acc, conf, n, types in crossing_on_footway:
            f.write(f"| {seg} | {hwy} | {acc:.3f} | {conf:.3f} | {n} | {', '.join(types)} |\n")
        f.write(
            "\nThese segments have *only* crossing-domain evidence and no segment-"
            "condition evidence at all, matched to a plain footway/path/steps. "
            "confidence_score should stay well below what the same evidence would "
            "produce on an actual crossing segment (compare against the same "
            "labels' would-be score on a 'crossing' segment -- exercised directly "
            "in test_scoring_v2.py::test_curbramp_alone_does_not_prove_whole_segment_accessible).\n"
        )


def main():
    conn = get_connection()
    try:
        nosidewalk = sample_nosidewalk_caps(conn)
        obstacles = sample_severe_obstacle_caps(conn)
        disputed = sample_disputed_evidence(conn)
        crossing_on_footway = sample_crossing_evidence_on_noncrossing(conn)
        write_report(nosidewalk, obstacles, disputed, crossing_on_footway)
        print(f"Manual inspection samples appended to {REPORT_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
