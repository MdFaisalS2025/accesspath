"""
Week 8: runs the FROZEN Week 7 benchmark set (docs/week7_benchmark_pairs.json,
read-only -- never regenerated or reselected here, per this week's explicit
instruction) and computes the evaluation metrics defined in Week 7's
docs/week7_hardening_report.md Section 5.

Writes machine-readable results to docs/week8_evaluation_results.json
(record-level, one row per pair x mode, plus an aggregate summary) and
prints a human-readable summary. docs/week8_evaluation_report.md is the
narrative write-up built from this file's output -- this script computes
numbers, it does not interpret them.

Run inside the api container (needs DB access + the in-process graph):
    docker compose exec api python scripts/run_evaluation.py
"""
import json
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, "/app")
from app.core import routing
from app.core.db import get_connection
from app.core.route_service import ASSUMED_WALKING_SPEED_MPS

FROZEN_PAIRS_PATH = "/docs/week7_benchmark_pairs.json"
OUTPUT_PATH = "/docs/week8_evaluation_results.json"
API_BASE = "http://localhost:8000"


def load_frozen_pairs():
    with open(FROZEN_PAIRS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data["pairs"]


def distance_by_predicate(segments, predicate):
    return sum(s["length_m"] for s in segments if predicate(s))


def evaluate_mode(conn, graph, route_result, shortest_result):
    """route_result / shortest_result: raw dicts from routing.find_route()
    (already computed, with 'segments' -- see routing.summarize_route)."""
    segments = route_result["segments"]
    total_m = route_result["total_length_m"]

    unknown_m = distance_by_predicate(segments, lambda s: s["coverage_status"] == "unknown")
    low_conf_m = distance_by_predicate(
        segments, lambda s: s["coverage_status"] == "labeled" and s["confidence_score"] < routing.LOW_CONFIDENCE_THRESHOLD
    )
    disputed_m = distance_by_predicate(
        segments,
        lambda s: s.get("evidence_consistency") is not None
        and s["evidence_consistency"] < routing.DISPUTED_CONSISTENCY_THRESHOLD,
    )

    dominant_hazards = route_result["dominant_hazards"]
    # dominant_hazards entries only carry segment_id + hazard_type (see
    # routing.summarize_route); look up each segment's dominant_hazard_ps_label_id
    # and severity via segment_scores/accessibility_labels for the severity report.
    hazard_details = []
    if dominant_hazards:
        seg_ids = [h["segment_id"] for h in dominant_hazards]
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT sc.segment_id, sc.dominant_hazard_type, sc.dominant_hazard_ps_label_id, l.severity
                FROM segment_scores sc
                LEFT JOIN accessibility_labels l ON l.ps_label_id = sc.dominant_hazard_ps_label_id
                WHERE sc.segment_id = ANY(%s)
                """,
                (seg_ids,),
            )
            for seg_id, hazard_type, ps_label_id, severity in cur.fetchall():
                hazard_details.append({"segment_id": seg_id, "hazard_type": hazard_type, "severity": severity})

    added_distance_m = total_m - shortest_result["total_length_m"] if shortest_result else 0.0
    added_time_s = added_distance_m / ASSUMED_WALKING_SPEED_MPS

    geometry_differs_from_shortest = (
        route_result["path_node_ids"] != shortest_result["path_node_ids"] if shortest_result else False
    )

    return {
        "distance_m": total_m,
        "estimated_time_s": total_m / ASSUMED_WALKING_SPEED_MPS,
        "added_distance_m_vs_shortest": added_distance_m,
        "added_time_s_vs_shortest": added_time_s,
        "added_distance_pct_vs_shortest": (added_distance_m / shortest_result["total_length_m"] * 100) if shortest_result and shortest_result["total_length_m"] else 0.0,
        "mean_accessibility": route_result["mean_accessibility"],
        "min_accessibility": route_result["min_accessibility"],
        "mean_confidence": route_result["mean_confidence"],
        "min_confidence": route_result["min_confidence"],
        "known_hazard_count": len(dominant_hazards),
        "hazard_details": hazard_details,
        "unknown_segment_distance_m": unknown_m,
        "unknown_segment_proportion": unknown_m / total_m if total_m else 0.0,
        "low_confidence_segment_distance_m": low_conf_m,
        "low_confidence_segment_proportion": low_conf_m / total_m if total_m else 0.0,
        "disputed_segment_distance_m": disputed_m,
        "disputed_segment_proportion": disputed_m / total_m if total_m else 0.0,
        "segment_count": len(segments),
        "geometry_differs_from_shortest": geometry_differs_from_shortest,
    }


def time_http_request(origin, destination):
    import urllib.request
    body = json.dumps({
        "origin_lat": origin["lat"], "origin_lon": origin["lon"],
        "destination_lat": destination["lat"], "destination_lon": destination["lon"],
    }).encode()
    req = urllib.request.Request(f"{API_BASE}/route/compare", data=body, headers={"Content-Type": "application/json"})
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()
        status_code = resp.status
    return time.perf_counter() - start, status_code


def evaluate_pair(conn, graph, pair):
    category = pair["category"]
    origin_id = pair["origin"]["node_id"]
    destination_id = pair["destination"]["node_id"]

    record = {"category": category, "origin_node_id": origin_id, "destination_node_id": destination_id}

    if pair["status"] != "ok":
        record["status"] = pair["status"]
        record["modes"] = {}
        return record

    record["status"] = "ok"
    raw_results = {}
    computation_stats = {}
    for mode in routing.MODES:
        stats = {}
        raw_results[mode] = routing.find_route(graph, origin_id, destination_id, mode, stats=stats)
        computation_stats[mode] = stats

    http_elapsed_s, http_status = time_http_request(pair["origin"], pair["destination"])

    modes = {}
    for mode in routing.MODES:
        metrics = evaluate_mode(conn, graph, raw_results[mode], raw_results[routing.SHORTEST])
        metrics["routing_computation_s"] = computation_stats[mode]["elapsed_s"]
        metrics["algorithm"] = computation_stats[mode]["algorithm"]
        # total_http_latency_s is per-PAIR (one /route/compare call returns
        # all 3 modes together -- there is no single-mode HTTP endpoint),
        # so the same value is attached to every mode's row with that noted.
        metrics["total_http_latency_s_for_all_3_modes"] = http_elapsed_s
        modes[mode] = metrics

    record["modes"] = modes
    record["modes_all_identical"] = len({tuple(r["path_node_ids"]) for r in raw_results.values()}) == 1
    return record


def build_aggregate_summary(records):
    ok_records = [r for r in records if r["status"] == "ok"]
    divergent = [r for r in ok_records if not r["modes_all_identical"]]

    def collect(mode, field):
        return [r["modes"][mode][field] for r in ok_records if mode in r["modes"]]

    accessible_added_pct = collect("accessible", "added_distance_pct_vs_shortest")
    confidence_aware_added_pct = collect("confidence_aware", "added_distance_pct_vs_shortest")

    def median(values):
        if not values:
            return None
        s = sorted(values)
        n = len(s)
        mid = n // 2
        return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2

    unknown_shortest = collect("shortest", "unknown_segment_proportion")
    unknown_confidence_aware = collect("confidence_aware", "unknown_segment_proportion")

    return {
        "total_pairs": len(records),
        "ok_pairs": len(ok_records),
        "no_connected_route_pairs": len(records) - len(ok_records),
        "pairs_with_mode_divergence": len(divergent),
        "pairs_with_mode_divergence_fraction": len(divergent) / len(ok_records) if ok_records else None,
        "accessible_added_distance_pct_median": median(accessible_added_pct),
        "accessible_added_distance_pct_max": max(accessible_added_pct) if accessible_added_pct else None,
        "confidence_aware_added_distance_pct_median": median(confidence_aware_added_pct),
        "confidence_aware_added_distance_pct_max": max(confidence_aware_added_pct) if confidence_aware_added_pct else None,
        "mean_unknown_segment_proportion_shortest": sum(unknown_shortest) / len(unknown_shortest) if unknown_shortest else None,
        "mean_unknown_segment_proportion_confidence_aware": sum(unknown_confidence_aware) / len(unknown_confidence_aware) if unknown_confidence_aware else None,
    }


def main():
    conn = get_connection()
    try:
        print("Loading routing graph...")
        graph = routing.load_routing_graph(conn)

        pairs = load_frozen_pairs()
        print(f"Loaded {len(pairs)} FROZEN pairs from {FROZEN_PAIRS_PATH} (not regenerated).")

        records = []
        for pair in pairs:
            print(f"Evaluating {pair['category']}...")
            records.append(evaluate_pair(conn, graph, pair))

        summary = build_aggregate_summary(records)

        output = {
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "frozen_pairs_source": FROZEN_PAIRS_PATH,
            "frozen_pairs_generated_at": json.load(open(FROZEN_PAIRS_PATH, encoding="utf-8"))["generated_at"],
            "records": records,
            "aggregate_summary": summary,
        }
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)

        print(f"\nWritten to {OUTPUT_PATH}\n")
        print(json.dumps(summary, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
