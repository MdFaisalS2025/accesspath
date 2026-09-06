"""
Week 3.5 parameter-sensitivity check, requested before Week 4 routing:
sweeps RELIABILITY_DOMINANCE_CUTOFF in {0.2, 0.3, 0.4} and
CROSS_DOMAIN_DISCOUNT in {0, 0.15, 0.30} (9 combinations), reporting how
each changes dominance-capped count, mean accessibility/confidence, the
count of segments whose score moves by more than 0.10 vs the current
defaults (0.3 / 0.15), and the six adversarial scenarios.

Appends to docs/week3_5_scoring_review.md.

    docker compose exec api python scripts/sensitivity_analysis.py
"""
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app")
from app.core import scoring
from app.core.db import get_connection
from scripts.compare_scoring_models import AS_OF, SCENARIOS
from scripts.compute_scores import fetch_all_segments, fetch_matched_labels

REPORT_PATH = "/docs/week3_5_scoring_review.md"

CUTOFFS = [0.2, 0.3, 0.4]
DISCOUNTS = [0.0, 0.15, 0.30]
DEFAULT_CUTOFF = 0.3
DEFAULT_DISCOUNT = 0.15


def score_all(labels_by_segment, segments, as_of, cutoff, discount):
    """{segment_id: result_dict} for every segment, at the given parameters."""
    results = {}
    for segment_id, highway_type in segments.items():
        results[segment_id] = scoring.score_segment(
            labels_by_segment.get(segment_id, []), as_of, highway_type,
            reliability_dominance_cutoff=cutoff, cross_domain_discount=discount,
        )
    return results


def summarize(results):
    labeled = [r for r in results.values() if r["coverage_status"] == "labeled"]
    capped = [r for r in labeled if r["dominant_hazard_type"] is not None]
    acc = [r["accessibility_score"] for r in labeled]
    conf = [r["confidence_score"] for r in labeled]
    return {
        "labeled": len(labeled),
        "dominance_capped": len(capped),
        "mean_accessibility": sum(acc) / len(acc) if acc else None,
        "mean_confidence": sum(conf) / len(conf) if conf else None,
    }


def count_large_changes(baseline, other, threshold=0.10):
    count = 0
    for segment_id, base_result in baseline.items():
        other_result = other[segment_id]
        if base_result["coverage_status"] != "labeled" or other_result["coverage_status"] != "labeled":
            continue
        if abs(base_result["accessibility_score"] - other_result["accessibility_score"]) > threshold:
            count += 1
    return count


def main():
    conn = get_connection()
    try:
        as_of = datetime.now(timezone.utc)
        print("Loading labels and segments...")
        labels_by_segment = fetch_matched_labels(conn)
        segments = fetch_all_segments(conn)

        print("Scoring at default parameters (baseline)...")
        baseline = score_all(labels_by_segment, segments, as_of, DEFAULT_CUTOFF, DEFAULT_DISCOUNT)

        grid = {}
        for cutoff in CUTOFFS:
            for discount in DISCOUNTS:
                print(f"Scoring at cutoff={cutoff}, discount={discount}...")
                results = score_all(labels_by_segment, segments, as_of, cutoff, discount)
                summary = summarize(results)
                summary["large_changes_vs_default"] = count_large_changes(baseline, results)
                grid[(cutoff, discount)] = summary

        print("Running adversarial scenarios at each grid point...")
        scenario_grid = {}
        for cutoff in CUTOFFS:
            for discount in DISCOUNTS:
                scenario_results = {}
                for name, labels, highway_type in SCENARIOS:
                    result = scoring.score_segment(
                        labels, AS_OF, highway_type,
                        reliability_dominance_cutoff=cutoff, cross_domain_discount=discount,
                    )
                    scenario_results[name] = result["accessibility_score"]
                scenario_grid[(cutoff, discount)] = scenario_results

        write_report(grid, scenario_grid)
        print(f"Sensitivity analysis appended to {REPORT_PATH}")
    finally:
        conn.close()


def write_report(grid, scenario_grid):
    with open(REPORT_PATH, "a", encoding="utf-8") as f:
        f.write("\n## Parameter sensitivity check (pre-Week-4)\n\n")
        f.write(
            f"Sweeps `RELIABILITY_DOMINANCE_CUTOFF` in {CUTOFFS} and "
            f"`CROSS_DOMAIN_DISCOUNT` in {DISCOUNTS} (9 combinations) against "
            "the full current DB. Current defaults: cutoff=0.3, discount=0.15 "
            "(bolded below). \"Large changes\" = segments whose "
            "accessibility_score moves by more than 0.10 vs the default "
            "parameters, among segments labeled under both.\n\n"
        )
        f.write(
            "| cutoff | discount | dominance_capped | mean_accessibility | "
            "mean_confidence | large changes vs default |\n|---|---|---|---|---|---|\n"
        )
        for cutoff in CUTOFFS:
            for discount in DISCOUNTS:
                s = grid[(cutoff, discount)]
                is_default = cutoff == DEFAULT_CUTOFF and discount == DEFAULT_DISCOUNT
                label = f"**{cutoff}**" if is_default else f"{cutoff}"
                dlabel = f"**{discount}**" if is_default else f"{discount}"
                f.write(
                    f"| {label} | {dlabel} | {s['dominance_capped']} | "
                    f"{s['mean_accessibility']:.3f} | {s['mean_confidence']:.3f} | "
                    f"{s['large_changes_vs_default']} |\n"
                )

        f.write("\n### Adversarial scenarios across the grid\n\n")
        f.write("accessibility_score for each scenario at each (cutoff, discount):\n\n")
        header = " | ".join(f"({c},{d})" for c in CUTOFFS for d in DISCOUNTS)
        f.write(f"| Scenario | {header} |\n")
        f.write("|---" * (1 + len(CUTOFFS) * len(DISCOUNTS)) + "|\n")
        for name, _, _ in SCENARIOS:
            row = " | ".join(
                f"{scenario_grid[(c, d)][name]:.3f}" for c in CUTOFFS for d in DISCOUNTS
            )
            f.write(f"| {name} | {row} |\n")
        f.write("\n")


if __name__ == "__main__":
    main()
