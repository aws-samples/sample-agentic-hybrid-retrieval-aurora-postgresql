"""Canonical Orion narrative — the single source of truth for the seed.

Every string here matches the five AuraLens mockups (and the React UI in
frontend/src/main.tsx) byte-for-byte. The generator emits these into Aurora so
the API returns the exact answer, the exact six citations, the exact trail, and
the exact diagnostics numbers the demo shows.

Divergences from the original static mockups (intentional, flagged in the
README): the six connected systems are Slack, Jira, Confluence, Salesforce, and
GitHub (ServiceNow dropped); the former ServiceNow INC-0012345 citation is now a
Jira ops ticket ORION-1489 surfaced primarily by full-text search; the corpus is
150 objects, symmetric 30 per system.
"""
from __future__ import annotations

# --- corpus shape --------------------------------------------------------------

SYSTEMS = ["slack", "jira", "confluence", "salesforce", "github"]
PER_SYSTEM = 30
CORPUS_TOTAL = len(SYSTEMS) * PER_SYSTEM  # 150

CANONICAL_QUESTION = "Why did Orion slip?"
CANONICAL_RUN_SLUG = "rr_7f3a9c"

# Fixed timestamps (no Date.now() anywhere — everything is reproducible).
RUN_FIRED_AT = "2026-07-09T09:14:07-04:00"
SEED_STAMP = "2026-07-09T00:00:00-04:00"

# --- the six cited objects (the golden thread) ---------------------------------
# order == citation number. external_id is the join key everywhere.

CITED = [
    {
        "n": 1,
        "source_system": "slack",
        "source_type": "Slack thread",
        "external_id": "SLACK-000271",
        "title": "Decision: Orion GA moves Jul 1 to Jul 15",
        "snippet": (
            "After the readiness review, we're making the call. Orion GA moves from July 1 to "
            "July 15. ORION-1473 replication lag is the sole gating item; hotfix path is "
            "partitioned WAL shipping. CS to notify Acme before EOD."
        ),
        "status": "Decision",
        "priority": "P1",
        "owner": "Priya Mehta",
        "owner_team": "Release Engineering",
        "account_name": "Acme Corp",
        "project_key": "ORION",
        "component": "#proj-orion",
        "environment": "prod",
        "updated_at": "2026-06-23T16:12:00-04:00",
        "created_at": "2026-06-23T16:12:00-04:00",
        "source_authority": 0.90,
        "final_score": 0.93,
        "text_rank": 0.02,
        "vector_score": 0.98,
        "trigram_score": None,
        "rrf_score": 0.0325,
        "cite_meta": "SLACK · #proj-orion · JUN 23 · final 0.93",
        "cite_why": 'The decision itself — answers "what did the team decide."',
    },
    {
        "n": 2,
        "source_system": "jira",
        "source_type": "Issue",
        "external_id": "ORION-1473",
        "title": "ORION-1473 — Cross-region replication lag exceeds 90s in events pipeline",
        "snippet": (
            "P1 blocker for ORION-1450 GA cutover. Consumers in eu-west-1 fall behind under peak "
            "write load; freshness SLO for the readiness gate is 15s. Root cause traced to "
            "single-stream WAL shipping; fix is regional partitioning."
        ),
        "status": "Resolved Jul 3",
        "priority": "P1",
        "owner": "Rafael Ortiz",
        "owner_team": "Events Platform",
        "account_name": None,
        "project_key": "ORION",
        "component": "Events pipeline",
        "environment": "prod",
        "updated_at": "2026-07-03T10:20:00-04:00",
        "created_at": "2026-06-12T09:41:00-04:00",
        "source_authority": 0.88,
        "final_score": 0.89,
        "text_rank": 0.96,
        "vector_score": 0.88,
        "trigram_score": 0.71,
        "rrf_score": 0.0322,
        "cite_meta": "JIRA · P1 · JUN 12 – JUL 3 · final 0.89",
        "cite_why": "Root cause and timeline; blocks the GA cutover story.",
    },
    {
        "n": 3,
        "source_system": "salesforce",
        "source_type": "Case",
        "external_id": "CASE-0012345",
        "title": "CASE-0012345 — Acme Corp go-live commitment at risk",
        "snippet": (
            "Contractual go-live July 8 per MSA addendum. CSM note: informed champion of Orion "
            "slip; negotiating revised date of July 22 with success-plan credit. Renewal ARR "
            "$1.2M is flagged as commitment impact."
        ),
        "status": "Mitigating",
        "priority": "Tier 1",
        "owner": "Dana Whitfield",
        "owner_team": "Customer Engineering",
        "account_name": "Acme Corp",
        "project_key": "ORION",
        "component": None,
        "environment": None,
        "updated_at": "2026-06-26T11:05:00-04:00",
        "created_at": "2026-06-24T09:00:00-04:00",
        "source_authority": 0.86,
        "final_score": 0.87,
        "text_rank": 0.72,
        "vector_score": 0.94,
        "trigram_score": None,
        "rrf_score": 0.0310,
        "cite_meta": "SALESFORCE · TIER 1 · JUN 26 · final 0.87",
        "cite_why": "The impacted contractual commitment and its mitigation.",
    },
    {
        "n": 4,
        "source_system": "confluence",
        "source_type": "Runbook",
        "external_id": "PAGE-2112",
        "title": "Orion Release Readiness Runbook — gate criteria and sign-off",
        "snippet": (
            "Gate 3 data freshness requires replication lag p99 ≤ 15s across regions for 72h. "
            "Jun 18 check: FAILED — lag p99 at 94s in eu-west-1. Per policy, GA date slips until "
            "gate passes."
        ),
        "status": "Published",
        "priority": "Policy",
        "owner": "Release Engineering",
        "owner_team": "Release Engineering",
        "account_name": None,
        "project_key": "ORION",
        "component": "Release gates",
        "environment": None,
        "updated_at": "2026-06-18T14:00:00-04:00",
        "created_at": "2026-05-02T10:00:00-04:00",
        "source_authority": 0.82,
        "final_score": 0.82,
        "text_rank": 0.90,
        "vector_score": 0.72,
        "trigram_score": None,
        "rrf_score": 0.0295,
        "cite_meta": "CONFLUENCE · GATE 3 · JUN 18 · final 0.82",
        "cite_why": "The policy mechanism that forced the date slip.",
    },
    {
        "n": 5,
        "source_system": "jira",
        "source_type": "Ops ticket",
        "external_id": "ORION-1489",
        "title": "ORION-1489 — replication_lag_seconds > 60 paging in prod (eu-west-1)",
        "snippet": (
            "Ops ticket auto-filed by the alerting bot: replication_lag_seconds > 60 paging since "
            "Jun 20 02:10 UTC in eu-west-1. Full-text match on the exact metric name and region. "
            "Linked to ORION-1473 as the root cause; mitigated by consumer scale-out, resolved "
            "after PR #1287."
        ),
        "status": "Resolved",
        "priority": "Sev2",
        "owner": "SRE on-call",
        "owner_team": "Events Platform",
        "account_name": "Acme Corp",
        "project_key": "ORION",
        "component": "Events pipeline",
        "environment": "prod",
        "updated_at": "2026-06-20T02:10:00+00:00",
        "created_at": "2026-06-20T02:10:00+00:00",
        "source_authority": 0.78,
        "final_score": 0.78,
        "text_rank": 0.94,
        "vector_score": 0.66,
        "trigram_score": 0.64,
        "rrf_score": 0.0271,
        "cite_meta": "JIRA · SEV2 · JUN 20 · final 0.78",
        "cite_why": "Production paging that corroborates the root cause — surfaced by full-text search.",
    },
    {
        "n": 6,
        "source_system": "github",
        "source_type": "Pull request",
        "external_id": "PR-1287",
        "title": "PR #1287 — events: partition WAL shipping by region",
        "snippet": (
            "Merged Jul 2. Fixes ORION-1473. Splits the single WAL stream into per-region "
            "partitions with bounded consumer groups; soak test shows replication lag p99 8s, "
            "down from 94s."
        ),
        "status": "Merged",
        "priority": "Change",
        "owner": "rafael-ortiz",
        "owner_team": "Events Platform",
        "account_name": None,
        "project_key": "ORION",
        "component": "orion/events-pipeline",
        "environment": "prod",
        "updated_at": "2026-07-02T19:47:00-04:00",
        "created_at": "2026-06-28T13:22:00-04:00",
        "source_authority": 0.80,
        "final_score": 0.74,
        "text_rank": 0.48,
        "vector_score": 0.76,
        "trigram_score": None,
        "rrf_score": 0.0253,
        "cite_meta": "GITHUB · MERGED JUL 2 · final 0.74",
        "cite_why": "The fix that unblocked the gate re-run.",
    },
]

# --- cross-system links (the trail: traverse_links over object_links) ----------
# from_external_id -> to_external_id, link_type, confidence

LINKS = [
    ("ORION-1473", "SLACK-000271", "referenced_by", 0.95),
    ("SLACK-000271", "ORION-1473", "references", 0.95),
    ("ORION-1473", "PAGE-2112", "gated_by", 0.92),
    ("PAGE-2112", "ORION-1473", "references", 0.92),
    ("ORION-1489", "ORION-1473", "caused_by", 0.93),
    ("ORION-1473", "ORION-1489", "caused", 0.93),
    ("SLACK-000271", "CASE-0012345", "impacts", 0.90),
    ("CASE-0012345", "SLACK-000271", "referenced_by", 0.90),
    ("PR-1287", "ORION-1473", "fixes", 0.96),
    ("ORION-1473", "PR-1287", "fixed_by", 0.96),
    ("PR-1287", "ORION-1489", "resolves", 0.90),
]

# --- the answer (ops.agent_answers.answer jsonb) -------------------------------
# RichToken arrays mirror frontend canonicalAnswer exactly:
#   {"text": ...} | {"b": ...} | {"hl": ...} | {"cite": n}

ANSWER = {
    "lead": [
        {"text": "Orion's GA slipped two weeks — "},
        {"hl": "July 1 to July 15"},
        {"text": " — because a P1 replication-lag blocker failed the release-readiness gate. The team decided the slip in Slack on June 23, and one contractual customer commitment, Acme Corp, is being renegotiated."},
    ],
    "why": [
        {"b": "Why it's delayed."},
        {"text": " The events pipeline developed cross-region replication lag of up to 94 seconds against a 15-second freshness SLO, filed as P1 "},
        {"b": "ORION-1473"},
        {"text": " on June 12 "},
        {"cite": 2},
        {"text": ". The Release Readiness Runbook's Gate 3 formally failed on June 18, and policy requires the GA date to slip until the gate passes "},
        {"cite": 4},
        {"text": ". The same root cause set off Sev2 paging ticket "},
        {"b": "ORION-1489"},
        {"text": " in production two days later "},
        {"cite": 5},
        {"text": "."},
    ],
    "decided": [
        {"b": "What the team decided."},
        {"text": " After the readiness review, engineering lead Priya Mehta recorded the decision in "},
        {"b": "#proj-orion"},
        {"text": " on June 23: GA moves from July 1 to July 15, partitioned WAL shipping is the hotfix path, and CS notifies Acme the same day "},
        {"cite": 1},
        {"text": ". The fix, "},
        {"b": "PR #1287"},
        {"text": ", merged July 2 and cut lag p99 from 94s to 8s "},
        {"cite": 6},
        {"text": "."},
    ],
    "impacted": [
        {"b": "Which commitments are impacted."},
        {"text": " One contractual commitment is directly affected: Acme Corp's go-live, promised for July 8 under an MSA addendum "},
        {"cite": 3},
        {"text": ". The CSM is renegotiating to July 22 with a success-plan credit; the $1.2M renewal is flagged but the exec sponsor is engaged."},
    ],
    "quote": {
        "text": '"We\'re making the call: Orion GA moves from July 1 to July 15. ORION-1473 is the sole gating item — hotfix path is partitioned WAL shipping. CS to notify Acme before EOD."',
        "attr": "Priya Mehta · #proj-orion · Jun 23, 2026 · 4:12 PM · cited as [1]",
    },
}

ANSWER_CONFIDENCE = 0.92
ANSWER_SOURCE_COUNT = 6
ANSWER_SYSTEM_COUNT = 5

# --- the plan (six tool calls; ops.retrieval_run_metrics.metadata) -------------

PLAN = [
    {"num": "1", "fn": "search_evidence", "args": "(\"orion delay root cause\", systems: jira+slack+confluence, window: 60d)", "desc": "Question decomposed; lexical + semantic + fuzzy retrieval run in parallel inside Aurora.", "res": "12 strong candidates · top: ORION-1473"},
    {"num": "2", "fn": "traverse_links", "args": "(from: ORION-1473, edges: blocks · fixes · caused-by · gates)", "desc": "Followed stored object_links across systems to the gate check, the incident, and the fix.", "res": "5 linked objects · 9 edges"},
    {"num": "3", "fn": "search_evidence", "args": "(\"orion customer commitments go-live\", systems: salesforce)", "desc": "Targeted pass for commitment language scoped to accounts referencing Orion.", "res": "3 candidates · 1 contractual"},
    {"num": "4", "fn": "compare_sources", "args": "(slack decision ↔ readiness runbook ↔ jira timeline)", "desc": "Checked the decision against gate policy and issue history for contradictions.", "res": "consistent · no conflicts found"},
    {"num": "5", "fn": "explain_result", "args": "(top 6)", "desc": "Captured per-candidate ranking signals for the diagnostics view.", "res": "signals stored on retrieval_candidates"},
    {"num": "6", "fn": "synthesize_with_citations", "args": "(6 sources, style: brief)", "desc": "Composed the answer; every claim bound to a citation row in Aurora.", "res": "9 claims · 9 citations · confidence 0.92"},
]

# --- diagnostics metrics (ops.retrieval_run_metrics) ---------------------------

PROFILE = "hybrid-rrf-final-v1"
EMBEDDING_MODEL = "cohere.embed-v4"
EMBEDDING_DIM = 1024
INDEX_SPEC = "HNSW m=16 ef=64"
TOTAL_LATENCY_MS = 341
P50_LATENCY_MS = 318
RRF_K = 60
RANKER_WEIGHTS = [1.0, 1.0, 0.5]
RERANK_CUT = 0.55
RERANKED_COUNT = 24

FUNNEL = {"fetched": CORPUS_TOTAL, "deduped": 92, "fused": 24, "above_cut": 12, "cited": 6}

STAGE_TIMINGS = [
    {"stage": "parse + plan", "ms": 12},
    {"stage": "lexical · FTS", "ms": 38},
    {"stage": "semantic · vector", "ms": 54},
    {"stage": "fuzzy · trgm", "ms": 21},
    {"stage": "fusion · RRF", "ms": 6},
    {"stage": "answer assembly", "ms": 210},
]

# Ten diagnostics rows: [rank, system, label, fts_pos, vec_pos, trgm, rrf, final_score, cited]
# Rows 1–6 are the cited golden thread; 7–10 are near-miss / below-cut objects.
DIAGNOSTICS_ROWS = [
    ["1", "slack", "Decision: GA moves Jul 1 → 15", "#2", "#1", "—", ".0325", "0.93", "✓ [1]"],
    ["2", "jira", "ORION-1473 replication lag", "#1", "#3", ".71", ".0322", "0.89", "✓ [2]"],
    ["3", "salesforce", "CASE-0012345 Acme go-live", "#6", "#2", "—", ".0310", "0.87", "✓ [3]"],
    ["4", "confluence", "Release Readiness Runbook", "#3", "#7", "—", ".0295", "0.82", "✓ [4]"],
    ["5", "jira", "ORION-1489 lag paging (FTS hit)", "#4", "#14", ".64", ".0271", "0.78", "✓ [5]"],
    ["6", "github", "PR #1287 partition WAL shipping", "#11", "#6", "—", ".0253", "0.74", "✓ [6]"],
    ["7", "slack", 'Standup thread "GA checklist"', "#7", "#12", "—", ".0231", "0.58", "above cut · unused"],
    ["8", "confluence", "Postmortem: May backpressure", "#14", "#9", "—", ".0212", "0.51", "below cut"],
    ["9", "jira", "ORION-1502 dashboards polish", "#8", "#15", ".58", ".0198", "0.38", "below cut"],
    ["10", "github", "PR #1244 consumer scale-out (reverted)", "—", "#8", ".66", ".0186", "0.34", "below cut"],
]

# --- near-miss objects (diagnostics rows 7–10, real objects, below the cut) ----
# These are cited nowhere but must exist so the funnel + diagnostics table are
# backed by real rows. External IDs are stable and system-appropriate.

NEAR_MISS = [
    {
        "source_system": "slack",
        "source_type": "Slack thread",
        "external_id": "SLACK-000288",
        "title": 'Standup thread "GA checklist"',
        "snippet": "Daily standup rollup for the Orion GA checklist. Owners confirm soak status, dashboards, and customer comms. No decision recorded here — see #proj-orion for the call.",
        "status": "Open",
        "priority": "P3",
        "owner": "Mina Lin",
        "owner_team": "Release Engineering",
        "project_key": "ORION",
        "component": "#proj-orion",
        "environment": "prod",
        "updated_at": "2026-06-24T09:15:00-04:00",
        "created_at": "2026-06-24T09:15:00-04:00",
        "source_authority": 0.68,
    },
    {
        "source_system": "confluence",
        "source_type": "Postmortem",
        "external_id": "PAGE-2044",
        "title": "Postmortem: May backpressure incident",
        "snippet": "Retrospective on the May events-pipeline backpressure. Consumer lag under load; remediation was a temporary scale-out. Related to but predates the ORION-1473 root cause.",
        "status": "Published",
        "priority": "Policy",
        "owner": "Release Engineering",
        "owner_team": "Release Engineering",
        "project_key": "ORION",
        "component": "Events pipeline",
        "environment": "prod",
        "updated_at": "2026-05-14T10:00:00-04:00",
        "created_at": "2026-05-14T10:00:00-04:00",
        "source_authority": 0.66,
    },
    {
        "source_system": "jira",
        "source_type": "Task",
        "external_id": "ORION-1502",
        "title": "ORION-1502 — dashboards polish for GA readiness board",
        "snippet": "Cosmetic polish on the readiness dashboards ahead of GA. Low priority; not on the critical path for the replication-lag gate.",
        "status": "In Progress",
        "priority": "P3",
        "owner": "Sam Ridley",
        "owner_team": "Release Engineering",
        "project_key": "ORION",
        "component": "Dashboards",
        "environment": "stage",
        "updated_at": "2026-06-29T15:40:00-04:00",
        "created_at": "2026-06-27T11:00:00-04:00",
        "source_authority": 0.60,
    },
    {
        "source_system": "github",
        "source_type": "Pull request",
        "external_id": "PR-1244",
        "title": "PR #1244 — events: consumer scale-out (reverted)",
        "snippet": "Attempted mitigation by scaling out consumers. Reverted after soak showed the lag returned under peak write load; superseded by regional WAL partitioning in PR #1287.",
        "status": "Closed",
        "priority": "Change",
        "owner": "rafael-ortiz",
        "owner_team": "Events Platform",
        "project_key": "ORION",
        "component": "orion/events-pipeline",
        "environment": "prod",
        "updated_at": "2026-06-19T17:30:00-04:00",
        "created_at": "2026-06-17T09:00:00-04:00",
        "source_authority": 0.62,
    },
]

# --- evaluation query + relevance judgments (ops.evaluation_queries) -----------

EVAL_QUERY_ID = "orion-why-slip"
RELEVANCE_JUDGMENTS = [
    ("SLACK-000271", 3, "The decision itself."),
    ("ORION-1473", 3, "Root cause and blocker."),
    ("CASE-0012345", 3, "Impacted contractual commitment."),
    ("PAGE-2112", 3, "Policy that forced the slip."),
    ("ORION-1489", 2, "Corroborating production paging; full-text hit."),
    ("PR-1287", 2, "The fix that unblocked the gate."),
    ("SLACK-000288", 1, "Related standup, no decision."),
    ("PAGE-2044", 1, "Related May postmortem, predates root cause."),
    ("ORION-1502", 0, "Off critical path."),
    ("PR-1244", 0, "Reverted mitigation, superseded."),
]
