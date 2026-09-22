# September 22 source and local delivery validation

These checks used the existing Aurora cluster and the local app. They do not
prove a fresh Workshop Studio deployment, event-account access or publication.
The source at validation was the working tree based on `c630066`; the model
receipt also carries its content fingerprint. Do not relabel an earlier receipt
as a measurement of a later commit.

| Check | Result and boundary |
| --- | --- |
| Offline Python | 1,545 pass; 61 database-dependent checks skipped offline and exercised through the separate live lanes |
| UI | 721 tests pass; production build passes; production dependency audit has no findings |
| Source contracts | Lint, database checksums, mission shape, configuration tripwire and release-workflow checks pass |
| MCP | Five contract tests and isolated wheel-install discovery pass |
| Existing Aurora | 53 SQL/eligibility checks and 110 retrieval/answerability checks pass |
| Mission and evaluation identity | 111 mission checks pass; 720 historical filter targets, 14 real targets and 38 historical canonical targets pass in their own schemas |
| Required labs | Lab 1 and Lab 2 production validators pass; Lab 3 and its source-comparison control pass with Studio's Sonnet 4.6 pin |
| SQL before/after | See `psql-lab-verification-2026-09-22.json`; those earlier runs used Sonnet 5 and retain that identity |
| Real catalog cache | 500,000 source/input-hash pairs, 9,496 saved vector batches and 32 source-verified review excerpts verified; no vectors regenerated |
| Runtime permissions | Actual database role can query the served catalog and register product evidence; temporary role and writes rolled back |
| Browser | More screen space shows Dell first, the 27-inch/4K/up-to-90W details and original listing links; its saved order moves from combined 32 to final 1 |
| Local Studio | Template lint and participant request parity pass; source pin/hash checks must run after the source is published |
| Public data delivery | Not performed; redistribution clearance remains unresolved in the source assessment |
| Fresh-account rehearsal | Excluded; still an event-owner acceptance gate |
| Broad quality benchmark | Pending for this catalog; historical synthetic metrics are withheld from the active scorecard |

## Repairs that matter for delivery

- Bootstrap verifies the new bundle before loading, restores and selects the real
  catalog, grants the runtime access to its schemas, and applies lab changes to
  the active search functions. Keeping only the old source pin would have served
  the retired catalog.
- Synthesis repair retains both product intents. An invalid draft cannot become
  a catalog refusal merely because a retry silently dropped one product. The
  current model run completes all required tools without a truncated response.
- Live release CI explicitly selects the mission dataset. Historical vocabulary
  calibration runs against its original retained schema; current spelling,
  eligibility and answerability checks use source products. Unknown prices are
  not converted to invented budget fixtures.
- Scoring rejects a mixed-catalog query set before paid calls. Source IDs and
  previous measurements remain preserved, with no claim that old scores apply.

## Publication order

Publish source with the configured maintainer Git identity. Confirm the remote
full SHA, then use Studio's `scripts/repin.py` to copy the bootstrap and update
SourceRevision, BootstrapScriptSha256 and InfrastructureRevision together.
The event owner handles S3 synchronization, published-object verification and
Studio Git/publication. Both historical cache shards and the new real-catalog
archive are needed; neither ignored bundle is supplied by cloning Studio.
