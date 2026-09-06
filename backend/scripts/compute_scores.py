"""
Computes accessibility_score + confidence_score for every segment from its
matched Project Sidewalk labels, using app.core.scoring's production model
(ceiling-capped risk accumulation, adopted in Week 3.5 -- see
docs/week3_5_scoring_review.md for why the original Week 3 weighted-average
model was rejected, and docs/week3_scoring_report.md for that original run).

Fully reproducible/idempotent: truncates and recomputes segment_scores from
accessibility_labels + segments each run. Run inside the api container,
after build_graph.py, validate_matching.py, and
backfill_label_provenance.py have populated accessibility_labels:

    docker compose exec api python scripts/compute_scores.py
"""
import sys
from collections import defaultdict
from datetime import datetime, timezone

import psycopg2.extras

sys.path.insert(0, "/app")
from app.core import scoring
from app.core.db import get_connection

REPORT_PATH = "/docs/week3_5_scoring_review.md"


def fetch_matched_labels(conn):
    """{segment_id: [label_dict, ...]} for every label with a resolved
    segment_id (i.e. match_method in ('ps_osm_way_id', 'nearest_segment');
    unmatched labels have no segment to score and are correctly excluded)."""
    by_segment = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT segment_id, ps_label_id, label_type, severity, agree_count, disagree_count,
                   unsure_count, label_date, match_method, match_distance_m, ambiguous_match, pano_id
            FROM accessibility_labels
            WHERE segment_id IS NOT NULL
            """
        )
        for row in cur.fetchall():
            (segment_id, ps_label_id, label_type, severity, agree_count, disagree_count,
             unsure_count, label_date, match_method, match_distance_m, ambiguous_match, pano_id) = row
            by_segment[segment_id].append(
                {
                    "ps_label_id": ps_label_id,
                    "label_type": label_type,
                    "severity": severity,
                    "agree_count": agree_count,
                    "disagree_count": disagree_count,
                    "unsure_count": unsure_count,
                    "label_date": label_date,
                    "match_method": match_method,
                    "match_distance_m": match_distance_m,
                    "ambiguous_match": ambiguous_match,
                    "pano_id": pano_id,
                }
            )
    return by_segment


def fetch_all_segments(conn):
    """{segment_id: highway_type}, for the domain-scoping discount."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, highway_type FROM segments")
        return dict(cur.fetchall())


def compute_all_scores(conn, as_of=None):
    as_of = as_of or datetime.now(timezone.utc)
    labels_by_segment = fetch_matched_labels(conn)
    segments = fetch_all_segments(conn)

    rows = []
    for segment_id, highway_type in segments.items():
        result = scoring.score_segment(labels_by_segment.get(segment_id, []), as_of, highway_type)
        rows.append(
            (
                segment_id,
                result["accessibility_score"],
                result["confidence_score"],
                result["coverage_status"],
                result["label_count"],
                result["staleness_days"],
                result["positive_evidence"],
                result["negative_evidence"],
                result["evidence_consistency"],
                result["dominant_hazard_type"],
                result["dominant_hazard_ps_label_id"],
            )
        )
    return rows


def store_scores(conn, rows):
    with conn.cursor() as cur:
        cur.execute("TRUNCATE segment_scores")
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO segment_scores
                (segment_id, accessibility_score, confidence_score, coverage_status, label_count,
                 staleness_days, positive_evidence, negative_evidence, evidence_consistency,
                 dominant_hazard_type, dominant_hazard_ps_label_id)
            VALUES %s
            """,
            rows,
            page_size=5000,
        )
    conn.commit()


def summarize(rows):
    labeled = [r for r in rows if r[3] == "labeled"]
    unknown = [r for r in rows if r[3] == "unknown"]
    capped = [r for r in labeled if r[9] is not None]  # dominant_hazard_type set

    def pct(values, p):
        if not values:
            return None
        s = sorted(values)
        k = int(round(p * (len(s) - 1)))
        return s[k]

    acc_labeled = [r[1] for r in labeled]
    conf_labeled = [r[2] for r in labeled]

    return {
        "total_segments": len(rows),
        "labeled": len(labeled),
        "unknown": len(unknown),
        "dominance_capped": len(capped),
        "accessibility_labeled": {
            "mean": sum(acc_labeled) / len(acc_labeled) if acc_labeled else None,
            "p10": pct(acc_labeled, 0.10),
            "p50": pct(acc_labeled, 0.50),
            "p90": pct(acc_labeled, 0.90),
        },
        "confidence_labeled": {
            "mean": sum(conf_labeled) / len(conf_labeled) if conf_labeled else None,
            "p10": pct(conf_labeled, 0.10),
            "p50": pct(conf_labeled, 0.50),
            "p90": pct(conf_labeled, 0.90),
        },
        "confidence_buckets": {
            "0.0-0.2": sum(1 for c in conf_labeled if c < 0.2),
            "0.2-0.5": sum(1 for c in conf_labeled if 0.2 <= c < 0.5),
            "0.5-0.8": sum(1 for c in conf_labeled if 0.5 <= c < 0.8),
            "0.8-1.0": sum(1 for c in conf_labeled if c >= 0.8),
        },
    }


def write_summary_section(summary):
    """Appends the post-migration distribution summary to
    docs/week3_5_scoring_review.md (the model-comparison narrative is
    written separately by scripts/compare_scoring_models.py, which should
    run first so this ends up after it)."""
    with open(REPORT_PATH, "a", encoding="utf-8") as f:
        f.write("\n## Production distribution (Model E, current DB)\n\n")
        f.write(f"- Total segments: {summary['total_segments']}\n")
        f.write(
            f"- `labeled`: {summary['labeled']} ({summary['labeled']/summary['total_segments']:.1%}), "
            f"`unknown`: {summary['unknown']} ({summary['unknown']/summary['total_segments']:.1%})\n"
        )
        f.write(
            f"- Dominance-capped (a reliable hazard set the ceiling below the graduated "
            f"base score): {summary['dominance_capped']} of {summary['labeled']} labeled "
            f"segments ({summary['dominance_capped']/summary['labeled']:.1%})\n\n"
        )
        a = summary["accessibility_labeled"]
        f.write(
            f"- Accessibility (labeled): mean {a['mean']:.3f}, p10 {a['p10']:.3f}, "
            f"p50 {a['p50']:.3f}, p90 {a['p90']:.3f}\n"
        )
        c = summary["confidence_labeled"]
        f.write(
            f"- Confidence (labeled): mean {c['mean']:.3f}, p10 {c['p10']:.3f}, "
            f"p50 {c['p50']:.3f}, p90 {c['p90']:.3f}\n\n"
        )
        f.write("| Confidence bucket | Segments |\n|---|---|\n")
        for bucket, count in summary["confidence_buckets"].items():
            f.write(f"| {bucket} | {count} |\n")
        f.write(
            "\n**vs. the original Week 3 model** (docs/week3_scoring_report.md, "
            "same underlying labels): mean accessibility fell from 0.692 to "
            f"{summary['accessibility_labeled']['mean']:.3f}, and mean confidence "
            f"fell from 0.258 to {summary['confidence_labeled']['mean']:.3f}. Both "
            "drops are expected and intended, not regressions: accessibility "
            "fell because segments with a reliable hazard no longer get "
            "diluted upward by unrelated positive evidence (that dilution was "
            "the entire problem this review fixed); confidence fell because "
            "it's now penalized by evidence *disagreement* in addition to "
            "quantity, and because near-duplicate same-pano labels no longer "
            "count as independent corroboration.\n\n"
        )


def main():
    conn = get_connection()
    try:
        as_of = datetime.now(timezone.utc)
        print(f"Computing scores as of {as_of.isoformat()}...")
        rows = compute_all_scores(conn, as_of)
        print(f"Storing {len(rows)} segment_scores rows...")
        store_scores(conn, rows)

        summary = summarize(rows)
        print(summary)
        write_summary_section(summary)
        print(f"Summary appended to {REPORT_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
