# DAT410 co-speaker review brief

Review `docs/SPEC-session.md`, then walk the current Workshop Studio guide from
the incident overview through replay. The target is one L400, 60-minute build,
not three adjacent workshops.

## Review questions

1. Does the incident remain a short, recognizable on-ramp to the retrieval
   problem?
2. Does every abstract claim have a participant checkpoint?
3. Can participants explain why exact, semantic, fuzzy, filters, RRF, and
   reranking each exist?
4. Does the agent answer require relationship traversal and cited evidence
   rather than plausible prose?
5. Can a saved `run_id` reproduce what the answer used without a model call?
6. Are RLS/masking, AgentCore Gateway, admission, and operations clearly
   optional?
7. Does the full core path fit in 60 minutes with the documented cut ladder?

## Technical boundary

Lab 1 uses the shipped 25,000-row `workbench_lab.orders` exercise. It measures
real PostgreSQL locks, wait events, PIDs, relation OIDs, and catalog rows. The
ordinary build's transaction is held open after the small index completes so
the genuine `ShareLock` remains observable. Reviewers must not interpret that
hold time as production index-build duration or throughput.

The old 25-million-row `shop.orders`, pgbench load generators, and 240-420
second timing gate are deferred design history. They are not missing release
assets and should not be proposed as required fixes unless the session scope is
deliberately expanded.

## Release evidence

- fresh Workshop Studio account on representative `db.r8g.2xlarge`;
- all nine incident scripts pass under the participant role;
- exact, fuzzy, semantic, hybrid, rerank fallback, cited answer, diagnostics,
  evaluation, and replay pass;
- source archive revision and v2 dump revision match; and
- optional modules publish only when their own gates pass.
