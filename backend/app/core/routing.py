"""
Week 4: pathfinding over the scored pedestrian graph. No API/frontend here
by design (deferred until this is reviewed) -- this module is usable
directly by tests and, later, by a thin FastAPI endpoint.

## Week 7: Dijkstra -> A*

Long routes (~14km) took 1.3-1.8s per mode with plain Dijkstra
(`nx.shortest_path`), because Dijkstra explores outward in all directions
by cost, with no notion of "toward the destination" -- for a long trip it
ends up relaxing a large fraction of the whole graph before the target is
popped. Switched to `nx.astar_path` with `_astar_heuristic()`: straight-line
(haversine) distance to the target. This is provably admissible for *all
three* modes, not just `shortest` -- every mode's edge weight is
`length_m * multiplier` with `multiplier >= 1` (see `edge_weight`), so true
path cost is always >= physical length >= straight-line distance; the
heuristic can never overestimate, so A* is guaranteed to still return a
cost-optimal path, exactly as Dijkstra did. Measured effect and the
correctness verification (identical path costs, identical
accessibility/confidence summaries, all existing tests still passing) are
in docs/week7_hardening_report.md. Other options considered and rejected:
bidirectional Dijkstra (real but smaller win than A*, and redundant with
it), a full route-comparison result cache (masks the per-request cost
rather than fixing it, and adds staleness-management complexity for a
one-off demo).

## Modes

Three modes, matching schema.sql's route_requests.mode:

- **shortest**: weight = length_m. Ignores accessibility/confidence entirely.
- **accessible**: penalizes low accessibility_score, indifferent to how
  confident that score is. A segment with a single old, barely-reliable
  label saying "great curb ramp" (high accessibility_score, low
  confidence_score) is treated the same as one with ten fresh agreeing
  labels saying the same thing.
- **confidence_aware**: same accessibility penalty as `accessible`, *plus*
  an independent penalty for low confidence_score -- so it actively
  prefers well-attested segments over merely optimistic-looking ones,
  including preferring a `labeled` segment with modest-but-certain
  accessibility over an `unknown` segment (accessibility_score=0.5 looks
  "moderate" but confidence_score=0.0 is the worst possible).

Weight formula for one edge (segment):

    accessible_weight = length_m * (1 + ACCESSIBILITY_PENALTY_WEIGHT * (1 - accessibility_score))
    confidence_aware_weight = accessible_weight * (1 + CONFIDENCE_PENALTY_WEIGHT * (1 - confidence_score))

Both penalty weights are initial, reasonable defaults (4.0 each) documented
as such -- they haven't been tuned against real routing outcomes (there is
no routing evaluation dataset yet), only verified to produce the intended
*qualitative* mode separation (see test_routing.py's synthetic three-path
scenario, where three different paths each uniquely win under a different
mode).

## Crossing evidence scope (carried over from scoring.py's domain scoping)

A crossing (a specific street-crossing point) and the footway segments that
lead to it are *separate edges* in this graph -- a crossing is its own
`segments` row with `highway_type = 'crossing'`. Crossing-domain evidence
(CurbRamp/NoCurbRamp/Crosswalk/Signal) already only feeds that crossing
edge's own accessibility_score/confidence_score at full weight (Week 3.5's
`domain_discount`); it does not, and structurally cannot, "certify" the
adjoining footway edges, because routing costs each edge independently from
its own segment_scores row. A route that crosses a well-curb-ramped
intersection in the middle of an otherwise poorly-attested footway still
pays that footway's own (low) accessibility/confidence on the footway
edges -- the good crossing only discounts the crossing edge itself.

## Route explanations

`summarize_route()` returns, instead of one number: `unknown_segment_ids`
(no evidence at all) kept separate from `low_confidence_segment_ids`
(evidence exists, coverage_status='labeled', but confidence_score is
still low) -- conflating these was explicitly flagged as something to
avoid. Also returned: `dominant_hazards` (segment_id + hazard type for
every dominance-capped edge on the route) and `disputed_segment_ids`
(evidence_consistency below DISPUTED_CONSISTENCY_THRESHOLD -- evidence
exists on both sides, not just "a little evidence").

## No-connected-route

Reuses app.core.graph.NoConnectedRouteError. find_route() checks the
`component_id` node attribute (see app.core.graph's docstring: component 0
is whichever component happens to be largest in the current graph build,
not "the whole network") before attempting a pathfind, so a
cross-component request fails with a specific, catchable error instead of
networkx.NetworkXNoPath (which looks identical to "no route exists for an
unrelated reason", e.g. a bug) or silently returning nothing.
"""
import time
from math import atan2, cos, radians, sin, sqrt

import networkx as nx

from app.core.graph import NoConnectedRouteError, UnknownNodeError

EARTH_RADIUS_M = 6371000.0

SHORTEST = "shortest"
ACCESSIBLE = "accessible"
CONFIDENCE_AWARE = "confidence_aware"
MODES = (SHORTEST, ACCESSIBLE, CONFIDENCE_AWARE)

ACCESSIBILITY_PENALTY_WEIGHT = 4.0
CONFIDENCE_PENALTY_WEIGHT = 4.0

LOW_CONFIDENCE_THRESHOLD = 0.3
DISPUTED_CONSISTENCY_THRESHOLD = 0.3


class InvalidRouteModeError(ValueError):
    pass


def haversine_distance_m(lat1, lon1, lat2, lon2):
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * atan2(sqrt(a), sqrt(1 - a))


def _astar_heuristic(graph):
    """Straight-line (haversine) distance to the target, in meters -- an
    admissible lower bound for every mode's edge weight, not just
    'shortest'. Every mode's weight formula is `length_m * multiplier`
    with multiplier >= 1 (see edge_weight), so true path cost is always
    >= physical length >= straight-line distance; A* with this heuristic
    can never overestimate and therefore never returns a worse-than-optimal
    path (see docs/week7_hardening_report.md for the correctness argument
    and empirical verification against the prior Dijkstra baseline).

    Falls back to 0 (equivalent to plain Dijkstra, still correct, just not
    accelerated) for any node missing lat/lon -- e.g. the synthetic graphs
    in test_routing.py that don't carry real coordinates."""
    def heuristic(u, v):
        nu, nv = graph.nodes[u], graph.nodes[v]
        if "lat" not in nu or "lat" not in nv:
            return 0.0
        return haversine_distance_m(nu["lat"], nu["lon"], nv["lat"], nv["lon"])
    return heuristic


def edge_weight(mode, length_m, accessibility_score, confidence_score):
    if mode == SHORTEST:
        return length_m
    if mode == ACCESSIBLE:
        return length_m * (1 + ACCESSIBILITY_PENALTY_WEIGHT * (1 - accessibility_score))
    if mode == CONFIDENCE_AWARE:
        accessible_weight = length_m * (1 + ACCESSIBILITY_PENALTY_WEIGHT * (1 - accessibility_score))
        return accessible_weight * (1 + CONFIDENCE_PENALTY_WEIGHT * (1 - confidence_score))
    raise InvalidRouteModeError(f"unknown route mode: {mode!r}, must be one of {MODES}")


def _weight_fn(mode):
    def weight(u, v, data):
        return edge_weight(mode, data["length_m"], data["accessibility_score"], data["confidence_score"])
    return weight


def find_route(graph, origin_node_id, destination_node_id, mode, stats=None):
    """graph: a networkx.Graph whose nodes carry a `component_id` attribute
    and whose edges carry length_m, accessibility_score, confidence_score,
    coverage_status, segment_id, and optionally dominant_hazard_type /
    evidence_consistency (see load_routing_graph / build_synthetic_graph).

    stats: optional dict; if given, populated with
    {"algorithm", "elapsed_s", "weight_evaluations"} for benchmarking
    (scripts/benchmark_routes.py, docs/week7_hardening_report.md).
    weight_evaluations counts calls to the edge-weight function as a proxy
    for search-space size -- networkx's shortest-path implementations
    don't expose a direct "nodes explored" count, and this is comparable
    across algorithms (dijkstra vs A*) since both call the same weight
    function once per edge relaxation. Zero overhead for normal callers
    (default None skips the counting wrapper entirely).

    Returns a dict from summarize_route(). Raises NoConnectedRouteError if
    the two nodes are in different components, UnknownNodeError if either
    node doesn't exist in the graph, InvalidRouteModeError for a bad mode,
    or networkx.NetworkXNoPath if they're supposedly in the same component
    but no path was found anyway (a graph-data inconsistency, not a normal
    "no route" case -- should not happen if component_id was computed from
    this same graph).
    """
    if mode not in MODES:
        raise InvalidRouteModeError(f"unknown route mode: {mode!r}, must be one of {MODES}")

    for node_id in (origin_node_id, destination_node_id):
        if node_id not in graph.nodes:
            raise UnknownNodeError(node_id)

    origin_component = graph.nodes[origin_node_id].get("component_id")
    destination_component = graph.nodes[destination_node_id].get("component_id")
    if origin_component != destination_component:
        raise NoConnectedRouteError(origin_node_id, destination_node_id, origin_component, destination_component)

    weight_fn = _weight_fn(mode)
    start = time.perf_counter()
    if stats is not None:
        call_count = 0

        def counting_weight(u, v, data, _base=weight_fn):
            nonlocal call_count
            call_count += 1
            return _base(u, v, data)

        weight_fn = counting_weight

    path = nx.astar_path(
        graph, origin_node_id, destination_node_id,
        heuristic=_astar_heuristic(graph), weight=weight_fn,
    )

    if stats is not None:
        stats["algorithm"] = "astar"
        stats["elapsed_s"] = time.perf_counter() - start
        stats["weight_evaluations"] = call_count

    return summarize_route(graph, path, mode)


def summarize_route(graph, path, mode):
    segments = []
    unknown_segment_ids = []
    low_confidence_segment_ids = []
    disputed_segment_ids = []
    dominant_hazards = []
    total_length_m = 0.0

    for u, v in zip(path, path[1:]):
        data = graph.edges[u, v]
        segment_id = data.get("segment_id")
        total_length_m += data["length_m"]
        segments.append(
            {
                "segment_id": segment_id,
                "from_node_id": u,
                "to_node_id": v,
                "length_m": data["length_m"],
                "highway_type": data.get("highway_type"),
                "accessibility_score": data["accessibility_score"],
                "confidence_score": data["confidence_score"],
                "coverage_status": data.get("coverage_status"),
                "dominant_hazard_type": data.get("dominant_hazard_type"),
                "evidence_consistency": data.get("evidence_consistency"),
            }
        )
        if data.get("coverage_status") == "unknown":
            unknown_segment_ids.append(segment_id)
        elif data["confidence_score"] < LOW_CONFIDENCE_THRESHOLD:
            low_confidence_segment_ids.append(segment_id)
        consistency = data.get("evidence_consistency")
        if consistency is not None and consistency < DISPUTED_CONSISTENCY_THRESHOLD:
            disputed_segment_ids.append(segment_id)
        if data.get("dominant_hazard_type"):
            dominant_hazards.append({"segment_id": segment_id, "hazard_type": data["dominant_hazard_type"]})

    accessibility_scores = [s["accessibility_score"] for s in segments]
    confidence_scores = [s["confidence_score"] for s in segments]

    return {
        "mode": mode,
        "path_node_ids": path,
        "total_length_m": total_length_m,
        "segments": segments,
        "mean_accessibility": sum(accessibility_scores) / len(accessibility_scores) if segments else None,
        "min_accessibility": min(accessibility_scores) if segments else None,
        "mean_confidence": sum(confidence_scores) / len(confidence_scores) if segments else None,
        "min_confidence": min(confidence_scores) if segments else None,
        # Kept separate on purpose -- "no evidence" and "evidence, but not
        # confident" are different situations a route explanation must not blur.
        "unknown_segment_ids": unknown_segment_ids,
        "low_confidence_segment_ids": low_confidence_segment_ids,
        "disputed_segment_ids": disputed_segment_ids,
        "dominant_hazards": dominant_hazards,
    }


def load_routing_graph(conn):
    """Builds the networkx graph from the live DB: nodes (with component_id),
    segments as edges carrying length_m + the current segment_scores row.
    A segment with no segment_scores row (shouldn't happen if
    compute_scores.py has run) is skipped rather than guessed at."""
    graph = nx.Graph()
    with conn.cursor() as cur:
        cur.execute("SELECT id, component_id, ST_Y(geom), ST_X(geom) FROM nodes")
        for node_id, component_id, lat, lon in cur.fetchall():
            graph.add_node(node_id, component_id=component_id, lat=lat, lon=lon)

        cur.execute(
            """
            SELECT s.id, s.from_node_id, s.to_node_id, s.length_m, s.highway_type,
                   sc.accessibility_score, sc.confidence_score, sc.coverage_status,
                   sc.dominant_hazard_type, sc.evidence_consistency
            FROM segments s
            JOIN segment_scores sc ON sc.segment_id = s.id
            """
        )
        for row in cur.fetchall():
            (segment_id, from_id, to_id, length_m, highway_type,
             accessibility_score, confidence_score, coverage_status,
             dominant_hazard_type, evidence_consistency) = row
            graph.add_edge(
                from_id, to_id,
                segment_id=segment_id, length_m=length_m, highway_type=highway_type,
                accessibility_score=accessibility_score, confidence_score=confidence_score,
                coverage_status=coverage_status, dominant_hazard_type=dominant_hazard_type,
                evidence_consistency=evidence_consistency,
            )
    return graph
