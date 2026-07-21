# Live Repository Evidence

This file is the controlled update surface for the optional repository connector
exercise. The connector projects selected GitHub repository files into Aurora
without making Aurora authoritative for their content.

Exact marker: `VERITY-LIVE-INDEX-001`

The first synchronization records the repository revision, path, blob hash, and
content hash. A later edit changes the content hash, invalidates only the changed
chunks' embeddings, and leaves every unchanged file untouched.

Full synchronization also reconciles deletions. A file missing from the latest
authoritative snapshot is tombstoned in `ops.source_objects`; it stops appearing
in retrieval while historical candidate foreign keys remain intact.
