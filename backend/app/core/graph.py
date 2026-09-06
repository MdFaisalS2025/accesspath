"""
Connectivity guard for future routing code.

nodes.component_id is populated by scripts/build_graph.py's
verify_connectivity(): component 0 is whichever connected component happens
to be largest (82.2% of nodes as of Week 2.5), components 1, 2, 3... are the
rest in decreasing size order. **component_id = 0 means "the largest
connected component found in the current graph build," not "the entire
Seattle pedestrian network" or "every routable place in the city.**" Most
non-zero components are believed to be OSM node-snapping artifacts rather
than real gaps (docs/week2_graph_report.md), but that hasn't been repaired —
a real, reachable Seattle sidewalk can still end up in component 3 because
of a digitization quirk, not because it's actually isolated. Component ids
are also not stable across a re-run of verify_connectivity() if the
underlying OSM extract changes (component 0 could become a different
physical region, or ids could shift) -- don't persist them outside this
graph build's lifetime.

Week 2.5 found the pedestrian graph has ~2,700 connected components — real
enough that a routing request between two nodes in different components
must fail loudly and specifically, not attempt a pathfind that silently
returns nothing or raises a generic exception.
"""


class NoConnectedRouteError(Exception):
    """Raised when two nodes are not in the same connected component, so no
    path between them can exist in the current graph."""

    def __init__(self, from_node_id, to_node_id, from_component_id, to_component_id):
        self.from_node_id = from_node_id
        self.to_node_id = to_node_id
        self.from_component_id = from_component_id
        self.to_component_id = to_component_id
        super().__init__(
            f"No connected route between node {from_node_id} (component "
            f"{from_component_id}) and node {to_node_id} (component "
            f"{to_component_id})."
        )


class UnknownNodeError(Exception):
    """Raised when a node id doesn't exist (e.g. a stale id, bad request)."""

    def __init__(self, node_id):
        self.node_id = node_id
        super().__init__(f"No such node: {node_id}")


def get_component_id(conn, node_id):
    with conn.cursor() as cur:
        cur.execute("SELECT component_id FROM nodes WHERE id = %s", (node_id,))
        row = cur.fetchone()
    if row is None:
        raise UnknownNodeError(node_id)
    return row[0]


def assert_connected(conn, from_node_id, to_node_id):
    """Raises NoConnectedRouteError if the two nodes aren't in the same
    component. Callers (future routing endpoints) should catch this and
    return a clear "no route exists" response rather than letting
    pathfinding fail silently or crash on an empty path."""
    from_component_id = get_component_id(conn, from_node_id)
    to_component_id = get_component_id(conn, to_node_id)
    if from_component_id != to_component_id:
        raise NoConnectedRouteError(from_node_id, to_node_id, from_component_id, to_component_id)
