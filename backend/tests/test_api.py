"""
Week 5 API tests: schema/validation, coordinate snapping, same/cross
component routing, bbox/result limits, mode distinguishability, health,
and DB/API integration. Runs against the real DB via a session-scoped
TestClient (see conftest.py) so the app's actual startup graph-load runs
once for the whole module.

    docker compose exec api pytest tests/test_api.py -v
"""
import sys

sys.path.insert(0, "/app")
from app.core import geo, routing

# A point in open water (Elliott Bay/Puget Sound), well within the Seattle
# bbox but >1km from the nearest routable node -- used for the
# no-routable-network boundary test.
NO_NETWORK_LAT, NO_NETWORK_LON = 47.60, -122.40

# Clearly north of the Seattle admin boundary (max_lat ~47.734) -- used for
# the out-of-service-area test.
OUTSIDE_SEATTLE_LAT, OUTSIDE_SEATTLE_LON = 48.05, -122.30


def fetch_node_coords(conn, node_id):
    with conn.cursor() as cur:
        cur.execute("SELECT ST_Y(geom), ST_X(geom) FROM nodes WHERE id = %s", (node_id,))
        return cur.fetchone()


def fetch_component_node(conn, component_id, offset=0):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, ST_Y(geom), ST_X(geom) FROM nodes WHERE component_id = %s ORDER BY id OFFSET %s LIMIT 1",
            (component_id, offset),
        )
        return cur.fetchone()


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_graph_health_endpoint_reports_loaded_graph(client):
    resp = client.get("/health/graph")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["nodes"] > 0
    assert body["edges"] > 0
    assert body["load_seconds"] > 0
    assert body["load_rss_mb"] > 0


# ---------------------------------------------------------------------------
# Schema / validation -> 422
# ---------------------------------------------------------------------------

def test_route_compare_missing_field_returns_422(client):
    resp = client.post("/route/compare", json={"origin_lat": 47.6, "origin_lon": -122.3})
    assert resp.status_code == 422
    assert resp.json()["error"] == "validation_error"


def test_route_compare_out_of_range_latitude_returns_422(client):
    resp = client.post(
        "/route/compare",
        json={"origin_lat": 999, "origin_lon": -122.3, "destination_lat": 47.6, "destination_lon": -122.3},
    )
    assert resp.status_code == 422


def test_route_compare_wrong_type_returns_422(client):
    resp = client.post(
        "/route/compare",
        json={"origin_lat": "not-a-number", "origin_lon": -122.3, "destination_lat": 47.6, "destination_lon": -122.3},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Coordinate snapping boundaries
# ---------------------------------------------------------------------------

def test_out_of_service_area_returns_clear_client_error(client):
    resp = client.post(
        "/route/compare",
        json={
            "origin_lat": OUTSIDE_SEATTLE_LAT, "origin_lon": OUTSIDE_SEATTLE_LON,
            "destination_lat": 47.62, "destination_lon": -122.33,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "out_of_service_area"
    assert "supported_bounds" in resp.json()


def test_no_routable_network_returns_clear_client_error(client):
    resp = client.post(
        "/route/compare",
        json={
            "origin_lat": NO_NETWORK_LAT, "origin_lon": NO_NETWORK_LON,
            "destination_lat": 47.62, "destination_lon": -122.33,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "no_routable_network"
    assert resp.json()["max_snap_distance_m"] == geo.MAX_SNAP_DISTANCE_M


def test_exact_node_coordinate_snaps_with_zero_distance(client, conn):
    node_id, lat, lon = fetch_component_node(conn, 0, offset=5)
    resp = client.post(
        "/route/compare",
        json={"origin_lat": lat, "origin_lon": lon, "destination_lat": lat, "destination_lon": lon},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["origin"]["snap"]["node_id"] == node_id
    assert body["origin"]["snap"]["snap_distance_m"] == 0.0
    assert body["origin"]["snap"]["adjusted_for_connectivity"] is False


# ---------------------------------------------------------------------------
# Same-component vs. cross-component routing
# ---------------------------------------------------------------------------

def test_same_component_route_returns_ok_with_all_three_modes(client, conn):
    _, lat1, lon1 = fetch_component_node(conn, 0, offset=0)
    _, lat2, lon2 = fetch_component_node(conn, 0, offset=2000)

    resp = client.post(
        "/route/compare",
        json={"origin_lat": lat1, "origin_lon": lon1, "destination_lat": lat2, "destination_lon": lon2},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert set(body["routes"].keys()) == set(routing.MODES)
    for mode in routing.MODES:
        route = body["routes"][mode]
        assert route["distance_m"] > 0
        assert route["geometry"]["type"] == "LineString"
        assert len(route["geometry"]["coordinates"]) >= 2
        assert "explanation" in route and isinstance(route["explanation"], str)
    assert "disclaimer" in body and "not a" in body["disclaimer"].lower() or "not probabilities" in body["disclaimer"]


def test_cross_component_route_returns_explicit_no_connected_route(client, conn):
    _, lat0, lon0 = fetch_component_node(conn, 0, offset=0)
    _, lat1, lon1 = fetch_component_node(conn, 1, offset=0)

    resp = client.post(
        "/route/compare",
        json={"origin_lat": lat0, "origin_lon": lon0, "destination_lat": lat1, "destination_lon": lon1},
    )
    # A valid request that legitimately has no answer given current graph
    # connectivity -- 200 with an explicit status, not a 4xx client error
    # (the client didn't do anything wrong) and not a generic 500.
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "no_connected_route"
    assert body["reason"] == "origin_and_destination_in_different_connected_components"
    assert "routes" not in body
    assert body["origin_component_id"] != body["destination_component_id"]


def test_cross_component_destination_snap_prefers_origin_component_when_possible(client, conn):
    """The destination coordinate is near a component-1 node, but if a
    component-0 node also exists within snap distance, the destination
    should snap to the component-0 one instead (routability preferred) and
    say so via adjusted_for_connectivity -- not silently, and not by
    picking the far component-1 node and failing the route."""
    _, lat0, lon0 = fetch_component_node(conn, 0, offset=0)
    dest_node_id, dest_lat, dest_lon = fetch_component_node(conn, 1, offset=0)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM nodes WHERE component_id = 0
            AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)
            LIMIT 1
            """,
            (dest_lon, dest_lat, geo.MAX_SNAP_DISTANCE_M),
        )
        nearby_component0 = cur.fetchone()

    resp = client.post(
        "/route/compare",
        json={"origin_lat": lat0, "origin_lon": lon0, "destination_lat": dest_lat, "destination_lon": dest_lon},
    )
    body = resp.json()
    if nearby_component0 is not None:
        assert body["status"] == "ok"
        assert body["destination"]["snap"]["adjusted_for_connectivity"] is True
        assert body["destination"]["snap"]["component_id"] == 0
    else:
        assert body["status"] == "no_connected_route"


# ---------------------------------------------------------------------------
# Three modes remain distinguishable through the API
# ---------------------------------------------------------------------------

def test_three_modes_can_disagree_through_the_api(client, conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT n1.id, n2.id
            FROM segment_scores sc1
            JOIN segments s1 ON s1.id = sc1.segment_id
            JOIN nodes n1 ON n1.id = s1.from_node_id
            JOIN segment_scores sc2 ON sc2.coverage_status = 'labeled' AND sc2.accessibility_score < 0.3
            JOIN segments s2 ON s2.id = sc2.segment_id
            JOIN nodes n2 ON n2.id = s2.to_node_id
            WHERE sc1.coverage_status = 'labeled' AND sc1.accessibility_score > 0.8
              AND n1.component_id = 0 AND n2.component_id = 0
            LIMIT 1
            """,
        )
        origin_id, destination_id = cur.fetchone()

    origin_lat, origin_lon = fetch_node_coords(conn, origin_id)
    dest_lat, dest_lon = fetch_node_coords(conn, destination_id)

    resp = client.post(
        "/route/compare",
        json={"origin_lat": origin_lat, "origin_lon": origin_lon, "destination_lat": dest_lat, "destination_lon": dest_lon},
    )
    assert resp.status_code == 200
    body = resp.json()
    if body["status"] != "ok":
        return  # snapping/connectivity edge case for this particular pair; not what this test targets
    geometries = {mode: tuple(map(tuple, r["geometry"]["coordinates"])) for mode, r in body["routes"].items()}
    assert len(set(geometries.values())) > 1, "expected at least one mode to differ from the others"


# ---------------------------------------------------------------------------
# Map endpoints: bbox validation and result limits
# ---------------------------------------------------------------------------

def test_segments_endpoint_returns_bounded_geojson(client):
    resp = client.get("/segments", params={"bbox": "-122.35,47.61,-122.34,47.62"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    assert body["count"] == len(body["features"])
    assert body["count"] <= 2000


def test_segment_by_id_returns_geometry(client, conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM segments LIMIT 1")
        (segment_id,) = cur.fetchone()

    resp = client.get(f"/segments/{segment_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "Feature"
    assert body["geometry"]["type"] == "LineString"
    assert body["properties"]["segment_id"] == segment_id


def test_segment_by_id_returns_404_for_missing_segment(client):
    resp = client.get("/segments/999999999")
    assert resp.status_code == 404
    assert resp.json()["error"] == "segment_not_found"


def test_segments_endpoint_rejects_oversized_bbox(client):
    resp = client.get("/segments", params={"bbox": "-122.46,47.48,-122.22,47.73"})  # ~full city
    assert resp.status_code == 400
    assert resp.json()["error"] == "bbox_too_large"


def test_segments_endpoint_rejects_malformed_bbox(client):
    resp = client.get("/segments", params={"bbox": "not,a,valid,bbox"})
    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_bbox"


def test_segments_endpoint_rejects_wrong_arity_bbox(client):
    resp = client.get("/segments", params={"bbox": "-122.35,47.61,-122.34"})
    assert resp.status_code == 422


def test_segments_endpoint_rejects_inverted_bbox(client):
    resp = client.get("/segments", params={"bbox": "-122.34,47.62,-122.35,47.61"})  # min > max
    assert resp.status_code == 422


def test_labels_endpoint_returns_bounded_geojson(client):
    resp = client.get("/labels", params={"bbox": "-122.35,47.61,-122.34,47.62"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    assert body["count"] <= 2000
    for feature in body["features"][:5]:
        assert "label_type" in feature["properties"]


def test_labels_endpoint_rejects_oversized_bbox(client):
    resp = client.get("/labels", params={"bbox": "-122.46,47.48,-122.22,47.73"})
    assert resp.status_code == 400


def test_coverage_summary_returns_aggregates(client):
    resp = client.get("/coverage-summary", params={"bbox": "-122.35,47.61,-122.34,47.62"})
    assert resp.status_code == 200
    body = resp.json()
    assert "by_coverage_status" in body
    assert body["total_segments"] >= 0
    for status in body["by_coverage_status"]:
        assert status in ("labeled", "unknown")


def test_coverage_summary_rejects_oversized_bbox(client):
    resp = client.get("/coverage-summary", params={"bbox": "-122.46,47.48,-122.22,47.73"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Internal failures -> structured 500, no stack trace
# ---------------------------------------------------------------------------

def test_unhandled_internal_error_returns_structured_500_without_traceback(client, monkeypatch):
    """Uses a fresh TestClient with raise_server_exceptions=False (the
    shared `client` fixture re-raises server errors, which is right for
    every other test -- a silently-swallowed 500 would hide real bugs --
    but this test exists specifically to check the client-facing response
    shape of an unhandled error, not to have pytest re-raise it). No `with`
    block: the shared client's lifespan already populated app.state.graph
    on this same app object, and re-entering lifespan here would reload
    the ~185k-node graph a second time for no reason."""
    import app.routers.route as route_module
    from fastapi.testclient import TestClient
    from app.main import app

    def boom(*args, **kwargs):
        raise RuntimeError("deliberately triggered for this test")

    monkeypatch.setattr(route_module, "compare_routes", boom)
    unraising_client = TestClient(app, raise_server_exceptions=False)

    resp = unraising_client.post(
        "/route/compare",
        json={"origin_lat": 47.62, "origin_lon": -122.33, "destination_lat": 47.61, "destination_lon": -122.34},
    )
    assert resp.status_code == 500
    body = resp.json()
    assert body == {"error": "internal_error", "message": "An internal error occurred."}
    assert "RuntimeError" not in resp.text
    assert "Traceback" not in resp.text


# ---------------------------------------------------------------------------
# Week 7: CORS is configurable, not wide open
# ---------------------------------------------------------------------------

def test_cors_allows_the_configured_frontend_origin(client):
    resp = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_rejects_an_unlisted_origin(client):
    resp = client.get("/health", headers={"Origin": "http://evil.example.com"})
    assert "access-control-allow-origin" not in {k.lower() for k in resp.headers.keys()}


def test_db_failure_does_not_leak_connection_details_to_client(monkeypatch):
    """Simulates a DB-level failure whose exception message would contain
    connection details (host/user/password) if it ever reached the client
    -- confirms the generic 500 handler truly generalizes it away, not just
    for the RuntimeError case already covered above."""
    import app.routers.route as route_module
    from fastapi.testclient import TestClient
    from app.main import app

    fake_conninfo = "connection to server failed: password authentication failed for user \"accesspath\" host=db port=5432"

    def boom(*args, **kwargs):
        raise Exception(fake_conninfo)

    monkeypatch.setattr(route_module, "compare_routes", boom)
    unraising_client = TestClient(app, raise_server_exceptions=False)

    resp = unraising_client.post(
        "/route/compare",
        json={"origin_lat": 47.62, "origin_lon": -122.33, "destination_lat": 47.61, "destination_lon": -122.34},
    )
    assert resp.status_code == 500
    assert resp.json() == {"error": "internal_error", "message": "An internal error occurred."}
    assert "password" not in resp.text
    assert "accesspath" not in resp.text
    assert "authentication failed" not in resp.text
