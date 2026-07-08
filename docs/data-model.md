# Data model

Important tables:

- `ops.source_connectors`: configured sources and sync cursors.
- `ops.ingest_jobs`: ingestion control plane.
- `ops.ingest_job_events`: per-step job events.
- `ops.source_objects`: normalized records from Slack/Jira/Confluence/Salesforce/GitHub/files.
- `ops.object_chunks`: searchable chunks, full-text vectors, and embeddings.
- `ops.object_links`: cross-source links.
- `ops.citations`: source attribution.
- `ops.entities`: extracted named entities.
- `ops.retrieval_runs`: query and filter trace.
- `ops.retrieval_candidates`: ranking diagnostics per candidate.
- `ops.evaluation_queries`: benchmark questions.
- `ops.relevance_judgments`: evaluation labels.
