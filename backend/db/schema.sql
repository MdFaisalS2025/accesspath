-- AccessPath schema (MVP)
-- Seattle only. See docs/data_verification.md for boundary/source notes.

CREATE EXTENSION IF NOT EXISTS postgis;

-- Routing graph vertices (intersections, endpoints, crossing points)
CREATE TABLE nodes (
    id              BIGSERIAL PRIMARY KEY,
    osm_node_id     BIGINT UNIQUE,
    geom            GEOMETRY(Point, 4326) NOT NULL,
    is_crossing     BOOLEAN NOT NULL DEFAULT FALSE,
    kerb_type       TEXT,              -- lowered | raised | flush | no | none | rolled | null
    -- Populated by scripts/build_graph.py from networkx connected_components;
    -- lets routing reject an origin/destination pair with no path instead of
    -- a silent pathfinding failure. See docs/week2_graph_report.md.
    component_id    INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_nodes_geom ON nodes USING GIST (geom);
CREATE INDEX idx_nodes_component_id ON nodes (component_id);

-- Routable sidewalk/path/crossing edges
CREATE TABLE segments (
    id                  BIGSERIAL PRIMARY KEY,
    osm_way_id          BIGINT,
    from_node_id        BIGINT NOT NULL REFERENCES nodes(id),
    to_node_id          BIGINT NOT NULL REFERENCES nodes(id),
    geom                GEOMETRY(LineString, 4326) NOT NULL,
    length_m            DOUBLE PRECISION NOT NULL,
    highway_type        TEXT,          -- footway | path | pedestrian | steps | crossing
    surface_tag         TEXT,
    source              TEXT NOT NULL DEFAULT 'osm',   -- osm | inferred
    last_osm_edit       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_segments_geom ON segments USING GIST (geom);
CREATE INDEX idx_segments_osm_way_id ON segments (osm_way_id);

-- Project Sidewalk accessibility labels (CC0), pre-joined to OSM ways
-- by Project Sidewalk itself via osm_way_id where available.
CREATE TABLE accessibility_labels (
    id                  BIGSERIAL PRIMARY KEY,
    ps_label_id         BIGINT UNIQUE NOT NULL,
    segment_id          BIGINT REFERENCES segments(id),   -- NULL until spatial/ID join resolved
    geom                GEOMETRY(Point, 4326) NOT NULL,
    label_type          TEXT NOT NULL,   -- CurbRamp | NoCurbRamp | NoSidewalk | SurfaceProblem | Obstacle | Crosswalk | Signal | Occlusion | Other
    severity            SMALLINT,        -- 1-3 observed in this extract (not 1-5 as originally
                                          -- documented -- verified against the loaded data in
                                          -- Week 3, see docs/week3_scoring_report.md); nullable,
                                          -- and always NULL for NoSidewalk/Occlusion in practice
    agree_count         INTEGER NOT NULL DEFAULT 0,
    disagree_count      INTEGER NOT NULL DEFAULT 0,
    unsure_count        INTEGER NOT NULL DEFAULT 0,
    region_name         TEXT,
    label_date          TIMESTAMPTZ,
    osm_way_id_hint      BIGINT,          -- osm_way_id as reported directly by Project Sidewalk
    match_method        TEXT,            -- 'ps_osm_way_id' | 'nearest_segment' | 'unmatched'
    match_distance_m    DOUBLE PRECISION,  -- distance to the nearest segment, preserved even when
                                            -- that distance exceeds the production threshold (unmatched)
    -- Second-nearest candidate + ambiguity flag (Week 2.5, docs/week2_graph_report.md):
    -- when the 1st and 2nd nearest segments are near-tied, the match is not
    -- silently resolved to the closer one without a trace — it's flagged here.
    second_match_segment_id    BIGINT REFERENCES segments(id),
    second_match_distance_m    DOUBLE PRECISION,
    ambiguous_match             BOOLEAN NOT NULL DEFAULT FALSE,
    -- Week 3.5 (docs/week3_5_scoring_review.md): lets scoring avoid treating
    -- labels from the same audit/viewpoint as fully independent observations.
    pano_id             TEXT,
    ps_user_id          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_labels_geom ON accessibility_labels USING GIST (geom);
CREATE INDEX idx_labels_segment_id ON accessibility_labels (segment_id);

-- Derived, recomputed-on-pipeline-run scores per segment. Scoring model
-- documented in backend/app/core/scoring.py; rationale for the Week 3.5
-- revision (ceiling-capped risk accumulation, replacing a plain weighted
-- average) in docs/week3_5_scoring_review.md.
CREATE TABLE segment_scores (
    segment_id          BIGINT PRIMARY KEY REFERENCES segments(id),
    accessibility_score DOUBLE PRECISION NOT NULL,  -- 0 (worst) - 1 (best)
    confidence_score    DOUBLE PRECISION NOT NULL,  -- 0 (no evidence) - 1 (well-attested)
    coverage_status     TEXT NOT NULL,               -- labeled | unknown
    label_count         INTEGER NOT NULL DEFAULT 0,
    staleness_days      INTEGER,
    -- Week 3.5: evidence quantity/consistency reported separately rather than
    -- collapsed into confidence_score alone, and the dominant hazard (if any)
    -- kept for explainability -- "why is this segment capped low".
    positive_evidence       DOUBLE PRECISION NOT NULL DEFAULT 0,  -- reliability-weighted supporting evidence
    negative_evidence       DOUBLE PRECISION NOT NULL DEFAULT 0,  -- reliability-weighted hazard evidence
    evidence_consistency    DOUBLE PRECISION,        -- 1 = one-sided evidence, 0 = maximally contested
    dominant_hazard_type    TEXT,                    -- label_type of the ceiling-setting hazard, if any
    dominant_hazard_ps_label_id BIGINT,               -- traceable back to accessibility_labels.ps_label_id
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Logged for the evaluation report (Section 13 of the plan); not user-facing.
CREATE TABLE route_requests (
    id                  BIGSERIAL PRIMARY KEY,
    origin_geom         GEOMETRY(Point, 4326) NOT NULL,
    destination_geom    GEOMETRY(Point, 4326) NOT NULL,
    mode                TEXT NOT NULL,   -- shortest | accessible | confidence_aware
    distance_m          DOUBLE PRECISION,
    accessibility_score DOUBLE PRECISION,
    confidence_score    DOUBLE PRECISION,
    requested_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
