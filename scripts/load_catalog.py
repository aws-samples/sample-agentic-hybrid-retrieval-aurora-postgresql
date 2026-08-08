#!/usr/bin/env python3
"""Stream the catalog shards into PostgreSQL and upsert into catalog.product."""
from __future__ import annotations
import argparse, gzip, json, os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def default_catalogs() -> list[Path]:
    manifest=json.loads((ROOT/'data/full/manifest.json').read_text(encoding='utf-8'))
    paths=[ROOT/path for path in manifest.get('full_datasets',[])]
    if not paths:
        raise SystemExit('Manifest does not declare full_datasets')
    return paths

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--database-url',default=os.getenv('DATABASE_URL'))
    ap.add_argument(
        '--catalog',
        type=Path,
        action='append',
        help='Catalog shard to load; repeat for multiple shards. Defaults to manifest order.',
    )
    ap.add_argument('--chunk-bytes',type=int,default=4*1024*1024)
    a=ap.parse_args()
    if not a.database_url: raise SystemExit('DATABASE_URL required')
    catalogs=a.catalog or default_catalogs()
    missing=[path for path in catalogs if not path.is_file()]
    if missing: raise SystemExit(f'Catalog shards not found: {missing}')
    try: import psycopg
    except ImportError as e: raise SystemExit('Install config/requirements.txt') from e
    upsert=(ROOT/'sql/02_upsert_from_stage.sql').read_text(encoding='utf-8')
    with psycopg.connect(a.database_url) as conn:
        conn.execute('TRUNCATE catalog_stage.product_raw')
        for catalog in catalogs:
            print(f'Loading {catalog}...')
            with gzip.open(catalog,'rb') as src, conn.cursor().copy('COPY catalog_stage.product_raw FROM STDIN WITH (FORMAT CSV, HEADER TRUE)') as cp:
                while chunk:=src.read(a.chunk_bytes): cp.write(chunk)
        print('Staging copy complete; transforming typed columns and upserting...')
        conn.execute(upsert)
        conn.commit()
        rows=conn.execute('SELECT domain,count(*) FROM catalog.product GROUP BY domain ORDER BY domain').fetchall()
        print(rows)
if __name__=='__main__':main()
