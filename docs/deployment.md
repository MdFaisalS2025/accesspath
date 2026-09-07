# Deployment Architecture

**Status: the frontend is prepared for Vercel deployment; nothing is deployed yet.** This document describes the target architecture and the exact configuration needed. No hosting account, database, or Vercel project has been created — see the README's Deployment section for what's been verified versus what still requires manual setup and approval.

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

## Suitable hosting options (for later approval — nothing created yet)

**Backend (FastAPI, persistent process)**:
- **Render** (Web Service) — free tier exists but spins down on inactivity (cold start would reload the ~370MB graph on the next request, ~2s+); paid tier avoids this.
- **Railway** — usage-based free credits, persistent container, straightforward Docker deploy from the existing `backend/Dockerfile`.
- **Fly.io** — free allowance for small VMs, good fit for a single always-on container with in-memory state like this one.

**Database (PostGIS-capable Postgres)**:
- **Neon** — has a free tier, but confirm PostGIS extension support before committing (some serverless-Postgres free tiers restrict extensions).
- **Supabase** — free tier includes PostGIS by default, commonly used for exactly this kind of geospatial hobby/portfolio project.
- **Render PostgreSQL** or **Railway PostgreSQL** with the PostGIS extension enabled — simplest if co-locating with the backend host above.

**Free-tier caveats to expect, regardless of provider chosen**: cold-start latency after inactivity (relevant here specifically because of the in-memory graph load), storage/row limits that are unlikely to bind at this dataset's size (213,508 segments, 262,053 labels) but should be checked against the specific plan, and most free database tiers pausing or deleting inactive projects after some weeks — worth confirming the exact policy before relying on one for anything beyond a portfolio demo.

## What "live" will mean

This project will not be described as deployed or live until: the frontend is reachable at its Vercel URL, the backend is reachable at its own deployed URL with `ALLOWED_ORIGINS` updated to include the Vercel domain, and a real `POST /route/compare` request made from the deployed frontend to the deployed backend succeeds end-to-end. None of that has happened yet as of this document.
