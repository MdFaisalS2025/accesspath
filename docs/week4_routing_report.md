# Week 4 — Routing

Pathfinding over the scored pedestrian graph. Design, formulas, and rationale are in `backend/app/core/routing.py`'s module docstring; this report is the real-data demonstration + test summary. No API endpoint or frontend yet -- `find_route()` and `load_routing_graph()` are called directly here and from tests.

## Requirements checklist

- **Crossing evidence scoped to crossing edges, not whole segments**: already true structurally from Week 3.5's domain scoping -- a crossing is its own graph edge with its own `segment_scores` row; routing costs each edge from its own row only. Verified by `test_routing.py::test_crossing_edge_score_does_not_affect_adjacent_footway_edge_weight`.
- **Route explanations expose dominant hazards, unknown segments, disputed evidence**: `summarize_route()` returns `dominant_hazards`, `unknown_segment_ids`, `disputed_segment_ids` as separate lists.
- **Unknown vs. low-confidence stay distinguishable**: `unknown_segment_ids` (coverage_status='unknown') and `low_confidence_segment_ids` (coverage_status='labeled' but confidence_score < 0.3) are reported as two separate lists, never merged.
- **Explicit no-connected-route result**: `find_route()` checks `component_id` before pathfinding and raises `app.core.graph.NoConnectedRouteError` (same exception Week 2.5's connectivity-guard tests already exercise), not a generic `networkx.NetworkXNoPath` or an empty result.
- **Three modes can produce different paths**: verified on a controlled synthetic graph (`test_routing.py`, 4 tests) and on real data below.
- No routing endpoint or frontend code added.

## Real-data demonstration: node 85107 -> node 136407

### Mode: `shortest`

- Path: 583 nodes, 11263.3m total
- Mean accessibility: 0.567, min accessibility: 0.087
- Mean confidence: 0.107, min confidence: 0.000
- Unknown segments: 247, low-confidence segments: 249, disputed segments: 2
- Dominant hazards on route: [{'segment_id': 36656, 'hazard_type': 'Obstacle'}, {'segment_id': 36662, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 175023, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 43791, 'hazard_type': 'Obstacle'}, {'segment_id': 43816, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 175032, 'hazard_type': 'Obstacle'}, {'segment_id': 38652, 'hazard_type': 'Obstacle'}, {'segment_id': 93943, 'hazard_type': 'NoCurbRamp'}, {'segment_id': 93910, 'hazard_type': 'Obstacle'}, {'segment_id': 93911, 'hazard_type': 'Obstacle'}, {'segment_id': 93912, 'hazard_type': 'Obstacle'}, {'segment_id': 93913, 'hazard_type': 'Obstacle'}, {'segment_id': 44156, 'hazard_type': 'Obstacle'}, {'segment_id': 44133, 'hazard_type': 'Obstacle'}, {'segment_id': 168379, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 135172, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 134810, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 133974, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 20419, 'hazard_type': 'NoCurbRamp'}, {'segment_id': 20395, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 49297, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 47843, 'hazard_type': 'Obstacle'}, {'segment_id': 10410, 'hazard_type': 'Obstacle'}]

### Mode: `accessible`

- Path: 621 nodes, 11508.8m total
- Mean accessibility: 0.585, min accessibility: 0.150
- Mean confidence: 0.115, min confidence: 0.000
- Unknown segments: 237, low-confidence segments: 288, disputed segments: 3
- Dominant hazards on route: [{'segment_id': 44827, 'hazard_type': 'Obstacle'}, {'segment_id': 93931, 'hazard_type': 'Obstacle'}, {'segment_id': 44163, 'hazard_type': 'Obstacle'}, {'segment_id': 44161, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 206445, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 44669, 'hazard_type': 'Obstacle'}, {'segment_id': 170232, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 20419, 'hazard_type': 'NoCurbRamp'}, {'segment_id': 20395, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 49297, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 10410, 'hazard_type': 'Obstacle'}]

### Mode: `confidence_aware`

- Path: 632 nodes, 11576.9m total
- Mean accessibility: 0.587, min accessibility: 0.087
- Mean confidence: 0.138, min confidence: 0.000
- Unknown segments: 230, low-confidence segments: 274, disputed segments: 4
- Dominant hazards on route: [{'segment_id': 44827, 'hazard_type': 'Obstacle'}, {'segment_id': 36662, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 175023, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 43791, 'hazard_type': 'Obstacle'}, {'segment_id': 43816, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 44705, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 38652, 'hazard_type': 'Obstacle'}, {'segment_id': 93943, 'hazard_type': 'NoCurbRamp'}, {'segment_id': 93910, 'hazard_type': 'Obstacle'}, {'segment_id': 93911, 'hazard_type': 'Obstacle'}, {'segment_id': 93912, 'hazard_type': 'Obstacle'}, {'segment_id': 93913, 'hazard_type': 'Obstacle'}, {'segment_id': 44156, 'hazard_type': 'Obstacle'}, {'segment_id': 44133, 'hazard_type': 'Obstacle'}, {'segment_id': 159209, 'hazard_type': 'Obstacle'}, {'segment_id': 44103, 'hazard_type': 'Obstacle'}, {'segment_id': 44104, 'hazard_type': 'Obstacle'}, {'segment_id': 44624, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 44669, 'hazard_type': 'Obstacle'}, {'segment_id': 170232, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 168379, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 136474, 'hazard_type': 'NoCurbRamp'}, {'segment_id': 71612, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 135819, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 20419, 'hazard_type': 'NoCurbRamp'}, {'segment_id': 20395, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 20372, 'hazard_type': 'Obstacle'}, {'segment_id': 20371, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 49567, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 53762, 'hazard_type': 'SurfaceProblem'}, {'segment_id': 10410, 'hazard_type': 'Obstacle'}, {'segment_id': 31531, 'hazard_type': 'Obstacle'}, {'segment_id': 128979, 'hazard_type': 'Obstacle'}]

The three modes above are computed on the exact same origin/destination pair and graph -- any difference in path length, node sequence, or the flag counts is the modes actually trading off distance against accessibility/confidence differently, not measurement noise.

**A counterintuitive-looking number here, explained:** `confidence_aware` shows *more* dominant hazards (32) than `shortest` (23), which looks backwards for the mode meant to avoid uncertainty. It isn't: `confidence_aware` also has *fewer* unknown segments (230 vs. 247) and higher mean confidence (0.138 vs. 0.107). A dominant hazard can only appear on a `labeled` segment (an `unknown` segment has no evidence to set a ceiling with); the mode is doing exactly what it's designed to do -- preferring a well-attested segment that's confidently reporting a problem over a segment with no evidence at all, since the latter's real condition is unknown, not necessarily better. On real, coverage-sparse data that trade-off is visible; on the synthetic graphs in `test_routing.py` it's isolated and asserted directly (`test_confidence_aware_mode_avoids_the_low_confidence_path`).

## Test results

`backend/tests/test_routing.py` (13 tests, synthetic graphs only, no DB):
shortest/accessible/confidence_aware mode separation (4 tests, including
the three-way-disagreement assertion above), no-connected-route +
unknown-node + invalid-mode error handling (4 tests), route-explanation
field correctness -- unknown vs. low-confidence vs. disputed vs. dominant
hazard, each independently exercised (4 tests), and the crossing/footway
edge-independence check (1 test).

`backend/tests/test_data_quality.py` adds 4 DB-integration routing tests:
`load_routing_graph()` produces a graph matching real node/edge counts, a
real same-component route succeeds, a real cross-component route raises
`NoConnectedRouteError`, and at least one real origin/destination pair
shows the three modes disagreeing (the query behind the demo above).

**64/64 tests pass** across the whole suite (`docker compose exec api
pytest tests/ -v`), unchanged from before Week 4 plus these 17 new ones.
