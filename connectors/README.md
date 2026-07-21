# Connector patterns

The core lab uses the deterministic Orion seed. These connectors show how a
production system replaces that bundle without changing the normalized
`SourceObject` contract.

## Repository projection

`github_repository.py` supports two source transports while emitting one
contract:

```bash
# Packaged/private workshop checkout
make github-export
make github-sync

# Public repository, or a private repository with GITHUB_TOKEN
GITHUB_TRANSPORT=github GITHUB_REF=main make github-sync
```

`github-sync` performs a full snapshot reconciliation, skips unchanged content,
tombstones missing files, and batches embeddings for this connector's new or
changed chunks. Its cursor records the transport, commit, snapshot hash, object
count, and dirty paths. Only clean Git or GitHub API content receives an
immutable blob URL.

## Other source patterns

- `github_pull_issues.py`: GitHub issues and pull requests through the API.
- `slack_federated_search.py`: ephemeral live lookup without persisting message
  bodies.
- `normalize_appflow_export.py`: normalize Salesforce, Jira, or other CSV exports.

Do not use real customer data or broad production chat data in a workshop
environment without explicit approval. See `docs/connector-lifecycle.md` for
cursor, deletion, embedding, and index-maintenance guidance.
