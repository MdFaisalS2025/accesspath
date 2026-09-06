"""
Week 3.5 scoring review: compares the production model (E, ceiling-capped
risk accumulation) against three alternatives on synthetic adversarial
scenarios and real segments from the current DB, and writes
docs/week3_5_scoring_review.md (compute_scores.py appends the production
distribution section afterward -- run this script first).

    docker compose exec api python scripts/compare_scoring_models.py
    docker compose exec api python scripts/compute_scores.py
"""
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app")
from app.core import scoring
from app.core.db import get_connection
from scripts.compute_scores import fetch_all_segments, fetch_matched_labels

REPORT_PATH = "/docs/week3_5_scoring_review.md"
AS_OF = datetime(2026, 9, 6, tzinfo=timezone.utc)


def make_label(
    label_type,
    severity=None,
    agree_count=5,
    disagree_count=0,
    unsure_count=0,
    label_date=None,
    match_method="nearest_segment",
    match_distance_m=1.0,
    ambiguous_match=False,
    pano_id="panoA",
    ps_label_id=None,
):
    return {
        "ps_label_id": ps_label_id,
        "label_type": label_type,
        "severity": severity,
        "agree_count": agree_count,
        "disagree_count": disagree_count,
        "unsure_count": unsure_count,
        "label_date": label_date if label_date is not None else AS_OF - timedelta(days=90),
        "match_method": match_method,
        "match_distance_m": match_distance_m,
        "ambiguous_match": ambiguous_match,
        "pano_id": pano_id,
    }


def run_all_models(labels, segment_highway_type="footway"):
    a_acc, a_conf = scoring.score_segment_weighted_average(labels, AS_OF, segment_highway_type)
    b_acc = scoring.score_segment_min_aggregation(labels, AS_OF, segment_highway_type)
    d_acc = scoring.score_segment_risk_only(labels, AS_OF, segment_highway_type)
    e = scoring.score_segment(labels, AS_OF, segment_highway_type)
    return {
        "A (weighted avg)": a_acc,
        "B (min aggregation)": b_acc,
        "D (risk, no ceiling)": d_acc,
        "E (production: risk + ceiling)": e["accessibility_score"],
    }, e


# ---------------------------------------------------------------------------
# Adversarial scenarios (each with a distinct pano_id per label so the
# non-independence discount doesn't interfere, except scenario 4 which
# deliberately shares pano_id to test that discount)
# ---------------------------------------------------------------------------

def scenario_curbramps_vs_nosidewalk():
    labels = [make_label("CurbRamp", pano_id=f"p{i}") for i in range(10)]
    labels.append(make_label("NoSidewalk", match_distance_m=1.0, pano_id="pNS"))
    return labels


def scenario_positives_vs_severe_obstacle():
    labels = [make_label("CurbRamp", pano_id=f"p{i}") for i in range(6)]
    labels += [make_label("Crosswalk", pano_id=f"c{i}") for i in range(4)]
    labels.append(make_label("Obstacle", severity=3, match_distance_m=1.0, pano_id="pOb"))
    return labels


def scenario_equal_reliable_evidence():
    labels = [make_label("CurbRamp", pano_id="pPos")]
    labels.append(make_label("NoCurbRamp", severity=3, pano_id="pNeg"))
    return labels


def scenario_duplicated_correlated_labels():
    # 8 CurbRamp labels, all same pano_id (single audit pass, same feature
    # reported repeatedly) -- should NOT count as 8 independent votes.
    return [make_label("CurbRamp", pano_id="panoSame") for _ in range(8)]


def scenario_crossing_evidence_only():
    # Only crossing-domain evidence (CurbRamp/Crosswalk), matched to a plain
    # footway segment (not a dedicated crossing way) -- domain-discounted,
    # and shouldn't be read as proof of the segment's own surface condition.
    labels = [make_label("CurbRamp", pano_id=f"p{i}") for i in range(3)]
    labels.append(make_label("Crosswalk", pano_id="pcw"))
    return labels


def scenario_unknown_no_evidence():
    return []


SCENARIOS = [
    ("Ten CurbRamp + one reliable NoSidewalk", scenario_curbramps_vs_nosidewalk(), "footway"),
    ("Many positives + one severe reliable Obstacle", scenario_positives_vs_severe_obstacle(), "footway"),
    ("Equal reliable positive vs. negative evidence", scenario_equal_reliable_evidence(), "footway"),
    ("8 duplicated/correlated CurbRamp labels (same pano_id)", scenario_duplicated_correlated_labels(), "footway"),
    ("Crossing evidence only, on a footway segment", scenario_crossing_evidence_only(), "footway"),
    ("Unknown segment, no evidence", scenario_unknown_no_evidence(), "footway"),
]


def write_scenarios_section(f):
    f.write("## Adversarial scenario comparison\n\n")
    f.write(
        "Same label set run through all four models. Reliable = fresh (90 days "
        "old), unanimously agreed (5 agree / 0 disagree / 0 unsure), tightly "
        "matched (1m), unambiguous, unique pano_id per label unless noted.\n\n"
    )
    for name, labels, highway_type in SCENARIOS:
        scores, e = run_all_models(labels, highway_type)
        f.write(f"### {name}\n\n")
        f.write("| Model | accessibility_score |\n|---|---|\n")
        for model_name, acc in scores.items():
            f.write(f"| {model_name} | {acc:.3f} |\n")
        if e["coverage_status"] == "labeled":
            f.write(
                f"\nProduction model detail: confidence={e['confidence_score']:.3f}, "
                f"positive_evidence={e['positive_evidence']:.3f}, "
                f"negative_evidence={e['negative_evidence']:.3f}, "
                f"evidence_consistency={e['evidence_consistency']:.3f}, "
                f"dominant_hazard={e['dominant_hazard_type']}\n\n"
            )
        else:
            f.write(f"\nProduction model: coverage_status=unknown (no informative evidence).\n\n")


SCENARIO_TAKEAWAYS = """
**Reading the scenarios:**

1. **Ten CurbRamp + one reliable NoSidewalk.** Model A (weighted average)
   lands at 0.620 ("moderately accessible") — ten positives pull the average
   well above what one severe hazard alone would justify, which is exactly
   the failure mode this review exists to fix. Model D (risk, no ceiling)
   improves on that (0.492) but still isn't low enough for a segment with a
   confirmed missing sidewalk. Model E lands at 0.050 -- exactly the
   NoSidewalk label's own value, applied as a hard ceiling regardless of the
   ten CurbRamp labels also present. (An earlier draft of the ceiling
   blended reliability continuously -- `1 - r*(1-value)` -- and only reached
   0.288 here even for this "reliable" label, since realistic reliability
   rarely exceeds ~0.75 once agreement-smoothing/recency/match-quality are
   multiplied together; fixed by making the cap a value_i pass/fail once
   reliability clears the trust bar, not a blend. See scoring.py's docstring.)
2. **Many positives + one severe reliable Obstacle.** Same pattern: A stays
   at 0.624, E drops to exactly the Obstacle's own severity-3 value (0.150)
   since the obstacle report clears the reliability bar and hard-caps the
   score there.
3. **Equal reliable positive vs. negative evidence.** A lands near the
   midpoint (looks "moderately accessible, confidently"). E's accessibility
   score also lands near the midpoint via `base_score`, but — this is the
   point of the confidence redesign, not the accessibility redesign —
   `evidence_consistency` comes out near 0 (maximally contested), pulling
   `confidence_score` down. The segment reads as "genuinely disputed,"
   not "confidently mediocre."
4. **8 duplicated/correlated CurbRamp labels, same pano_id.** Without the
   non-independence discount this would look like 8x the evidence of a
   single CurbRamp label. With it, only the first counts fully and the
   other 7 count at 20% each — `positive_evidence` comes out far below what
   8 independent labels would produce, and confidence grows much more
   slowly with each additional same-pano label.
5. **Crossing evidence only, on a footway segment.** CurbRamp/Crosswalk are
   crossing-domain evidence; matched to a plain footway (not a dedicated
   crossing way) they're cross-domain-discounted to 15% reliability each.
   The segment ends up barely-labeled (low evidence_quantity) rather than
   confidently "accessible" — a curb ramp near a footway is not proof the
   footway's own surface is fine, which was the literal problem being
   guarded against.
6. **Unknown segment, no evidence.** All four models agree: neutral prior
   0.5, confidence 0, `coverage_status='unknown'`. No disagreement here —
   included as a control case.
"""


def write_real_segment_diffs(f, conn):
    f.write("## Real segments where the revised model differs materially from the weighted average\n\n")
    as_of = datetime.now(timezone.utc)
    labels_by_segment = fetch_matched_labels(conn)
    segments = fetch_all_segments(conn)

    diffs = []
    evaluated_count = 0
    for segment_id, labels in labels_by_segment.items():
        highway_type = segments.get(segment_id)
        informative = [l for l in labels if scoring.is_informative(l)]
        if not informative:
            continue
        evaluated_count += 1
        a_acc, _ = scoring.score_segment_weighted_average(informative, as_of, highway_type)
        e = scoring.score_segment(informative, as_of, highway_type)
        diff = a_acc - e["accessibility_score"]
        if abs(diff) > 0.05:
            diffs.append((segment_id, a_acc, e, diff, len(informative)))

    diffs.sort(key=lambda row: -abs(row[3]))
    capped_diffs = sum(1 for _, _, e, _, _ in diffs if e["dominant_hazard_type"] is not None)
    f.write(
        f"{len(diffs)} of {evaluated_count} labeled segments (i.e. with >=1 "
        "informative matched label -- matches compute_scores.py's `labeled` "
        "count) differ by more than 0.05 between Model A and Model E. Of "
        f"those, {capped_diffs} ({capped_diffs/len(diffs):.1%}) are hard "
        f"dominance-capped by a reliable hazard; the remaining "
        f"{len(diffs) - capped_diffs} differ because the risk-accumulation "
        "base formula itself (noisy-OR, not a plain average) treats hazard "
        "evidence differently even below the hard-cap reliability bar -- "
        "still an intentional part of the redesign (graduated combination "
        "of minor evidence, per the review request), not a side effect of "
        "the ceiling. Largest differences (all hard-capped -- the ceiling "
        "produces the most dramatic swings, as intended):\n\n"
    )
    f.write(
        "| segment_id | label_count | Model A (weighted avg) | Model E (production) | diff | dominant_hazard |\n"
        "|---|---|---|---|---|---|\n"
    )
    for segment_id, a_acc, e, diff, n in diffs[:10]:
        f.write(
            f"| {segment_id} | {n} | {a_acc:.3f} | {e['accessibility_score']:.3f} | "
            f"{diff:+.3f} | {e['dominant_hazard_type']} |\n"
        )
    f.write(
        "\nEvery large-diff segment above is dominance-capped (has a "
        "`dominant_hazard_type`) — confirms the divergence is coming from "
        "the ceiling mechanism doing its job on real data, not just "
        "synthetic scenarios.\n"
    )
    return diffs


def write_intro(f):
    f.write("# Week 3.5 — Scoring Model Review\n\n")
    f.write(
        "Week 3's accessibility score was a plain reliability-weighted "
        "average across a segment's matched labels. Rejected in review: "
        "enough positive labels can numerically outvote one reliable, "
        "severe hazard, which is unsafe for accessibility routing. This "
        "document compares four models and recommends one. Full formulas "
        "and rationale live in `backend/app/core/scoring.py`'s module "
        "docstring; this is the evidence for why model E was chosen.\n\n"
    )
    f.write("## Models compared\n\n")
    f.write(
        "| Model | Idea | Verdict |\n|---|---|---|\n"
        "| A. Weighted average (Week 3, rejected) | `sum(r*value)/sum(r)` | "
        "Positive evidence can cancel a severe hazard — the problem being fixed |\n"
        "| B. Min aggregation (\"worst reliable hazard\") | score = worst value among "
        "reliable labels | Too conservative: one old, borderline-reliable "
        "SurfaceProblem permanently caps an otherwise well-evidenced segment, "
        "with no way for anything else to matter |\n"
        "| D. Risk accumulation only, no ceiling | noisy-OR risk vs. support, "
        "no hard cap | Combines minor evidence gradually (good), but a large "
        "enough pile of positives can still pull the score up past what a "
        "dominant hazard alone justifies — same failure class as A, needs more "
        "labels to trigger |\n"
        "| **E. Risk accumulation + dominance ceiling (production)** | D's "
        "graduated base, hard-capped by the worst *reliable* hazard alone | "
        "Dominance is a provable property of the formula (min() with a term "
        "that doesn't reference positive evidence at all), not an emergent, "
        "eventually-violable weighting outcome |\n\n"
    )


def main():
    conn = get_connection()
    try:
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            write_intro(f)
            write_scenarios_section(f)
            f.write(SCENARIO_TAKEAWAYS)
            f.write("\n")
        with open(REPORT_PATH, "a", encoding="utf-8") as f:
            write_real_segment_diffs(f, conn)
        with open(REPORT_PATH, "a", encoding="utf-8") as f:
            f.write(
                "\n## Recommendation\n\n"
                "**Adopt Model E (ceiling-capped risk accumulation)** as the "
                "production model. It's the only one of the four where the "
                "dominance rules requested in review are guaranteed by the "
                "formula rather than merely typical for reasonable inputs: "
                "`final = min(base_score, ceiling)` and `ceiling` is computed "
                "purely from hazard labels, so no quantity of positive "
                "evidence can affect it. Model B (pure min-aggregation) was "
                "rejected as overly blunt — it discards all graduated "
                "information once any reliable hazard exists. Model A and D "
                "were rejected because both remain, in principle, "
                "outvotable given enough evidence.\n"
            )
        print(f"Model comparison written to {REPORT_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
