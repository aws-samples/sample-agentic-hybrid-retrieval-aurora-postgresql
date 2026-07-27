"""Canonical verify-SQL registry (Law 2 / gate G-13).

Every panel that renders retrieval or proof data publishes a ``_verify_sql``
descriptor - the exact statement the endpoint itself executed, plus its bind
parameters - so a participant can paste it into psql and reproduce the number on
screen. The statement text lives here once; the endpoint imports it to *both*
query Aurora and publish the descriptor. There is no hand-maintained twin to
drift (that drift is the defect G-13 exists to catch).

Grain of reproducibility (SPEC-session Section 6.2):

* **Panel grain** - the receipt family (run / candidates / stages / answer) is
  four single ``run_id``-bound SELECTs; each panel publishes one descriptor.
* **Element grain** - composite panels (graph edges, timeline events) are not one
  SELECT, so each element publishes its own single-key SELECT drawn from the same
  projection the batch query uses. The batch and element statements share their
  SELECT/FROM/JOIN block, so their columns cannot diverge; the element replays by
  its own natural key (``edge_key`` for an edge, ``evidence_id`` for an event),
  which is unique, so the replay returns exactly the displayed row.
* **No run-bound reproduction** - the live EXPLAIN plan and the evaluation
  leaderboard are a live capture and a harness aggregate; they carry an honest
  label instead of a verify affordance, never a decorative SQL string.

Named binds (``%(name)s``) keep each descriptor self-describing and let the gate
replay it with a plain dict.
"""

from __future__ import annotations

from typing import Any

# --- Panel grain: the receipt family (explain_ranking_impl) ------------------

RUN_RECEIPT_SQL = "SELECT * FROM proof.v_run_receipts WHERE run_id = %(run_id)s"

CANDIDATE_RECEIPT_SQL = (
    "SELECT *\n"
    "FROM proof.v_candidate_receipts\n"
    "WHERE run_id = %(run_id)s\n"
    "ORDER BY result_rank"
)

STAGE_RECEIPT_SQL = (
    "SELECT stage_ordinal, stage_name, duration_ms, details\n"
    "FROM proof.run_stages\n"
    "WHERE run_id = %(run_id)s\n"
    "ORDER BY stage_ordinal"
)

ANSWER_RECEIPT_SQL = (
    "SELECT * FROM proof.v_answer_receipts WHERE run_id = %(run_id)s"
)

# --- Element grain: graph edges ----------------------------------------------
# One SELECT/FROM/JOIN block shared by the batch query (run_graph) and the
# per-edge verify statement, so their columns are identical by construction.

EVIDENCE_EDGE_SELECT = (
    "SELECT\n"
    "  edge.edge_key,\n"
    "  edge.from_evidence_id,\n"
    "  from_item.external_key AS from_external_key,\n"
    "  edge.to_evidence_id,\n"
    "  to_item.external_key AS to_external_key,\n"
    "  edge.relation,\n"
    "  edge.origin,\n"
    "  edge.confidence,\n"
    "  edge.metadata\n"
    "FROM retrieval.evidence_edges edge\n"
    "JOIN casework.evidence_items from_item\n"
    "  ON from_item.evidence_id = edge.from_evidence_id\n"
    "JOIN casework.evidence_items to_item\n"
    "  ON to_item.evidence_id = edge.to_evidence_id"
)

EVIDENCE_EDGE_BATCH_SQL = (
    f"{EVIDENCE_EDGE_SELECT}\n"
    "WHERE edge.from_evidence_id = ANY(%(ids)s::uuid[])\n"
    "  AND edge.to_evidence_id = ANY(%(ids)s::uuid[])\n"
    "ORDER BY edge.origin, edge.relation, edge.edge_key"
)

EVIDENCE_EDGE_VERIFY_SQL = (
    f"{EVIDENCE_EDGE_SELECT}\nWHERE edge.edge_key = %(edge_key)s"
)

# --- Element grain: timeline events ------------------------------------------

TIMELINE_EVENT_SELECT = (
    "SELECT\n"
    "  document.evidence_id,\n"
    "  document.external_key,\n"
    "  document.evidence_kind,\n"
    "  document.title,\n"
    "  document.source_system,\n"
    "  document.source_revision,\n"
    "  document.cluster_id,\n"
    "  document.incident_id,\n"
    "  document.account_name,\n"
    "  document.severity,\n"
    "  document.occurred_at\n"
    "FROM retrieval.documents document"
)

TIMELINE_EVENT_BATCH_SQL = (
    f"{TIMELINE_EVENT_SELECT}\n"
    "WHERE document.evidence_id = ANY(%(ids)s::uuid[])\n"
    "  AND document.is_current\n"
    "ORDER BY document.occurred_at, document.external_key"
)

TIMELINE_EVENT_VERIFY_SQL = (
    f"{TIMELINE_EVENT_SELECT}\n"
    "WHERE document.evidence_id = %(evidence_id)s\n"
    "  AND document.is_current"
)


def _descriptor(statement: str, binds: dict[str, Any]) -> dict[str, Any]:
    """Return one ``_verify_sql`` descriptor: the statement and its binds."""
    return {"statement": statement, "binds": binds}


def receipt_verify_sql(run_id: str) -> dict[str, dict[str, Any]]:
    """Return the four panel-grain descriptors for a run receipt.

    Args:
        run_id: The run whose receipt is being rendered.

    Returns:
        A ``panel -> descriptor`` map for the run, candidates, stages, and answer
        panels, each replayable with ``{"run_id": run_id}``.
    """
    binds = {"run_id": run_id}
    return {
        "run": _descriptor(RUN_RECEIPT_SQL, binds),
        "candidates": _descriptor(CANDIDATE_RECEIPT_SQL, binds),
        "stages": _descriptor(STAGE_RECEIPT_SQL, binds),
        "answer": _descriptor(ANSWER_RECEIPT_SQL, binds),
    }


def edge_verify_sql(edge_key: str) -> dict[str, Any]:
    """Return the element-grain descriptor reproducing one graph edge."""
    return _descriptor(EVIDENCE_EDGE_VERIFY_SQL, {"edge_key": edge_key})


def event_verify_sql(evidence_id: str) -> dict[str, Any]:
    """Return the element-grain descriptor reproducing one timeline event."""
    return _descriptor(TIMELINE_EVENT_VERIFY_SQL, {"evidence_id": str(evidence_id)})
