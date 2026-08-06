"""The agent's structured, human-reviewed action proposal.

This module creates an audit record about the agent's recommendation. It has no
capability to execute DDL: a participant reviews the rendered SQL and runs it
later. The database catalog, not model output, measures every precondition.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


# Bounded constants rather than model-supplied values: an unbounded CREATE INDEX
# on the workshop's 3,000,000-row table is exactly the operational mistake this
# lab teaches participants to avoid.
STATEMENT_TIMEOUT = "5min"
LOCK_TIMEOUT = "5s"
MAX_IDENTIFIER_BYTES = 63

IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
DIRECTIONS = ("asc", "desc")
ACTION_TYPES = ("create_index",)
INDEX_METHODS = ("btree",)

ACTION_PROPOSAL_TOOL_NAME = "record_action_proposal"

ACTION_PROPOSAL_TOOL_SPEC: dict[str, Any] = {
    "toolSpec": {
        "name": ACTION_PROPOSAL_TOOL_NAME,
        "description": (
            "Record the one database change your cited answer recommends. You "
            "never execute it: a human reviews the proposal and runs it "
            "themselves. Recommend exactly one plain index."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "action_type": {
                        "type": "string",
                        "enum": list(ACTION_TYPES),
                    },
                    "target_schema": {"type": "string"},
                    "target_table": {"type": "string"},
                    "index_method": {
                        "type": "string",
                        "enum": list(INDEX_METHODS),
                    },
                    "is_unique": {"type": "boolean"},
                    "key_columns": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {"type": "string"},
                                "direction": {
                                    "type": "string",
                                    "enum": list(DIRECTIONS),
                                },
                            },
                            "required": ["column", "direction"],
                        },
                        "description": (
                            "Key columns in index order. Order is semantically "
                            "load-bearing; list columns in the order the index "
                            "should use."
                        ),
                    },
                    "included_columns": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    # A partial-index predicate is deliberately not advertised:
                    # it cannot be fingerprinted consistently against catalog
                    # read-back and would be the only free text rendered into
                    # participant-run DDL. The parser rejects it if supplied.
                    "expected_effect": {
                        "type": "string",
                        "description": (
                            "What the query plan should do differently after the "
                            "human executes the proposal, in one sentence."
                        ),
                    },
                    "supporting_citations": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "citation_number": {"type": "integer"},
                                "claim": {"type": "string"},
                            },
                            "required": ["citation_number", "claim"],
                        },
                        "description": (
                            "Bracketed citation numbers from your cited answer "
                            "that support this recommendation, with the claim "
                            "each citation supports."
                        ),
                    },
                },
                "required": [
                    "action_type",
                    "target_schema",
                    "target_table",
                    "key_columns",
                    "expected_effect",
                    "supporting_citations",
                ],
            }
        },
    }
}


@dataclass(frozen=True)
class IndexKey:
    column: str
    direction: str


@dataclass(frozen=True)
class ProposalFields:
    action_type: str
    target_schema: str
    target_table: str
    index_method: str
    is_unique: bool
    key_columns: tuple[IndexKey, ...]
    included_columns: tuple[str, ...]
    predicate: str | None
    expected_effect: str
    supporting_citations: tuple[dict[str, Any], ...]


def _identifier(value: Any, field: str) -> str:
    """Validate one lower-case, unquoted PostgreSQL identifier."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string, got {type(value).__name__}")
    folded = value.strip().lower()
    if not IDENTIFIER.fullmatch(folded):
        raise ValueError(f"{field} is not a plain SQL identifier: {value!r}")
    if len(folded.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        raise ValueError(f"{field} exceeds {MAX_IDENTIFIER_BYTES} bytes: {value!r}")
    return folded


def _string_list(value: Any, field: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    return value


def parse_proposal_fields(payload: dict[str, Any]) -> ProposalFields:
    """Turn model-supplied structured fields into safe proposal fields.

    Every identifier returned by this function is rendered into DDL a human may
    paste into psql. Quoting does not solve that boundary because quoted names
    change canonical fingerprint semantics, so only plain lower-case identifiers
    are accepted.
    """
    if not isinstance(payload, dict):
        raise ValueError("action proposal must be an object")

    action_type = str(payload.get("action_type") or "").strip().lower()
    if action_type not in ACTION_TYPES:
        raise ValueError(f"unsupported action_type: {action_type!r}")
    index_method = str(payload.get("index_method") or "btree").strip().lower()
    if index_method not in INDEX_METHODS:
        raise ValueError(f"unsupported index_method: {index_method!r}")

    is_unique = payload.get("is_unique", False)
    if not isinstance(is_unique, bool):
        raise ValueError("is_unique must be a boolean")

    raw_keys = payload.get("key_columns")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise ValueError("key_columns must be a non-empty list")
    keys: list[IndexKey] = []
    for position, entry in enumerate(raw_keys, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"key_columns[{position}] must be an object")
        direction = str(entry.get("direction") or "asc").strip().lower()
        if direction not in DIRECTIONS:
            raise ValueError(
                f"key_columns[{position}].direction must be asc or desc, "
                f"got {direction!r}"
            )
        keys.append(
            IndexKey(
                column=_identifier(
                    entry.get("column"),
                    f"key_columns[{position}].column",
                ),
                direction=direction,
            )
        )
    key_names = [key.column for key in keys]
    if len(set(key_names)) != len(key_names):
        raise ValueError(f"key_columns repeats a column: {key_names}")

    included = tuple(
        _identifier(value, f"included_columns[{position}]")
        for position, value in enumerate(
            _string_list(payload.get("included_columns"), "included_columns"),
            start=1,
        )
    )
    if len(set(included)) != len(included):
        raise ValueError(f"included_columns repeats a column: {list(included)}")
    overlap = sorted(set(included) & set(key_names))
    if overlap:
        raise ValueError(
            "included_columns cannot repeat key_columns: " + ", ".join(overlap)
        )

    # A predicate is rejected, not sanitized. PostgreSQL rewrites predicates
    # through pg_get_expr() on catalog read-back, making an identical partial
    # index fingerprint differently from its proposal. It would also be the only
    # unvalidated free-text field interpolated into a DDL statement.
    predicate = payload.get("predicate")
    if predicate is not None and str(predicate).strip():
        raise ValueError(
            "predicate is not supported: a partial-index predicate cannot be "
            "fingerprinted consistently and would reach rendered DDL as free text"
        )

    raw_citations = _string_list(
        payload.get("supporting_citations"),
        "supporting_citations",
    )
    citations: list[dict[str, Any]] = []
    for position, entry in enumerate(raw_citations, start=1):
        if not isinstance(entry, dict):
            continue
        number = entry.get("citation_number")
        claim = str(entry.get("claim") or "").strip()
        if isinstance(number, bool) or not isinstance(number, int) or not claim:
            continue
        citations.append({"citation_number": number, "claim": claim})

    effect = str(payload.get("expected_effect") or "").strip()
    if not effect:
        raise ValueError("expected_effect must not be blank")

    return ProposalFields(
        action_type=action_type,
        target_schema=_identifier(payload.get("target_schema"), "target_schema"),
        target_table=_identifier(payload.get("target_table"), "target_table"),
        index_method=index_method,
        is_unique=is_unique,
        key_columns=tuple(keys),
        included_columns=included,
        predicate=None,
        expected_effect=effect,
        supporting_citations=tuple(citations),
    )


def index_name_for(fields: ProposalFields) -> str:
    """Derive a deterministic index name within PostgreSQL's 63-byte limit."""
    columns = [key.column for key in fields.key_columns]
    while columns:
        name = "_".join(["idx", fields.target_table, *columns])
        if len(name.encode("utf-8")) <= MAX_IDENTIFIER_BYTES:
            return name
        columns.pop()
    return f"idx_{fields.target_table}"[:MAX_IDENTIFIER_BYTES]


def render_create_index(fields: ProposalFields) -> tuple[str, str]:
    """Render `(index_name, ddl)` from validated fields, never model SQL."""
    if fields.predicate:
        raise ValueError("render_create_index received an unsupported predicate")
    index_name = index_name_for(fields)
    keys = ", ".join(
        f"{key.column} {key.direction.upper()}" for key in fields.key_columns
    )
    include = (
        f" INCLUDE ({', '.join(fields.included_columns)})"
        if fields.included_columns
        else ""
    )
    unique = "UNIQUE " if fields.is_unique else ""
    return index_name, (
        f"CREATE {unique}INDEX {index_name}\n"
        f"  ON {fields.target_schema}.{fields.target_table} "
        f"USING {fields.index_method} ({keys}){include};"
    )


def render_rollback(fields: ProposalFields, index_name: str) -> str:
    """Render rollback DDL for the index this module rendered."""
    return f"DROP INDEX IF EXISTS {fields.target_schema}.{index_name};"


def sql_sha256(statement: str) -> str:
    """Return the audit-only hash of exact rendered SQL."""
    return hashlib.sha256(statement.encode("utf-8")).hexdigest()


def propose_action_live(
    question: str,
    answer: str,
    evidence: list[dict[str, Any]],
) -> ProposalFields:
    """Ask Bedrock for structured fields for the recommendation it just made."""
    from .bedrock import get_bedrock_client
    from .config import get_settings
    from .synthesis import evidence_block

    settings = get_settings()
    if settings.bedrock_model_transport != "converse_global_cris":
        raise ValueError(
            "unsupported BEDROCK_MODEL_TRANSPORT; use converse_global_cris"
        )
    if not settings.bedrock_synthesis_model.startswith(
        ("global.", "us.", "eu.", "apac.")
    ):
        raise ValueError(
            "BEDROCK_SYNTHESIS_MODEL must be a cross-region inference profile ID"
        )

    response = get_bedrock_client(
        "bedrock-runtime",
        region=settings.aws_region,
    ).converse(
        modelId=settings.bedrock_synthesis_model,
        system=[
            {
                "text": (
                    "You recommend database changes but never execute them. "
                    "A human reviews the proposal and runs it themselves. Call "
                    "record_action_proposal exactly once with the structured "
                    "fields for the one index your cited answer recommends. "
                    "Cite only bracketed evidence numbers that occur in the "
                    "answer. Do not write SQL: the caller renders it from your "
                    "validated fields."
                )
            }
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            f"Question: {question}\n\n"
                            f"Your cited answer:\n{answer}\n\n"
                            f"Evidence:\n{evidence_block(evidence)}\n\n"
                            "Record the single recommended index."
                        )
                    }
                ],
            }
        ],
        toolConfig={
            "tools": [ACTION_PROPOSAL_TOOL_SPEC],
            "toolChoice": {"tool": {"name": ACTION_PROPOSAL_TOOL_NAME}},
        },
        inferenceConfig={"maxTokens": settings.bedrock_synthesis_max_tokens},
    )
    if response.get("stopReason") == "max_tokens":
        raise ValueError("action proposal reached the configured token limit")
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    for block in blocks:
        tool_use = block.get("toolUse") if isinstance(block, dict) else None
        if tool_use and tool_use.get("name") == ACTION_PROPOSAL_TOOL_NAME:
            return parse_proposal_fields(tool_use.get("input") or {})
    raise ValueError(
        f"model did not call {ACTION_PROPOSAL_TOOL_NAME}; "
        f"stopReason={response.get('stopReason')!r}"
    )


def _value(row: Any, key: str) -> Any:
    """Read one selected scalar from psycopg tuple or dict rows."""
    if isinstance(row, Mapping):
        return row[key]
    return row[0]


def measure_preconditions(
    cursor: Any,
    fields: ProposalFields,
) -> list[dict[str, Any]]:
    """Measure the proposal's preconditions from the live PostgreSQL catalog."""
    qualified = f"{fields.target_schema}.{fields.target_table}"
    cursor.execute(
        "SELECT to_regclass(%s) IS NOT NULL AS table_exists",
        (qualified,),
    )
    table_exists = bool(_value(cursor.fetchone(), "table_exists"))

    required_columns = [
        *(key.column for key in fields.key_columns),
        *fields.included_columns,
    ]
    cursor.execute(
        """
        SELECT count(*) = %(expected)s AS columns_exist
        FROM pg_attribute attribute
        WHERE attribute.attrelid = to_regclass(%(qualified)s)
          AND NOT attribute.attisdropped
          AND attribute.attnum > 0
          AND attribute.attname = ANY(%(columns)s)
        """,
        {
            "qualified": qualified,
            "columns": required_columns,
            "expected": len(required_columns),
        },
    )
    columns_exist = bool(_value(cursor.fetchone(), "columns_exist"))

    cursor.execute(
        """
        SELECT proof.index_action_fingerprint(
                 %(action_type)s,
                 %(schema)s,
                 %(table)s,
                 %(method)s,
                 %(is_unique)s,
                 (
                   SELECT array_agg(
                            proof.canonical_index_key(key.expr, key.direction,
                                                      NULL, NULL)
                            ORDER BY key.ordinality
                          )
                   FROM unnest(%(expressions)s::text[], %(directions)s::text[])
                        WITH ORDINALITY AS key(expr, direction, ordinality)
                 ),
                 %(included_columns)s::text[],
                 %(predicate)s
               ) AS proposed_fingerprint
        """,
        {
            "action_type": fields.action_type,
            "schema": fields.target_schema,
            "table": fields.target_table,
            "method": fields.index_method,
            "is_unique": fields.is_unique,
            "expressions": [key.column for key in fields.key_columns],
            "directions": [key.direction for key in fields.key_columns],
            "included_columns": list(fields.included_columns),
            "predicate": fields.predicate,
        },
    )
    fingerprint = _value(cursor.fetchone(), "proposed_fingerprint")

    cursor.execute(
        """
        SELECT count(*) AS equivalent_indexes
        FROM pg_index index_relation
        JOIN pg_class index_class ON index_class.oid = index_relation.indexrelid
        CROSS JOIN proof.observed_index_fingerprint(index_relation.indexrelid) observed
        WHERE index_relation.indrelid = to_regclass(%(qualified)s)
          AND observed.fingerprint = %(fingerprint)s
        """,
        {
            "qualified": qualified,
            "fingerprint": fingerprint,
        },
    )
    equivalent_indexes = int(_value(cursor.fetchone(), "equivalent_indexes"))
    index_name, ddl = render_create_index(fields)

    return [
        {
            "check": "target_table_exists",
            "satisfied": table_exists,
            "detail": qualified,
        },
        {
            "check": "key_columns_exist",
            "satisfied": columns_exist,
            "detail": ", ".join(required_columns),
        },
        {
            "check": "no_equivalent_index_exists",
            "satisfied": equivalent_indexes == 0,
            "detail": (
                f"{equivalent_indexes} index(es) already match this fingerprint"
                if equivalent_indexes
                else "no existing index matches this fingerprint"
            ),
        },
        {
            "check": "statement_is_rendered_not_model_authored",
            "satisfied": True,
            "detail": f"{index_name}: {ddl.splitlines()[0]}",
        },
    ]


def persist_action_proposal(
    cursor: Any,
    *,
    agent_run_id: str,
    run_id: str,
    fields: ProposalFields,
    valid_citation_numbers: list[int],
) -> str:
    """Persist one structured proposal and its surviving citation links."""
    index_name, ddl = render_create_index(fields)
    preconditions = measure_preconditions(cursor, fields)
    cursor.execute(
        """
        INSERT INTO proof.action_proposals(
          agent_run_id,
          run_id,
          action_type,
          target_schema,
          target_table,
          index_method,
          is_unique,
          key_columns,
          included_columns,
          predicate,
          proposed_fingerprint,
          proposed_sql,
          proposed_sql_sha256,
          preconditions,
          expected_effect,
          rollback_sql,
          rollback_guidance,
          statement_timeout,
          lock_timeout
        )
        VALUES (
          %(agent_run_id)s,
          %(run_id)s,
          %(action_type)s,
          %(schema)s,
          %(table)s,
          %(method)s,
          %(is_unique)s,
          (
            SELECT array_agg(
                     proof.canonical_index_key(key.expr, key.direction,
                                               NULL, NULL)
                     ORDER BY key.ordinality
                   )
            FROM unnest(%(expressions)s::text[], %(directions)s::text[])
                 WITH ORDINALITY AS key(expr, direction, ordinality)
          ),
          %(included_columns)s::text[],
          %(predicate)s,
          proof.index_action_fingerprint(
            %(action_type)s,
            %(schema)s,
            %(table)s,
            %(method)s,
            %(is_unique)s,
            (
              SELECT array_agg(
                       proof.canonical_index_key(key.expr, key.direction,
                                                 NULL, NULL)
                       ORDER BY key.ordinality
                     )
              FROM unnest(%(expressions)s::text[], %(directions)s::text[])
                   WITH ORDINALITY AS key(expr, direction, ordinality)
            ),
            %(included_columns)s::text[],
            %(predicate)s
          ),
          %(ddl)s,
          %(ddl_sha256)s,
          %(preconditions)s::jsonb,
          %(expected_effect)s,
          %(rollback_sql)s,
          %(rollback_guidance)s,
          %(statement_timeout)s,
          %(lock_timeout)s
        )
        RETURNING proposal_id
        """,
        {
            "agent_run_id": agent_run_id,
            "run_id": run_id,
            "action_type": fields.action_type,
            "schema": fields.target_schema,
            "table": fields.target_table,
            "method": fields.index_method,
            "is_unique": fields.is_unique,
            "expressions": [key.column for key in fields.key_columns],
            "directions": [key.direction for key in fields.key_columns],
            "included_columns": list(fields.included_columns),
            "predicate": fields.predicate,
            "ddl": ddl,
            "ddl_sha256": sql_sha256(ddl),
            "preconditions": json.dumps(preconditions),
            "expected_effect": fields.expected_effect,
            "rollback_sql": render_rollback(fields, index_name),
            "rollback_guidance": (
                f"Dropping {index_name} restores the pre-change plan. The index "
                "is additive: it changes no row and no column, so the rollback "
                "loses no data."
            ),
            "statement_timeout": STATEMENT_TIMEOUT,
            "lock_timeout": LOCK_TIMEOUT,
        },
    )
    proposal_id = str(_value(cursor.fetchone(), "proposal_id"))

    allowed = set(valid_citation_numbers)
    links = [
        (
            proposal_id,
            run_id,
            citation["citation_number"],
            citation["claim"],
        )
        for citation in fields.supporting_citations
        if citation["citation_number"] in allowed
    ]
    if links:
        cursor.executemany(
            """
            INSERT INTO proof.action_proposal_citations(
              proposal_id,
              run_id,
              citation_number,
              claim
            )
            VALUES (%s, %s, %s, %s)
            """,
            links,
        )
    return proposal_id
