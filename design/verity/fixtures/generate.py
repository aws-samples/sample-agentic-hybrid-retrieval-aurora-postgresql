#!/usr/bin/env python3
"""
Canonical numeric model for the Verity workshop fixtures.

This file is the single source of truth for every number the workshop displays.
Nothing downstream hardcodes an RRF value, a fused rank, or a final rank: they
are computed here from arm positions and the fusion controls, then emitted.

The only hand-authored numbers in the whole package are:
  * per-arm ORDERINGS (which evidence the arm returned, in what order);
  * raw arm diagnostics (ts_rank, cosine distance, trigram similarity);
  * rerank scores (a model output, which cannot be derived).

Everything else -- rrf_score, fused_rank, final_rank, candidate_count,
citation numbering, parity goldens -- is derived, and asserted before write.

Run:  python3 fixtures/generate.py        (writes fixtures)
      python3 fixtures/generate.py --check (verifies without writing)

Why this exists: the previous prototype pass published an RRF value of 0.0491
next to inputs that summed to 0.06505. Hardcoded result tables drift out of
agreement with their own formulas. Derived tables cannot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CONTRACT_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Fusion controls. These are the OpenAPI SearchControls defaults.
# ---------------------------------------------------------------------------

DEFAULT_CONTROLS: dict[str, Any] = {
    "mode": "hybrid",
    "candidate_pool": 24,
    "rrf_k": 60,
    "text_weight": 2.0,
    "vector_weight": 1.0,
    "fuzzy_weight": 1.0,
    "fuzzy_threshold": 0.30,
    "ef_search": 40,
    "iterative_scan": "strict_order",
    "rerank": False,
}

PRINCIPAL_WORKSHOP = {"scopes": ["workshop"], "principals": []}
PRINCIPAL_SUPPORT_LEAD = {"scopes": ["workshop"], "principals": ["support-lead"]}

ID_TOKEN_RE = re.compile(r"\b[A-Z]{2,6}-[0-9]{3,6}\b")

# ---------------------------------------------------------------------------
# Evidence catalog.
# ---------------------------------------------------------------------------

EVIDENCE: list[dict[str, Any]] = [
    {
        "id": "CHG-1000", "kind": "change", "role": "confirmed cause",
        "title": "Ordinary CREATE INDEX on orders(customer_id)",
        "occurred_at": "2026-05-19T09:17:00Z", "restricted": False,
        "quote": "CREATE INDEX idx_orders_customer_id ON orders (customer_id); executed against checkout-prod-01 at 09:17 UTC without the CONCURRENTLY option.",
    },
    {
        "id": "CHG-1001", "kind": "change", "role": "ruled out",
        "title": "Checkout worker pool resize",
        "occurred_at": "2026-05-19T09:05:00Z", "restricted": False,
        "quote": "Checkout worker pool resized from 24 to 32 workers at 09:05 UTC. Change is application-tier only and acquires no database locks.",
    },
    {
        "id": "CHG-1002", "kind": "change", "role": "preventive follow-up",
        "title": "Rebuild index with CREATE INDEX CONCURRENTLY",
        "occurred_at": "2026-05-19T10:05:00Z", "restricted": False,
        "quote": "Rebuild scheduled using CREATE INDEX CONCURRENTLY outside a transaction block, with progress monitoring and INVALID index cleanup on failure.",
    },
    {
        "id": "CHG-1010", "kind": "change", "role": "background change",
        "title": "Checkout read-replica endpoint rotation",
        "occurred_at": "2026-05-18T22:40:00Z", "restricted": False,
        "quote": "Read-replica endpoint rotated to the new reader endpoint. No writer-side effect.",
    },
    {
        "id": "INC-2000", "kind": "incident", "role": "canonical incident",
        "title": "Checkout writes blocked while reads continued",
        "occurred_at": "2026-05-19T09:24:00Z", "restricted": False,
        "quote": "Sev-2 declared 09:24 UTC. Checkout write transactions queued on checkout-prod-01 while read traffic served normally. Approximately 34 minutes of blocked writes.",
    },
    {
        "id": "INC-2001", "kind": "incident", "role": "look-alike decoy",
        "title": "Older checkout deploy incident",
        "occurred_at": "2025-11-04T14:10:00Z", "restricted": False,
        "quote": "Checkout latency incident traced to a bad application deploy. Writes and reads both degraded. No database lock involvement.",
    },
    {
        "id": "LOCK-3000", "kind": "lock", "role": "first lock proof",
        "title": "Writer 4182 blocked by index backend 3944",
        "occurred_at": "2026-05-19T09:19:00Z", "restricted": False,
        "quote": "pid 4182 waiting on Lock:relation, blocked by pid 3944 holding ShareLock on orders. wait_event_type=Lock, wait_event=relation.",
    },
    {
        "id": "LOCK-3001", "kind": "lock", "role": "second lock proof",
        "title": "Writer 4210 blocked by index backend 3944",
        "occurred_at": "2026-05-19T09:22:00Z", "restricted": False,
        "quote": "pid 4210 waiting on Lock:relation, blocked by the same pid 3944. Confirms a single blocker rather than lock contention among writers.",
    },
    {
        "id": "CASE-4000", "kind": "case", "role": "visible affected",
        "title": "Acme Retail checkout failures",
        "occurred_at": "2026-05-19T09:38:00Z", "restricted": False,
        "quote": "Acme Retail reported checkout submission failures beginning 09:38 UTC. Confirmed affected; browse and search unaffected.",
    },
    {
        "id": "CASE-4001", "kind": "case", "role": "restricted affected",
        "title": "Regulated account write errors",
        "occurred_at": "2026-05-19T09:41:00Z", "restricted": True,
        "quote": "Regulated account reported write errors during the same window. Record is restricted to the support-lead principal.",
    },
    {
        "id": "CASE-4002", "kind": "case", "role": "visible unaffected",
        "title": "Zenith Corp impact inquiry",
        "occurred_at": "2026-05-19T10:12:00Z", "restricted": False,
        "quote": "Zenith Corp asked whether they were affected. Their traffic is served by a separate cluster; no impact recorded during the window.",
    },
    {
        "id": "RB-5000", "kind": "runbook", "role": "approved safe fix",
        "title": "Concurrent index builds on production writers",
        "occurred_at": "2026-04-02T00:00:00Z", "restricted": False,
        "quote": "Cancel the blocking build, then rebuild with CREATE INDEX CONCURRENTLY outside a transaction block. Monitor pg_stat_progress_create_index and drop any INVALID index before retrying.",
    },
    {
        "id": "RB-5001", "kind": "runbook", "role": "decoy",
        "title": "Generic write-latency triage",
        "occurred_at": "2025-08-14T00:00:00Z", "restricted": False,
        "quote": "General write-latency triage: check connection saturation, checkpoint tuning, and autovacuum backlog.",
    },
    {
        "id": "COMMIT-6000", "kind": "commitment", "role": "customer commitment",
        "title": "RCA and safe-fix plan for Acme Retail",
        "occurred_at": "2026-05-20T00:00:00Z", "restricted": False,
        "quote": "Committed to Acme Retail: written RCA and a preventive safe-fix plan by 2026-05-26.",
    },
]

EV_BY_ID = {e["id"]: e for e in EVIDENCE}

# ---------------------------------------------------------------------------
# Retrieval runs.
#
# `text` merges two SQL sources: exact B-tree hits on external_key (tier 0,
# prepended, ordered by appearance of the token in the question) followed by
# GIN tsvector hits (tier 1), deduplicated by evidence_id, positions assigned
# 1..n after DISTINCT ON.
#
# `fuzzy` probes ONLY identifier-shaped tokens that produced no exact hit.
# A query whose identifiers all resolve has a legitimately empty fuzzy arm.
# ---------------------------------------------------------------------------

RUNS: dict[str, dict[str, Any]] = {
    "RUN-7000": {
        "preset": "canonical",
        "label": "canonical full agent run",
        "query": (
            "During INC-2000 on checkout-prod-01, why did checkout writes appear to hang "
            "while reads continued? Determine whether CHG-1000 or CHG-1001 caused the "
            "incident, identify the customer impact visible to the current principal, "
            "explain what evidence rules out the alternative change, and cite the lock "
            "evidence and approved runbook supporting both immediate recovery and the "
            "preventive follow-up."
        ),
        "arms": {
            "text":   ["INC-2000", "CHG-1000", "CHG-1001", "LOCK-3000", "CASE-4000",
                       "RB-5000", "INC-2001", "LOCK-3001"],
            "vector": ["INC-2000", "LOCK-3000", "CHG-1000", "LOCK-3001", "RB-5000",
                       "CASE-4000", "INC-2001", "CHG-1002"],
            "fuzzy":  [],
        },
        "arms_support_lead": {
            "text":   ["INC-2000", "CHG-1000", "CHG-1001", "LOCK-3000", "CASE-4000",
                       "CASE-4001", "RB-5000", "INC-2001", "LOCK-3001"],
            "vector": ["INC-2000", "LOCK-3000", "CHG-1000", "LOCK-3001", "RB-5000",
                       "CASE-4000", "CASE-4001", "INC-2001", "CHG-1002"],
            "fuzzy":  [],
        },
        "raw": {
            "text":   {"INC-2000": 0.4082, "CHG-1000": 0.3711, "CHG-1001": 0.3204,
                       "LOCK-3000": 0.2871, "CASE-4000": 0.2618, "RB-5000": 0.2402,
                       "INC-2001": 0.2214, "LOCK-3001": 0.2050, "CASE-4001": 0.2509},
            "vector": {"INC-2000": 0.208, "LOCK-3000": 0.231, "CHG-1000": 0.246,
                       "LOCK-3001": 0.259, "RB-5000": 0.274, "CASE-4000": 0.288,
                       "INC-2001": 0.311, "CHG-1002": 0.334, "CASE-4001": 0.291},
            "fuzzy":  {},
        },
        "rerank": {
            "CHG-1000": 0.94, "INC-2000": 0.91, "LOCK-3000": 0.88, "RB-5000": 0.81,
            "CASE-4000": 0.76, "LOCK-3001": 0.69, "CHG-1001": 0.47, "CHG-1002": 0.39,
            "INC-2001": 0.18, "CASE-4001": 0.73,
        },
    },
    "RUN-7001": {
        "preset": "semantic-symptom",
        "label": "semantic symptom, no identifier in the query",
        "query": "Why were checkout writes hanging while reads still worked?",
        "arms": {
            "text":   ["INC-2000", "CASE-4000", "LOCK-3000", "INC-2001"],
            "vector": ["INC-2000", "LOCK-3000", "LOCK-3001", "CHG-1000", "INC-2001",
                       "CASE-4000"],
            "fuzzy":  [],
        },
        "raw": {
            "text":   {"INC-2000": 0.4082, "CASE-4000": 0.2871, "LOCK-3000": 0.2214,
                       "INC-2001": 0.1908},
            "vector": {"INC-2000": 0.208, "LOCK-3000": 0.231, "LOCK-3001": 0.256,
                       "CHG-1000": 0.298, "INC-2001": 0.305, "CASE-4000": 0.321},
            "fuzzy":  {},
        },
        "rerank": {
            "INC-2000": 0.94, "LOCK-3000": 0.89, "LOCK-3001": 0.84, "CHG-1000": 0.71,
            "CASE-4000": 0.66, "INC-2001": 0.21,
        },
    },
    "RUN-7002": {
        "preset": "exact-change",
        "label": "exact identifier lookup",
        "query": "What did CHG-1000 change?",
        "arms": {
            "text":   ["CHG-1000", "INC-2000", "LOCK-3000", "CHG-1002"],
            "vector": ["CHG-1000", "CHG-1002", "INC-2000", "LOCK-3000"],
            "fuzzy":  [],
        },
        "raw": {
            "text":   {"CHG-1000": 0.6931, "INC-2000": 0.2871, "LOCK-3000": 0.2214,
                       "CHG-1002": 0.2019},
            "vector": {"CHG-1000": 0.114, "CHG-1002": 0.221, "INC-2000": 0.263,
                       "LOCK-3000": 0.288},
            "fuzzy":  {},
        },
        "rerank": {
            "CHG-1000": 0.97, "INC-2000": 0.83, "LOCK-3000": 0.79, "CHG-1002": 0.58,
        },
    },
    "RUN-7003": {
        "preset": "fuzzy-change-id",
        "label": "typo recovery: CGH-1000 does not resolve exactly",
        "query": "Did CGH-1000 cause INC-2000?",
        "arms": {
            "text":   ["INC-2000", "LOCK-3000", "CHG-1000"],
            "vector": ["INC-2000", "LOCK-3000", "CHG-1000", "LOCK-3001"],
            "fuzzy":  ["CHG-1000"],
        },
        "raw": {
            "text":   {"INC-2000": 0.5108, "LOCK-3000": 0.2214, "CHG-1000": 0.1904},
            "vector": {"INC-2000": 0.212, "LOCK-3000": 0.244, "CHG-1000": 0.271,
                       "LOCK-3001": 0.283},
            "fuzzy":  {"CHG-1000": 0.5000},
        },
        "rerank": {
            "CHG-1000": 0.95, "INC-2000": 0.90, "LOCK-3000": 0.86, "LOCK-3001": 0.64,
        },
    },
    # -- per-subquestion retrievals issued by the agent -------------------
    "RUN-7100": {
        "preset": "agent-subquestion", "label": "SQ-1 · symptom",
        "query": "Why did checkout writes hang while reads continued during INC-2000?",
        "arms": {"text": ["INC-2000", "LOCK-3000", "CASE-4000", "INC-2001"],
                 "vector": ["INC-2000", "LOCK-3000", "LOCK-3001", "CHG-1000", "INC-2001"],
                 "fuzzy": []},
        "raw": {"text": {"INC-2000": 0.5108, "LOCK-3000": 0.2871, "CASE-4000": 0.2214, "INC-2001": 0.1904},
                "vector": {"INC-2000": 0.196, "LOCK-3000": 0.224, "LOCK-3001": 0.248,
                           "CHG-1000": 0.281, "INC-2001": 0.309}, "fuzzy": {}},
        "rerank": {}},
    "RUN-7101": {
        "preset": "agent-subquestion", "label": "SQ-2 · which change",
        "query": "Did CHG-1000 or CHG-1001 cause INC-2000?",
        "arms": {"text": ["CHG-1000", "CHG-1001", "INC-2000", "LOCK-3000"],
                 "vector": ["CHG-1000", "LOCK-3000", "INC-2000", "CHG-1002"],
                 "fuzzy": []},
        "raw": {"text": {"CHG-1000": 0.6931, "CHG-1001": 0.6410, "INC-2000": 0.3204, "LOCK-3000": 0.2214},
                "vector": {"CHG-1000": 0.148, "LOCK-3000": 0.232, "INC-2000": 0.267,
                           "CHG-1002": 0.294}, "fuzzy": {}},
        "rerank": {}},
    "RUN-7102": {
        "preset": "agent-subquestion", "label": "SQ-3 · visible impact",
        "query": "Which customer impact is visible to the current principal?",
        "arms": {"text": ["CASE-4000", "CASE-4002", "INC-2000"],
                 "vector": ["CASE-4000", "CASE-4002", "COMMIT-6000", "INC-2000"],
                 "fuzzy": []},
        "arms_support_lead": {
            "text": ["CASE-4000", "CASE-4002", "CASE-4001", "INC-2000"],
            "vector": ["CASE-4000", "CASE-4002", "CASE-4001", "COMMIT-6000", "INC-2000"],
            "fuzzy": []},
        "raw": {"text": {"CASE-4000": 0.4468, "CASE-4002": 0.3011, "CASE-4001": 0.2664, "INC-2000": 0.2108},
                "vector": {"CASE-4000": 0.171, "CASE-4002": 0.219, "CASE-4001": 0.238,
                           "COMMIT-6000": 0.271, "INC-2000": 0.303}, "fuzzy": {}},
        "rerank": {}},
    "RUN-7103": {
        "preset": "agent-subquestion", "label": "SQ-4 · rules out",
        "query": "What evidence rules out the alternative change?",
        "arms": {"text": ["CHG-1001", "LOCK-3000", "LOCK-3001"],
                 "vector": ["LOCK-3000", "LOCK-3001", "CHG-1001", "CHG-1000"],
                 "fuzzy": []},
        "raw": {"text": {"CHG-1001": 0.5108, "LOCK-3000": 0.2871, "LOCK-3001": 0.2644},
                "vector": {"LOCK-3000": 0.201, "LOCK-3001": 0.226, "CHG-1001": 0.259,
                           "CHG-1000": 0.288}, "fuzzy": {}},
        "rerank": {}},
    "RUN-7104": {
        "preset": "agent-subquestion", "label": "SQ-5 · attempt 1 · cluster filter on",
        "query": "Which lock evidence and approved runbook support recovery and the preventive follow-up?",
        "arms": {"text": ["LOCK-3000", "LOCK-3001", "CHG-1002"],
                 "vector": ["LOCK-3000", "LOCK-3001", "CHG-1002", "INC-2000"],
                 "fuzzy": []},
        "raw": {"text": {"LOCK-3000": 0.4082, "LOCK-3001": 0.3711, "CHG-1002": 0.2214},
                "vector": {"LOCK-3000": 0.213, "LOCK-3001": 0.241, "CHG-1002": 0.276,
                           "INC-2000": 0.312}, "fuzzy": {}},
        "rerank": {}},
    "RUN-7105": {
        "preset": "agent-counterfactual", "label": "SQ-5 · ef_search 200, filter kept",
        "query": "Which lock evidence and approved runbook support recovery and the preventive follow-up?",
        "arms": {"text": ["LOCK-3000", "LOCK-3001", "CHG-1002", "INC-2000"],
                 "vector": ["LOCK-3000", "LOCK-3001", "CHG-1002", "INC-2000", "INC-2001"],
                 "fuzzy": []},
        "raw": {"text": {"LOCK-3000": 0.4082, "LOCK-3001": 0.3711, "CHG-1002": 0.2214, "INC-2000": 0.1908},
                "vector": {"LOCK-3000": 0.213, "LOCK-3001": 0.241, "CHG-1002": 0.276,
                           "INC-2000": 0.312, "INC-2001": 0.344}, "fuzzy": {}},
        "rerank": {}},
    "RUN-7106": {
        "preset": "agent-escalated", "label": "SQ-5 · attempt 2 · cluster filter dropped",
        "query": "Which lock evidence and approved runbook support recovery and the preventive follow-up?",
        "arms": {"text": ["RB-5000", "LOCK-3000", "LOCK-3001", "CHG-1002", "RB-5001"],
                 "vector": ["RB-5000", "LOCK-3000", "RB-5001", "LOCK-3001", "CHG-1002", "INC-2000"],
                 "fuzzy": []},
        "raw": {"text": {"RB-5000": 0.4871, "LOCK-3000": 0.4082, "LOCK-3001": 0.3711,
                         "CHG-1002": 0.2214, "RB-5001": 0.1802},
                "vector": {"RB-5000": 0.188, "LOCK-3000": 0.213, "RB-5001": 0.237,
                           "LOCK-3001": 0.241, "CHG-1002": 0.276, "INC-2000": 0.312}, "fuzzy": {}},
        "rerank": {}},
    "RUN-7004": {
        "preset": "customer-impact",
        "label": "customer impact under ACL",
        "query": "Which customer was affected by INC-2000?",
        "arms": {
            "text":   ["INC-2000", "CASE-4000", "CASE-4002"],
            "vector": ["CASE-4000", "CASE-4002", "COMMIT-6000", "INC-2000"],
            "fuzzy":  [],
        },
        "arms_support_lead": {
            "text":   ["INC-2000", "CASE-4000", "CASE-4002", "CASE-4001"],
            "vector": ["CASE-4000", "CASE-4002", "CASE-4001", "COMMIT-6000", "INC-2000"],
            "fuzzy":  [],
        },
        "raw": {
            "text":   {"INC-2000": 0.4468, "CASE-4000": 0.3902, "CASE-4002": 0.2871,
                       "CASE-4001": 0.2664},
            "vector": {"CASE-4000": 0.183, "CASE-4002": 0.229, "CASE-4001": 0.241,
                       "COMMIT-6000": 0.276, "INC-2000": 0.294},
            "fuzzy":  {},
        },
        "rerank": {
            "CASE-4000": 0.96, "CASE-4002": 0.72, "INC-2000": 0.68, "COMMIT-6000": 0.55,
            "CASE-4001": 0.93,
        },
    },
}

# ---------------------------------------------------------------------------
# Agent run.
#
# The canonical question has five subquestions. Retrieving once over the whole
# sentence and calling it an agent is a stored procedure with a JSON schema on
# the front. Here each subquestion gets its own retrieval, coverage is a
# deterministic rule over evidence kinds, and an uncovered subquestion triggers
# one bounded escalation.
#
# SQ-5 is the interesting one. RB-5000 is a runbook, and a runbook is not scoped
# to a cluster -- so `cluster_id = 'checkout-prod-01'`, the filter that makes the
# other four subquestions precise, is exactly what hides it. Widening the ANN
# search does not help: no value of ef_search recovers a row the WHERE clause
# excluded. RUN-7105 exists to prove that.
# ---------------------------------------------------------------------------

AGENT_RUN_ID = "ARUN-8000"
AGENT_BUDGET = {"max_tool_calls": 12, "max_escalations": 2}

# Evidence with cluster_id None is not cluster-scoped. Load-bearing: if RB-5000
# ever gains a cluster, the escalation stops being necessary and Module 2's
# teaching moment silently disappears.
UNSCOPED = {"RB-5000", "RB-5001", "COMMIT-6000"}

SUBQUESTIONS = [
    {"id": "SQ-1", "run": "RUN-7100", "required_kinds": ["incident", "lock"],
     "text": "Why did checkout writes hang while reads continued during INC-2000?"},
    {"id": "SQ-2", "run": "RUN-7101", "required_kinds": ["change", "lock"],
     "text": "Did CHG-1000 or CHG-1001 cause INC-2000?"},
    {"id": "SQ-3", "run": "RUN-7102", "required_kinds": ["case"],
     "text": "Which customer impact is visible to the current principal?"},
    {"id": "SQ-4", "run": "RUN-7103", "required_kinds": ["change", "lock"],
     "text": "What evidence rules out the alternative change?"},
    {"id": "SQ-5", "run": "RUN-7104", "required_kinds": ["lock", "runbook"],
     "counterfactual": "RUN-7105", "escalated": "RUN-7106",
     "text": "Which lock evidence and approved runbook support recovery and the preventive follow-up?"},
]

ESCALATION = {
    "subquestion_id": "SQ-5",
    "reason": "missing_required_kind",
    "missing_kinds": ["runbook"],
    # Shape matches the proof.agent_escalations.changed column comment.
    "changed": {
        "before": {"controls": {"ef_search": 40, "candidate_pool": 24},
                   "filters": {"cluster_id": "checkout-prod-01"}},
        "after":  {"controls": {"ef_search": 200, "candidate_pool": 48},
                   "filters": {"cluster_id": None}},
    },
    "rationale": (
        "A runbook is not scoped to a cluster. The cluster_id filter that makes the incident "
        "subquestions precise is what excludes RB-5000 from SQ-5. Raising ef_search alone does "
        "not recover it -- see the RUN-7105 counterfactual -- because no ANN widening returns a "
        "row the WHERE clause removed before the index was consulted."
    ),
    "outcome": "covered",
}

# EXPLAIN (ANALYZE, BUFFERS) on Aurora emits aurora_orcache_hit and
# aurora_storage_read, which exist in no other PostgreSQL. They are the reason
# the agent's escalation is measurable rather than merely asserted.
# Illustrative until the release gate replaces them with target-Aurora captures.
AURORA_BUFFERS = {
    "RUN-7104": {"shared_hit": 214, "read": 0,   "aurora_orcache_hit": 0,   "aurora_storage_read": 0},
    "RUN-7105": {"shared_hit": 486, "read": 112, "aurora_orcache_hit": 96,  "aurora_storage_read": 16},
    "RUN-7106": {"shared_hit": 531, "read": 147, "aurora_orcache_hit": 118, "aurora_storage_read": 29},
}

CITATION_ORDER = ["INC-2000", "CHG-1000", "LOCK-3000", "CASE-4000", "RB-5000"]

VERDICTS = [
    {"evidence_id": "CHG-1000", "verdict": "change_confirmed",
     "rationale": "Held ShareLock on orders across the incident window; both lock snapshots name its backend pid 3944 as the blocker."},
    {"evidence_id": "CHG-1001", "verdict": "change_ruled_out",
     "rationale": "Application-tier worker pool resize. Acquires no database lock and does not appear in either lock snapshot."},
    {"evidence_id": "CHG-1002", "verdict": "preventive_follow_up",
     "rationale": "Implements the approved runbook by rebuilding the index concurrently."},
    {"evidence_id": "CASE-4000", "verdict": "affected",
     "rationale": "Reported checkout submission failures inside the blocked-write window."},
    {"evidence_id": "CASE-4002", "verdict": "not_affected",
     "rationale": "Served by a separate cluster; no impact recorded during the window."},
]

RELATIONSHIPS = [
    ("INC-2000", "CHG-1000", "caused_by", "canonical", 1.0, None),
    ("INC-2000", "LOCK-3000", "evidenced_by", "canonical", 1.0, None),
    ("INC-2000", "LOCK-3001", "evidenced_by", "canonical", 1.0, None),
    ("LOCK-3000", "CHG-1000", "blocked_by", "canonical", 1.0, None),
    ("LOCK-3001", "CHG-1000", "blocked_by", "canonical", 1.0, None),
    ("INC-2000", "CASE-4000", "affects", "canonical", 1.0, None),
    ("INC-2000", "CASE-4001", "affects", "canonical", 1.0, None),
    ("INC-2000", "CASE-4002", "not_affects", "canonical", 1.0, None),
    ("CHG-1000", "RB-5000", "remediated_by", "canonical", 1.0, None),
    ("CHG-1002", "RB-5000", "implements", "canonical", 1.0, None),
    ("CASE-4000", "COMMIT-6000", "commitment_for", "canonical", 1.0, None),
    ("INC-2000", "INC-2001", "resembles", "inferred", 0.62, "embedding_knn"),
    ("CHG-1001", "INC-2000", "considered_for", "inferred", 0.41, "temporal_proximity"),
]

TIMELINE = [
    ("2026-05-19T09:05:00Z", "CHG-1001", "Checkout worker pool resized (no locks taken)"),
    ("2026-05-19T09:17:00Z", "CHG-1000", "CREATE INDEX starts on orders, no CONCURRENTLY"),
    ("2026-05-19T09:19:00Z", "LOCK-3000", "Writer 4182 blocked by backend 3944"),
    ("2026-05-19T09:22:00Z", "LOCK-3001", "Writer 4210 blocked by the same backend"),
    ("2026-05-19T09:24:00Z", "INC-2000", "Sev-2 declared: writes hang, reads normal"),
    ("2026-05-19T09:38:00Z", "CASE-4000", "Acme Retail reports checkout failures"),
    ("2026-05-19T09:51:00Z", "CHG-1000", "Blocking build cancelled (~34 min of blocked writes)"),
    ("2026-05-19T10:05:00Z", "CHG-1002", "Rebuild scheduled with CREATE INDEX CONCURRENTLY"),
    ("2026-05-20T00:00:00Z", "COMMIT-6000", "RCA and safe-fix plan committed to Acme Retail"),
]

# Illustrative until replaced by target-Aurora release-gate measurements.
STAGE_TIMINGS = {
    "exact_fts_ms": 2.3, "vector_ms": 3.8, "fuzzy_ms": 1.1, "fuse_ms": 0.7,
    "traverse_ms": 9.4, "compare_ms": 6.1, "rerank_ms": 74.0, "synthesis_ms": 1240.0,
}

EVAL_MODES = [
    {"mode": "lexical only",    "recall_at_10": 0.62, "mrr": 0.58, "ndcg_at_10": 0.61},
    {"mode": "semantic only",   "recall_at_10": 0.71, "mrr": 0.64, "ndcg_at_10": 0.68},
    {"mode": "fuzzy only",      "recall_at_10": 0.24, "mrr": 0.22, "ndcg_at_10": 0.23},
    {"mode": "hybrid RRF",      "recall_at_10": 0.89, "mrr": 0.81, "ndcg_at_10": 0.85},
    {"mode": "hybrid + rerank", "recall_at_10": 0.89, "mrr": 0.93, "ndcg_at_10": 0.91},
]

EVAL_ARCHETYPES = [
    {"archetype": "exact identifier", "lexical": 0.98, "semantic": 0.41, "fuzzy": 0.35, "hybrid": 0.99},
    {"archetype": "semantic symptom", "lexical": 0.44, "semantic": 0.88, "fuzzy": 0.05, "hybrid": 0.91},
    {"archetype": "typo identifier",  "lexical": 0.02, "semantic": 0.28, "fuzzy": 0.94, "hybrid": 0.96},
    {"archetype": "customer impact",  "lexical": 0.72, "semantic": 0.74, "fuzzy": 0.11, "hybrid": 0.88},
]

# Reported separately from retrieval metrics -- traversal is not retrieval.
EVAL_TRAVERSAL = {"relationship_recall": 0.92, "relationship_precision": 0.86}


# ---------------------------------------------------------------------------
# Derivation.
# ---------------------------------------------------------------------------

def positions(order: list[str]) -> dict[str, int]:
    """Dense 1..n positions, assigned after DISTINCT ON (evidence_id)."""
    seen: dict[str, int] = {}
    n = 0
    for ev in order:
        if ev in seen:
            continue
        n += 1
        seen[ev] = n
    return seen


def rrf_terms(pos: dict[str, int | None], controls: dict[str, Any]) -> dict[str, float]:
    """Per-arm RRF contribution. An absent arm contributes exactly zero."""
    k = controls["rrf_k"]
    w = {"text": controls["text_weight"],
         "vector": controls["vector_weight"],
         "fuzzy": controls["fuzzy_weight"]}
    return {arm: (w[arm] / (k + p) if p is not None else 0.0) for arm, p in pos.items()}


def build_run(run_id: str, principal_key: str = "arms",
              controls: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = RUNS[run_id]
    controls = dict(controls or DEFAULT_CONTROLS)
    arms = spec.get(principal_key) or spec["arms"]

    pos = {arm: positions(arms.get(arm, [])) for arm in ("text", "vector", "fuzzy")}
    universe: list[str] = []
    for arm in ("text", "vector", "fuzzy"):
        for ev in arms.get(arm, []):
            if ev not in universe:
                universe.append(ev)

    rows = []
    for ev in universe:
        p = {arm: pos[arm].get(ev) for arm in ("text", "vector", "fuzzy")}
        terms = rrf_terms(p, controls)
        rows.append({
            "evidence_id": ev,
            "external_key": ev,
            "kind": EV_BY_ID[ev]["kind"],
            "title": EV_BY_ID[ev]["title"],
            "source_uri": f"workshop://{EV_BY_ID[ev]['kind']}/{ev}",
            "source_revision": "rev-0001",
            "text_position": p["text"],
            "vector_position": p["vector"],
            "fuzzy_position": p["fuzzy"],
            "text_score": spec["raw"]["text"].get(ev),
            "vector_distance": spec["raw"]["vector"].get(ev),
            "fuzzy_score": spec["raw"]["fuzzy"].get(ev),
            "rrf_terms": {a: round(v, 8) for a, v in terms.items()},
            "rrf_score": round(sum(terms.values()), 8),
            "rerank_score": spec["rerank"].get(ev),
        })

    # Fused rank: rrf DESC, then text_position NULLS LAST, then external_key ASC.
    rows.sort(key=lambda r: (-r["rrf_score"],
                             r["text_position"] if r["text_position"] is not None else 10**6,
                             r["external_key"]))
    for i, r in enumerate(rows, 1):
        r["fused_rank"] = i

    # final_rank is fused_rank when rerank is off; otherwise it is derived by
    # sorting on the model score. It is never hand-assigned.
    if controls["rerank"]:
        ordered = sorted(rows, key=lambda r: (-(r["rerank_score"] or 0.0), r["fused_rank"]))
        for i, r in enumerate(ordered, 1):
            r["final_rank"] = i
    else:
        for r in rows:
            r["final_rank"] = r["fused_rank"]

    return {
        "run_id": run_id,
        "preset": spec["preset"],
        "label": spec["label"],
        "query": spec["query"],
        "controls": controls,
        "principal": PRINCIPAL_SUPPORT_LEAD if principal_key == "arms_support_lead" else PRINCIPAL_WORKSHOP,
        "arm_orders": arms,
        "candidates": rows,
    }


def coverage(run: dict[str, Any], required_kinds: list[str], top_n: int = 8) -> dict[str, Any]:
    """A subquestion is covered when its retrieval returned at least one
    candidate of each required kind inside the top N. Deterministic SQL rule,
    not a model judgement -- the agent's decision has to be as inspectable as
    everything else in this session."""
    top = sorted(run["candidates"], key=lambda r: r["fused_rank"])[:top_n]
    covering, missing = {}, []
    for kind in required_kinds:
        hit = next((r["evidence_id"] for r in top if r["kind"] == kind), None)
        if hit:
            covering[kind] = hit
        else:
            missing.append(kind)
    return {"covered": not missing, "missing_kinds": missing,
            "covering_evidence_ids": covering, "considered": len(top)}


def build_agent_run(controls: dict[str, Any]) -> dict[str, Any]:
    escalated_controls = {**controls, "ef_search": 200, "candidate_pool": 48}
    scoped = {"cluster_id": "checkout-prod-01"}

    subs, retrievals, tool_calls = [], [], 0
    for sq in SUBQUESTIONS:
        first = build_run(sq["run"], controls=controls)
        tool_calls += 1
        cov = coverage(first, sq["required_kinds"])
        record = {"subquestion_id": sq["id"], "text": sq["text"],
                  "required_kinds": sq["required_kinds"], "attempts": 1,
                  "runs": [{"run_id": sq["run"], "attempt": 1, "controls": controls,
                            "filters": scoped, "coverage": cov,
                            "aurora_buffers": AURORA_BUFFERS.get(sq["run"])}]}
        retrievals.append((sq["run"], sq["id"], 1))

        if not cov["covered"] and sq.get("escalated"):
            esc = build_run(sq["escalated"], controls=escalated_controls)
            tool_calls += 1
            ecov = coverage(esc, sq["required_kinds"])
            record["attempts"] = 2
            # Integer attempt ordinal, matching proof.agent_retrievals.superseded_by.
            record["runs"][0]["superseded_by"] = 2
            record["runs"][0]["superseded_by_run_id"] = sq["escalated"]
            record["runs"].append({"run_id": sq["escalated"], "attempt": 2,
                                   "controls": escalated_controls, "filters": {"cluster_id": None},
                                   "coverage": ecov,
                                   "aurora_buffers": AURORA_BUFFERS.get(sq["escalated"])})
            retrievals.append((sq["escalated"], sq["id"], 2))
            record["final_coverage"] = ecov
        else:
            record["final_coverage"] = cov
        subs.append(record)

    tool_calls += 3     # follow_evidence_links, compare_sources, synthesize_cited_answer

    cf = build_run("RUN-7105", controls=escalated_controls)
    counterfactual = {
        "run_id": "RUN-7105", "subquestion_id": "SQ-5",
        "controls": escalated_controls, "filters": scoped,
        "coverage": coverage(cf, ["lock", "runbook"]),
        "aurora_buffers": AURORA_BUFFERS["RUN-7105"],
        "note": ("Participant experiment, not an agent tool call. Raises ef_search 40 -> 200 and "
                 "the pool 24 -> 48 but keeps the cluster filter. Still uncovered: no ANN widening "
                 "returns a row the WHERE clause excluded before the index was consulted."),
    }

    return {
        "agent_run_id": AGENT_RUN_ID,
        "question": RUNS["RUN-7000"]["query"],
        "principal": PRINCIPAL_WORKSHOP,
        "filters_initial": scoped,
        "controls_initial": controls,
        "budget": AGENT_BUDGET,
        "tool_calls_spent": tool_calls,
        "escalations_spent": 1,
        "status": "succeeded",     # vocabulary from the proof.agent_runs CHECK
        "steps": ["decompose_question", "search_evidence x5", "evaluate_coverage",
                  "search_evidence (escalated x1)", "follow_evidence_links",
                  "compare_sources", "synthesize_cited_answer"],
        "subquestions": subs,
        "escalations": [ESCALATION],
        "counterfactual": counterfactual,
        "retrievals": [{"run_id": r, "subquestion_id": s, "attempt": a} for r, s, a in retrievals],
    }


def citations(run: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = {c["evidence_id"]: c for c in run["candidates"]}
    out = []
    for n, ev in enumerate(CITATION_ORDER, 1):
        if ev not in by_id:
            raise AssertionError(f"citation {ev} is not in the visible candidate set")
        out.append({
            "citation_number": n,
            "evidence_id": ev,
            "external_key": ev,
            "source_uri": by_id[ev]["source_uri"],
            "source_revision": by_id[ev]["source_revision"],
            "quote": EV_BY_ID[ev]["quote"],
        })
    return out


ANSWER = (
    "CHG-1000 ran an ordinary CREATE INDEX on orders(customer_id) against the production "
    "writer [2]. A non-concurrent index build takes a SHARE lock on the table, which "
    "conflicts with the ROW EXCLUSIVE lock every INSERT, UPDATE and DELETE needs, but not "
    "with the ACCESS SHARE lock a SELECT needs — so checkout writes queued while reads "
    "continued to serve [1]. Both lock snapshots name the same blocking backend, pid 3944, "
    "which rules out contention among writers [3]. CHG-1001 is ruled out: it is an "
    "application-tier worker pool resize that acquires no database lock and appears in "
    "neither snapshot. Acme Retail is the affected customer visible to this principal [4]. "
    "RB-5000 is the approved recovery: cancel the blocking build, then rebuild with "
    "CREATE INDEX CONCURRENTLY outside a transaction block, monitoring "
    "pg_stat_progress_create_index and dropping any INVALID index before retrying [5]."
)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


# ---------------------------------------------------------------------------
# Assertions. These run on every generate and every --check.
# ---------------------------------------------------------------------------

def assert_model(runs: dict[str, dict[str, Any]]) -> list[str]:
    checks: list[str] = []

    for run_id, run in runs.items():
        c = run["controls"]
        k, w = c["rrf_k"], (c["text_weight"], c["vector_weight"], c["fuzzy_weight"])

        for r in run["candidates"]:
            # 1. Every rrf_score reproduces from the formula and the positions.
            expect = 0.0
            for arm, weight in zip(("text", "vector", "fuzzy"), w):
                p = r[f"{arm}_position"]
                if p is not None:
                    expect += weight / (k + p)
            assert abs(expect - r["rrf_score"]) < 1e-8, (
                f"{run_id} {r['evidence_id']}: rrf_score {r['rrf_score']} != computed {expect}")

            # 2. An absent arm contributes exactly zero.
            for arm in ("text", "vector", "fuzzy"):
                if r[f"{arm}_position"] is None:
                    assert r["rrf_terms"][arm] == 0.0, f"{run_id} {r['evidence_id']}: absent {arm} arm is non-zero"

        # 3. fused_rank is dense, gapless, and strictly ordered by rrf DESC.
        ranks = sorted(r["fused_rank"] for r in run["candidates"])
        assert ranks == list(range(1, len(ranks) + 1)), f"{run_id}: fused_rank is not dense 1..n"
        ordered = sorted(run["candidates"], key=lambda r: r["fused_rank"])
        for a, b in zip(ordered, ordered[1:]):
            assert a["rrf_score"] >= b["rrf_score"], f"{run_id}: fused_rank contradicts rrf_score"

        # 4. No two candidates tie on rrf_score (ties would make replay
        #    dependent on the tiebreak rather than on the ranking).
        scores = [r["rrf_score"] for r in run["candidates"]]
        assert len(set(scores)) == len(scores), f"{run_id}: rrf_score tie -- ranking is not determined by the score alone"

        # 5. final_rank is dense and monotonic with rerank_score when rerank is on.
        finals = sorted(r["final_rank"] for r in run["candidates"])
        assert finals == list(range(1, len(finals) + 1)), f"{run_id}: final_rank is not dense 1..n"
        if run["controls"]["rerank"]:
            byfinal = sorted(run["candidates"], key=lambda r: r["final_rank"])
            for a, b in zip(byfinal, byfinal[1:]):
                assert (a["rerank_score"] or 0) >= (b["rerank_score"] or 0), (
                    f"{run_id}: final_rank contradicts rerank_score")
        else:
            for r in run["candidates"]:
                assert r["final_rank"] == r["fused_rank"], f"{run_id}: rerank off but final_rank != fused_rank"

        # 6. ACL: restricted evidence is absent, not present-and-marked.
        ids = {r["evidence_id"] for r in run["candidates"]}
        if run["principal"] == PRINCIPAL_WORKSHOP:
            assert "CASE-4001" not in ids, f"{run_id}: restricted CASE-4001 leaked to the default principal"

        # 7. The fuzzy arm only fires on identifier tokens that do not resolve exactly.
        tokens = set(ID_TOKEN_RE.findall(run["query"]))
        unresolved = {t for t in tokens if t not in EV_BY_ID}
        if not unresolved:
            assert not run["arm_orders"].get("fuzzy"), (
                f"{run_id}: fuzzy arm fired but every identifier token resolved exactly")

        checks.append(f"{run_id}: {len(run['candidates'])} candidates, RRF reproduces, ranks dense, no ties")

    # 8. Every citation is in the canonical run's visible set.
    canonical = runs["RUN-7000"]
    vis = {r["evidence_id"] for r in canonical["candidates"]}
    for ev in CITATION_ORDER:
        assert ev in vis, f"citation {ev} is not retrievable in RUN-7000"
    checks.append(f"citations: {len(CITATION_ORDER)} of {len(vis)} visible candidates, all retrievable")

    # 9. Every quote is non-empty and every cited item exists.
    for ev in CITATION_ORDER:
        assert EV_BY_ID[ev]["quote"].strip(), f"{ev}: empty quote"

    # 10. The typo probe resolves to exactly one row above threshold.
    assert "CGH-1000" not in EV_BY_ID, "the typo fixture must not exist as evidence"
    assert RUNS["RUN-7003"]["arms"]["fuzzy"] == ["CHG-1000"], "typo probe must return exactly CHG-1000"
    checks.append("typo probe CGH-1000 -> CHG-1000 only (0.5000; next-nearest 0.2857 is below the 0.30 threshold)")

    # 11. Relationship endpoints all exist.
    for s, t, *_ in RELATIONSHIPS:
        assert s in EV_BY_ID and t in EV_BY_ID, f"relationship endpoint missing: {s} -> {t}"

    return checks


def assert_agent(agent: dict[str, Any], runs: dict[str, dict]) -> list[str]:
    """The agent loop has to be a loop. These assertions are what stop it
    quietly reverting to a fixed pipeline."""
    checks = []
    by_id = {s["subquestion_id"]: s for s in agent["subquestions"]}

    # 1. Every subquestion ends covered, or the run is not 'complete'.
    uncovered = [s["subquestion_id"] for s in agent["subquestions"]
                 if not s["final_coverage"]["covered"]]
    assert not uncovered or agent["status"] != "succeeded", f"uncovered but succeeded: {uncovered}"

    # 2. At least one subquestion must actually fail first. Without this the
    #    escalation path is unreachable and the loop is decorative.
    first_fail = [s for s in agent["subquestions"] if not s["runs"][0]["coverage"]["covered"]]
    assert first_fail, "no subquestion failed coverage -- the escalation path is never exercised"

    # 3. SQ-5 specifically: uncovered on attempt 1, missing exactly the runbook.
    sq5 = by_id["SQ-5"]
    assert sq5["runs"][0]["coverage"]["missing_kinds"] == ["runbook"], "SQ-5 attempt 1 must miss the runbook"
    assert sq5["attempts"] == 2 and sq5["final_coverage"]["covered"], "SQ-5 must be covered after escalation"

    # 4. The counterfactual must STILL fail. This is the teaching point: no ANN
    #    widening recovers a row the WHERE clause excluded. If a fixture edit
    #    ever makes this pass, the escalation stops proving anything.
    cf = agent["counterfactual"]
    assert not cf["coverage"]["covered"], (
        "the ef_search-only counterfactual is covered -- the escalation no longer demonstrates "
        "that the filter, not the ANN width, was the constraint")
    assert cf["coverage"]["missing_kinds"] == ["runbook"], "counterfactual must miss the runbook"

    # 5. The escalation must change the filter, not only the controls.
    assert ESCALATION["changed"]["after"]["filters"]["cluster_id"] is None, "escalation must drop cluster_id"
    assert ESCALATION["changed"]["before"]["filters"]["cluster_id"] is not None, "before-state must be filtered"

    # 6. Budget is respected and reported.
    assert agent["tool_calls_spent"] <= agent["budget"]["max_tool_calls"], "tool-call budget exceeded"
    assert agent["escalations_spent"] <= agent["budget"]["max_escalations"], "escalation budget exceeded"

    # 7. Aurora buffer counters must rise with the widened scan, or the plan
    #    diff shows nothing and the Aurora claim is unsupported.
    a1, cfb, a2 = (AURORA_BUFFERS["RUN-7104"], AURORA_BUFFERS["RUN-7105"], AURORA_BUFFERS["RUN-7106"])
    assert a2["aurora_storage_read"] > a1["aurora_storage_read"] and cfb["aurora_storage_read"] > a1["aurora_storage_read"], \
        "widening the scan must be visible in aurora_storage_read"

    # 8. Every cited item must be reachable from some subquestion retrieval.
    reachable = set()
    for s in agent["subquestions"]:
        for r in s["runs"]:
            reachable |= {c["evidence_id"] for c in runs[r["run_id"]]["candidates"]}
    for ev in CITATION_ORDER:
        assert ev in reachable, f"cited {ev} is not retrieved by any subquestion"

    # 9. explain_ranking must not be scripted as an agent step.
    assert not any("explain_ranking" in s for s in agent["steps"]), \
        "explain_ranking is a human diagnostic surface, not an agent step"

    checks.append(f"{AGENT_RUN_ID}: {len(agent['subquestions'])} subquestions, "
                  f"1 escalation, {agent['tool_calls_spent']}/{agent['budget']['max_tool_calls']} tool calls")
    checks.append("SQ-5 uncovered at ef_search 40 -> still uncovered at 200 with the filter kept "
                  "-> covered only when cluster_id is dropped")
    return checks


# ---------------------------------------------------------------------------
# Emit.
# ---------------------------------------------------------------------------

def write(path: Path, obj: Any, dry: bool) -> None:
    if dry:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="verify without writing")
    args = ap.parse_args()
    dry = args.check

    runs = {rid: build_run(rid) for rid in RUNS}
    runs_sl = {
        "RUN-7000": build_run("RUN-7000", "arms_support_lead"),
        "RUN-7004": build_run("RUN-7004", "arms_support_lead"),
        "RUN-7102": build_run("RUN-7102", "arms_support_lead"),
    }
    reranked = {rid: build_run(rid, controls={**DEFAULT_CONTROLS, "rerank": True})
                for rid in RUNS if RUNS[rid]["rerank"]}

    checks = assert_model(runs)
    assert_model(reranked)
    assert_model(runs_sl)

    agent = build_agent_run(DEFAULT_CONTROLS)
    checks += assert_agent(agent, runs)

    canonical = runs["RUN-7000"]
    cites = citations(canonical)

    # -- canonical-scenario.json -------------------------------------------
    write(ROOT / "canonical-scenario.json", {
        "contract_version": CONTRACT_VERSION,
        "question_full": canonical["query"],
        "question_compact": "Why did writes hang during INC-2000, which change caused it, who was affected, and what was the safe recovery?",
        "typo_probe": {
            "token": "CGH-1000",
            "resolves_to": "CHG-1000",
            "similarity": 0.5,
            "next_nearest": 0.2857,
            "threshold": 0.30,
            "note": "Letter transposition. Chosen because it clears the threshold against exactly one row. The former CHG-0100 tied at 0.5000 with CHG-1100.",
        },
        "principal_default": PRINCIPAL_WORKSHOP,
        "principal_support_lead": PRINCIPAL_SUPPORT_LEAD,
        "cluster": "checkout-prod-01",
        "controls_default": DEFAULT_CONTROLS,
        "evidence": [
            {"id": e["id"], "kind": e["kind"], "role": e["role"], "title": e["title"],
             "occurred_at": e["occurred_at"], "restricted": e["restricted"],
             # None means not cluster-scoped. Load-bearing: if RB-5000 ever gains
             # a cluster, the SQ-5 escalation stops being necessary and Module 2's
             # teaching moment silently disappears.
             "cluster_id": None if e["id"] in UNSCOPED else "checkout-prod-01",
             "quote": e["quote"]}
            for e in EVIDENCE
        ],
        "subquestions": [{"subquestion_id": s["id"], "text": s["text"],
                          "required_kinds": s["required_kinds"]} for s in SUBQUESTIONS],
        "relationships": [
            {"source_id": s, "target_id": t, "relationship": rel, "origin": o,
             "confidence": conf, "method": m}
            for s, t, rel, o, conf, m in RELATIONSHIPS
        ],
        "timeline": [{"at": at, "evidence_id": ev, "event": txt} for at, ev, txt in TIMELINE],
        "expected_visible_default": sorted(e["id"] for e in EVIDENCE if not e["restricted"]),
        "expected_hidden_default": sorted(e["id"] for e in EVIDENCE if e["restricted"]),
        "expected_citations": CITATION_ORDER,
        "expected_verdicts": {v["evidence_id"]: v["verdict"] for v in VERDICTS},
    }, dry)

    # -- retrieval-presets.json --------------------------------------------
    presets = {}
    for rid, run in runs.items():
        if run["preset"].startswith("agent") or run["preset"] == "canonical":
            continue
        presets[run["preset"]] = {
            "run_id": rid,
            "label": run["label"],
            "query": run["query"],
            "request": {
                "query": run["query"],
                "principal": PRINCIPAL_WORKSHOP,
                "filters": {"cluster_id": "checkout-prod-01"},
                "controls": DEFAULT_CONTROLS,
            },
            "expected_fused_order": [r["evidence_id"] for r in
                                     sorted(run["candidates"], key=lambda r: r["fused_rank"])],
            "expected_arm_positions": {
                r["evidence_id"]: {"text": r["text_position"],
                                   "vector": r["vector_position"],
                                   "fuzzy": r["fuzzy_position"]}
                for r in sorted(run["candidates"], key=lambda r: r["fused_rank"])
            },
        }
    write(ROOT / "retrieval-presets.json", presets, dry)

    # -- runs/*.json (replayable receipts, including the missing RUN-7000) --
    for rid, run in runs.items():
        receipt = {
            "contract_version": CONTRACT_VERSION,
            "run_id": rid,
            "preset": run["preset"],
            "query": run["query"],
            "principal": run["principal"],
            "filters": {"cluster_id": "checkout-prod-01"},
            "controls": run["controls"],
            "candidate_count": len(run["candidates"]),
            "candidates": [{k: v for k, v in r.items() if k != "rrf_terms"}
                           for r in sorted(run["candidates"], key=lambda r: r["fused_rank"])],
            "rrf_terms": {r["evidence_id"]: r["rrf_terms"] for r in run["candidates"]},
            "stage_timings_illustrative": STAGE_TIMINGS,
        }
        if rid == "RUN-7000":
            receipt |= {
                "answer": ANSWER,
                "synthesis_mode": "extractive",
                "citations": cites,
                "verdicts": VERDICTS,
                "relationships": [
                    {"source_id": s, "target_id": t, "relationship": rel, "origin": o,
                     "confidence": conf, "method": m}
                    for s, t, rel, o, conf, m in RELATIONSHIPS
                    if not EV_BY_ID[t]["restricted"] and not EV_BY_ID[s]["restricted"]
                ],
                "timeline": [{"at": at, "evidence_id": ev, "event": txt}
                             for at, ev, txt in TIMELINE],
                "evaluation": {"modes": EVAL_MODES, "archetypes": EVAL_ARCHETYPES,
                               "traversal": EVAL_TRAVERSAL},
            }
        write(ROOT / "runs" / f"{rid}.json", receipt, dry)

    # -- captures/*.json ---------------------------------------------------
    # Rerank is OFF, so the parity path needs no Bedrock call and runs offline.
    body = {
        "contract_version": CONTRACT_VERSION,
        "candidate_count": len(canonical["candidates"]),
        "candidates": [{k: v for k, v in r.items() if k != "rrf_terms"}
                       for r in sorted(canonical["candidates"], key=lambda r: r["fused_rank"])],
        "citations": cites,
        "verdicts": VERDICTS,
        "hidden_by_acl_count": 1,
    }
    transports = [
        ("http", {"transport": "http", "request_id": "req-http-1", "run_id": "RUN-HTTP-001",
                  "latency_ms": 86.1, "tool_name": "search_evidence"}),
        ("mcp", {"transport": "stdio_mcp", "request_id": "req-mcp-1", "run_id": "RUN-MCP-001",
                 "latency_ms": 88.3, "tool_name": "search_evidence"}),
        ("agentcore", {"transport": "agentcore_gateway", "request_id": "req-ac-1",
                       "run_id": "RUN-AC-001", "latency_ms": 102.4,
                       "transport_trace_id": "trace-ac-1",
                       "tool_name": "verity-openapi-tools___search_evidence"}),
    ]
    for name, envelope in transports:
        write(ROOT / "captures" / f"{name}.json", {**envelope, **body}, dry)

    # -- tool-parity-golden.json -------------------------------------------
    write(ROOT / "tool-parity-golden.json", {
        "contract_version": CONTRACT_VERSION,
        "tool": "search_evidence",
        "gateway_target_name": "verity-openapi-tools",
        "gateway_tool_name": "verity-openapi-tools___search_evidence",
        "query": canonical["query"],
        "principal": PRINCIPAL_WORKSHOP,
        "controls": canonical["controls"],
        "candidate_order": [r["evidence_id"] for r in
                            sorted(canonical["candidates"], key=lambda r: r["fused_rank"])],
        "positions": {
            r["evidence_id"]: {"text": r["text_position"], "vector": r["vector_position"],
                               "fuzzy": r["fuzzy_position"]}
            for r in sorted(canonical["candidates"], key=lambda r: r["fused_rank"])
        },
        "rrf_scores": {r["evidence_id"]: r["rrf_score"] for r in canonical["candidates"]},
        "hidden": sorted(e["id"] for e in EVIDENCE if e["restricted"]),
        "citation_ids": CITATION_ORDER,
        "verdicts": {v["evidence_id"]: v["verdict"] for v in VERDICTS},
    }, dry)

    # -- agent/ARUN-8000.json ----------------------------------------------
    write(ROOT / "agent" / f"{AGENT_RUN_ID}.json",
          {"contract_version": CONTRACT_VERSION, **agent,
           "answer": ANSWER, "synthesis_mode": "extractive", "citations": cites,
           "verdicts": VERDICTS}, dry)

    # -- ui-model.json (consumed by the workbench; UI recomputes RRF) -------
    write(ROOT / "ui-model.json", {
        "contract_version": CONTRACT_VERSION,
        "controls_default": DEFAULT_CONTROLS,
        "agent": agent,
        "aurora_buffers": AURORA_BUFFERS,
        "evidence": {e["id"]: {k: e[k] for k in
                     ("kind", "role", "title", "occurred_at", "restricted", "quote")}
                     for e in EVIDENCE},
        "runs": {rid: {"preset": r["preset"], "label": r["label"], "query": r["query"],
                       "arm_orders": r["arm_orders"], "raw": RUNS[rid]["raw"],
                       "rerank": RUNS[rid]["rerank"]} for rid, r in runs.items()},
        "runs_support_lead": {rid: {"arm_orders": r["arm_orders"]} for rid, r in runs_sl.items()},
        "citation_order": CITATION_ORDER,
        "answer": ANSWER,
        "verdicts": VERDICTS,
        "relationships": [
            {"source_id": s, "target_id": t, "relationship": rel, "origin": o,
             "confidence": conf, "method": m} for s, t, rel, o, conf, m in RELATIONSHIPS],
        "timeline": [{"at": at, "evidence_id": ev, "event": txt} for at, ev, txt in TIMELINE],
        "stage_timings_illustrative": STAGE_TIMINGS,
        "evaluation": {"modes": EVAL_MODES, "archetypes": EVAL_ARCHETYPES,
                       "traversal": EVAL_TRAVERSAL},
        "tools": ["decompose_question", "search_evidence", "follow_evidence_links",
                  "compare_sources", "explain_ranking", "synthesize_cited_answer",
                  "answer_with_citations"],
        "gateway_target_name": "verity-openapi-tools",
    }, dry)

    print(("CHECK" if dry else "WROTE") + f" -- contract {CONTRACT_VERSION}")
    for c in checks:
        print("  ok  " + c)
    print(f"\n  canonical fused order: "
          f"{' > '.join(r['evidence_id'] for r in sorted(canonical['candidates'], key=lambda r: r['fused_rank']))}")
    print(f"  normalized body digest: {digest(body)}")


if __name__ == "__main__":
    main()
