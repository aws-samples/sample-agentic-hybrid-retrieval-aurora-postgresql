# Fresh-account rehearsal — 29 September 2026

The Workshop Studio deployment of source
`cf691d2adf9782c7a6a665d37ed9ab816401ecd1` and workshop commit
`4c8f68486e678b7a5567d52f29615d342725993b` reached `CREATE_COMPLETE` in
the root and all three nested stacks. Bootstrap completed, including managed
Runtime/Gateway, model access and Memory readiness. The account was then patched
with the cache and error-message corrections described below. This record
distinguishes original provisioning from the subsequent patched rehearsal; it
does not certify pristine provisioning of a later source pin.

The operator retained sanitized command logs, before/after search receipts,
saved agent runs and streaming events outside the public source tree.

## Catalog and required labs

- Aurora contained 553,911 real products and saved 1,024-dimensional Cohere
  vectors, with zero incompatible vectors, text-hash mismatches, foreign
  products, synthetic brands or historical search/vocabulary rows.
- Catalog restore took 1,119.854 seconds. Index creation included in that
  restore took 127.71 seconds, including 97.08 seconds for HNSW with seven
  maintenance workers. These are individual observations, not a speedup study.
- Each required lab passed two independent reset, expected-failure, repair and
  production-proof cycles. Lab 3 included deployment, Gateway verification,
  completion against the original saved answer, and evidence-grounding checks.
- Lab 2's predeclared `k=30` proposal correctly failed its improvement rule:
  Exact results fell from 128 to 123, with one judged query improving and six
  worsening. Rejecting this proposal passed the decision check. Independent
  SQL calculations agreed with production fusion after repair.
- The managed agent's follow-ups distinguished a documented 90W monitor from
  an unsupported 100W requirement and separated headphone microphone claims
  from mixed reviewer experience.

## Corrections found during rehearsal

Lab 2's bundled candidate cache predated the historical-price filter repair;
its generator also omitted production HNSW configuration. Cache generation now
uses production settings, and bootstrap prepares a cache on the workshop's own
Aurora indexes. Grading verifies source, catalog, function and HNSW identities,
then repeats live searches. No retrieval limits, weights or checks were relaxed.

A rehearsal follow-up omitted products from the previous answer's authorized
context. The request correctly failed, but the transport mislabeled its HTTP
409 as a deployment mismatch. The corrected harness supplied the complete
context; both Lab 3 cycles passed. The transport now directs participants to
check deployment state instead of asserting unproven source drift.

## Optional Memory

Saving a preference, recalling it, starting a new session and streaming a cited
answer passed. The specific monitor preference became available after 83.87
seconds, and four records were recalled. The answer used current catalog sources
for a 27-inch 4K monitor with documented 90W USB-C charging.

An earlier attempt proceeded after recalling only the broad fact that Alex
works from home; answerability validation refused its synthesis. That failure
is retained. The successful attempt waited for the monitor preference, as the
page instructs. One successful retry does not establish a failure rate.

## Evidence limits

The patched source passed 2,320 Python tests with Aurora available, the live
mission and evaluation contracts, the function census and bootstrap data checks.
SQL integration gates ran from a separate release-source checkout against the
same Aurora database; the managed-agent checks ran from the participant checkout
with its deployed additional instruction. Offline validation also passed 2,281
Python tests (64 Aurora skips), 790 UI tests, the UI build, package/configuration
checks and the MCP package tests.

The nine-query canonical scorecard retained Recall@10 1.0, MRR 0.759259 and
nDCG@10 0.803296. Two headphone cases changed lower-ranked alternatives on this
fresh index, while their judged Bose target remained first. The operator reviewed
the changed ranks before refreshing the measured release artifacts.

The rehearsal used maintainer commands and includes debugging interruptions;
its durations are not human participant completion times. Physical projector
legibility, controlled cold starts and a pristine deployment of the corrected
bootstrap remain separate checks. The account's completed lab work was preserved.
