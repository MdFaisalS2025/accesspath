# Week 5 — FastAPI Routing & Geospatial Endpoints

Implementation: `backend/app/main.py` (app + lifespan), `backend/app/routers/route.py`
and `backend/app/routers/map.py` (endpoints), `backend/app/core/route_service.py`
(route-comparison orchestration), `backend/app/core/geo.py` (coordinate
validation + snapping), `backend/app/core/db.py` (connection pool). Builds
directly on Week 4's `app.core.routing` (unchanged) and Week 3.5's
`segment_scores`.

## Audit question resolved first

See the "Audit: does CROSS_DOMAIN_DISCOUNT actually propagate into
confidence?" section appended to `docs/week3_5_scoring_review.md`.
**Not a defect** — confirmed at full float precision that discount does
propagate into confidence (0.1246 → 0.1398 → 0.1547 across discount
0/0.15/0.3), and that `RELIABILITY_DOMINANCE_CUTOFF`'s invariance is
correct by design (it's used in exactly one place in `scoring.py`, gating
the accessibility-score ceiling, and has no path into the confidence
formula at all). No code change made.

## 1. `POST /route/compare`

### Example request

```json
POST /route/compare
{
  "origin_lat": 47.6831576,
  "origin_lon": -122.3746339,
  "destination_lat": 47.6094471,
  "destination_lon": -122.3413975
}
```

### Example response (`status: "ok"`, trimmed — one mode shown, geometry truncated)

```json
{
  "status": "ok",
  "origin": {
    "requested": {"lat": 47.6831576, "lon": -122.3746339},
    "snap": {
      "node_id": 37, "snapped_lat": 47.6831576, "snapped_lon": -122.3746339,
      "snap_distance_m": 0.0, "component_id": 0,
      "adjusted_for_connectivity": false,
      "nearest_unconstrained_node_id": 37, "nearest_unconstrained_distance_m": 0.0
    }
  },
  "destination": { "...": "same shape as origin" },
  "disclaimer": "accessibility_score and confidence_score are relative decision-support indicators derived from crowdsourced Project Sidewalk reports and OSM tags, not probabilities or a safety guarantee. A high score does not certify a route is safe, and a low or unknown score does not mean it is impassable -- verify accessibility needs independently.",
  "routes": {
    "shortest": {
      "mode": "shortest",
      "geometry": {"type": "LineString", "coordinates": [["...lon,lat pairs..."]]},
      "distance_m": 9610.41,
      "estimated_travel_time_s": 8008.68,
      "accessibility_score": 0.5259,
      "min_accessibility_score": 0.0,
      "confidence_score": 0.0738,
      "min_confidence_score": 0.0,
      "coverage": {"total_segments": 488, "labeled_segments": 228, "unknown_segments": 260},
      "hazards": [{"segment_id": 180643, "hazard_type": "SurfaceProblem"}, "... 23 more"],
      "unknown_segment_ids": [180660, 183695, "... 258 more"],
      "low_confidence_segment_ids": [180661, 180655, "... 186 more"],
      "disputed_segment_ids": [180655, 188200, "... 6 more"],
      "explanation": "shortest route: 9610m across 488 segments. Known hazards on this route (reliable reports that capped a segment's score): 7 NoCurbRamp, 11 Obstacle, 7 SurfaceProblem. 260 segment(s) have no accessibility evidence at all (unknown, not verified either way). 188 segment(s) have some evidence but low confidence in it. 8 segment(s) have conflicting (disputed) evidence."
    },
    "accessible": { "...": "same shape" },
    "confidence_aware": { "...": "same shape" }
  },
  "comparison_notes": [
    "confidence_aware passes through more segments with a known, reliably-reported issue than shortest (44 vs 25), but fewer segments with no evidence at all (235 vs 260) -- it prefers a documented imperfect path over an unverified one.",
    "confidence_aware passes through more segments with a known, reliably-reported issue than accessible (44 vs 29), but fewer segments with no evidence at all (235 vs 256) -- it prefers a documented imperfect path over an unverified one."
  ]
}
```

This is a real captured response (node ids, counts, and the comparison
note are exactly what the running system produced) — not a hand-written
example.

### Example response (`status: "no_connected_route"`)

```json
{
  "status": "no_connected_route",
  "reason": "origin_and_destination_in_different_connected_components",
  "origin": { "...": "snap details" },
  "destination": { "...": "snap details" },
  "disclaimer": "...",
  "origin_component_id": 0,
  "destination_component_id": 1
}
```

No `routes` key at all in this case — a client checks `status` first, not
presence/absence of fields.

**Design choice, stated plainly:** a cross-component request returns
**HTTP 200**, not a 4xx. The request itself is valid; the graph simply has
no path between those two points *right now* (see `app.core.graph`'s
docstring — most disconnection is an OSM digitization artifact, not a
real gap, per Week 2.5). This is the same shape choice mapping services
make for "zero results" vs. a client error. Genuinely bad input (outside
the service area, no nearby network at all) does use 4xx — see below.

## 2. Coordinate snapping

`app.core.geo.snap_point()`. `MAX_SNAP_DISTANCE_M = 75.0` (documented
constant, not configurable per-request) — chosen as a generous single-block
radius: far enough to absorb ordinary GPS/click imprecision, not so far
that a request from an unmapped area (a park, a body of water) silently
lands on an unrelated street.

- Every snap response includes `snap_distance_m`, `snapped_lat/lon`,
  `component_id`, `nearest_unconstrained_node_id`, and
  `nearest_unconstrained_distance_m` — even when no connectivity
  adjustment happened, so a client can always see exactly what was
  matched and how far.
- The destination is snapped preferring nodes in the **origin's**
  component (`prefer_component_id`) once the origin is resolved, since
  that's what actually determines routability for this pair. If a
  same-component node exists within `MAX_SNAP_DISTANCE_M`, it's chosen
  over the absolute-nearest node and `adjusted_for_connectivity: true` is
  set — the substitution is reported, never silent. If no same-component
  node is within range, the absolute-nearest node is used regardless of
  component, and `find_route()` will then correctly produce
  `no_connected_route`.
- Beyond `MAX_SNAP_DISTANCE_M`, snapping fails outright
  (`no_routable_network`) rather than silently picking a very distant
  node.

## 3. Error handling

| Situation | Status | Body shape |
|---|---|---|
| Missing/wrong-type field, lat/lon outside ±90/±180 | 422 | `{"error": "validation_error", "message": ..., "details": [pydantic errors]}` |
| Coordinate outside the Seattle service area | 400 | `{"error": "out_of_service_area", "message": ..., "supported_bounds": {...}}` |
| No routable node within 75m of a coordinate | 400 | `{"error": "no_routable_network", "message": ..., "max_snap_distance_m": 75.0}` |
| Origin/destination in different components | **200** | `{"status": "no_connected_route", "reason": ..., "origin_component_id": ..., "destination_component_id": ...}` — see rationale above |
| bbox malformed / wrong arity / inverted | 422 | `{"error": "invalid_bbox", "message": ...}` |
| bbox exceeds max size | 400 | `{"error": "bbox_too_large", "message": ..., "max_lat_span_deg": ..., "max_lon_span_deg": ...}` |
| Unhandled internal error | 500 | `{"error": "internal_error", "message": "An internal error occurred."}` — real exception is logged server-side only, never serialized to the client |

One envelope shape for every status code: a custom `HTTPException` handler
(`app.main.http_exception_handler`) flattens `exc.detail` to the top level
instead of leaving it nested under `"detail"` (FastAPI's default for
`HTTPException`) — so 400/422/500 all read as `{"error": ..., "message": ...}`
plus status-specific extra fields, with no special-casing needed on the
client side to know where to look.

## 4. Read-only map endpoints

`GET /segments?bbox=min_lon,min_lat,max_lon,max_lat`,
`GET /labels?bbox=...`, `GET /coverage-summary?bbox=...`.

- `MAX_BBOX_LAT_SPAN_DEG = 0.03`, `MAX_BBOX_LON_SPAN_DEG = 0.045` (~3.3km ×
  3.3km at Seattle's latitude — a generous single map-viewport, not the
  ~0.25° × 0.22° full city).
- `MAX_RESULTS = 2000` for `/segments` and `/labels`; the response always
  carries `"truncated": true/false` and `"count"` so a client can tell
  whether it saw everything in the box. `/coverage-summary` is a `GROUP BY`
  aggregate (a handful of numbers regardless of bbox), so no result cap
  applies, but the same bbox-size cap does (bounded query cost either way).

### Example: `GET /segments?bbox=-122.35,47.61,-122.34,47.62`

```json
{
  "type": "FeatureCollection",
  "count": 187,
  "truncated": false,
  "features": [
    {
      "type": "Feature",
      "geometry": {"type": "LineString", "coordinates": [["..."]]},
      "properties": {"segment_id": 12345, "osm_way_id": 987654321, "highway_type": "footway", "length_m": 42.1}
    }
  ]
}
```

### Example: `GET /coverage-summary?bbox=-122.35,47.61,-122.34,47.62`

```json
{
  "bbox": {"min_lon": -122.35, "min_lat": 47.61, "max_lon": -122.34, "max_lat": 47.62},
  "total_segments": 412,
  "dominance_capped_segments": 31,
  "by_coverage_status": {
    "labeled": {"segment_count": 190, "mean_accessibility_score": 0.58, "mean_confidence_score": 0.16, "dominance_capped_count": 31},
    "unknown": {"segment_count": 222, "mean_accessibility_score": null, "mean_confidence_score": null, "dominance_capped_count": 0}
  }
}
```

## 5. Application lifecycle

`app.main`'s `lifespan` context manager runs once at process startup:
initializes a `psycopg2.pool.ThreadedConnectionPool` (`app.core.db`,
1–10 connections) and calls `app.core.routing.load_routing_graph()` once,
storing the result on `app.state.graph` — every request reuses it via
`request.app.state.graph`, never rebuilding it. Every DB-touching request
uses `Depends(get_conn)` (`app.dependencies`), which checks a connection
out of the pool and always returns it in a `finally`, even on error.
Pool is closed on shutdown (`close_pool()`).

### Measured (this machine, this DB)

- **Graph load time: 1.90s** (185k nodes / 213.5k edges after simple-graph
  dedup), measured via `time.monotonic()` around `load_routing_graph()`.
- **Memory after load: 362MB RSS** (`resource.getrusage().ru_maxrss`).
- **Route latency** (`POST /route/compare`, wall-clock via `curl`, warm
  process):
  - Short route (~450m, 12–32 segments/mode): **55–97ms**.
  - Long route (~9.6–9.9km, 488–563 segments/mode): **2.75–3.2s**.
- **Map endpoint latency** (~3.3km×3.3km bbox): `/segments` ~119ms,
  `/labels` ~116ms, `/coverage-summary` ~76ms.

Both are exposed at runtime via `GET /health/graph` (nodes, edges,
`load_seconds`, `load_rss_mb`), not just logged once at startup.

**Known risk, not fixed this week:** the long-route latency (up to ~3.2s)
is dominated by running `networkx.shortest_path` (Dijkstra) three times
over a ~185k-node graph — Dijkstra's explored search space grows with
route distance, and it's the same graph regardless of mode. Short routes
are fast (<100ms); a genuinely long cross-city route is not. Documented
in "Unresolved risks" below rather than addressed now (a bidirectional
search or component-local subgraph extraction would help, but that's
routing-algorithm work beyond this week's API-focused scope).

## 6. Deterministic explanations

`route_service.build_mode_explanation()` builds the same string from the
same route data every time (no randomness; hazard types are
alphabetically sorted before joining) and explicitly separates four
distinct situations rather than folding them into one "some issues" line:
known/reliable hazards (`dominant_hazards`), segments with no evidence at
all (`unknown_segment_ids`), segments with evidence but low confidence in
it (`low_confidence_segment_ids`), and segments with conflicting evidence
(`disputed_segment_ids`). `build_comparison_notes()` specifically covers
the case called out in review — when `confidence_aware` trades more known
imperfections for fewer unknowns relative to `shortest`/`accessible`, a
note says so explicitly (see the real example above, where
`confidence_aware` shows 44 hazards vs. shortest's 25, but fewer unknowns:
235 vs. 260). Every response also carries `SCORE_DISCLAIMER` verbatim,
stating scores are relative decision-support indicators, not
probabilities or a safety guarantee.

## 7. Testing

`backend/tests/test_api.py` — 22 tests against a session-scoped
`TestClient` (the app's real lifespan runs once for the whole module, so
the graph loads once, not per test):

- Schema/validation: missing field, out-of-range latitude, wrong type → all 422.
- Coordinate snapping: out-of-service-area (400), no-routable-network in
  open water >1km from any node (400), exact-node-coordinate snaps at
  distance 0.
- Same-component routing: 200, all three modes present, valid GeoJSON
  geometry, non-empty explanation.
- Cross-component routing: 200 with `status: "no_connected_route"`,
  no `routes` key.
- Destination-snap component preference: verifies `adjusted_for_connectivity`
  and the resulting component when a same-component alternative exists.
- Mode distinguishability through the real API (not just the unit-level
  synthetic graph in `test_routing.py`): finds a real mixed-evidence
  origin/destination pair and asserts at least one mode's geometry differs.
- bbox/result-limit tests: valid bbox, oversized bbox (400), malformed/
  wrong-arity/inverted bbox (422), for all three map endpoints.
- Health regression test + a new `/health/graph` test.
- Internal-failure test: monkeypatches `compare_routes` to raise, confirms
  a 500 with the structured body and that no exception name or traceback
  text leaks into the response.

**Full suite: 86/86 tests pass** (`docker compose exec api pytest tests/ -v`),
64 unchanged from before Week 5 plus these 22 new API tests.

## Unresolved risks / follow-ups (not fixed this week, flagged for visibility)

1. **Long-route latency** (up to ~3.2s) — see Section 5. Acceptable for a
   research prototype, not for a production SLA.
2. **No rate limiting / auth** on any endpoint — explicitly out of scope
   per this week's instructions (no auth work), but a real deployment
   would need it before `/segments`/`/labels` are exposed publicly, since
   even bounded bbox queries can be repeated arbitrarily.
3. **`ASSUMED_WALKING_SPEED_MPS = 1.2`** is a documented guess, not
   calibrated against any real pedestrian trip data — `estimated_travel_time_s`
   should be read as illustrative, not a commitment.
4. **Single-process connection pool** (`ThreadedConnectionPool`, max 10):
   fine for one uvicorn worker; would need a per-worker pool or an
   external pooler (pgbouncer) if this API is ever run with multiple
   worker processes.
