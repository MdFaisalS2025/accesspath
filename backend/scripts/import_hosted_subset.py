"""
Idempotently imports the JSON subset produced by build_hosted_subset.py
into a TARGET database -- a local scratch database for testing (Phase 4 of
the deployment plan), or the real Neon hosted-demo database (Phase 5).

Safe to re-run: every insert is an upsert (INSERT ... ON CONFLICT DO
UPDATE) keyed on the same primary keys the source database used, so
running this script twice against the same target does not duplicate a
single row -- the second run just re-applies the same values. Sequences
are reset after loading so any future INSERT without an explicit id still
gets a non-colliding one.

Reads the subset file (default: backend/generated/hosted_subset/subset.json,
gitignored, produced by build_hosted_subset.py) and TARGET_DATABASE_URL
from the environment -- never hardcoded, never logged, never printed. This
script prints only host/dbname (for a human to sanity-check *which*
database was targeted) and row counts/sizes, never the full connection
string or password.

Usage:
    TARGET_DATABASE_URL=postgresql://... python scripts/import_hosted_subset.py
"""
import json
import os
import sys
from urllib.parse import urlsplit

import psycopg2
import psycopg2.extras

SUBSET_PATH = os.environ.get("HOSTED_SUBSET_PATH", "/app/generated/hosted_subset/subset.json")
SCHEMA_PATH = os.environ.get("SCHEMA_PATH", "/app/db/schema.sql")


def redacted_target_description(database_url):
    """host/dbname only -- never the password, never the full URL."""
    parts = urlsplit(database_url)
    return f"{parts.hostname}:{parts.port or 5432}/{parts.path.lstrip('/')}"


def ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'nodes')"
        )
        schema_exists = cur.fetchone()[0]
    if schema_exists:
        print("Schema already present on target -- skipping (idempotent).")
        return
    print(f"Applying schema from {SCHEMA_PATH}...")
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema_sql = f.read()
    with conn.cursor() as cur:
        cur.execute(schema_sql)
    conn.commit()
    print("Schema applied.")


def upsert_nodes(conn, nodes):
    rows = [
        (n["id"], n["osm_node_id"], n["geom_geojson"], n["is_crossing"], n["kerb_type"], n["component_id"])
        for n in nodes
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO nodes (id, osm_node_id, geom, is_crossing, kerb_type, component_id)
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                osm_node_id = EXCLUDED.osm_node_id, geom = EXCLUDED.geom,
                is_crossing = EXCLUDED.is_crossing, kerb_type = EXCLUDED.kerb_type,
                component_id = EXCLUDED.component_id
            """,
            rows,
            template="(%s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s, %s, %s)",
            page_size=2000,
        )
    conn.commit()


def upsert_segments(conn, segments):
    rows = [
        (
            s["id"], s["osm_way_id"], s["from_node_id"], s["to_node_id"], s["geom_geojson"],
            s["length_m"], s["highway_type"], s["surface_tag"], s["source"], s["last_osm_edit"],
        )
        for s in segments
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO segments (id, osm_way_id, from_node_id, to_node_id, geom, length_m,
                                   highway_type, surface_tag, source, last_osm_edit)
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                osm_way_id = EXCLUDED.osm_way_id, from_node_id = EXCLUDED.from_node_id,
                to_node_id = EXCLUDED.to_node_id, geom = EXCLUDED.geom, length_m = EXCLUDED.length_m,
                highway_type = EXCLUDED.highway_type, surface_tag = EXCLUDED.surface_tag,
                source = EXCLUDED.source, last_osm_edit = EXCLUDED.last_osm_edit
            """,
            rows,
            template="(%s, %s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s, %s, %s, %s, %s)",
            page_size=2000,
        )
    conn.commit()


def upsert_labels(conn, labels):
    rows = [
        (
            l["id"], l["ps_label_id"], l["segment_id"], l["geom_geojson"], l["label_type"], l["severity"],
            l["agree_count"], l["disagree_count"], l["unsure_count"], l["region_name"], l["label_date"],
            l["osm_way_id_hint"], l["match_method"], l["match_distance_m"],
            l["second_match_segment_id"], l["second_match_distance_m"], l["ambiguous_match"],
            l["pano_id"], l["ps_user_id"],
        )
        for l in labels
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO accessibility_labels (
                id, ps_label_id, segment_id, geom, label_type, severity,
                agree_count, disagree_count, unsure_count, region_name, label_date,
                osm_way_id_hint, match_method, match_distance_m,
                second_match_segment_id, second_match_distance_m, ambiguous_match,
                pano_id, ps_user_id
            )
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                ps_label_id = EXCLUDED.ps_label_id, segment_id = EXCLUDED.segment_id,
                geom = EXCLUDED.geom, label_type = EXCLUDED.label_type, severity = EXCLUDED.severity,
                agree_count = EXCLUDED.agree_count, disagree_count = EXCLUDED.disagree_count,
                unsure_count = EXCLUDED.unsure_count, region_name = EXCLUDED.region_name,
                label_date = EXCLUDED.label_date, osm_way_id_hint = EXCLUDED.osm_way_id_hint,
                match_method = EXCLUDED.match_method, match_distance_m = EXCLUDED.match_distance_m,
                second_match_segment_id = EXCLUDED.second_match_segment_id,
                second_match_distance_m = EXCLUDED.second_match_distance_m,
                ambiguous_match = EXCLUDED.ambiguous_match,
                pano_id = EXCLUDED.pano_id, ps_user_id = EXCLUDED.ps_user_id
            """,
            rows,
            template="(%s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            page_size=2000,
        )
    conn.commit()


def upsert_scores(conn, scores):
    rows = [
        (
            s["segment_id"], s["accessibility_score"], s["confidence_score"], s["coverage_status"],
            s["label_count"], s["staleness_days"], s["positive_evidence"], s["negative_evidence"],
            s["evidence_consistency"], s["dominant_hazard_type"], s["dominant_hazard_ps_label_id"],
        )
        for s in scores
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO segment_scores (
                segment_id, accessibility_score, confidence_score, coverage_status,
                label_count, staleness_days, positive_evidence, negative_evidence,
                evidence_consistency, dominant_hazard_type, dominant_hazard_ps_label_id
            )
            VALUES %s
            ON CONFLICT (segment_id) DO UPDATE SET
                accessibility_score = EXCLUDED.accessibility_score,
                confidence_score = EXCLUDED.confidence_score,
                coverage_status = EXCLUDED.coverage_status, label_count = EXCLUDED.label_count,
                staleness_days = EXCLUDED.staleness_days, positive_evidence = EXCLUDED.positive_evidence,
                negative_evidence = EXCLUDED.negative_evidence,
                evidence_consistency = EXCLUDED.evidence_consistency,
                dominant_hazard_type = EXCLUDED.dominant_hazard_type,
                dominant_hazard_ps_label_id = EXCLUDED.dominant_hazard_ps_label_id
            """,
            rows,
            page_size=2000,
        )
    conn.commit()


def reset_sequences(conn):
    """After loading explicit ids, bump each BIGSERIAL sequence past the max
    imported id -- otherwise a future plain INSERT (id omitted) could try to
    reuse an id this import already took."""
    with conn.cursor() as cur:
        for table, id_col in (("nodes", "id"), ("segments", "id"), ("accessibility_labels", "id")):
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence(%s, %s), COALESCE((SELECT MAX({id_col}) FROM {table}), 1))",
                (table, id_col),
            )
    conn.commit()


def main():
    target_url = os.environ.get("TARGET_DATABASE_URL")
    if not target_url:
        print("TARGET_DATABASE_URL not set -- refusing to guess a target. Set it explicitly.", file=sys.stderr)
        sys.exit(1)

    with open(SUBSET_PATH, encoding="utf-8") as f:
        subset = json.load(f)

    print(f"Target: {redacted_target_description(target_url)}")
    print(f"Subset generated_at={subset['generated_at']} buffer_radius_m={subset['buffer_radius_m']}")
    print(f"Importing: nodes={len(subset['nodes'])} segments={len(subset['segments'])} "
          f"labels={len(subset['labels'])} scores={len(subset['scores'])}")

    conn = psycopg2.connect(target_url)
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        conn.commit()

        ensure_schema(conn)

        print("Upserting nodes...")
        upsert_nodes(conn, subset["nodes"])
        print("Upserting segments...")
        upsert_segments(conn, subset["segments"])
        print("Upserting accessibility_labels...")
        upsert_labels(conn, subset["labels"])
        print("Upserting segment_scores...")
        upsert_scores(conn, subset["scores"])
        print("Resetting sequences...")
        reset_sequences(conn)

        # Re-running this script is safe at the row level (upserts, verified
        # above), but each upsert leaves a dead MVCC tuple version behind --
        # on a repeated import (e.g. re-syncing after a source data refresh)
        # that bloats the on-disk size without changing row counts, which
        # matters when the whole point of the subset is staying well under
        # a free-tier storage cap. VACUUM FULL reclaims it. Needs its own
        # connection outside the transaction VACUUM can't run inside.
        conn.commit()
        print("Reclaiming space (VACUUM FULL)...")
        old_isolation = conn.isolation_level
        conn.set_isolation_level(0)  # AUTOCOMMIT, required for VACUUM
        with conn.cursor() as cur:
            for table in ("nodes", "segments", "accessibility_labels", "segment_scores"):
                cur.execute(f"VACUUM FULL ANALYZE {table}")
        conn.set_isolation_level(old_isolation)

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM nodes")
            node_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM segments")
            segment_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM accessibility_labels")
            label_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM segment_scores")
            score_count = cur.fetchone()[0]
            cur.execute("SELECT pg_size_pretty(pg_database_size(current_database())), pg_database_size(current_database())")
            size_pretty, size_bytes = cur.fetchone()

        print(f"\nTarget now has: nodes={node_count} segments={segment_count} "
              f"labels={label_count} scores={score_count}")
        print(f"Target database size: {size_pretty} ({size_bytes} bytes)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
