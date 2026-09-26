# Fresh-account deployment evidence — 26 September 2026

Deployment acceptance passed for application source
`49fc03f31ffb89b36ca200df81ac250283b8175f` and workshop commit
`2ce708740dafab3fc4db5e4175fd15ef2ec30796`. Workshop Studio's build succeeded;
the root and all nested CloudFormation stacks reached `CREATE_COMPLETE`.
This record describes that deployment, not later commits on `main`.

This is a sanitized summary of the operator's local rehearsal manifest,
bootstrap reports, request receipts and browser observations. Raw receipts and
private account and event identifiers are retained outside the public source
tree. The broader rehearsal remains incomplete as described below.

## Catalog and required path

- Restored 553,911 real source products and 553,911 saved Cohere Embed v4
  vectors at 1,024 dimensions, without product re-embedding.
- Verified catalog hash
  `c4d5913f89050332f71512baf2a0351331208ab94eac0621be9ac63e653cfa00`,
  model, receipt, vocabulary and required indexes. Acceptance found zero
  foreign products, synthetic brands, historical search documents or
  historical vocabulary rows.
- Each of Labs 1–3 passed two reset → expected production failure → repair →
  production success cycles. Lab 3 included G-021 and the separate G-019
  evidence-grounding control. Participant model-access preflights passed.
- Missing or spoofed origin credentials returned 401; direct nginx access
  returned 403; authorized requests returned 200.
- A 13-request mixed workload had no errors. A 16-request burst returned
  12 successes and four 429 responses with `Retry-After`; a recovery query
  then succeeded. These are bounded single-instance checks, not room-scale
  throughput measurements.
- Shop, required labs and Ask Mosaic were inspected at narrow and wide sizes;
  tablet and 1080p lab layouts were checked. Keyboard navigation moved focus
  to main content. Stop, retry to a cited answer, and clear-chat behavior passed.

## Measured time

| Measurement | Result | Boundary |
|---|---:|---|
| Stack creation to observed completion | 51.89 min | Poll-bounded observation, not exact completion event |
| Full bootstrap | 22.10 min | Bootstrap log creation to completion marker |
| Asset setup, transfer and verified join | 20.24 s | Cache directory creation to verified join event |
| Catalog restore | 1,111.656 s | Restore report; excludes archive unpack |
| All search indexes | 129.15 s | Included in restore |
| HNSW index | 95.52 s | Seven maintenance workers; included in search indexes |
| Reranked search, first/repeat | 1.91 / 1.65 s | Operator probes after bootstrap model canaries |
| Grounded agent, first/repeat | 51.33 / 46.75 s | Four citations and two recommendations each |
| First recorder query through CloudFront | 3.71 s | Earlier operator requests had warmed the API |

The parallel HNSW build optimization ran successfully. This deployment is not
a paired before/after speedup experiment, and the model probes are not global
cold-start measurements. See the separate
[controlled index comparison](../remediation-status.md#bootstrap-optimization-audit)
for its different measurement conditions.

## Remaining evidence

The rehearsal manifest remains `in_progress`. Physical projector/back-row
legibility, human participant completion timing, matched before/after refactor
captures, controlled delayed filter-race browser checks, cold-start timings,
a reviewed real-catalog
scorecard and measured independent relevance remain outstanding. The supplied
feedback's `docs/hardening-review.md` is still absent.

The recorder identity correction (PR #5) and HNSW availability explanation
(PR #6) subsequently merged into the source repository; this deployment did
not contain them. New source changes require their own release pins and
acceptance evidence.
