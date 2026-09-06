# Week 8 Evaluation Report

**Status: curated prototype evaluation. This is not proof of real-world route safety or general routing effectiveness across Seattle.** It exercises exactly 8 hand-selected origin/destination pairs, frozen in Week 7 *before* any of these results were seen (`docs/week7_benchmark_pairs.json`, generated 2026-09-06T20:51:38Z). Nothing about pair selection, scoring parameters, or thresholds was changed after seeing the numbers below. Raw, machine-readable output is in [`docs/week8_evaluation_results.json`](week8_evaluation_results.json); geometry sanity-check output is in [`docs/week8_geometry_validation.json`](week8_geometry_validation.json).

## 1. What was run

All 8 frozen categories (`short`, `medium`, `long`, `well_labeled_area`, `heavy_unknown_coverage`, `cross_component`, `modes_agree`, `modes_diverge`) were evaluated across all 3 routing modes (`shortest`, `accessible`, `confidence_aware`) via `backend/scripts/run_evaluation.py`, run inside the API container against the live PostGIS data and in-process graph — the same code path the frontend uses (`/route/compare`), not a separate evaluation-only implementation.

7 of 8 pairs produced a route in all 3 modes. `cross_component` produced `status: "no_connected_route"` in all 3 modes — this is the *expected, designed* outcome for that category (its origin and destination were deliberately chosen in Week 7 to sit in different connected components of the sidewalk graph), not a failure.

### Record-level results

| Category | Mode | Distance (m) | Added vs shortest | Mean access. | Mean conf. | Known hazards | Unknown % | Low-conf % | Disputed % | Geometry differs |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| short | shortest | 420.5 | — | 0.531 | 0.040 | 0 | 39.6% | 56.4% | 0.0% | — |
| short | accessible | 420.6 | +0.02% | 0.539 | 0.045 | 0 | 38.4% | 57.8% | 0.0% | yes |
| short | confidence_aware | 420.6 | +0.02% | 0.539 | 0.045 | 0 | 38.4% | 57.8% | 0.0% | yes |
| medium | shortest | 3460.7 | — | 0.561 | 0.093 | 10 | 40.0% | 53.1% | 4.33% | — |
| medium | accessible | 3467.4 | +0.19% | 0.566 | 0.100 | 11 | 42.4% | 52.5% | 2.13% | yes |
| medium | confidence_aware | 3572.5 | +3.23% | 0.560 | 0.124 | 21 | 38.4% | 44.2% | 4.50% | yes |
| long | shortest | 13882.6 | — | 0.525 | 0.063 | 28 | 53.9% | 27.4% | 0.05% | — |
| long | accessible | 14201.7 | +2.30% | 0.541 | 0.065 | 20 | 49.9% | 45.8% | 2.52% | yes |
| long | confidence_aware | 14277.2 | +2.84% | 0.540 | 0.085 | 36 | 36.2% | 41.3% | 0.46% | yes |
| well_labeled_area | shortest | 48.7 | — | 0.602 | 0.161 | 0 | 7.4% | 60.5% | 18.8% | — |
| well_labeled_area | accessible | 53.9 | +10.60% | 0.707 | 0.267 | 0 | 6.2% | 18.9% | 0.0% | yes |
| well_labeled_area | confidence_aware | 53.9 | +10.60% | 0.707 | 0.267 | 0 | 6.2% | 18.9% | 0.0% | yes |
| heavy_unknown_coverage | all 3 | 64.9 | 0.00% | 0.500 | 0.000 | 0 | 100.0% | 0.0% | 0.0% | no (only path exists) |
| cross_component | all 3 | — | no connected route (expected) | — | — | — | — | — | — |
| modes_agree | all 3 | 27.5 | 0.00% | 0.500 | 0.000 | 0 | 100.0% | 0.0% | 0.0% | no (only path exists) |
| modes_diverge | shortest | 11263.3 | — | 0.567 | 0.107 | 23 | 38.8% | 42.2% | 0.93% | — |
| modes_diverge | accessible | 11508.8 | +2.18% | 0.585 | 0.115 | 11 | 40.6% | 48.3% | 0.36% | yes |
| modes_diverge | confidence_aware | 11576.9 | +2.78% | 0.587 | 0.138 | 33 | 28.2% | 46.1% | 0.37% | yes |

Routing computation time was sub-millisecond to ~0.75s even for the 14km `long` route (A*, all 3 modes computed server-side per pair). `total_http_latency_s_for_all_3_modes` ranged ~8ms (trivial pairs) to ~1.86s (`long`) for the single `/route/compare` call that returns all 3 modes together — there is no single-mode HTTP endpoint, so this latency figure is **per pair, not per mode**, and is attached identically to all 3 mode rows for that pair in the raw JSON; do not read it as "confidence_aware takes 1.86s," it means "the whole 3-mode comparison for `long` takes 1.86s including HTTP overhead."

### Aggregate summary

```json
{
  "total_pairs": 8, "ok_pairs": 7, "no_connected_route_pairs": 1,
  "pairs_with_mode_divergence": 5, "pairs_with_mode_divergence_fraction": 0.714,
  "accessible_added_distance_pct_median": 0.193, "accessible_added_distance_pct_max": 10.60,
  "confidence_aware_added_distance_pct_median": 2.784, "confidence_aware_added_distance_pct_max": 10.60,
  "mean_unknown_segment_proportion_shortest": 0.542,
  "mean_unknown_segment_proportion_confidence_aware": 0.496
}
```

## 2. Honest interpretation

**How often do the 3 modes diverge?** 5 of 7 connected pairs (71.4%) produced at least one mode with a different route geometry than `shortest`. The 2 pairs where all 3 modes were identical (`heavy_unknown_coverage`, `modes_agree`) are both trivial, very short pairs where only a single connected path existed at all — there was no alternative route for any mode to choose, so agreement there reflects an absence of choice, not agreement on trade-offs. Among pairs with more than one viable path, mode divergence was the norm, not the exception.

**Median / max accessibility-aware detour.** `accessible` mode: median +0.19% added distance, max +10.60% (`well_labeled_area`). `confidence_aware` mode: median +2.78% added distance, max +10.60% (also `well_labeled_area`, where `accessible` and `confidence_aware` picked the identical route). **The 10.60% max figure is misleading in isolation**: it is 5.16 extra meters on a 48.7m route. Presenting it as "up to a 10.6% detour" without the absolute figure would overstate the real-world cost — this is exactly the kind of framing the evaluation brief warned against, so both numbers are reported together everywhere in this document. On the two longest, most realistic pairs (`long`, `modes_diverge`), `confidence_aware` added 2.30–2.84% distance for 313–395 extra meters over 11–14km walks.

**Does confidence-aware reduce unknown-segment exposure?** Yes, but conditionally and with a real trade-off attached, not unconditionally. Comparing `shortest` → `confidence_aware` unknown-segment proportion: `short` 39.6%→38.4%, `medium` 40.0%→38.4%, `long` 53.9%→36.2%, `well_labeled_area` 7.4%→6.2%, `modes_diverge` 38.8%→28.2%. Every one of the 5 pairs with a real choice showed a reduction, and the aggregate mean (0.542→0.496) confirms it holds on average, most strongly on the two longest routes where there was the most graph to route around. It never got *worse* in this sample.

**When does confidence-aware choose a known-imperfect segment over an unknown one?** This is visible directly in `known_hazard_count`, which is *higher* under `confidence_aware` than under `shortest` in the 3 pairs with rich hazard data: `medium` (10→21), `long` (28→36), `modes_diverge` (23→33). This is the model working as designed — it is explicitly built to prefer a segment with reliable evidence (even evidence describing a real, documented problem) over a segment with no evidence at all, because "no evidence" is not the same as "no problem." The frontend and this report both avoid calling this "more hazards" without that context, since a higher hazard *count* here reflects more *documented* segments, not necessarily a route with more actual barriers than the unknown-heavy alternative.

**Unexpectedly-worse-metric cases.** Two are worth naming plainly rather than omitting:
- `low_confidence_segment_proportion` gets *worse* under `confidence_aware` than under `shortest` in 3 of 5 divergent pairs: `short` (56.4%→57.8%), `long` (27.4%→41.3%, the largest regression), `modes_diverge` (42.2%→46.1%). This is a direct consequence of the unknown-exposure trade described above: routing away from *unknown* segments necessarily routes onto *some* segment, and when the only alternative is a segment with existing but low-confidence evidence, that's where the router goes. `confidence_aware` is not a strictly-dominant improvement on every uncertainty metric simultaneously — it improves unknown-exposure at the recorded cost of low-confidence-exposure in over half of the pairs where it had a real choice.
- `disputed_segment_proportion` is very slightly worse under `confidence_aware` in `medium` (4.33%→4.50%, a 0.17-percentage-point difference on a low-base metric) — negligible in this sample but included for completeness rather than cherry-picked out.

**Which results support the thesis, which weaken it?**
- *Supports*: mode divergence is frequent and not cosmetic (71.4% of connected pairs); the confidence-aware mode consistently reduces unknown-segment exposure when there is a real routing choice, at a typically small absolute distance cost (median +2.78%, and even the worst realistic case is a few hundred meters over an 11–14km walk); the dominance-aware scoring model visibly trades toward *documented* imperfection over *undocumented* uncertainty, which is the specific design goal from Week 3.5.
- *Weakens / complicates*: `confidence_aware` is not a strict improvement across every confidence-related metric — it can and does increase low-confidence-segment exposure while decreasing unknown-segment exposure, so it should never be marketed as "more confident everywhere," only as "shifts exposure from unknown toward known-but-uncertain, on average, in this sample." Mean confidence scores themselves remain low in absolute terms across every pair (0.00–0.27 on presumably a 0–1 scale) — this reflects how sparse the real Project Sidewalk coverage is over this OSM extract, and it means even the routing choices described above are being made on genuinely thin evidence.

**Are 8 pairs sufficient?** No — 8 pairs, one per category, is sufficient only to *demonstrate that the three modes behave differently and to illustrate the specific trade-offs above with concrete, inspectable examples*. It is not sufficient to estimate how often these trade-offs occur across Seattle generally, what the true distribution of added-distance or hazard counts looks like citywide, or whether the 71.4% divergence rate and the low-confidence regression rate generalize beyond this specific, hand-picked, non-random sample. Any claim beyond "in this curated set of 8 examples, X happened" would be overreach.

## 3. Route geometry validation

A programmatic check (`backend/scripts/validate_route_geometry.py`) inspected every route (all 3 modes × 7 connected pairs = 21 routes) for consecutive-point jumps >150m, duplicate/looping points, and bounding-box sanity. Output: [`docs/week8_geometry_validation.json`](week8_geometry_validation.json).

It flagged jumps in `medium` (1 jump, 170m), `long` (10 jumps, up to 704.6m), and `modes_diverge` (multiple jumps, up to 210m). Each flagged jump was investigated directly against the database rather than dismissed or excluded:

- Every flagged jump was cross-checked against the `segments` and `nodes` tables. In every case, the segment-to-segment boundary coordinates matched the shared node's stored coordinate exactly (e.g. segment 35353's last point and segment 35354's first point both equal node 25774's coordinate `(47.6305365, -122.3433391)` to full precision; same result for segments 154025/154026 at node 181020).
- The jumps are entirely **internal to single OSM segments that have very few digitized vertices** — e.g. segment 35354 is 201.8m long but stored as only 2 coordinate points (a straight line), so any single "hop" between its two points is large by construction, independent of the routing/geometry-stitching code.
- **Conclusion: no defect.** This is normal OSM digitization sparsity, not a routing bug, a broken stitch at a segment boundary, or a sign that the route geometry is wrong. Per this week's instruction ("if an evaluation exposes a defect, fix it and rerun"), no fix was made and the frozen benchmark was not rerun, because no defect was found — only a diagnostic artifact in a first draft of the investigation script itself (an off-by-one in coordinate-ownership attribution), which was corrected before drawing this conclusion, not worked around.

**Live-browser spot check.** Because the exact frozen-pair coordinates can't be reproduced pixel-perfectly through click-based browser automation, the numeric/geometric check above is the exact, authoritative validation of the frozen pairs' geometry. As a complementary check on the *frontend rendering pipeline itself* (not the frozen pairs), a route comparison was run in the live UI between two points in roughly the same geography as `modes_diverge` (South Seattle → Belltown/Capitol Hill area). It rendered correctly: three distinct route lines following real streets, no visual jumps, loops, or incorrect water crossings, and it surfaced a real disconnected-component snap fallback in the UI copy ("A closer point existed (13m away) but was not part of the same connected network as the other endpoint, so this slightly farther point was used instead to make a route possible") — confirming that user-facing disclosure text works correctly on a live, unscripted example, not just in unit tests.

## 4. Demo pair selection

**Primary: `modes_diverge`** (origin node 85107 → destination node 136407). Chosen for clarity, not for the most favorable metrics: all 3 modes produce visibly different routes, the trade-off is easy to narrate in under two minutes (confidence-aware cuts unknown-segment exposure from 38.8% to 28.2% while accepting more documented hazards, for a 2.8%/313m detour), and its live-browser rendering was already spot-checked above with no issues.

**Fallback: `medium`** (origin node 1 → destination node 134). Also shows 3-way mode divergence with an interpretable hazard story (10 → 11 → 21 known hazards across shortest/accessible/confidence_aware) and a shorter, faster-to-narrate route (~3.5km) if the primary pair has any live-demo issue (e.g. a slow network during a real-time demo).

`well_labeled_area` was deliberately **not** selected as either pair despite its dramatic-looking 10.6% detour figure — that number is 5 meters in absolute terms and would misrepresent the system's typical behavior if used as the headline demo example.
