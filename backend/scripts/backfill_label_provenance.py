"""
Week 3.5: backfills accessibility_labels.pano_id / ps_user_id from the raw
Project Sidewalk extract, keyed by ps_label_id. These weren't captured in
Week 2's initial load_labels() -- needed now so scoring can avoid treating
multiple labels from the same audit/viewpoint as fully independent
observations (docs/week3_5_scoring_review.md).

Run inside the api container:
    docker compose exec api python scripts/backfill_label_provenance.py
"""
import sys

import ijson
import psycopg2.extras

sys.path.insert(0, "/app")
from app.core.db import get_connection

LABELS_PATH = "/data/raw/sidewalk_labels_seattle.json"
BATCH_SIZE = 20000


def main():
    conn = get_connection()
    try:
        batch = []
        total = 0
        with open(LABELS_PATH, "rb") as f:
            for feat in ijson.items(f, "features.item"):
                props = feat["properties"]
                batch.append((props.get("pano_id"), props.get("user_id"), props["label_id"]))
                if len(batch) >= BATCH_SIZE:
                    total += apply_batch(conn, batch)
                    batch = []
        if batch:
            total += apply_batch(conn, batch)
        conn.commit()
        print(f"Backfilled {total} rows")

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM accessibility_labels WHERE pano_id IS NULL")
            missing = cur.fetchone()[0]
        print(f"Rows still missing pano_id: {missing}")
    finally:
        conn.close()


def apply_batch(conn, batch):
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            UPDATE accessibility_labels AS l
            SET pano_id = v.pano_id, ps_user_id = v.ps_user_id
            FROM (VALUES %s) AS v(pano_id, ps_user_id, ps_label_id)
            WHERE l.ps_label_id = v.ps_label_id
            """,
            batch,
            page_size=BATCH_SIZE,
        )
        return cur.rowcount


if __name__ == "__main__":
    main()
