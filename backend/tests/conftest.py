import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, "/app")
from app.core.db import get_connection


@pytest.fixture(scope="session")
def conn():
    connection = get_connection()
    yield connection
    connection.close()


@pytest.fixture(scope="session")
def client():
    """Session-scoped: the app's lifespan loads the ~185k-node routing graph
    once (a few seconds) and every API test reuses it, instead of reloading
    per test."""
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
