from __future__ import annotations
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))
from app.db import get_dict_conn

with get_dict_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM ops.v_corpus_profile")
        print(cur.fetchone())
        cur.execute("SELECT * FROM ops.v_source_distribution LIMIT 10")
        for row in cur.fetchall():
            print(row)
