from app.core.db import pooled_connection


def get_conn():
    """FastAPI dependency: `conn = Depends(get_conn)`. Checks a connection
    out of the pool for this request only, returns it in a `finally` even
    if the handler raises."""
    with pooled_connection() as conn:
        yield conn
