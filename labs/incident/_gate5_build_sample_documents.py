#!/usr/bin/env python3
"""Gate 5 step 1: build a realistic sample of ~180-250 Wave-A-shaped document
bodies across the six signal-type categories, from real varying measurements
(not copy-pasted text), for the diversity check in _gate5_corpus_diversity.py.
Throwaway prototype.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

random.seed(20260804)

documents: list[tuple[str, str]] = []

# 1. Lock and blocking-state transitions: each document is a DISTINCT event
# on the real timeline (a specific writer entering OR leaving a wait, at a
# specific real timestamp), not a template with one number swapped -- this
# is the actual design-spec pattern (state-change/interval-boundary, never
# a fixed-count loop over the same sentence shape). Only 10 hot writers exist
# in the real design, so only ~10-14 genuinely distinct lock-transition
# events are possible per run (each writer transitions in, and separately
# times out) -- generating 40 was itself the mistake; a real implementation
# would cap this category near its natural event count, not pad it to a
# target number.
writer_durations = [3.19, 3.58, 4.04, 4.29, 4.68, 5.09, 5.39, 5.81, 6.15, 3.01]
writer_outcomes = ["statement_timeout"] * 9 + ["pool_timeout"]
backfill_pid = 5287
lock_events = []
for writer_idx in range(10):
    hot_writer_pid = 5100 + writer_idx
    duration = writer_durations[writer_idx]
    outcome = writer_outcomes[writer_idx]
    lock_events.append(
        f"Application writer session (PID {hot_writer_pid}, targeting order_id "
        f"{writer_idx + 1}) entered a Lock:Transactionid wait against the open "
        f"backfill transaction (PID {backfill_pid})."
    )
    if outcome == "statement_timeout":
        lock_events.append(
            f"Writer session PID {hot_writer_pid} was canceled by its own "
            f"3-second statement_timeout after {duration:.2f}s of waiting on "
            f"Lock:Transactionid, having already been checked out from the pool."
        )
    else:
        lock_events.append(
            f"Writer session targeting order_id {writer_idx + 1} never reached "
            f"a lock wait at all: it exhausted its 3-second pool-checkout "
            f"timeout after {duration:.2f}s because all 10 pool slots were "
            f"already occupied by the other nine blocked writers."
        )
for i, body in enumerate(lock_events, 1):
    documents.append((f"TEL-LOCK-{i:03d}", body))

# 2. Pool saturation and recovery snapshots: STATE-CHANGE events only, per
# the design spec's rule (the 250ms poll is control, not document generation
# -- one document per transition, not one per poll tick). The real pool
# progression from Gate 4 has exactly a handful of genuine state changes
# (empty -> filling -> saturated -> draining -> recovered), not 35 near-
# identical snapshots. Each document below describes a DIFFERENT kind of
# transition in different words, not the same sentence with three numbers
# swapped.
pool_state_changes = [
    "The connection pool began accepting hot-write checkouts with all 10 slots free and zero requests queued.",
    "Pool occupancy crossed 30% as the first three hot-write sessions checked out connections and immediately blocked on the backfill's row locks.",
    "Pool occupancy crossed 70% with seven connections checked out; two additional requests began queuing behind the exhausted slots.",
    "The pool reached full saturation: all 10 connections checked out, zero available, with request queuing first observed.",
    "Queued-request depth peaked while the pool remained fully saturated, the maximum concurrent backlog observed during the hold.",
    "The first queued request exhausted its checkout timeout and returned a PoolTimeout while the pool remained fully saturated.",
    "The backfill transaction committed, releasing every row lock the ten blocked sessions were waiting on.",
    "Checked-out connections began returning to the pool as the previously blocked sessions completed their now-unblocked writes.",
    "Pool availability crossed 50% recovered as more than half the previously checked-out connections returned.",
    "The pool returned to its resting state with all 10 connections available and zero requests queued, confirming full recovery.",
]
for i, body in enumerate(pool_state_changes, 1):
    documents.append((f"TEL-POOL-{i:02d}", body))

# 3. Request latency and timeout aggregates: one document per DISTINCT
# outcome class actually observed (not padded to a target count with
# repeated sentence shapes).
documents.append((
    "TEL-REQ-01",
    "Nine of the ten hot-write requests were canceled by their own 3-second "
    "statement_timeout after already checking out a connection, with "
    "individual wait durations ranging from 3.19 to 6.15 seconds.",
))
documents.append((
    "TEL-REQ-02",
    "One hot-write request never obtained a connection at all: it exhausted "
    "its 3-second pool-checkout timeout after 3.01 seconds because every "
    "pool slot was already held by the other nine blocked writers.",
))
documents.append((
    "TEL-REQ-03",
    "No hot-write request completed successfully during the proven hold; "
    "the first successful write was the post-commit recovery probe issued "
    "after the backfill released its locks.",
))

# 4. WAL and statement deltas: distinct MILESTONES in the backfill's progress,
# described in different structural terms (not "at time T, N rows" repeated
# with different T/N), matching the real design intent of capturing meaningful
# progress markers rather than uniform time-sliced snapshots.
wal_milestones = [
    "The backfill's row-version churn began immediately on the first batch of updated rows, each generating a new heap tuple version.",
    "By roughly one third of the backfill's total duration, row-version churn had accumulated across the first million touched rows.",
    "At the midpoint of the backfill, WAL volume generated by the update was substantial enough to be a measurable, distinct signal from ordinary application traffic.",
    "In the final third of the backfill, the remaining untouched rows were processed at a consistent per-row rate, matching the measured 7.1 seconds per million rows observed on this instance class.",
    "The backfill's total measured duration was 21.12 seconds across all 3,000,000 rows, consistent with the empirically calibrated linear rate for this table shape and instance class.",
]
for i, body in enumerate(wal_milestones, 1):
    documents.append((f"TEL-WAL-{i:02d}", body))

# 5. Backfill, recovery, and index metadata (~10 docs): distinct lifecycle
# events, not repeated snapshots.
lifecycle_events = [
    ("Migration step 1", "ADD COLUMN priority_tier committed separately in 0.04s, retaining no lock beyond its own brief AccessExclusiveLock."),
    ("Migration step 2", "Backfill transaction opened; unbatched UPDATE over all 3,000,000 rows began."),
    ("Backfill completion", "Backfill UPDATE completed in 21.12s; transaction intentionally left open to hold acquired row locks."),
    ("Proven hold begin", "Three consecutive 250ms samples confirmed pool_size=pool_max=10, pool_available=0, requests_waiting>=2, and all ten tagged sessions blocked on Lock:Transactionid referencing the backfill PID."),
    ("Hold duration", "Observation hold sustained for the proven state before commit was triggered."),
    ("Commit", "Backfill transaction committed; all acquired row locks released."),
    ("Recovery verification", "Pool availability restored to full capacity; zero sessions remained blocked by the backfill; a fresh hot-write request succeeded."),
    ("Query regression discovered", "The post-migration query against the new column returned via a sequential scan filtering 2,400,000 of 3,000,000 rows."),
    ("ANALYZE attempted", "Table statistics refreshed; the query plan remained a sequential scan with materially unchanged execution time."),
    ("Diagnosis published", "The evidence-backed finding recommended a composite index on (priority_tier, created_at) as the missing access path, not a statistics refresh."),
]
for i, (title, body) in enumerate(lifecycle_events, 1):
    documents.append((f"TEL-META-{i:02d}", f"{title}: {body}"))

# 6. Query-plan checkpoints (exactly 3, fixed, real measured numbers).
plan_checkpoints = [
    ("before ANALYZE", "sequential scan", "471.75", "600000 actual rows, 2400000 removed by filter, 53041 buffers"),
    ("after ANALYZE, still no index", "sequential scan", "245.65", "600000 actual rows, 2400000 removed by filter, 53038 buffers"),
    ("after the supporting index", "index scan using idx_orders_priority_created", "2.24", "20 actual rows, 0 removed by filter, 23 buffers"),
]
for i, (label, plan_type, exec_ms, detail) in enumerate(plan_checkpoints, 1):
    documents.append((
        f"TEL-PLAN-{i:02d}",
        f"Query-plan checkpoint {label}: {plan_type}, execution time {exec_ms}ms, {detail}.",
    ))

print(f"total documents generated: {len(documents)}")
by_prefix: dict[str, int] = {}
for key, _ in documents:
    prefix = key.rsplit("-", 1)[0]
    by_prefix[prefix] = by_prefix.get(prefix, 0) + 1
for prefix, count in sorted(by_prefix.items()):
    print(f"  {prefix}: {count}")

Path("/tmp/gate5_sample_documents.json").write_text(json.dumps(documents))
print("written to /tmp/gate5_sample_documents.json")
