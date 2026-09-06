# Week 7 — Performance, Security, Reliability, and Evaluation Preparation

No new product features. Interface and scope unchanged from Week 6.

## 1. Performance baseline

Reproducible benchmark set: `backend/scripts/benchmark_routes.py` (in-process
routing measurement, run inside the api container) selects 8
origin/destination pairs by category, resolves them to real coordinates,
and measures each of the three modes. `backend/scripts/benchmark_http.py`
(run on the host) measures the same pairs through the real HTTP API,
cold-start vs. warm, and container memory. Both write their raw results to
`docs/week7_benchmark_pairs.json` / `docs/week7_benchmark_http.json` (and
`*_before.json` copies of the pre-optimization run, kept for the diff in
this report).

### Pair selection (documented rationale, in `benchmark_routes.py`'s
`select_*` functions)

| Category | Selection method | Why |
|---|---|---|
| `short` | anchor node + a node ~300m away by real geodesic distance | typical single-block trip |
| `medium` | anchor + ~3km away | a normal cross-neighborhood trip |
| `long` | anchor + ~12km away | Seattle's own diagonal extent, a genuine cross-city trip |
| `well_labeled_area` | endpoints of the two segments with the most matched Project Sidewalk labels | a route through substantial real evidence |
| `heavy_unknown_coverage` | endpoints of two `coverage_status='unknown'` segments | a route through little/no evidence |
| `cross_component` | one node in component 0, one in component 1 | must produce `no_connected_route`, not a path |
| `modes_agree` | short-range candidates checked empirically for identical paths across all 3 modes (not assumed from distance alone) | confirms the "no divergence" case is real, not just short |
| `modes_diverge` | the same mixed-evidence search pattern that produced real divergence in the Week 4/5 demos, checked empirically | confirms genuine mode disagreement, not synthetic |

**Correction made during selection**: an earlier version of `select_long`
picked the two extreme node ids in the table, assuming id order tracked
geographic distance. It didn't -- those two ids turned out to be 5m apart.
Fixed by selecting on real `ST_Distance` instead of id order (see the
function's docstring for the full explanation). This is exactly the kind
of factual, structural correction the freeze process is meant to catch
before locking in a benchmark set -- not a result-driven change.

`modes_agree`/`modes_diverge` are qualified by testing the *actual graph*
for the property that defines the category (all three paths identical, or
not), not assumed from a proxy like distance. The first candidate meeting
each category's structural selection rule that also passes this check is
used -- not cherry-picked among many for a flattering outcome.

### Metrics measured, before optimizing

For each `ok` pair and each mode: routing computation time and a
weight-function-call count (`weight_evaluations` -- see "why not a literal
node count" below) via `app.core.routing.find_route(..., stats={})`;
total API latency via real HTTP calls to `/route/compare`; path distance;
mean accessibility/confidence; container memory via `docker stats`;
cold-start (first request after a container restart) vs. warm (repeat).

**Why `weight_evaluations` instead of a literal "nodes explored" count**:
networkx's `shortest_path`/`astar_path` don't expose an explored-node
count through their public API. The edge-weight function, however, is
called exactly once per edge relaxation by both Dijkstra and A* -- wrapping
it with a counter (`find_route`'s `stats` parameter, zero overhead when
unused) gives a fair, apples-to-apples proxy for search-space size across
both algorithms, without needing a hand-rolled pathfinding implementation
that itself becomes a new place for the actual routing logic to be
correct.

### Baseline results (Dijkstra, pre-optimization)

In-process routing time (all 3 modes) and full HTTP latency (median of 3
warm requests):

| Category | Distance | Routing (shortest/accessible/conf-aware) | HTTP median |
|---|---|---|---|
| short | 421m | 1.9 / 2.0 / 2.3 ms | 105ms |
| medium | 3.5km | 90.5 / 221.0 / 113.3 ms | 355ms |
| **long** | 13.9-14.3km | **1485.5 / 1429.4 / 1291.0 ms** | **4740ms** |
| well_labeled_area | 49-54m | <1ms | 11ms |
| heavy_unknown_coverage | 65m | <1ms | 25ms |
| cross_component | -- | `no_connected_route` | -- |
| modes_agree | 27m | <1ms | 9ms |
| modes_diverge | 11.3-11.6km | 491.6 / 344.1 / 517.4 ms | 1464ms |

Cold start (fresh container, graph loaded at startup, first request on the
`long` pair): graph load 1.86s / 362MB RSS; first request 5.12s; immediate
repeat 4.98s (i.e. cold vs. warm barely differs here -- the graph is
already loaded by the time any request can arrive, so "cold" mostly
reflects DB-pool/OS-cache warm-up, not the graph load itself).
Steady-state container memory: 570.6MB (measurement noise from concurrent
benchmarking activity, not a leak indicator on its own -- see the
post-optimization repeated-request check below).

## 2. Optimization: Dijkstra -> A*

### Why long routes were slow

Plain Dijkstra (`networkx.shortest_path`) explores outward from the origin
by accumulated cost in every direction, with no notion of "toward the
destination." For a 14km trip that means relaxing a large fraction of the
whole ~185k-node graph before the target is even popped from the queue --
confirmed directly by the `weight_evaluations` counts above (up to 255,676
edge relaxations for one mode of the `long` pair).

### Options compared

| Option | Verdict |
|---|---|
| **A\* with a geographic admissible heuristic** | **Chosen.** See correctness argument below. |
| Bidirectional Dijkstra | A real, smaller win than A*, and redundant with it -- not implemented, to keep one algorithm change instead of two. |
| Reusing shared request preparation across the 3 modes | Already true before this week (one shared in-memory graph, one DB connection) for the pathfinding step itself; the one *new* shared-preparation win available was geometry fetching (below), which was implemented. |
| Avoiding repeated graph/score transformations | N/A -- the graph is already built once at startup and never transformed per-request. |
| Safe caching of identical route-comparison requests | **Rejected.** Masks the per-request cost for a repeated request rather than fixing it for the (more common, in a demo/evaluation) case of a *new* pair; also adds staleness-management complexity (the cache would need invalidating whenever `segment_scores` is recomputed) for a one-off local prototype. Not implemented. |

### Implementation

`app.core.routing.find_route()` now calls `networkx.astar_path` instead of
`networkx.shortest_path`, with a heuristic (`_astar_heuristic`) equal to
the haversine (straight-line) distance from a node to the destination.

**Correctness argument (why the heuristic is admissible for all three
modes, not just `shortest`)**: every mode's edge weight is
`length_m * multiplier` with `multiplier >= 1` (see `edge_weight` --
`accessible`'s and `confidence_aware`'s multipliers only ever *increase*
cost above raw length, never reduce it). True path cost is therefore
always `>= length_m >= straight_line_distance` (triangle inequality). An
admissible heuristic can never overestimate true remaining cost -- A* with
this heuristic is guaranteed to still return a cost-optimal path, for
every mode, exactly as Dijkstra did. The heuristic falls back to 0
(equivalent to plain Dijkstra) for any node missing lat/lon, so it never
breaks on a coordinate-free graph (e.g. `test_routing.py`'s synthetic
fixtures).

Also implemented: `route_service.compare_routes()` now fetches segment
geometry once for the *union* of all three modes' segment ids, instead of
once per mode (3 DB round trips -> 1) -- a long route's three modes
typically share most of their path, so this also avoids re-fetching the
same segment's geometry multiple times, not just cutting round trips. Low
risk (pure query consolidation, no algorithm change); measured as a small
addition on top of A*'s much larger effect (see results below).

### Correctness evidence

Ran the full benchmark set before and after and diffed every field:

- **Every single `distance_m` and `mean_accessibility`/`mean_confidence`
  value is bit-identical before and after**, for all 8 categories and all
  3 modes (see `docs/week7_benchmark_pairs_before.json` vs.
  `docs/week7_benchmark_pairs.json`) -- not just equally-optimal-cost, the
  literal path found is the same set of segments in the same order.
- `cross_component` still correctly returns `no_connected_route` after
  the change (component check happens before pathfinding either way,
  untouched).
- `modes_agree`/`modes_diverge` still show the same agreement/divergence
  pattern (`modes_all_identical` unchanged for every category).
- **Full test suite (91 backend tests) still passes**, including
  `test_routing.py`'s controlled synthetic 3-path-disagreement scenario
  and the real-data mode-disagreement test in `test_data_quality.py`.
- **Memory does not grow without bound**: 15 repeated real HTTP requests
  for the `long` pair held container memory flat at 378MiB (measured via
  `docker stats`), no upward drift.

### Before / after latency by category

In-process routing (sum of all 3 modes) and full HTTP median:

| Category | Routing before | Routing after | HTTP before | HTTP after | HTTP speedup |
|---|---|---|---|---|---|
| short | 6.2ms | 3.7ms | 105ms | 31ms | 3.3x |
| medium | 424.8ms | 226.5ms | 355ms | 336ms | 1.06x |
| **long** | **4205.9ms** | **1622.4ms** | **4740ms** | **1918ms** | **2.5x** |
| well_labeled_area | <1ms | <1ms | 11ms | 31ms | n/a (noise, see below) |
| heavy_unknown_coverage | <1ms | <1ms | 25ms | 30ms | n/a (noise, see below) |
| modes_agree | <1ms | <1ms | 9ms | 16ms | n/a (noise, see below) |
| modes_diverge | 1353.1ms | 404.4ms | 1464ms | 468ms | 3.1x |

The three sub-100m categories show *apparent* small regressions (9-25ms ->
16-31ms) that are measurement noise, not an A* cost: their in-process
routing time was and remains sub-millisecond either way, so the observed
change is entirely in fixed per-request overhead (HTTP, DB connection
checkout, JSON serialization) that has nothing to do with the pathfinding
algorithm -- confirmed by the in-process numbers being identical (<1ms
before and after) for these three categories.

**Decision: keep A* + geometry batching.** The optimization is small in
code (one function call swapped, one heuristic added, one query
consolidated), provably correct (admissibility argument above, plus
bit-identical empirical output), adds no new failure modes, and delivers
a 2.5-3.3x reduction in exactly the latency this week set out to fix
(long/diverging routes), with zero measurable regression on real
computation for short routes. A cache or bidirectional search would add
more code for a smaller or redundant benefit -- rejected as unjustified
complexity for this codebase's actual bottleneck.

## 3. Dependency and security review

### npm audit findings (frontend, before remediation)

| Package | Advisory | Severity | Prod or dev? | Reachable here? |
|---|---|---|---|---|
| `esbuild` (<=0.24.2, via vite) | [GHSA-67mh-4wv8-2f99](https://github.com/advisories/GHSA-67mh-4wv8-2f99) -- dev server allows any website to send requests and read responses | Moderate | **Dev only** (esbuild is Vite's dev-server transform layer, not shipped in `npm run build` output) | Only if the Vite dev server (port 5173) is reachable by an attacker's browser via a victim visiting a malicious page while the dev server runs -- true in principle for our docker-compose dev setup exposed on localhost, not for the production build. |
| `vite` (<=6.4.2) | [GHSA-fx2h-pf6j-xcff](https://github.com/advisories/GHSA-fx2h-pf6j-xcff) -- `server.fs.deny` bypass on Windows | High (CVSS 7.5) | **Dev only** (`vite` dev server's static file serving) | Same as above -- dev-server-only, and specifically a Windows-alternate-path bypass; this project's dev server does run on Windows via Docker Desktop, so this was a real (if dev-only) risk here, not purely theoretical. |
| `vite` (<=6.4.1 / <=6.4.2) | GHSA-4w7w-66w2-5vf9, GHSA-v6wh-96g9-6wx3 | Moderate | Dev only | Same dev-server-only reachability. |
| `vite-node` (via vite) | transitive | Moderate | Dev only (used by Vitest to run test files) | Not reachable outside the test-runner process itself. |
| `@vitest/mocker` / `vitest` (<3.2.6) | [GHSA-5xrq-8626-4rwp](https://github.com/advisories/GHSA-5xrq-8626-4rwp) -- Vitest **UI** server allows arbitrary file read/execute | **Critical (CVSS 9.8)** | **Dev only** | **Not reachable in this project's actual usage**: the vulnerable code path is Vitest's `--ui` server, which this project never runs (`npm test` = `vitest run`, no `--ui` anywhere in scripts or CI). The vulnerable *package version* was installed either way. |

**None of the five findings touch production runtime code** — `react`,
`react-dom`, and `maplibre-gl` (the actual dependencies shipped to a
user's browser) have zero reported vulnerabilities. All five are in the
Vite/Vitest dev-tooling chain, and none are practically exploitable via
this project's built, deployed frontend; the highest-severity one
(critical, Vitest UI RCE-like read) additionally requires a code path
(`--ui`) this project never invokes.

### Remediation applied

`npm audit fix` (no `--force`) found no compatible fix within the pinned
major versions (`vite ^5.4.8`, `vitest ^2.1.2` -- both entirely below the
fixed versions). `npm audit fix --force` would have jumped to `vite@8.2.2`
/ `vitest@5.0.0`, multiple majors ahead and a real compatibility risk (the
latest `@vitejs/plugin-react` now requires `vite ^8`, a mismatch with our
other pinned dev tooling). Chose the **smallest version bump that actually
resolves every advisory**: `vite ^6.4.3` (first patched release in the
6.x line), `vitest ^3.2.7` (first patched release after the critical UI
advisory), `@vitejs/plugin-react ^4.3.4` (latest 4.x, still compatible
with vite 6, avoiding the plugin's newer major that requires vite 8).

Applying this surfaced one real, pre-existing gap unrelated to the
security fix itself: `npm run build` had never actually been run since
`jest-axe`/the a11y tests were added in Week 6 (`npm test` only runs
Vitest, which doesn't type-check test files) -- it failed on a missing
`@types/jest-axe` declaration and one loosely-typed test helper. Fixed
both (added `@types/jest-axe`, tightened a `Promise` executor's type in
`App.test.tsx`) since a broken production build is worse than the
security items being remediated.

**Result**: `npm audit` now reports **0 vulnerabilities**. Full frontend
test suite re-run after the upgrade: **26/26 pass** (25 existing + 1 new
retry test, see Section 4), production build succeeds, Playwright e2e
**2/2 pass** against the upgraded toolchain.

### CORS: configurable, not wide open

Was `allow_origins=["*"]` (Week 6, flagged then as "risk beyond a demo").
Now reads `ALLOWED_ORIGINS` (comma-separated) from the environment,
defaulting to just the two local-dev origins
(`http://localhost:5173`, `http://127.0.0.1:5173`) instead of every
origin on the internet; `docker-compose.yml` sets it explicitly so a
deployment only has to change one line to point at a real frontend
origin. Also narrowed `allow_methods`/`allow_headers` from `["*"]` to the
actual `GET, POST` / `Content-Type` this API uses. Verified with two new
tests: the configured origin gets `access-control-allow-origin` echoed
back, an unlisted origin (`http://evil.example.com`) does not.

### Error/log redaction

- `DATABASE_URL` (which contains the DB password) is read exactly twice
  in the whole codebase (`app/core/db.py`, to construct the connection),
  never logged, never included in a response body.
- The catch-all exception handler (`app.main.unhandled_exception_handler`)
  always returns the fixed `{"error": "internal_error", "message": "An
  internal error occurred."}` body regardless of what the underlying
  exception says, and logs the real exception/traceback server-side only
  (`logger.exception`, not returned to the client). Added a test that
  raises an exception whose message contains a fake Postgres
  authentication-failure string (host/user/password-shaped) and confirms
  none of it appears in the client-visible response.
- No endpoint returns a file path, stack trace, or environment variable
  value anywhere in this codebase (checked by reading every response
  body-construction site in `app/routers/` and `app/core/route_service.py`).

### SQL injection

Every `cur.execute(...)` call in `app/` and `backend/scripts/` uses
parameterized placeholders (`%s`/`%(name)s`) -- confirmed by grepping for
f-strings, `.format()`, or string concatenation feeding into `execute()`
calls (none found). The one endpoint that accepts a raw path/query value
used structurally (`GET /segments/{segment_id}`) has it typed as `int` by
FastAPI/Pydantic before it ever reaches SQL, and is still passed as a
bound parameter regardless. `bbox` query strings are parsed with
`float()` in Python and only ever reach SQL as bound parameters to
`ST_MakeEnvelope(%s, %s, %s, %s, 4326)`, never interpolated into query
text.

### Map/bbox limits, reconfirmed unchanged

`MAX_BBOX_LAT_SPAN_DEG`/`MAX_BBOX_LON_SPAN_DEG` (~3.3km x 3.3km) and
`MAX_RESULTS = 2000` in `app/routers/map.py` are untouched this week;
existing tests (`test_segments_endpoint_rejects_oversized_bbox`, etc.)
still pass, reconfirming the caps are enforced after this week's other
changes.

## 4. Reliability and UX

Addressed, in proportion to what Week 6 flagged:

1. **Map first-paint quirk, reduced**: added a `ResizeObserver` on the map
   container that calls `map.resize()` whenever the container's actual
   size changes. This targets both the originally-observed blank/split
   first paint (the container's final layout may not have settled at
   construction time) *and* a real, previously-unaddressed bug this
   incidentally fixes: MapLibre does not resize its own canvas on a
   browser window resize or phone rotation without something calling
   `resize()` for it. Verified live: page loads in this session's browser
   checks rendered correctly on the first screenshot (previously
   intermittent), both desktop and mobile viewports.
2. **Retry action added** for recoverable failures (`StatusMessage`'s
   "Try again" button) -- offered only for API-unavailable and unexpected-
   error states, where retrying the *same* request could plausibly
   succeed. Deliberately *not* offered for out-of-service-area /
   no-routable-network / validation errors, since those are properties of
   the selected points themselves and retrying identically would just
   fail again -- a retry button there would be misleading; the existing
   "pick different points" guidance stays as the correct action.
3. **Coverage-loading state clarified**: the button already read "Loading
   coverage…" and disabled itself; added `aria-busy` and an explicit
   `role="status"` announcement ("Loading coverage data for the current
   map view…") so screen reader users get the same information sighted
   users do, not just a visual state change.
4. **Offline support**: confirmed out of scope, not added -- a transient
   failure now has a retry action (item 2), which is the proportionate
   response for a local demo, not full offline caching.

### Accessibility re-verification of the changed/added states

- Retry button is a real `<button>`, keyboard-reachable and activatable
  like every other control; new test
  (`retrying a recoverable failure re-issues the same comparison
  request`) exercises it via `fireEvent.click`, same pattern as every
  other interactive-control test.
- Coverage loading announcement uses `role="status"` (a polite live
  region), consistent with the existing loading-state pattern used
  elsewhere in the app (`role="status"` on the main comparison-loading
  text).
- Re-ran the `jest-axe` checks (`RouteCard` in isolation, `App`'s idle
  state) after all changes: **0 violations**, same as Week 6.

## 5. Evaluation preparation (frozen benchmark, no results computed)

The benchmark-pair set in `docs/week7_benchmark_pairs.json` (Section 1's
frozen 8 categories, selection code documented above) is adopted as the
**frozen evaluation benchmark** — chosen and empirically qualified (for
the `modes_agree`/`modes_diverge` categories, checked against the real
graph for the structural property that defines each category) *before*
any evaluation metric below has been computed against it. No conclusions
about system quality are drawn in this report; that is explicitly deferred
to a separate evaluation step per this week's instructions.

### Final evaluation metrics (defined now, computed later)

For each frozen pair with `status: "ok"`, computed per non-`shortest`
mode relative to that pair's own `shortest` route:

1. **Added distance and time vs. shortest routing** — `(mode.distance_m -
   shortest.distance_m)` and the equivalent for
   `estimated_travel_time_s`, both as absolute and percentage differences.
2. **Known hazard exposure** — count of `dominant_hazards` on the route
   (segments where a reliable report capped the accessibility score).
3. **Dominant hazard exposure by type** — the same count broken down by
   `hazard_type`, since "1 severe NoSidewalk" and "1 mild SurfaceProblem"
   are not equivalent even though both count as one dominant hazard.
4. **Unknown-segment proportion** — `len(unknown_segment_ids) /
   coverage.total_segments`.
5. **Low-confidence and disputed-segment proportion** —
   `len(low_confidence_segment_ids) / total_segments` and
   `len(disputed_segment_ids) / total_segments`, reported separately (not
   summed), consistent with Week 6's rule that these are different
   situations.
6. **Route confidence/evidence summary** — the route's own
   `confidence_score` (mean) and `min_confidence_score`, read alongside
   metric 4 (a route can have a merely-moderate mean confidence because
   it's mostly `unknown`, or because it has real but contested evidence —
   metrics 4 and 6 together distinguish those, per Week 6's confidence-
   communication rules).
7. **Frequency and magnitude of route-mode divergence** — across the
   frozen set, how many pairs show `modes_all_identical = False` (already
   computed per-pair in Section 1's raw JSON), and for those that diverge,
   the magnitude (added distance/time from metric 1, and the hazard/
   unknown deltas from metrics 2-5) between `accessible`/`confidence_aware`
   and `shortest`.
8. **Routing latency** — already measured in Section 1/2 per category;
   carried into the evaluation as context for interpreting the other
   metrics (e.g. a route with high added-distance on a `long`-category
   pair is a different finding than the same added-distance on a `short`
   pair).

### Mandatory framing for any evaluation write-up using these metrics

**Accessibility and confidence scores are relative decision-support
measures, derived from incomplete, crowdsourced, and OSM-tag evidence —
not probabilities of any real-world outcome and not a safety guarantee.**
A route with a lower `dominant_hazards` count is not "safer" in any
calibrated sense; it is "associated with fewer reliable reports of a
capping issue in the data this prototype has access to." This framing
(already enforced in the frontend's `SCORE_DISCLAIMER` and confidence-
communication copy, Week 6) applies identically to any future evaluation
report built on these metrics — the evaluation step must restate it, not
assume it carries over silently.

## 6. Verification

- **Backend**: 91/91 pass (`docker compose exec api pytest tests/ -v`) —
  88 from Week 6 + 3 new this week (CORS allowed/rejected, DB-failure
  redaction).
- **Frontend**: 26/26 pass (`npm test` inside `frontend/`) — 25 from
  Week 6 + 1 new (retry re-issues the request), after the vite/vitest
  security upgrade.
- **Playwright e2e**: 2/2 pass against the live stack (full required flow
  + API-unavailable), re-run after the dependency upgrade and after the
  reliability changes.
- **Dependency audit**: `npm audit` — **0 vulnerabilities** (was 3
  moderate, 1 high, 1 critical).
- **Full Docker Compose clean restart**: `docker compose down` (removes
  containers + network, **not** the `db_data` volume) followed by
  `docker compose up -d` — all three services (`db`, `api`, `frontend`)
  came up healthy in ~10 seconds; `GET /health`, `GET /health/graph`, and
  the frontend's root page all returned 200; `SELECT count(*) FROM nodes`
  / `segment_scores` confirmed all data survived the restart untouched
  (184,695 nodes, 214,056 scored segments, same as before the restart).
- **Representative browser checks**: desktop (1280x720-equivalent) and
  mobile (375x812) — map rendered correctly on first load in this
  session's checks (previously intermittent, see Section 4), a real
  route comparison completed and rendered within the observed latency
  budget, mobile layout stacked correctly with no clipping.

## Remaining limitations (reported honestly)

1. **`medium`-category HTTP latency barely improved** (355ms -> 336ms,
   ~1.06x) despite a real in-process routing speedup (424.8ms -> 226.5ms
   combined). At this size, fixed per-request overhead (DB connection
   checkout, geometry fetch, JSON serialization of a several-hundred-point
   LineString, network round trip) is a larger fraction of total latency
   than pathfinding itself — A* helps the routing component but doesn't
   move the overhead floor. Not addressed this week; would need its own
   profiling pass if `medium`-length routes become the primary use case.
2. **Weight-function-call counts sometimes went *up* for `accessible`/
   `confidence_aware` under A* despite being faster in wall-clock time**
   (e.g. `long`/accessible: 255,676 -> 320,399 evaluations, but 1429ms ->
   637ms). Plausible explanation: A*'s heuristic calls add their own
   per-node overhead not captured by the weight-evaluation counter, and
   the two algorithms explore genuinely different search orders even
   when reaching the same optimal answer — the counter is a useful proxy
   for Dijkstra-vs-Dijkstra or A*-vs-A* comparisons, less clean across the
   two algorithms. Reported as observed, not fully explained.
3. **npm audit's dev-only findings were all in the Vite/Vitest chain
   specifically** — this doesn't generalize to "dev dependencies are
   always safe to ignore"; each finding still had to be individually
   checked for reachability (documented in Section 3's table) rather than
   dismissed by category.
4. **CORS default is still permissive to two local origins**, appropriate
   for this local dev/demo prototype; a real deployment must set
   `ALLOWED_ORIGINS` to its actual frontend origin(s), which is now
   possible but not automatic.
5. **The evaluation metrics in Section 5 are defined, not yet computed.**
   No accessibility/confidence quality conclusions exist yet for this
   system — that is intentionally deferred, per this week's instructions,
   to a separate evaluation step against the now-frozen benchmark.
6. **Bundle size warning persists** (frontend production JS ~972KB,
   mostly MapLibre GL) — unchanged from Week 6, not addressed this week
   (out of scope: no product/feature work).
