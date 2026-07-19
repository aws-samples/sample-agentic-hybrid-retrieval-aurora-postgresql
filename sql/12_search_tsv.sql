-- ---------------------------------------------------------------------------
-- Restore-path reconciliation for the object-level lexical vector.
--
-- The committed seed dump was taken with the OLD schema, which had a title-only
-- generated column ops.source_objects.title_tsv (weight A on title only) and an
-- index idx_objects_title_tsv over it. That column was never queried by any search
-- function — the lexical arm reads object_chunks.tsv — so an exact-ID query only
-- matched when the external_id happened to appear in a chunk body.
--
-- sql/01_schema.sql now defines search_tsv (external_id + title, both weight A) and
-- sql/02_indexes.sql builds idx_objects_search_tsv, so a fresh `make schema` is
-- already correct. This file reconciles a database RESTORED from the old dump:
-- it drops the dead title_tsv column/index and adds search_tsv + its GIN index.
-- Pure DDL guarded on existence, additive, and safe to re-run. Keep the search_tsv
-- expression IN SYNC with sql/01_schema.sql.
-- ---------------------------------------------------------------------------

-- Drop the dead title-only index and column if a restored dump still carries them.
DROP INDEX IF EXISTS ops.idx_objects_title_tsv;
ALTER TABLE ops.source_objects DROP COLUMN IF EXISTS title_tsv;

-- Add the object-level lexical vector if it is not already present (a fresh schema
-- built from sql/01 already has it; a restored old dump does not).
ALTER TABLE ops.source_objects
  ADD COLUMN IF NOT EXISTS search_tsv tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(external_id, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(title, '')), 'A')
  ) STORED;

CREATE INDEX IF NOT EXISTS idx_objects_search_tsv
  ON ops.source_objects USING GIN(search_tsv);
