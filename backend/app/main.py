"""
Week 5: FastAPI app. The routing graph is loaded once here at startup
(app.state.graph) and reused by every request -- app.core.routing's
find_route() takes a graph object as a parameter specifically so this
works, rather than each request rebuilding it from the DB. See
docs/week5_api_report.md for measured load time/memory and typical
request latency.
"""
import logging
import os
import resource
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.db import close_pool, get_connection, init_pool
from app.core.routing import load_routing_graph
from app.routers import map as map_router
from app.routers import route as route_router

logger = logging.getLogger("accesspath")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_pool()

    start = time.monotonic()
    conn = get_connection()
    try:
        app.state.graph = load_routing_graph(conn)
    finally:
        conn.close()
    app.state.graph_load_seconds = time.monotonic() - start
    # ru_maxrss is KB on Linux (the api container), bytes on macOS -- this
    # container always runs Linux, so KB is correct here.
    app.state.graph_load_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

    logger.info(
        "Routing graph loaded: %d nodes, %d edges, %.2fs, %.1fMB RSS",
        app.state.graph.number_of_nodes(), app.state.graph.number_of_edges(),
        app.state.graph_load_seconds, app.state.graph_load_rss_mb,
    )

    yield

    close_pool()


app = FastAPI(title="AccessPath API", lifespan=lifespan)

# Week 6 added this for the frontend (localhost:5173) calling the API
# (localhost:8000) -- a different origin, so the browser needs CORS. It
# started as allow_origins=["*"], flagged in that week's report as "fine
# for now, risk beyond a demo": wide-open CORS means *any* website can
# read this API's responses from a visitor's browser (there's no
# authentication to protect, but /route/compare and the map endpoints
# still shouldn't be scraped from arbitrary third-party pages at scale).
# Week 7: configurable via ALLOWED_ORIGINS (comma-separated), defaulting to
# just the two local-dev origins (the Vite dev server's own port, and the
# same on 127.0.0.1) rather than "*" -- set it to the real deployed
# frontend origin(s) in any non-local environment.
_default_origins = "http://localhost:5173,http://127.0.0.1:5173"
allowed_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(route_router.router)
app.include_router(map_router.router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Pydantic/FastAPI validation failures (bad types, out-of-range lat/lon,
    missing fields) -> 422 with the field-level errors, no stack trace."""
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "message": "Invalid request.", "details": exc.errors()},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Routers raise HTTPException with a dict `detail` (e.g.
    {"error": "out_of_service_area", "message": ...}); normalize that to the
    same top-level {"error", "message", ...} shape as the 422/500 handlers
    below, instead of leaving it nested under "detail" (FastAPI's default)
    -- one envelope shape for every error status, not two."""
    if isinstance(exc.detail, dict):
        content = exc.detail
    else:
        content = {"error": "http_error", "message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all: never leak a stack trace or internal detail to the client.
    The real exception is still logged server-side for debugging."""
    logger.exception("Unhandled exception handling %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "message": "An internal error occurred."},
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/health/graph")
def graph_health(request: Request) -> dict:
    """Not in the original Week 1 health check -- added so graph load
    time/memory (item 5's reporting requirement) is queryable at runtime,
    not just logged once at startup."""
    graph = getattr(request.app.state, "graph", None)
    if graph is None:
        return {"status": "not_loaded"}
    return {
        "status": "ok",
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "load_seconds": request.app.state.graph_load_seconds,
        "load_rss_mb": request.app.state.graph_load_rss_mb,
    }
