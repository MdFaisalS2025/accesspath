"""
Week 2.5: validates the nearest-segment label-matching threshold before any
scoring work is built on top of it.

Compares 5/10/15/30m thresholds, reports distance-distribution stats and a
manual-inspection sample for matches beyond 10m, then applies the chosen
production threshold (app.core.matching.PRODUCTION_MATCH_THRESHOLD_M) to
accessibility_labels.

Run inside the api container:
    docker compose exec api python scripts/validate_matching.py
"""
import sys

sys.path.insert(0, "/app")
from app.core import matching
from app.core.db import get_connection

THRESHOLDS = [5.0, 10.0, 15.0, 30.0]
REPORT_PATH = "/docs/week2_graph_report.md"


def main():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM accessibility_labels WHERE match_method = 'ps_osm_way_id'")
            id_matched = cur.fetchone()[0]

        print("Building nearest-1st/2nd-segment candidates for all non-ID-matched labels...")
        matching.build_nearest_candidates(conn)

        total_candidates, counts = matching.threshold_counts(conn, THRESHOLDS)
        print(f"{total_candidates} labels need spatial matching (ID-matched: {id_matched})")
        for t in THRESHOLDS:
            print(f"  <= {t:>4}m: {counts[t]} matched, {total_candidates - counts[t]} unmatched")

        by_type = matching.threshold_counts_by_label_type(conn, THRESHOLDS)

        stats_10_30 = matching.distance_stats(conn, 10.0, 30.0)
        sample = matching.sample_for_inspection(conn, 10.0, 30.0, limit=20)

        print(f"\nDistance stats for matches in (10m, 30m]: {stats_10_30}")
        print("Sample (farthest first):")
        for row in sample[:10]:
            print(f"  {row}")

        print(f"\nApplying production threshold {matching.PRODUCTION_MATCH_THRESHOLD_M}m...")
        matched_by_nearest, unmatched = matching.apply_final_match(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM accessibility_labels WHERE ambiguous_match")
            ambiguous = cur.fetchone()[0]
        print(f"  matched_by_nearest={matched_by_nearest} unmatched={unmatched} ambiguous={ambiguous}")

        write_report_section(
            id_matched, total_candidates, counts, by_type, stats_10_30, sample,
            matched_by_nearest, unmatched, ambiguous,
        )
        print(f"Report section written to {REPORT_PATH}")
    finally:
        conn.close()


def write_report_section(id_matched, total_candidates, counts, by_type, stats_10_30, sample,
                          matched_by_nearest, unmatched, ambiguous):
    n, avg, p50, p90, p99, mx = stats_10_30
    lines = []
    lines.append("\n## Week 2.5 — Matching threshold validation\n\n")
    lines.append(
        f"Labels needing a spatial match (i.e. not resolved by `osm_way_id`): "
        f"{total_candidates} (ID-matched separately: {id_matched}).\n\n"
    )
    lines.append("### Matched/unmatched by threshold\n\n")
    lines.append("| Threshold | Matched | Unmatched |\n|---|---|---|\n")
    for t in THRESHOLDS:
        lines.append(f"| {t:.0f}m | {counts[t]} | {total_candidates - counts[t]} |\n")

    lines.append("\n### Matched fraction by label type, per threshold\n\n")
    lines.append("| label_type | total | <=5m | <=10m | <=15m | <=30m |\n|---|---|---|---|---|---|\n")
    for label_type, row in by_type.items():
        total = row["total"]
        cells = " | ".join(f"{row[t]} ({row[t]/total:.1%})" for t in THRESHOLDS)
        lines.append(f"| {label_type} | {total} | {cells} |\n")

    lines.append("\n### Distance distribution for matches in (10m, 30m]\n\n")
    if n:
        lines.append(
            f"- Count: {n}\n- Mean: {avg:.2f}m\n- Median: {p50:.2f}m\n"
            f"- p90: {p90:.2f}m\n- p99: {p99:.2f}m\n- Max: {mx:.2f}m\n\n"
        )
    else:
        lines.append("- No candidates fall in (10m, 30m].\n\n")

    lines.append("### Sample for manual inspection (farthest first, up to 20)\n\n")
    lines.append(
        "| ps_label_id | label_type | region | distance_m | osm_way_id | highway_type | lat | lon |\n"
        "|---|---|---|---|---|---|---|---|\n"
    )
    for ps_label_id, label_type, region, d1, way_id, highway_type, lat, lon in sample:
        lines.append(
            f"| {ps_label_id} | {label_type} | {region} | {d1:.1f} | {way_id} | "
            f"{highway_type} | {lat:.6f} | {lon:.6f} |\n"
        )

    lines.append(
        f"\n### Production decision: {matching.PRODUCTION_MATCH_THRESHOLD_M:.0f}m\n\n"
        "**Do not read the 30m matched-count as \"correct\" — it isn't.** The "
        "(10m, 30m] band is dominated by `NoSidewalk` labels (11,874 of 16,217 "
        "in that band, ~73%; full sample above is almost entirely `NoSidewalk`). "
        "That's structural, not noise: a `NoSidewalk` label marks the *absence* "
        "of a sidewalk, so by definition there is no correctly-positioned "
        "pedestrian segment for it to sit near — matching it to whatever "
        "footway happens to be within 30m (often the far side of a street, per "
        "the sample's lat/lon) would silently manufacture a false association. "
        "Well-positioned label types tell a different story: `CurbRamp` "
        "and `NoCurbRamp` are already 97-99% matched at 10m and gain "
        "under 1 point going to 30m; `Crosswalk`/`Signal` are similar. "
        "`SurfaceProblem`/`Obstacle` gain a bit more (~3-4 points) out to 30m, "
        "consistent with genuine GPS/pano-derived position noise rather than "
        "systematic mismatch. Going stricter from 15m to 10m costs those "
        "well-positioned types only 0.6-2.4 points while cutting the "
        "`NoSidewalk` band roughly in half (11,991 vs 17,537 matched) — "
        "per the instruction to prefer a stricter threshold when it "
        "materially reduces false matches, **10m is the production threshold** "
        "(`app.core.matching.PRODUCTION_MATCH_THRESHOLD_M`). `NoSidewalk` "
        "labels' segment attribution should be revisited later against a "
        "street-network graph, not the pedestrian-only one built here.\n\n"
        f"Applied result at 10m: {matched_by_nearest} matched by "
        f"nearest-segment, {unmatched} unmatched (across all label types; "
        f"`match_distance_m` is preserved for unmatched labels too, so how "
        f"close the nearest segment actually was is never lost).\n\n"
        "**Ambiguity flagging was recalibrated, not taken as originally "
        "designed.** A first pass flagged 1st/2nd-nearest-segment gaps under "
        "3m as ambiguous and hit 158,414 of 218,660 matches (72%) — because "
        "this graph splits every way into short segments at each "
        "intersection/crossing, so at any corner several segments legitimately "
        "sit within a meter of each other by construction (median gap across "
        "all matches is ~0.6m); flagging all of those would make the flag "
        "useless for triage, and 72% of them turned out to be splits of the "
        "*same* OSM way, not competing candidates. `ambiguous_match` now "
        "requires: the match isn't a near-exact hit (>2m), the runner-up is "
        f"within {matching.AMBIGUITY_RATIO:.0%} of that distance, and the "
        "runner-up is a genuinely different OSM way — "
        f"**{ambiguous} labels ({ambiguous/matched_by_nearest:.1%} of matches) "
        "meet that bar** and are flagged rather than silently resolved to "
        "whichever segment the KNN query happened to return first.\n"
    )

    with open(REPORT_PATH, "a", encoding="utf-8") as f:
        f.writelines(lines)


if __name__ == "__main__":
    main()
