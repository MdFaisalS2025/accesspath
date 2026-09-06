"""
Coordinate validation and node-snapping for the routing API (Week 5).

## Seattle service area

The bounding box from docs/data_verification.md's Week 1 boundary check
(the real admin-boundary polygon, not this bbox itself -- this is just a
cheap first-pass rejection before the more expensive nearest-node lookup).
A coordinate inside this bbox but outside the actual city polygon (e.g. a
lake, or a corner of the bbox that isn't Seattle) will still just fail to
find a nearby node and get the "no routable network" error instead --
correct behavior either way, just via a different check.

## Snapping

`snap_point()` finds the nearest graph node to a coordinate. MAX_SNAP_DISTANCE_M
(75m) is a documented, fixed cutoff: farther than that and we refuse to
silently teleport the user onto an unrelated path (a request in a park
half a km from the nearest mapped sidewalk should fail loudly, not return
a route that starts somewhere the user never said they were).

When a `prefer_component_id` is given (used for the destination once the
origin's component is known, since that's what actually determines
routability), the nearest node *in that component* is used instead of the
absolute nearest node, provided it's still within MAX_SNAP_DISTANCE_M --
but the response always carries both the chosen node and the
unconstrained nearest node (`adjusted_for_connectivity`), so a caller can
always see that a connectivity-driven substitution happened; it is never
silently concealed.
"""
SEATTLE_MIN_LAT = 47.4810022
SEATTLE_MAX_LAT = 47.7341503
SEATTLE_MIN_LON = -122.4596960
SEATTLE_MAX_LON = -122.2244330

MAX_SNAP_DISTANCE_M = 75.0


class OutOfServiceAreaError(Exception):
    def __init__(self, lat, lon):
        self.lat = lat
        self.lon = lon
        super().__init__(f"({lat}, {lon}) is outside the supported Seattle service area")


class NoRoutableNetworkError(Exception):
    def __init__(self, lat, lon, max_distance_m):
        self.lat = lat
        self.lon = lon
        self.max_distance_m = max_distance_m
        super().__init__(
            f"No routable node within {max_distance_m}m of ({lat}, {lon})"
        )


def is_within_seattle_bounds(lat, lon):
    return SEATTLE_MIN_LAT <= lat <= SEATTLE_MAX_LAT and SEATTLE_MIN_LON <= lon <= SEATTLE_MAX_LON


def _query_nearest(conn, lat, lon, component_id, limit):
    with conn.cursor() as cur:
        if component_id is None:
            cur.execute(
                """
                SELECT id, component_id, ST_Y(geom), ST_X(geom),
                       ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography) AS d
                FROM nodes
                ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)
                LIMIT %(limit)s
                """,
                {"lat": lat, "lon": lon, "limit": limit},
            )
        else:
            cur.execute(
                """
                SELECT id, component_id, ST_Y(geom), ST_X(geom),
                       ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography) AS d
                FROM nodes
                WHERE component_id = %(component_id)s
                ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)
                LIMIT %(limit)s
                """,
                {"lat": lat, "lon": lon, "component_id": component_id, "limit": limit},
            )
        return cur.fetchall()


def snap_point(conn, lat, lon, prefer_component_id=None, max_distance_m=MAX_SNAP_DISTANCE_M):
    """Returns a dict describing the snap. Raises OutOfServiceAreaError or
    NoRoutableNetworkError; never returns a snap beyond max_distance_m."""
    if not is_within_seattle_bounds(lat, lon):
        raise OutOfServiceAreaError(lat, lon)

    overall_rows = _query_nearest(conn, lat, lon, component_id=None, limit=1)
    if not overall_rows:
        raise NoRoutableNetworkError(lat, lon, max_distance_m)
    overall_id, overall_component, overall_lat, overall_lon, overall_dist = overall_rows[0]

    chosen = {
        "node_id": overall_id,
        "component_id": overall_component,
        "snapped_lat": overall_lat,
        "snapped_lon": overall_lon,
        "snap_distance_m": overall_dist,
        "nearest_unconstrained_node_id": overall_id,
        "nearest_unconstrained_distance_m": overall_dist,
        "adjusted_for_connectivity": False,
    }

    if prefer_component_id is not None and prefer_component_id != overall_component:
        preferred_rows = _query_nearest(conn, lat, lon, component_id=prefer_component_id, limit=1)
        if preferred_rows and preferred_rows[0][4] <= max_distance_m:
            pref_id, pref_component, pref_lat, pref_lon, pref_dist = preferred_rows[0]
            chosen = {
                "node_id": pref_id,
                "component_id": pref_component,
                "snapped_lat": pref_lat,
                "snapped_lon": pref_lon,
                "snap_distance_m": pref_dist,
                "nearest_unconstrained_node_id": overall_id,
                "nearest_unconstrained_distance_m": overall_dist,
                "adjusted_for_connectivity": True,
            }

    if chosen["snap_distance_m"] > max_distance_m:
        raise NoRoutableNetworkError(lat, lon, max_distance_m)

    return chosen
