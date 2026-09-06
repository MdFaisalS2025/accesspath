# Week 2 — Graph Build & Label Join Report

## Graph connectivity

- Nodes: 184695
- Edges (segments): 213508
- Connected components: 2696
- Largest component: 151778 nodes (82.1776% of all nodes)
- Top 10 component sizes: [151778, 23325, 1207, 516, 302, 163, 162, 112, 110, 103]
- Isolated nodes (degree 0): 1559

Edge count is deduplicated (networkx `Graph` collapses parallel edges between the same two nodes), so it can be slightly below the raw segment count. The ~18% of nodes outside the largest component are mostly small disconnected clusters (e.g. isolated courtyard paths, a footway that ends at a crossing node not shared with the road network) rather than one large second region — see the component-size list above. Each node's `component_id` (0 = largest) is persisted for routing to use. See the Week 2.5 section below for a deeper look at whether the smaller components are legitimate or data artifacts.

## Project Sidewalk label join

- Total labels loaded: 262053
- Matched via `osm_way_id` (Project Sidewalk's own join): 71
- Matched via nearest-segment fallback (<= 10m, validated in Week 2.5 below): 210868
- Unmatched: 51114

**Finding, contradicting the Week 1 plan (docs/data_verification.md):** `osm_way_id` on Project Sidewalk labels almost never matches a way in our pedestrian extract (footway/path/pedestrian/steps/footway=crossing) — only 71 of 262053 labels. Spot-checking confirms PS's `osm_way_id` is the *street* way each label's `street_edge_id` was derived from, not a dedicated sidewalk/footway way. The nearest-segment spatial join is therefore the primary matching method in practice, not a fallback for edge cases as the Week 1 doc assumed; the ID join is kept first since it is authoritative on the rare occasions it does resolve.

## Week 2.5 — Matching threshold validation

Labels needing a spatial match (i.e. not resolved by `osm_way_id`): 261982 (ID-matched separately: 71).

### Matched/unmatched by threshold

| Threshold | Matched | Unmatched |
|---|---|---|
| 5m | 198869 | 63113 |
| 10m | 210868 | 51114 |
| 15m | 218660 | 43322 |
| 30m | 227052 | 34930 |

### Matched fraction by label type, per threshold

| label_type | total | <=5m | <=10m | <=15m | <=30m |
|---|---|---|---|---|---|
| CurbRamp | 100729 | 95990 (95.3%) | 98570 (97.9%) | 99224 (98.5%) | 99644 (98.9%) |
| NoSidewalk | 51630 | 6068 (11.8%) | 11991 (23.2%) | 17537 (34.0%) | 23863 (46.2%) |
| NoCurbRamp | 44613 | 42240 (94.7%) | 43111 (96.6%) | 43462 (97.4%) | 43720 (98.0%) |
| SurfaceProblem | 37491 | 32854 (87.6%) | 33829 (90.2%) | 34413 (91.8%) | 35082 (93.6%) |
| Obstacle | 17946 | 13523 (75.4%) | 14381 (80.1%) | 14806 (82.5%) | 15409 (85.9%) |
| Crosswalk | 6234 | 5615 (90.1%) | 6025 (96.6%) | 6098 (97.8%) | 6125 (98.3%) |
| Signal | 1653 | 1515 (91.7%) | 1612 (97.5%) | 1628 (98.5%) | 1640 (99.2%) |
| Occlusion | 1157 | 779 (67.3%) | 1000 (86.4%) | 1050 (90.8%) | 1090 (94.2%) |
| Other | 529 | 285 (53.9%) | 349 (66.0%) | 442 (83.6%) | 479 (90.5%) |

### Distance distribution for matches in (10m, 30m]

- Count: 16184
- Mean: 16.94m
- Median: 15.28m
- p90: 26.03m
- p99: 29.59m
- Max: 30.00m

### Sample for manual inspection (farthest first, up to 20)

| ps_label_id | label_type | region | distance_m | osm_way_id | highway_type | lat | lon |
|---|---|---|---|---|---|---|---|
| 212595 | NoSidewalk | Mid-Beacon Hill | 30.0 | 1546201357 | footway | 47.551151 | -122.307872 |
| 230298 | NoSidewalk | Columbia City | 30.0 | 1393686423 | steps | 47.567176 | -122.291029 |
| 74941 | NoSidewalk | Roxhill | 30.0 | 685297198 | footway | 47.526371 | -122.365845 |
| 243984 | NoSidewalk | Meadowbrook | 30.0 | 1083609439 | footway | 47.700193 | -122.293172 |
| 66039 | NoSidewalk | Olympic Hills | 30.0 | 1022449890 | crossing | 47.723145 | -122.301979 |
| 227880 | NoSidewalk | Mid-Beacon Hill | 30.0 | 384271217 | crossing | 47.546430 | -122.301162 |
| 23921 | NoSidewalk | Industrial District | 30.0 | 758629544 | crossing | 47.571659 | -122.340050 |
| 65046 | NoSidewalk | South Park | 30.0 | 1054563754 | footway | 47.539516 | -122.337006 |
| 14115 | NoSidewalk | Fauntleroy | 30.0 | 1350818445 | path | 47.530060 | -122.390480 |
| 45799 | NoSidewalk | Maple Leaf | 30.0 | 1073212099 | footway | 47.698559 | -122.314606 |
| 50702 | NoSidewalk | Leschi | 30.0 | 185030486 | footway | 47.600574 | -122.288383 |
| 276689 | NoSidewalk | Riverview | 30.0 | 1232817671 | footway | 47.546298 | -122.357098 |
| 89706 | Obstacle | South Delridge | 30.0 | 1249392428 | crossing | 47.527950 | -122.363106 |
| 250492 | NoSidewalk | Matthews Beach | 30.0 | 1268926168 | footway | 47.695862 | -122.273810 |
| 109655 | NoSidewalk | Mount Baker | 30.0 | 228562540 | footway | 47.580814 | -122.286438 |
| 39876 | NoSidewalk | Sand Point | 30.0 | 502476230 | footway | 47.679077 | -122.260963 |
| 239201 | Obstacle | Dunlap | 30.0 | 808920563 | footway | 47.530116 | -122.270918 |
| 55190 | NoSidewalk | Fauntleroy | 30.0 | 868866099 | crossing | 47.524853 | -122.389694 |
| 40888 | NoSidewalk | North Queen Anne | 30.0 | 1126004429 | crossing | 47.644978 | -122.361748 |
| 10769 | NoSidewalk | Stevens | 30.0 | 286689630 | footway | 47.635120 | -122.308235 |

### Production decision: 10m

**Do not read the 30m matched-count as "correct" — it isn't.** The (10m, 30m] band is dominated by `NoSidewalk` labels (11,874 of 16,217 in that band, ~73%; full sample above is almost entirely `NoSidewalk`). That's structural, not noise: a `NoSidewalk` label marks the *absence* of a sidewalk, so by definition there is no correctly-positioned pedestrian segment for it to sit near — matching it to whatever footway happens to be within 30m (often the far side of a street, per the sample's lat/lon) would silently manufacture a false association. Well-positioned label types tell a different story: `CurbRamp` and `NoCurbRamp` are already 97-99% matched at 10m and gain under 1 point going to 30m; `Crosswalk`/`Signal` are similar. `SurfaceProblem`/`Obstacle` gain a bit more (~3-4 points) out to 30m, consistent with genuine GPS/pano-derived position noise rather than systematic mismatch. Going stricter from 15m to 10m costs those well-positioned types only 0.6-2.4 points while cutting the `NoSidewalk` band roughly in half (11,991 vs 17,537 matched) — per the instruction to prefer a stricter threshold when it materially reduces false matches, **10m is the production threshold** (`app.core.matching.PRODUCTION_MATCH_THRESHOLD_M`). `NoSidewalk` labels' segment attribution should be revisited later against a street-network graph, not the pedestrian-only one built here.

Applied result at 10m: 210868 matched by nearest-segment, 51114 unmatched (across all label types; `match_distance_m` is preserved for unmatched labels too, so how close the nearest segment actually was is never lost).

**Ambiguity flagging was recalibrated, not taken as originally designed.** A first pass flagged 1st/2nd-nearest-segment gaps under 3m as ambiguous and hit 158,414 of 218,660 matches (72%) — because this graph splits every way into short segments at each intersection/crossing, so at any corner several segments legitimately sit within a meter of each other by construction (median gap across all matches is ~0.6m); flagging all of those would make the flag useless for triage, and 72% of them turned out to be splits of the *same* OSM way, not competing candidates. `ambiguous_match` now requires: the match isn't a near-exact hit (>2m), the runner-up is within 130% of that distance, and the runner-up is a genuinely different OSM way — **17329 labels (8.2% of matches) meet that bar** and are flagged rather than silently resolved to whichever segment the KNN query happened to return first.

## Week 2.5 — Connectivity investigation

Largest component (`component_id = 0`): 151778 nodes (82.2% of all 184695), bounding box lat 47.5037–47.7343, lon -122.4357–-122.2413 — essentially the full Seattle extent from `docs/data_verification.md` (lat 47.4810–47.7342, lon -122.4597–-122.2244), confirming it's the real connected pedestrian network core, not a spurious local cluster.

2695 smaller components hold the remaining 32917 nodes (17.8%). Classified by distance from each component's nearest node to the nearest node in a *different* component: <3m = likely digitization artifact (should be one shared node), 3–50m = plausible real-world gap worth a human look, >50m = genuinely spatially isolated.

| Classification | Components | Nodes |
|---|---|---|
| artifact | 353 | 25643 |
| short_gap | 2060 | 6193 |
| isolated | 282 | 1081 |

### Nearest-other-component gap, smallest 15 components

| component_id | nodes | gap_m | classification |
|---|---|---|---|
| 712 | 2 | 0.10 | artifact |
| 1809 | 1 | 0.17 | artifact |
| 2515 | 1 | 0.25 | artifact |
| 1615 | 1 | 0.40 | artifact |
| 146 | 8 | 0.46 | artifact |
| 355 | 4 | 0.46 | artifact |
| 1704 | 1 | 0.47 | artifact |
| 1908 | 1 | 0.59 | artifact |
| 516 | 3 | 0.59 | artifact |
| 1431 | 1 | 0.62 | artifact |
| 1486 | 1 | 0.68 | artifact |
| 1 | 23325 | 0.69 | artifact |
| 166 | 7 | 0.69 | artifact |
| 2479 | 1 | 0.70 | artifact |
| 1203 | 1 | 0.91 | artifact |

**Finding:** most disconnection is a snapping artifact, not missing real-world infrastructure or an extraction bug — the majority of non-largest-component *nodes* sit in components whose nearest external node is within a few meters (typically the same physical intersection digitized as two unshared OSM nodes, e.g. a footway endpoint and a `kerb=*` node a hair apart that should be the same point, or a crossing way that wasn't node-split where it meets a footway). The `short_gap` and `isolated` groups are smaller and plausibly real (a park's internal path network with no direct pedestrian link to the street grid, a plaza reachable only by crossing a road with no mapped crossing). Node-snapping within a few meters is the highest-leverage follow-up before scoring — it would reconnect most of the graph — but is out of scope for this pass; flagging it, not fixing it, is Week 2.5's job.
