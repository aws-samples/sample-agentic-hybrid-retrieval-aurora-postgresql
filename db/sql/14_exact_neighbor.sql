\set ON_ERROR_STOP on

-- Exact nearest neighbours, precomputed.
--
-- The HNSW instrument computes recall live against these rows rather than
-- re-running the exact query, because the exact query is a sequential scan over
-- 3,870 MB of TOASTed vectors: measured 2,355 ms p50 and 2,300,855 shared buffer
-- hits on this cluster. Precomputing is what keeps the probe endpoint's cost
-- ceiling a filtered HNSW scan instead of a full scan, which is the property that
-- makes an interactive surface safe for a room full of participants.
--
-- `dataset_manifest_sha256` is part of the primary key because ground truth is only
-- valid for the corpus that produced it. A reseed must invalidate these rows loudly
-- rather than silently serve neighbours that no longer exist — recall computed
-- against another corpus is not recall.
CREATE TABLE IF NOT EXISTS mosaic_bench.exact_neighbor (
    anchor_product_id        bigint           NOT NULL,
    filter_preset            text             NOT NULL,
    k                        integer          NOT NULL CHECK (k > 0),
    dataset_manifest_sha256  text             NOT NULL,
    neighbor_rank            integer          NOT NULL CHECK (neighbor_rank > 0),
    neighbor_product_id      bigint           NOT NULL,
    cosine_distance          double precision NOT NULL,
    computed_at              timestamptz      NOT NULL DEFAULT now(),
    source_revision          text,
    PRIMARY KEY (
        anchor_product_id, filter_preset, k, dataset_manifest_sha256, neighbor_rank
    )
);

COMMENT ON TABLE mosaic_bench.exact_neighbor IS
    'Precomputed exact top-k neighbours per anchor and filter preset. Written by '
    'scripts/seed_exact_neighbors.py; read by the /api/hnsw instrument to compute '
    'recall without re-running a 2.4-second sequential scan.';

CREATE INDEX IF NOT EXISTS exact_neighbor_manifest_idx
    ON mosaic_bench.exact_neighbor (dataset_manifest_sha256, filter_preset);
