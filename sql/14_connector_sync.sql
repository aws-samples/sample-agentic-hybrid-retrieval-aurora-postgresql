-- Connector synchronization state for rebuildable evidence projections.
--
-- Full-sync connectors mark records missing from the latest authoritative
-- snapshot inactive instead of deleting them. Retrieval and corpus diagnostics
-- ignore inactive rows, while historical run/candidate foreign keys remain
-- intact for audit.
ALTER TABLE ops.source_objects
  ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true;

ALTER TABLE ops.source_objects
  ADD COLUMN IF NOT EXISTS source_deleted_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_objects_active_source
  ON ops.source_objects(source_id, external_id)
  WHERE is_active;

COMMENT ON COLUMN ops.source_objects.is_active IS
  'True when the object exists in the connector''s latest authoritative snapshot.';

COMMENT ON COLUMN ops.source_objects.source_deleted_at IS
  'When the connector first observed the source object missing; NULL while active.';
