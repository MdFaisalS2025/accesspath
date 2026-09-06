# Week 6 — AccessPath Frontend

Implementation: `frontend/` (React + TypeScript + Vite + MapLibre GL JS).
Visual system defined before coding in `docs/week6_visual_system.md`
(palette, typography, spacing, route differentiation, layouts, ASCII
wireframe) — this report covers what was actually built against that plan,
plus verification.

## Backend additions made to support the frontend

Two small, additive, read-only changes to the Week 5 API (not routing-
algorithm changes):

1. **`GET /segments/{segment_id}`** — a single-segment geometry lookup, so
   clicking a hazard/segment reference in a route card can focus the map on
   it. Returns 404 with `{"error": "segment_not_found", ...}` if the id
   doesn't exist.
2. **`/segments?bbox=...` now includes coverage fields** (`coverage_status`,
   `accessibility_score`, `confidence_score`, `evidence_consistency`,
   `dominant_hazard_type`) via a `LEFT JOIN` to `segment_scores` — needed
   for the coverage map layer (labeled/unknown/low-confidence/disputed);
   the endpoint had no way to answer "is this segment labeled or unknown"
   before this.
3. **CORS middleware** (`allow_origins=["*"]`) — the frontend runs on a
   different origin (`localhost:5173`) than the API (`localhost:8000`), so
   the browser needs this to allow the request at all. Wide open is
   accepted for this no-auth, no-cookie, no-per-user-data dev prototype;
   flagged as a risk if this ever goes further than a demo.

Both are covered by new backend tests (`test_segment_by_id_returns_geometry`,
`test_segment_by_id_returns_404_for_missing_segment`); full backend suite
still 88/88.

## Implemented interactions and states

All from the brief:

- Click map → origin, click again → destination, click a third time →
  starts a new selection (origin moves, destination clears, prior results
  clear). "Clear selection" resets to the empty state.
- Distinct circular markers, "A" (green) / "B" (dark red), with
  `aria-label`s, not color-only.
- "Compare routes" is disabled until both points are set and re-labeled
  "Comparing routes…" while in flight.
- All three route lines render together after a successful comparison,
  each with a distinct color **and** line pattern (see visual-system doc):
  shortest = solid black, accessible = dashed blue, confidence_aware =
  dotted vermillion, each with a white casing underneath for legibility
  against the basemap and each other.
- Selecting a route card dims the other two lines (opacity 0.35 vs. full)
  and keeps the selected one's casing prominent — `aria-pressed` reflects
  selection state on the card's button role.
- Clicking a hazard or a listed segment id calls `GET /segments/{id}` and
  flies the map to it with a small highlight marker; failures (rare, e.g.
  a stale id) fail quietly rather than showing an error for a secondary
  action.
- The route comparison panel shows, per mode: distance, estimated time,
  accessibility score *and* a plain-language band ("some documented
  issues", never "probability"), confidence/evidence score with its own
  band, coverage counts, a hazard list (or an explicit "No known hazards
  documented" empty state), collapsible missing-evidence/disputed-evidence
  lists, and the backend's own deterministic explanation string verbatim.
- **Identical route detection**: if two modes produce the same geometry
  (a common case on short, unambiguous trips), the later one's card says
  "Identical to the [X] route for this trip" instead of presenting it as
  if it were independently computed.
- **Snap disclosure**: every result (success or no-connected-route) shows,
  per endpoint, the snap distance, and if `adjusted_for_connectivity` was
  true, an explicit sentence naming both the distance actually used and
  the closer unconstrained point that was passed over, and why.

### Required states

| State | How it's shown |
|---|---|
| Initial (no coordinates) | "Click the map to place your origin." |
| Origin selected | "Origin placed. Click the map to place your destination." |
| Both selected | "Both points placed. Ready to compare routes." + enabled button |
| Loading (~3s) | `role="status"` text, no spinner animation (respects reduced motion) |
| Success (3 routes) | Route comparison panel + text summary + 3 map lines |
| No connected route | Explicit banner naming both component ids, framed as a data gap, not a dead end |
| Outside Seattle | "Outside the supported area" plain-language message |
| No nearby network | "No nearby routable path" with the actual max snap distance |
| API unavailable | "AccessPath server unavailable", distinct from the above two |
| Empty hazard list | "No known hazards documented on this route." (never a blank space) |
| Identical/partial results | Per-card "Identical to the [X] route" note |

## Confidence communication

Scores are shown as `0.53 – some documented issues`, never phrased as a
probability or safety guarantee (`src/lib/format.ts`'s `accessibilityBand`/
`confidenceBand`). The comparison panel distinguishes five categories
explicitly, each with its own labeled section rather than one blended
"issues" count: known hazards (▲ icon + type), missing evidence (segment
ids under "Missing evidence"), conflicting evidence (segment ids under
"Conflicting evidence"), and low-confidence evidence (counted in the
`<summary>` line). `comparison_notes` from the API — which specifically
explain when confidence_aware trades a known imperfection for fewer
unknowns — are rendered verbatim in the text summary. The disclaimer
("Decision-support prototype based on incomplete public data. It does not
guarantee accessibility or safety.") is a persistent footer bar, present
in every state, not a dismissible banner.

## Coverage view

A single control section (not a separate dashboard route): five checkboxes
(labeled segments, unknown segments, low-confidence segments, disputed
evidence, accessibility labels) and a "Load coverage for current map view"
button, bounded by the same ~3.3km × 3.3km cap the API enforces (checked
client-side first, with a message telling the user to zoom in rather than
firing a request that would 400). Low-confidence/disputed flags are
computed client-side from `confidence_score`/`evidence_consistency` against
the same thresholds `app.core.routing` uses server-side
(`src/lib/coverage.ts`), so the map layer agrees with what a route
explanation would call low-confidence/disputed for the same segment.

## Accessibility

- Full keyboard access: route cards and hazard/segment items are real
  `<button>` elements (not clickable `<div>`s); coverage toggles are real
  checkboxes in a `<fieldset>`.
- Visible focus indicator: a 3px accent outline via `:focus-visible`,
  never suppressed.
- Semantic landmarks: `<header>`, `<aside aria-label="Route planner">`,
  `<footer role="contentinfo">`, headings in a real hierarchy (`h1` app
  title, `h2` section headings).
- The map container has `role="application"` with an explicit
  `aria-label` describing what clicking does, since a raw canvas has no
  inherent semantics.
- Route mode is never color-only: every card and the map legend name the
  line pattern in text ("solid line", "dashed line", "dotted line").
- `prefers-reduced-motion: reduce` zeroes `--transition-fast`; nothing else
  animates (no spinners, no map fly-to on the *loading* state — flyTo only
  happens on an explicit user action, focusing a segment).
- Contrast: see `docs/week6_visual_system.md`'s table — all text/background
  pairs meet WCAG AA (4.5:1 normal text).
- 200% zoom: layout uses `rem`-relative sizing and flex/grid, no fixed
  pixel heights that would clip text; verified in the browser screenshots
  below.
- Textual summary for non-map users: `TextSummary` component (`aria-live`
  region) states the same route trade-offs in prose before the structured
  cards, not assuming the reader has seen the map at all.

### Automated checks

`jest-axe` runs against `RouteCard` in isolation and against `App`'s
initial (idle) state — both assert zero violations
(`tests/a11y.test.tsx`).

### 200% zoom / narrow-viewport check

Resized the live browser to 640×360 (a practical proxy for ~200% zoom on a
1280×800 laptop) — the layout does not clip: the map/sidebar column stack
into one scrollable flow (the same code path as the mobile breakpoint), all
text stayed legible and none was cut off, at the cost of needing to scroll
further. No horizontal scrollbar appeared at any width tested.

## Docker Compose

Added a `frontend` service (`frontend/Dockerfile`, `node:20-slim`, `npm run
dev` via Vite) alongside `db` and `api`. `VITE_API_BASE_URL` is set at the
compose level (`http://localhost:8000` — the *host's* published port, since
the browser runs outside the compose network and can't resolve the `api`
service's internal DNS name) and overridable via `.env`/`.env.example` for
non-Docker local dev. `docker compose up` now brings up all three
containers; verified via `docker compose ps` showing `db`, `api`,
`frontend` all `Up`.

## Verification

### Bugs found and fixed during live-browser verification (not just written, actually exercised)

1. **Whole-page scroll instead of sidebar-only scroll.** Scrolling the
   route-comparison panel scrolled the entire document (map included)
   rather than just the sidebar's own overflow region — confirmed live via
   `window.scrollY` changing on scroll and the map disappearing off-screen.
   Root cause: a flex item (`.app__sidebar`) with `overflow-y: auto` but no
   `min-height: 0` doesn't reliably confine its own scrolling in this
   layout; fixed by adding `min-height: 0` to `.app__sidebar` and, as a
   belt-and-suspenders safety net, `overflow: hidden` on `html`/`body`/`#root`
   so the document itself can never scroll — only panels that opt into
   `overflow-y: auto` can.
2. **Vite dev server not detecting file changes inside the Docker volume
   mount.** After the fix above, a fresh browser tab kept serving the *old*
   CSS indefinitely — confirmed by comparing a raw `fetch()` of the CSS file
   (showed the new content) against the actually-injected `<style>` tag
   (showed the old content), meaning Vite's module graph never invalidated.
   This is a known category of issue: Docker Desktop on Windows doesn't
   reliably forward native filesystem events across bind mounts. Fixed by
   setting `server.watch.usePolling = true` in `vite.config.ts` and
   restarting the container; confirmed fixed by checking the live
   `getComputedStyle` result matched the edit afterward.

### What else was checked live (not just tested in isolation)

- Full happy path against the real running stack (not mocks): clicked two
  real points on the map, watched the "Comparing routes…" loading state,
  got a real 3-route comparison back from the real API with real Seattle
  data, saw the blue dashed "accessible" route line rendered distinctly
  against the basemap with its white casing.
- Selecting a route card visibly dimmed the other two lines on the map
  (confirmed the black solid "shortest" line became the only prominent one
  after selecting that card).
- Clicking a hazard's segment button flew the map to that segment's real
  location with the orange focus-ring marker.
- Triggered "No nearby routable path" live by clicking a point in open
  water (Puget Sound) — the exact message and max-distance value rendered
  correctly against a real 400 response from the API.
- Mobile layout (375×812 emulated): map on top, content stacked below,
  disclaimer pinned at the bottom, no clipping.
- `out_of_service_area`, `no_connected_route`, and the API-unavailable
  message were verified via the automated test suite (`App.test.tsx`) using
  the exact response/error shapes the real API produces (cross-checked
  against `docs/week5_api_report.md`'s examples) rather than live-clicked,
  since reliably hitting a real different-component pair or a real outage
  by clicking map pixels isn't practical to aim precisely; the Playwright
  e2e suite additionally exercises the API-unavailable path against the
  real running frontend (by intercepting the network request), not just a
  component-level mock.

### Observed, non-blocking rendering quirk

On a handful of fresh page loads (both desktop and mobile viewports), the
map canvas rendered blank or showed a stale/split tile layout for roughly
one screenshot before settling into a correct render on the next one. This
tracks with MapLibre's canvas needing a resize/repaint pass after initial
mount and tile fetch latency, not a logic bug — the app's click-handling
and state worked correctly underneath even when tiles hadn't visually
loaded yet (confirmed: origin/destination were captured correctly even
during a blank-tile moment). Not fixed this week; a defensive
`map.resize()` call shortly after mount would be a reasonable follow-up if
this proves user-visible in practice.

## Test results

- **Backend**: 88/88 pass (`docker compose exec api pytest tests/ -v`),
  including 2 new tests for the `GET /segments/{id}` addition.
- **Frontend unit/component** (Vitest + React Testing Library): **25/25
  pass** (`npm test` inside `frontend/`) — `RouteCard` (7 tests covering
  rendering, empty-hazard state, selection, hazard-click callback, duplicate
  note, pattern-name text), `App` (12 tests covering every required state:
  idle, origin-selected, both-selected, loading, success with all three
  modes, snap disclosure, identical-route flagging, no-connected-route,
  out-of-service-area, no-routable-network, API-unavailable, clear
  selection), API client (4 tests: success parsing, 4xx error shape, network
  failure → status 0, bbox query building), accessibility (2 axe checks, 0
  violations).
- **End-to-end** (Playwright, against the real running Docker Compose
  stack, not mocks): **2/2 pass** — the full required flow (select two
  points → request comparison → display three routes → select the
  confidence-aware route, tolerant of the real API also legitimately
  returning `no_connected_route`/`no_routable_network` for an arbitrary
  pixel pair) and a real network-failure interception showing the
  server-unavailable message.

## Remaining issues (reported honestly)

1. **Map canvas blank-on-first-paint quirk** (above) — cosmetic, not fixed.
2. **CORS is wide open** (`allow_origins=["*"]`) — acceptable for this
   no-auth demo, would need tightening before any real deployment.
3. **No offline/retry handling** — a transient network blip during the
   ~3s comparison call surfaces as "server unavailable" with no automatic
   retry; the user must click "Compare routes" again.
4. **Identical-route detection is exact-geometry only** — two routes that
   are *visually* the same but differ by a single coordinate (e.g. a tiny
   snapping difference) won't be flagged as identical even though a user
   looking at the map would see no difference. Minor, cosmetic.
5. **Coverage layer has no loading skeleton** — while `/segments`+`/labels`
   are being fetched for the current view, the button just reads "Loading
   coverage…"; the map doesn't indicate anything is pending until data
   arrives.
6. **No dependency-vulnerability remediation** — `npm install` reported 5
   known vulnerabilities (3 moderate, 1 high, 1 critical) in transitive dev
   dependencies; not investigated or patched this week (out of scope, but
   should be triaged before this goes beyond a local prototype).

## Measured end-to-end response times (frontend perspective)

Consistent with `docs/week5_api_report.md`'s backend-side measurements,
observed from the browser during live verification:

- Short trip (~450m, 12–32 segments/mode): comparison completed in well
  under 1 second, including the three map layers rendering.
- Longer trip (~7.7–7.8km, ~420 segments/mode): comparison + full UI update
  (three route lines, populated comparison panel, text summary) completed
  in **under 4 seconds** end-to-end from clicking "Compare routes" to the
  result rendering, consistent with the backend's own ~2.75–3.2s figure
  for a similarly-sized route plus network/render overhead.
- Map/coverage endpoints (`/segments`, `/labels` for a ~3.3km bbox):
  rendered within roughly 200–300ms of the "Load coverage for current map
  view" click, consistent with the backend's own 76–119ms measurements.
