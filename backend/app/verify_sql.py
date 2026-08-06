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
  result shape the batch query uses. The batch and element statements share their
  SELECT/FROM/JOIN block, so their columns cannot diverge; the element replays by
  its own natural key (``edge_key`` for an edge, ``evidence_id`` for an event),
  which is unique, so the replay returns exactly the displayed row.
* **No run-bound reproduction** - the live EXPLAIN plan and the evaluation
  leaderboard are a live capture and a harness aggregate; they carry an honest
  label instead of a verify affordance, never a decorative SQL string.

Named binds (``%(name)s``) keep each descriptor self-describing and let the gate
replay it with a plain dict.

``rendered`` is a plain read-only transaction around the SELECT. The workshop
uses one fixed visibility scope, so the descriptor never changes database role.
"""

from __future__ import annotations

from typing import Any

from psycopg import sql

from .config import get_settings

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

# Observed-window hand-off. The window is a single run_id-bound row; the optional
# lock-analysis link is composed from it plus deployment config, so the
# reproducible value on screen is the window itself.
OBSERVABILITY_REF_SQL = (
    "SELECT run_id, db_resource_id, window_start, window_end, wait_event,\n"
    "       sql_digest, captured_at\n"
    "FROM proof.observability_refs\n"
    "WHERE run_id = %(run_id)s"
)

# --- Panel grain: supervised execution --------------------------------------
# The verdict calls proof.autonomy_readiness() directly. Reimplementing its
# eligibility rules here would create a second, drift-prone source of truth.
ACTION_PROPOSAL_SQL = (
    "SELECT proposal_id, agent_run_id, run_id, action_type, target_schema,\n"
    "       target_table, index_method, is_unique, key_columns,\n"
    "       included_columns, predicate, proposed_fingerprint, proposed_sql,\n"
    "       proposed_sql_sha256, preconditions, expected_effect, rollback_sql,\n"
    "       rollback_guidance, statement_timeout, lock_timeout, created_at\n"
    "FROM proof.action_proposals\n"
    "WHERE run_id = %(run_id)s\n"
    "ORDER BY created_at DESC, proposal_id DESC"
)

ACTION_EXECUTION_SQL = (
    "WITH selected_proposal AS (\n"
    "  SELECT proposal_id\n"
    "  FROM proof.action_proposals\n"
    "  WHERE run_id = %(run_id)s\n"
    "  ORDER BY created_at DESC, proposal_id DESC\n"
    "  LIMIT 1\n"
    ")\n"
    "SELECT execution.execution_id, execution.proposal_id, execution.run_id,\n"
    "       execution.approved_by, execution.approved_at,\n"
    "       observed_index_definition, observed_fingerprint,\n"
    "       fingerprint_matches, outcome, outcome_detail, started_at,\n"
    "       completed_at, plan_before_checkpoint, plan_after_checkpoint,\n"
    "       wave_b_capture_id, wave_b_ingest_id\n"
    "FROM proof.action_executions execution\n"
    "JOIN selected_proposal proposal\n"
    "  ON proposal.proposal_id = execution.proposal_id\n"
    # Keep the same ordering proof.autonomy_readiness() uses: two attempts can
    # share approved_at, and the panel must describe the attempt it evaluated.
    "ORDER BY execution.approved_at DESC, execution.recorded_seq DESC"
)

AUTONOMY_VERDICT_SQL = (
    "SELECT p.proposal_id,\n"
    "       v.pre_execution_eligible,\n"
    "       v.pre_execution_reasons,\n"
    "       v.post_execution_validated,\n"
    "       v.post_execution_reasons\n"
    "FROM proof.action_proposals p\n"
    "CROSS JOIN proof.autonomy_readiness(p.proposal_id) v\n"
    "WHERE p.run_id = %(run_id)s\n"
    "ORDER BY p.created_at DESC, p.proposal_id DESC"
)

PROPOSAL_CITATION_SQL = (
    "SELECT link.citation_number, link.claim, citation.source_uri,\n"
    "       citation.source_revision, citation.quote_text, validation.is_valid,\n"
    "       validation.issue\n"
    "FROM proof.action_proposal_citations link\n"
    "JOIN proof.action_proposals proposal\n"
    "  ON proposal.proposal_id = link.proposal_id\n"
    " AND proposal.run_id = link.run_id\n"
    "LEFT JOIN proof.answer_citations citation\n"
    "  ON citation.run_id = link.run_id\n"
    " AND citation.citation_number = link.citation_number\n"
    "LEFT JOIN proof.validate_answer_citations(proposal.run_id) validation\n"
    "  ON validation.citation_number = link.citation_number\n"
    "WHERE link.proposal_id = %(proposal_id)s\n"
    "ORDER BY link.citation_number"
)

# --- Panel grain: corpus distribution ----------------------------------------
# The diagnostics endpoint executes this exact statement and publishes the same
# descriptor. Wave provenance is resolved by v_corpus_distribution itself.
CORPUS_DISTRIBUTION_SQL = "SELECT * FROM retrieval.v_corpus_distribution"

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
    "JOIN evidence.evidence_items from_item\n"
    "  ON from_item.evidence_id = edge.from_evidence_id\n"
    "JOIN evidence.evidence_items to_item\n"
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


PERSONAS: tuple[str, ...] = ("app_engineer", "dba", "auditor")


def persona_role(persona: str) -> str:
    """Map a persona to its database role.

    Duplicated from backend.app.db by design: this module is pure string
    construction and is imported by the MCP-facing tool layer, so it must not
    pull in the connection pool. test_verify_sql.py asserts the two agree.

    Args:
        persona: One of PERSONAS.

    Returns:
        The role name the envelope will ``SET LOCAL ROLE`` to.

    Raises:
        ValueError: The persona is not one of the three bound values.
    """
    if persona not in PERSONAS:
        raise ValueError(
            f"unknown persona {persona!r}; expected one of {', '.join(PERSONAS)}"
        )
    return f"persona_{persona}"


def _render(
    statement: str, binds: dict[str, Any], set_role: str | None
) -> str:
    """Render the copy-pasteable envelope for a human (A3).

    The statement is parameterized for psycopg; a paste has no bind mechanism, so
    the values are inlined here — quoted with psycopg's own literal quoting, not
    string formatting, because a bind value can contain a quote.

    ROLLBACK, always: the paste is read-only and idempotent, so a participant can
    run it in the middle of anything without consequence.
    """
    inlined = statement
    for name, value in binds.items():
        inlined = inlined.replace(f"%({name})s", sql.Literal(value).as_string(None))
    body = inlined.strip().rstrip(";")
    identity_line = f"{set_role};\n" if set_role else ""
    return f"BEGIN;\n{identity_line}{body};\nROLLBACK;"


def _descriptor(
    statement: str,
    binds: dict[str, Any],
    persona: str,
) -> dict[str, Any]:
    """Return one ``_verify_sql`` descriptor.

    Four fields, two audiences. ``statement`` + ``binds`` are what a machine
    executes (G-13 replays them and diffs against the API JSON). ``set_role`` is
    the one identity statement the app issued, which the replayer must issue too;
    it is null in core mode, where the app issues none. ``rendered`` is the
    pasteable envelope a participant takes to psql.

    Keeping ``statement`` single and parameterized is deliberate: a multi-statement
    string cannot be client-side bound and yields only its first result set, so a
    replayer would silently verify nothing.

    Args:
        statement: One parameterized SELECT.
        binds: Its named parameters.
        persona: The persona whose rows this panel showed.

    Returns:
        The descriptor dict serialized into the API payload as ``_verify_sql``.
    """
    role = persona_role(persona)
    set_role = (
        f"SET LOCAL ROLE {role}"
        if get_settings().workbench_security_enabled
        else None
    )
    return {
        "statement": statement,
        "binds": binds,
        "set_role": set_role,
        "rendered": _render(statement, binds, set_role),
    }


def receipt_verify_sql(run_id: str, persona: str) -> dict[str, dict[str, Any]]:
    """Return the four panel-grain descriptors for a run receipt.

    Args:
        run_id: The run whose receipt is being rendered.
        persona: The persona whose rows this receipt showed. Required, never
            defaulted: a defaulted persona would let a panel emit an
            ``app_engineer`` envelope for rows a ``dba`` fetched.

    Returns:
        A ``panel -> descriptor`` map for the run, candidates, stages, and answer
        panels, each replayable with ``{"run_id": run_id}``.
    """
    binds = {"run_id": run_id}
    return {
        "run": _descriptor(RUN_RECEIPT_SQL, binds, persona),
        "candidates": _descriptor(CANDIDATE_RECEIPT_SQL, binds, persona),
        "stages": _descriptor(STAGE_RECEIPT_SQL, binds, persona),
        "answer": _descriptor(ANSWER_RECEIPT_SQL, binds, persona),
    }


def supervision_verify_sql(
    run_id: str,
    persona: str,
    proposal_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Return panel-grain descriptors for a supervised execution record.

    ``proposal_id`` is supplied only after the reader has selected the proposal
    displayed by this run. Citation links are proposal-grain, while the other
    three panels are run-grain.
    """
    binds = {"run_id": run_id}
    descriptors = {
        "proposal": _descriptor(ACTION_PROPOSAL_SQL, binds, persona),
        "execution": _descriptor(ACTION_EXECUTION_SQL, binds, persona),
        "verdict": _descriptor(AUTONOMY_VERDICT_SQL, binds, persona),
    }
    if proposal_id is not None:
        descriptors["citations"] = _descriptor(
            PROPOSAL_CITATION_SQL,
            {"proposal_id": proposal_id},
            persona,
        )
    return descriptors


def corpus_distribution_verify_sql(persona: str) -> dict[str, Any]:
    """Return the descriptor reproducing the live Corpus distribution panel."""
    return _descriptor(CORPUS_DISTRIBUTION_SQL, {}, persona)


def edge_verify_sql(edge_key: str, persona: str) -> dict[str, Any]:
    """Return the element-grain descriptor reproducing one graph edge.

    Args:
        edge_key: The edge's natural key.
        persona: The persona whose rows this panel showed. Required, never
            defaulted.
    """
    return _descriptor(EVIDENCE_EDGE_VERIFY_SQL, {"edge_key": edge_key}, persona)


def event_verify_sql(evidence_id: str, persona: str) -> dict[str, Any]:
    """Return the element-grain descriptor reproducing one timeline event.

    Args:
        evidence_id: The event's evidence id.
        persona: The persona whose rows this panel showed. Required, never
            defaulted.
    """
    return _descriptor(
        TIMELINE_EVENT_VERIFY_SQL, {"evidence_id": str(evidence_id)}, persona
    )
