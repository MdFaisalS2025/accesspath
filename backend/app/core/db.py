import os
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool as psycopg2_pool

_pool = None


def get_connection():
    """Standalone, unpooled connection -- used by the one-off scripts/*.py
    pipeline steps, which each run once and exit. The API (app.main) uses
    the pool below instead, so a request never opens a fresh TCP connection."""
    return psycopg2.connect(os.environ["DATABASE_URL"])


def init_pool(minconn=1, maxconn=10):
    """Called once from app.main's lifespan handler on startup."""
    global _pool
    if _pool is None:
        _pool = psycopg2_pool.ThreadedConnectionPool(minconn, maxconn, os.environ["DATABASE_URL"])
    return _pool


def close_pool():
    """Called once from app.main's lifespan handler on shutdown -- closes
    every pooled connection instead of leaking them at process exit."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


@contextmanager
def pooled_connection():
    """Checks a connection out of the pool for the duration of one request
    and always returns it (even on error) -- use as a FastAPI dependency:

        def endpoint(conn = Depends(get_conn)): ...

    where get_conn is a generator wrapping this context manager (see
    app.dependencies.get_conn)."""
    if _pool is None:
        raise RuntimeError("connection pool not initialized -- app.main's lifespan should call init_pool()")
    conn = _pool.getconn()
    try:
        yield conn
    finally:
        _pool.putconn(conn)
