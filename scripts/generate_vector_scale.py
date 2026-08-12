#!/usr/bin/env python3
"""Stream clustered synthetic vectors into a dedicated benchmark table.

This creates meaningful neighborhoods rather than duplicating identical vectors.
It is intended for physical 1M/5M/10M labs when the target environment has the
capacity. A 100M run is supported by the interface but should be treated as a
serious data-loading exercise, not a laptop quick-start.
"""
from __future__ import annotations
import argparse, math, os
import numpy as np


def normalize(x: np.ndarray) -> np.ndarray:
    return x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-12)


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument('--database-url',default=os.getenv('DATABASE_URL'))
    ap.add_argument('--rows',type=int,default=1_000_000)
    ap.add_argument('--dimensions',type=int,default=1024)
    ap.add_argument('--clusters',type=int,default=2048)
    ap.add_argument('--batch-size',type=int,default=2000)
    ap.add_argument('--seed',type=int,default=20260806)
    ap.add_argument('--truncate',action='store_true')
    a=ap.parse_args()
    if not a.database_url: raise SystemExit('DATABASE_URL required')
    try:
        import psycopg
        from pgvector.psycopg import register_vector
    except ImportError as e: raise SystemExit('Run `uv sync --frozen` first') from e
    rng=np.random.default_rng(a.seed)
    centroids=normalize(rng.normal(size=(a.clusters,a.dimensions)).astype(np.float32))
    with psycopg.connect(a.database_url) as conn:
        register_vector(conn)
        if a.truncate: conn.execute('TRUNCATE catalog_bench.vector_item')
        start=conn.execute('SELECT coalesce(max(item_id),0)+1 FROM catalog_bench.vector_item').fetchone()[0]
        written=0
        while written<a.rows:
            n=min(a.batch_size,a.rows-written)
            ids=np.arange(start+written,start+written+n,dtype=np.int64)
            cluster_ids=rng.integers(0,a.clusters,size=n,dtype=np.int32)
            noise_scale=rng.uniform(.035,.13,size=(n,1)).astype(np.float32)
            vectors=normalize(centroids[cluster_ids]+rng.normal(size=(n,a.dimensions)).astype(np.float32)*noise_scale)
            domains=rng.integers(1,4,size=n,dtype=np.int16)
            prices=rng.integers(1,21,size=n,dtype=np.int16)
            with conn.cursor().copy('COPY catalog_bench.vector_item(item_id,cluster_id,domain_id,price_bucket,embedding) FROM STDIN') as cp:
                for row in zip(ids,cluster_ids,domains,prices,vectors): cp.write_row((int(row[0]),int(row[1]),int(row[2]),int(row[3]),row[4]))
            conn.commit(); written+=n
            if written%100000==0 or written==a.rows: print(f'{written:,}/{a.rows:,}')
    print('Run ANALYZE and build the HNSW index after loading the desired scale.')
if __name__=='__main__': main()
