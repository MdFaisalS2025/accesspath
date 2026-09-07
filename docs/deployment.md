# Deployment Architecture

**Status: deployment profile approved (Vercel + Render + Neon, portfolio-demo geographic subset), local build and validation in progress.** This document describes the target architecture and the exact configuration needed, and the measured results of the deployment-subset work so far. See the README's Deployment section for the current summary of what's live versus still pending.

## Deployment profile: portfolio-demo geographic subset

The hosted deployment does **not** serve the full Seattle dataset (397MB). It serves a graph-aware subset built around the two frozen demo routes (`modes_diverge`, `medium`) — chosen over the full dataset specifically to make a genuinely free deployment reliable rather than "barely" fitting a free tier's storage/memory limits. Local development is unaffected and continues to use the complete dataset; this subset exists only for the hosted copy.

### How the subset is built (`backend/scripts/build_hosted_subset.py`)

Not one rectangle spanning both demo areas (they're ~9km apart, so a single bounding box would waste most of its space on irrelevant area in between). Instead:
1. Both frozen pairs' routes are computed for all 3 modes each, against the full local graph — capturing whichever segments *any* mode actually uses.
2. The union of those 6 route geometries is buffered by 450m (`BUFFER_RADIUS_M`) — wide enough to include real parallel-street alternatives, so `accessible`/`confidence_aware` still have a genuine choice to make in the subset, not just the exact segments the full dataset happened to use.
3. Every segment intersecting that buffer is included, along with every node it references, every accessibility label matched to an included segment, and every included segment's already-computed `segment_scores` row (copied verbatim — scores are never recalculated for the subset, only filtered).
4. `component_id` is recomputed from scratch on the subset's own connectivity (cutting most of Seattle away necessarily splits some full-dataset components further).
5. The subset is validated by reconstructing an in-memory graph directly from the exported rows and running the same `routing.find_route()` the real API uses, confirming both demo pairs still resolve and `modes_diverge` still shows real mode divergence — a hard failure here (exit code 1) is meant to block deployment, not be silently accepted.

**Measured result** (buffer radius 450m, run against the full local database):

| | Subset | Full dataset | Fraction |
|---|---|---|---|
| Nodes | 19,263 | 184,695 | 10.4% |
| Segments | 22,529 | 213,508 | 10.6% |
| Labels | 25,312 | 262,053 | 9.7% |
| Segment scores | 22,529 | 214,056 | 10.5% |

Connectivity: 104 components in the subset; the largest holds 18,780 nodes (97.5% of subset nodes) — comparable in shape to the full dataset's own 82.2%-in-largest-component split, not a connectivity regression introduced by subsetting.

Validation (via the real `routing.find_route()`, in-memory, against only the subset's own rows): both `modes_diverge` and `medium` resolve to a route for all 3 modes, and **both still show mode divergence** (`modes_diverge`: shortest 11,263.3m / accessible 11,508.8m / confidence_aware 11,576.9m; `medium`: 3,460.7m / 3,467.4m / 3,572.5m — identical, to the meter, to the full-dataset Week 8 evaluation numbers, since the buffer fully contains the original chosen paths).

### How the subset is imported (`backend/scripts/import_hosted_subset.py`)

Idempotent by construction: every row is an `INSERT ... ON CONFLICT DO UPDATE`, keyed on the same primary keys the source database used (ids are preserved exactly, not re-serialized), so re-running the import against the same target never duplicates a row — verified by re-running it three times locally and confirming row counts stay identical each time. Row-level idempotency doesn't prevent on-disk bloat from repeated `UPDATE`s though (Postgres MVCC leaves a dead tuple version behind per upsert) — the script runs `VACUUM FULL ANALYZE` on all four tables at the end specifically to reclaim that, confirmed to bring the measured size back down after a repeat import rather than growing unbounded.

Applies `backend/db/schema.sql` itself if the target database is empty (checked via `information_schema`, so this is also safe to run against an already-provisioned database). Reads the target from `TARGET_DATABASE_URL` (deliberately a different variable name from the app's own `DATABASE_URL`, to make it hard to accidentally import into the wrong database) — never hardcoded, never logged in full; only host/dbname is printed for a human sanity check, never the password.

**Measured result, local scratch-database test** (a second Postgres database in the same local `db` container, not Neon — this is the Phase 4 "verify before external deployment" step): **37–38MB**, stable across three repeated idempotent import runs. Well under the 250MB target (85%+ headroom) and the proportional estimate from the raw row-count fraction (~10.5% × 397MB ≈ 42MB) landed close to this, but this number is the actually-measured `pg_database_size()` result, not the estimate.

### Deployment-mode configuration

`DEPLOYMENT_MODE` environment variable (`backend/app/main.py`, defaults to `"full"`) — set to `"hosted_subset"` only on the actual hosted deployment. Controls `GET /deployment-info`, which the frontend calls once on load:
- `mode: "full"` → `message`/`coverage_boundary` both `null`, nothing shown in the UI.
- `mode: "hosted_subset"` → `message` is the required disclosure text ("Hosted demo coverage is limited to selected Seattle areas. The local project supports the full Seattle dataset."), shown in a persistent, restrained banner (`CoverageBanner.tsx`); `coverage_boundary` is a simplified GeoJSON polygon of the subset's buffered area, drawn as a subtle dashed outline on the map (`MapView.tsx`'s `hosted-subset-boundary` layer — thin line, 4% fill opacity, never obscures the basemap or competes with route lines).

This is a live runtime fact from the API, not baked into the frontend build — the same Vercel build works against either a full or subset backend, it just displays differently depending on what `/deployment-info` reports. Setting `DEPLOYMENT_MODE=hosted_subset` on a database that actually has the full dataset would only change what the UI *says*, not what data actually exists — the two must be kept in sync operationally (set the env var only on the deployment whose database was actually built from `import_hosted_subset.py`).

The map endpoints (`/segments`, `/labels`, `/coverage-summary`) need no code change to respect the subset boundary: they only ever return rows that exist in the connected database, and the subset database simply has no rows outside the buffered area, so a bbox query over an unsubsetted part of Seattle returns an empty result set structurally, not a fabricated "unknown" placeholder implying data was ever loaded there.

### Readiness check

`GET /ready` (`backend/app/main.py`) — returns `503` with `{"error": "not_ready", ...}` until `app.state.graph` is loaded and has at least one node, `200` with node/edge counts and the active `deployment_mode` once it has. This is the target for a hosting platform's readiness probe (e.g. Render's health check path); unlike `/health`, which returns `200` the instant the ASGI server accepts connections, `/ready` reflects the actual graph-loaded state an orchestrator needs to know before routing traffic to the instance.

### Environment variables

See `backend/.env.example` (committed, no real values) for `DATABASE_URL`, `ALLOWED_ORIGINS`, `DEPLOYMENT_MODE`. The import script's `TARGET_DATABASE_URL` is deliberately not in that file (it's a one-off script argument for building/refreshing the hosted database, not part of the running app's own configuration) — set it inline on the command line or in a local, gitignored shell profile, e.g.:

```bash
TARGET_DATABASE_URL="postgresql://...neon.tech/..." python scripts/import_hosted_subset.py
```

## Split architecture

AccessPath's three Docker Compose services split across two different hosting models in production — this is a deliberate, minimal-change split, not a rewrite:

| Service | Local (Docker Compose) | Production |
|---|---|---|
| `frontend` | Vite dev server, container | **Vercel** — static build (`dist/`), CDN-hosted |
| `api` | Uvicorn, container | A separately deployed **persistent** service (Vercel does not host this — see below) |
| `db` | PostGIS container, `db_data` volume | A **managed external PostGIS-capable Postgres** instance |

**Why the API can't move to Vercel in this phase**: Vercel's serverless functions are stateless and short-lived, but this API holds an in-process NetworkX graph (184,695 nodes / 213,508 edges, ~370MB RSS, ~2s load) cached in memory at startup and reused across every request (`app.state.graph`, see [`docs/architecture.md`](architecture.md)). Rebuilding that graph on every cold serverless invocation would be both slow and wasteful, and a serverless function can't hold long-lived in-process state the way this design assumes. Migrating routing to a serverless-compatible architecture is explicitly out of scope for this phase — the FastAPI backend needs a normal persistent host (a container platform, a VM, or a PaaS with an always-on process), not Vercel Functions.

## Vercel configuration (frontend only)

No `vercel.json` was added — Vercel's automatic Vite framework detection already supplies the correct build command (`npm run build`) and output directory (`dist`) for this project with zero extra configuration, and the app has exactly one client-side route (no router library, no rewrites needed). Adding a config file here would be redundant, not clarifying.

What **does** need to be set manually when the Vercel project is created (a dashboard/CLI step, not a code change):

1. **Root Directory**: `frontend` — this is a monorepo (`backend/`, `frontend/`, `docs/` all at the repo root), so Vercel must be told to build from the `frontend/` subdirectory. This is a Vercel project setting, not expressible in a repo-committed `vercel.json` field.
2. **Environment variable**: `VITE_API_BASE_URL` = the deployed backend's real URL (e.g. `https://api.example.com`), set in the Vercel project's Environment Variables settings. **Vite inlines `VITE_`-prefixed env vars at build time**, so this must be set before the first production build, not adjustable after the fact without a rebuild.

Everything else (build command `npm run build`, output directory `dist`, Node version) is Vercel's own Vite-project default.

## What happens if `VITE_API_BASE_URL` is missing

Before this change, an unset `VITE_API_BASE_URL` silently fell back to `http://localhost:8000` — harmless in local dev (where that's correct), but actively misleading in a real deployment: a visitor's browser would try to reach *their own machine's* port 8000, fail, and see a generic "server unavailable" message indistinguishable from a real backend outage.

This is now caught explicitly (`frontend/src/api/client.ts`'s `API_BASE_URL_MISCONFIGURED`): a production build (`import.meta.env.PROD`) with no `VITE_API_BASE_URL` set fails immediately, before attempting any network request, with a distinct "AccessPath is not configured" message (`StatusMessage.tsx`, `error.status === -1`) — clearly different from the existing "AccessPath server unavailable" message (`status === 0`) used for a real, reachable-in-principle backend that didn't respond. Local dev and Docker Compose are unaffected, since both already set the env var explicitly.

## Backend CORS

The backend's `ALLOWED_ORIGINS` environment variable (comma-separated, read in `backend/app/main.py`) must include the final Vercel domain (e.g. `https://accesspath.vercel.app`, plus any preview-deployment domain if those should also work) once the backend is deployed. It currently defaults to the two local Vite dev origins only (`http://localhost:5173`, `http://127.0.0.1:5173`) — a production deployment will get CORS-rejected by the backend until this is updated, which is the correct, safe default (fail closed, not open) rather than a bug to work around.

## Database and data pipeline in production

The routing graph and accessibility/confidence scores are **not** computed at every application startup — the offline pipeline (`build_graph.py` → `validate_matching.py` → `analyze_connectivity.py` → `backfill_label_provenance.py` → `compare_scoring_models.py` → `compute_scores.py`, see the README's Data pipeline section) is a one-time (or occasional, on data refresh) setup step that populates the `segments`/`accessibility_labels`/`segment_scores` tables. The API's in-process graph is loaded from those already-populated tables at process startup (`load_routing_graph()`), not rebuilt from raw OSM/Project Sidewalk data on every boot. In production this means: run the pipeline once against the managed database as part of initial deployment (or whenever the underlying data is refreshed), not as part of the API's request-serving startup path.

## Approved providers (subset-sized deployment)

- **Database: Neon**, free tier (500MB limit). The measured subset (37–38MB) uses ~7.5% of that — genuine headroom, not the "barely fits" 79%-utilized case the full 397MB dataset would have been.
- **Backend: Render**, free Web Service tier (512MB RAM). Idle memory (~377–390MB against the full dataset; expected proportionally lower against the ~10.5%-sized subset, to be re-measured against the actual subset in Phase 4) and this deployment's much smaller graph (subset: 19,263 nodes / 22,529 edges vs. full 184,695 / 213,508) should load faster and use less memory than the full-dataset measurements in this document's earlier draft — re-verified with the real constrained simulation before anything is deployed.
- **Frontend: Vercel**, free tier — static build, no compute/storage constraint relevant to this project's size.

Render's free tier spins down after inactivity; the frontend's loading state now says so explicitly when talking to the hosted subset (`isHostedSubset` in `App.tsx`) — "the hosted demo server may take up to about a minute to wake up" — rather than letting a cold start look indistinguishable from a broken deployment.

No payment method is added, no paid tier is enabled, and no usage-based billing is turned on for any of these three services as part of this deployment.

## What "live" will mean

This project will not be described as deployed or live until: the frontend is reachable at its Vercel URL, the backend is reachable at its own deployed URL with `ALLOWED_ORIGINS` updated to include the Vercel domain, and a real `POST /route/compare` request made from the deployed frontend to the deployed backend succeeds end-to-end. None of that has happened yet as of this document.
