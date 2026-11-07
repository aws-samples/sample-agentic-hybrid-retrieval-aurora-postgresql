# DAT410 remediation checks — 7 November 2026

The initial pass below records checks of an **uncommitted working tree** based on
`d662b6196ba6edfbac071d24070f0611dc47245b`. It is not release certification,
a Workshop Studio build, or a fresh-account rehearsal. Workshop Studio content
and the three participant edit blocks were unchanged. The source README,
workshop overview and maintainer documentation describe the changed checks.

## Changes and evidence

| Area | Change | Verification |
|---|---|---|
| Finished-answer support | `service/claim_review.py` reviews every passage of the actual draft, requires supporting quotations from that passage's cited records, and rejects incomplete or unsupported decisions. `service/synthesis.py` retains deterministic checks, adds spelled measurements and property checks, and permits only its existing one replacement draft. | Regression cases first reproduced acceptance of unsupported claims. Positive cases, malformed review responses, quotation binding, replacement review, usage accounting and answer hashes are covered offline. Eight live Bedrock probes passed; see the JSON artifact below. |
| Changed requirements | `service/lab_followup.py` and `service/lab_proof.py` require the saved 100W question, a new search containing the named monitor, its current specification, matching deployed code, and a checked answer or relevant decline. The setup answer also needs its finished-draft review receipt. | The missing-follow-up regression failed against the old completion path. Tests reject skipped searches, missing/stale specifications, different code, changed answers and invalid citations; supported shortfalls and relevant declines pass. The manifest question matches the existing guide verbatim. No managed deployment was performed. |
| Turn deadline | `service/agent_execution.py` uses a process-owned loop and bounded executor for synchronous invocation and fallback. Fallback shares the remaining turn budget and works on isolated state. Cancellation blocks subsequent synthesis/review calls. | A real 500ms worker defeated the old 50ms deadline (about 506ms elapsed). Tests now cover real worker waits, context propagation, exhausted budgets, synchronous and streaming fallback, cancellation, and prevention of late answer publication. Persistence retains its separate DB timeout. An in-flight SDK call still cannot be interrupted. |
| Reranking pool | The configuration accepts the exercise's 75-product pool independently of the public result cap and evidence grant. | A live request produced a fused pool of 75, 50 public results and an authorization window of two. Offline agent-path tests cover pools of 50, 75 and 100. The served default remains unchanged. |
| Semantic rank order | `db/sql/08_search_channels.sql` materializes the bounded ANN candidates and explicitly sorts `distance + 0, product_id` before assigning rank. | The installed original function violated distance order on **54/141** judged queries. The read-only repaired query had **0/141** violations and identical candidate membership on every query. Its plan retained the HNSW index scan and added a full sort of the bounded set. The permanent integration test failed against the old function and passed after the approved development update. |
| Evaluation cache | `scripts/cache_lab2_arms.py` requests the actual served channel limits, rather than prefixes of larger ANN lists. The consumer rejects different limits or fuzzy thresholds. | Rebuilt all 141 judged queries and four chair controls against the repaired development function at FTS/fuzzy/semantic limits **120/80/150**. The live comparison passed its three cache spot checks. |

The explicit ANN sort follows the
[pgvector iterative-scan guidance](https://github.com/pgvector/pgvector#iterative-index-scans).
This fixes rank order within the retrieved candidate set; it does not turn ANN
retrieval into exact nearest-neighbor search.

## Live results

The final offline Python run passed **3,361 tests**, with **49 skipped**. Ruff
checks/formatting, package/SQL/config/tool-contract validation, release-workflow
checks and `git diff --check` passed. All **820 UI tests** and the UI production
build passed. The existing runtime package allowlist includes all three new
service modules. Python exited successfully but emitted a non-fatal psycopg
pool-worker shutdown warning (`pool-4-worker-2`, five-second join timeout);
deployed process shutdown has not been validated here.

Development Aurora reported `mosaic_v2`, 553,911 listings, pgvector 0.8.1 and
pg_trgm 1.6. Catalog, embedding coverage, index readiness and retrieval-setting
checks passed. No product data or indexes were changed. With explicit approval,
only `search_semantic` and its existing applied-source receipt were updated.
Production retrieval probes created normal search audit records.

- Lab 1: all **10** production proof checks passed.
  Search events: `3f2e6ca9-fec0-4d96-9f4b-b35ba6c553cb`,
  `729927c3-0427-465f-88f7-c6d775b941bc`,
  `bc3b2d8c-00ec-43bf-b18a-9910ad34ed8a`.
- Lab 2: all **15** production proof checks passed.
  Search events: `1c15db89-55c5-44b7-b265-42b253477071`,
  `816fcf66-08bb-4c16-bb76-167fb40f2981`,
  `9819bf3e-5950-45a0-b7a9-c753ed7bf72b`,
  `e71ca813-a941-4dde-b2ec-580ee788353f`.
- Pool/grant separation: search event
  `23c43600-f467-4eb6-b4a6-b81009e5203a` recorded 75 fused candidates and a
  two-product grant while returning 50 results.
- Lab 2 comparison: baseline retained 128 exact judgments; the 75-product cutoff
  retained 17 more across 16 queries, with no losses. This measures retention
  before reranking. The comparison does not call the reranking model and cannot
  establish improved final recommendations. Chair controls remain separate from
  the relevance judgments.
- Mission gate: **126 checks passed**. Evaluation validation covered 17 canonical,
  65 coverage-corpus and 2,081 held-out judged targets. Function census passed.
- The selected live SQL/anchor test run had **18 passes and one failure**;
  the memory mutation test was deliberately deselected. The failure is recorded
  below, not counted as a pass.

[Claim-support probe results](claim-support-2026-11-07.json) record the exact
fixture inputs, decisions, model, usage and latency. All eight cases passed with
`global.anthropic.claude-sonnet-5-5`; measured calls took **1.986–5.192 seconds**.
These are single-pass examples using in-memory fixtures, not a false-acceptance
rate, latency percentile, or timed workshop measurement. The model judge can
still err and shares a model family with the answer writer.

The temporary PostgreSQL ingress rule was removed after the checks; the existing
rule was preserved and its presence verified.

## Remaining release work

1. **Resolve the confirmed Shop count timeout.**
   `tests/test_sql_integration.py:141` failed twice with HTTP 503 from
   `POST /api/catalog/counts`. A direct call to the unchanged
   `service/live_catalog.py:301` raised `QueryCanceled`, SQLSTATE `57014`, after
   31.1 seconds. The six-filter batch is in that test. The server reported work
   inside `matches_filter_values`; EXPLAIN showed a catalog scan and a
   source-price hash join. A read-only `UNION ALL` alternative also timed out,
   so it was not adopted. Investigate predicate inlining and filter evaluation
   cost, preserve the shared filter semantics, and rerun the existing endpoint
   comparison within the configured timeout. Do not raise the timeout to obtain
   a green check. Neither this API nor its filter function was modified here.
2. **Measure the clean release candidate.** `make score-evals` correctly refused
   this dirty working tree before making calls. The previous scorecard was not
   rewritten. After review and commit, run the scorecard and stage ablation and
   inspect any ranking changes before updating baselines.
3. **Deploy and rehearse Lab 3 on the final source pin.** Confirm Gateway/Runtime
   execution, both saved questions, support-review receipts, completion, failure
   recovery, and end-to-end latency. Offline tests and direct Bedrock probes do
   not certify these managed paths. No agent runtime or workshop was deployed
   or published in this pass.
4. **Time an unfamiliar participant.** Preserve the three-lab structure and the
   45-minute hands-on budget, including completion. Added review calls and the
   strengthened completion check require measurement on the delivered build.

## Technical closure pass

The owner subsequently authorized closing items 1–3, publishing source and
re-pinning Workshop Studio before the separate guide audit.

The Shop timeout is repaired. `matches_filter_values` contained a subquery that
prevented PostgreSQL from inlining it. Moving case normalization of the brand
array into an immutable helper preserves the shared predicate, including null,
empty, duplicate and mixed-case brand values. The six-count transaction-only
probe completed in **2.848 seconds**, with counts
`207636, 0, 363779, 0, 0, 541336`; the old implementation exceeded its unchanged
30-second timeout. EXPLAIN changed from an opaque per-product function call to
inlined predicates. The permanent plan regression was observed failing before
the repair and passing afterward.

The helper and filter function were applied to development Aurora with the
existing source-digest guard and receipt. No catalog rows, indexes, lab
functions or timeout settings changed. All **23 selected Aurora SQL and pool
recovery tests passed**; the unrelated memory-writing test was deselected.
The endpoint test compares the six batch counts with the Shop's individual
filtered totals. The 141-query/four-control cache was rebuilt in **84 seconds**,
and its identity now includes the helper definition.

Tracing pool creation identified an unintended telemetry database write in
`test_agent_declares_the_window_it_grants_not_the_one_it_requests`: its search
was mocked, but its telemetry persistence was not. That unit test now isolates
the write. Production idle-connection replacement and timeout rollback/reuse
both passed against Aurora.

The final offline run passed **3,361 tests**, with **56 skipped**,
in 83.68 seconds and emitted no pool shutdown warning. All **820 UI tests**, the
production UI build, lint/configuration/release-workflow checks, 126 mission
checks, and the three evaluation-contract populations passed. The installed
production count call took **3.847 seconds**, including connection setup, with
the same six totals. The function census found 15 names with one signature each.

The source repair was published as `1410900540994aa6b9c916e6301c9623721ea19e`
under the maintainer's configured Git identity, and all three source CI runs
passed. The new canonical measurement uses the existing pinned query vectors.
All nine scored product-retrieval queries kept their per-query metrics and
deterministic release checks: Recall@10 **1.0**, MRR **0.759259**, and nDCG@10
**0.803296**. The only returned-list change was below the intended first result
in `G-003`; its named hard negatives remained excluded. This establishes
regression coverage on these judgments, not improved general relevance.

The stage comparison also retained its previous measured metrics. At cutoff 10,
full-text/fuzzy/semantic recall was **0.388889 / 0.555556 / 0.444444**; fusion
reached **0.722222**, and managed reranking reached **1.0**. Every judged relevant
product was present in the fused shortlist. The artifact preserves its explicit
warning about the small population: nine queries and 14 judgments cannot resolve
small differences. Its reranked arm reuses the newly measured canonical results;
the other four arms were queried again against Aurora. All 148 measurement and
artifact contract tests passed.

Managed deployment and saved-run acceptance are recorded separately with the
Workshop Studio build and test event. This source record does not claim a timed
unfamiliar-participant rehearsal or fresh-event acceptance from offline tests.
