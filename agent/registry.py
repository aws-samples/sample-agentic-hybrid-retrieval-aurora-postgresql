"""The one place Hybrid Retrieval Workbench's agent tools are defined (T4).

Seven tools live here: the six the model can reason about plus
``answer_with_citations``, the whole-loop tool the managed transports expose. A
:class:`ToolSpec` carries a tool's model-facing prose, its typed parameters, the
``/v1`` path that serves it over HTTP, and the ``backend.app.agent`` implementation
that owns its retrieval logic. Nothing here re-implements retrieval; the registry
owns *naming, typing, and documentation*, and the canonical SQL boundary stays in
:mod:`backend.app.agent` (see the project ``CLAUDE.md``).

Every transport is generated from this file:

* the Strands tool specs (:mod:`backend.app.agent_tools` reads
  :func:`ToolSpec.strands_input_schema` and :attr:`ToolSpec.description` straight
  into the ``@tool`` decorator, so the model sees exactly this text);
* the stdio MCP server (``agent/generate_mcp_server.py`` emits
  ``mcp-server/src/server.generated.ts``);
* the AgentCore Gateway Lambda dispatch (``agent/generate_gateway_dispatch.py``
  emits ``lambda_mcp/generated_dispatch.py``).

Gate G-17 regenerates the last two and fails CI on any diff, so a parameter added
here reaches all three transports or the build goes red.

Two shape decisions are encoded here deliberately:

1. ``search_evidence`` lists the full :class:`~backend.app.models.SearchRequest`
   surface, but only ``query``, ``incident_id``, ``cluster_id``, ``kinds``, and
   ``limit`` carry ``model_visible=True``. The Strands schema filters on that flag
   to keep the model's token budget for evidence; MCP and Gateway expose the full
   set for programmatic callers.
2. ``synthesize_cited_answer`` takes ``run_ids`` (a list) on every transport,
   backed by :func:`synthesize_cited_answer_from_runs_impl`. The list shape is the
   general one: it preserves the multi-run interleave the canonical compound
   answer depends on, and a legacy scalar ``run_id`` is coerced to a one-element
   list at each transport's adapter boundary, not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from backend.app.agent import (
    answer_with_citations_impl,
    compare_sources_impl,
    decompose_question_impl,
    explain_ranking_impl,
    follow_evidence_links_impl,
    search_evidence_impl,
    synthesize_cited_answer_from_runs_impl,
)
from backend.app.models import EvidenceKind

JsonType = str  # one of: string, integer, number, boolean, array, object

# Sourced from the single Literal so the tool schema and the model never disagree
# about which evidence kinds exist.
EVIDENCE_KINDS: tuple[str, ...] = tuple(EvidenceKind.__args__)


@dataclass(frozen=True)
class ToolParam:
    """One tool parameter, rendered into every transport's schema.

    Attributes:
        name: The canonical snake_case parameter name. It is the impl keyword, the
            HTTP payload key, and the base the MCP generator camelCases from.
        json_type: JSON Schema type: string, integer, number, boolean, array, or
            object.
        required: Whether the parameter must be supplied. Required parameters emit
            no ``default`` and appear in the schema's ``required`` list.
        default: Value used when the parameter is omitted. Ignored when
            ``required`` is true.
        description: Parameter help. For model_visible params this is teaching
            copy the model reads; keep it factual.
        item_type: Element JSON type when ``json_type`` is ``array``.
        enum: Allowed values, or None. Renders as a schema enum and a Zod enum.
        minimum: Inclusive lower bound for numeric types, or None.
        maximum: Inclusive upper bound for numeric types, or None.
        model_visible: When false, the parameter is hidden from the Strands schema
            (kept out of the model's context) but still exposed to MCP and Gateway.
        identity_bound: When true, the parameter is the caller persona. It is
            never model_visible and is bound server-side by the Strands wrapper; a
            model that could set it would escalate past every ACL check.
        min_length: Minimum length. On a string it bounds characters; on an array
            it bounds elements. Consumed by the Zod (MCP) renderer only.
        max_length: Maximum length, interpreted like ``min_length``.
        str_format: A string format such as ``"uuid"``. On an array it applies to
            the element type. Consumed by the Zod (MCP) renderer only.
    """

    name: str
    json_type: JsonType
    required: bool = False
    default: Any = None
    description: str = ""
    item_type: JsonType | None = None
    enum: tuple[str, ...] | None = None
    minimum: float | None = None
    maximum: float | None = None
    model_visible: bool = True
    identity_bound: bool = False
    min_length: int | None = None
    max_length: int | None = None
    str_format: str | None = None

    def json_schema(self) -> dict[str, Any]:
        """Render this parameter as one JSON Schema property.

        Returns:
            The property body. Optional parameters carry a ``default``; required
            ones do not, matching the shape Strands emits from a signature.
        """
        prop: dict[str, Any] = {"type": self.json_type, "description": self.description}
        if not self.required:
            prop["default"] = self.default
        if self.item_type is not None:
            prop["items"] = {"type": self.item_type}
        if self.enum is not None:
            prop["enum"] = list(self.enum)
        if self.minimum is not None:
            prop["minimum"] = self.minimum
        if self.maximum is not None:
            prop["maximum"] = self.maximum
        return prop


@dataclass(frozen=True)
class ToolSpec:
    """One tool, defined once for every transport.

    Attributes:
        name: The tool name as advertised on every transport.
        description: The model-facing description, used verbatim as the Strands
            tool description and the MCP tool description.
        params: The full parameter set, model_visible or not, in schema order.
        returns_description: One line describing the return payload.
        impl: The ``backend.app.agent`` function that performs the work, callable
            with the tool's parameters as keyword arguments.
        http_path: The ``/v1`` path the MCP server POSTs to for this tool.
        strands_selectable: Whether the Strands event loop may pick this tool. The
            two server tools and the whole-loop tool are not model-selectable.
        exposed_via: The transports that expose this tool.
    """

    name: str
    description: str
    params: tuple[ToolParam, ...]
    returns_description: str
    impl: Callable[..., dict[str, Any]]
    http_path: str
    strands_selectable: bool = True
    exposed_via: tuple[str, ...] = ("strands", "mcp", "gateway")

    def full_description(self) -> str:
        """The description plus a ``Returns:`` block, one copy for every transport.

        Matches the text Strands composes from a docstring, so wrapping an impl with
        ``@tool(description=spec.full_description())`` reproduces today's advertised
        description exactly instead of re-parsing a docstring.

        Returns:
            The model-facing prose with the return line appended.
        """
        return f"{self.description}\n\nReturns:\n    {self.returns_description}"

    def model_params(self) -> tuple[ToolParam, ...]:
        """Parameters the model may set (model_visible, never identity-bound)."""
        return tuple(p for p in self.params if p.model_visible and not p.identity_bound)

    def strands_input_schema(self) -> dict[str, Any]:
        """Render the Strands ``inputSchema`` (model-visible parameters only).

        Returns:
            The ``{"json": {...}}`` envelope the Strands ``@tool`` decorator
            accepts, so the advertised schema comes from this registry rather than
            from docstring parsing.
        """
        model_params = self.model_params()
        return {
            "json": {
                "type": "object",
                "properties": {p.name: p.json_schema() for p in model_params},
                "required": [p.name for p in model_params if p.required],
            }
        }


_KINDS_DESCRIPTION = (
    "Restrict to these evidence kinds. Valid values: " + ", ".join(EVIDENCE_KINDS) + "."
)


def _param_hidden(param: ToolParam) -> ToolParam:
    """Return ``param`` marked model-invisible, for the MCP/Gateway-only surface."""
    return ToolParam(
        name=param.name,
        json_type=param.json_type,
        required=param.required,
        default=param.default,
        description=param.description,
        item_type=param.item_type,
        enum=param.enum,
        minimum=param.minimum,
        maximum=param.maximum,
        model_visible=False,
    )


def _search_filter_params() -> tuple[ToolParam, ...]:
    """The SearchRequest filter surface beyond the model-visible five."""
    return (
        ToolParam("account_name", "string", description="Restrict to one account."),
        ToolParam(
            "severities",
            "array",
            item_type="string",
            description="Restrict to these severities.",
        ),
        ToolParam("environment", "string", description="Restrict to one environment."),
        ToolParam("service_name", "string", description="Restrict to one service."),
        ToolParam("engine_version", "string", description="Restrict to one engine version."),
        ToolParam("aws_region", "string", description="Restrict to one AWS region."),
        ToolParam("start_date", "string", description="Earliest occurred_at, ISO-8601."),
        ToolParam("end_date", "string", description="Latest occurred_at, ISO-8601."),
    )


def _search_knob_params() -> tuple[ToolParam, ...]:
    """The retrieval knobs on SearchRequest, all optional with server defaults."""
    return (
        ToolParam(
            "candidate_pool", "integer", default=24, minimum=8, maximum=2000,
            description="Rows pulled per arm before fusion.",
        ),
        ToolParam(
            "rrf_k", "integer", default=60, minimum=1, maximum=1000,
            description="Reciprocal-rank-fusion k constant.",
        ),
        ToolParam(
            "w_text", "number", default=2.0, minimum=0.0, maximum=10.0,
            description="Full-text arm weight in fusion.",
        ),
        ToolParam(
            "w_vector", "number", default=1.0, minimum=0.0, maximum=10.0,
            description="Vector arm weight in fusion.",
        ),
        ToolParam(
            "w_trgm", "number", default=1.0, minimum=0.0, maximum=10.0,
            description="Trigram arm weight in fusion.",
        ),
        ToolParam(
            "fuzzy_threshold", "number", default=0.3, minimum=0.1, maximum=1.0,
            description="Minimum trigram similarity for the fuzzy arm.",
        ),
        ToolParam(
            "ef_search", "integer", default=40, minimum=1, maximum=1000,
            description="HNSW ef_search for the vector arm.",
        ),
        ToolParam(
            "iterative_scan", "string", default="strict_order",
            enum=("off", "strict_order", "relaxed_order"),
            description="pgvector iterative-scan mode.",
        ),
        ToolParam(
            "rerank", "boolean", description="Force Cohere rerank on or off; omit for the service default.",
        ),
    )


_ROLE_PARAM = ToolParam(
    "role", "string", model_visible=False, identity_bound=True,
    enum=("analyst", "admin", "auditor"), default="analyst",
    description="Caller persona; bound server-side, never set by the model.",
)


TOOLS: dict[str, ToolSpec] = {
    "decompose_question": ToolSpec(
        name="decompose_question",
        description=(
            "Break an incident question into the evidence steps Aurora can answer.\n\n"
            "Call this first. It extracts the identifiers and cluster named in the\n"
            "question and returns the subquestions to retrieve, so later searches are\n"
            "filtered instead of broad."
        ),
        params=(
            ToolParam("question", "string", required=True, min_length=1, max_length=4000, description="The user's incident question, verbatim."),
        ),
        returns_description="Detected identifiers, inferred filters, and ordered subquestions.",
        impl=decompose_question_impl,
        http_path="/v1/tools/decompose",
        strands_selectable=True,
    ),
    "search_evidence": ToolSpec(
        name="search_evidence",
        description=(
            "Retrieve evidence from Aurora using hybrid retrieval, and persist a receipt.\n\n"
            "Runs all four signals in one SQL statement: exact identifier, full text,\n"
            "pgvector semantic, and trigram fuzzy. Exact identifier matches are returned\n"
            "as a tier above the fused candidates, so a named identifier cannot be\n"
            "outranked. Keep the returned run_id: explain_ranking and\n"
            "synthesize_cited_answer both require it."
        ),
        params=(
            ToolParam("query", "string", required=True, min_length=1, max_length=2000, description="Search text. Include any identifier verbatim, such as CHG-1842."),
            ToolParam("incident_id", "string", description="Restrict to one incident, such as INC-2047."),
            ToolParam("cluster_id", "string", description="Restrict to one database cluster, such as checkout-prod-cluster-01."),
            ToolParam("kinds", "array", item_type="string", enum=EVIDENCE_KINDS, description=_KINDS_DESCRIPTION),
            ToolParam("limit", "integer", default=8, minimum=1, maximum=50, description="Rows to return, 1 to 50."),
            *(_param_hidden(p) for p in _search_filter_params()),
            *(_param_hidden(p) for p in _search_knob_params()),
            _ROLE_PARAM,
        ),
        returns_description="run_id, the ranked rows with their match tier, and the ranking groups.",
        impl=search_evidence_impl,
        http_path="/v1/search",
        strands_selectable=True,
    ),
    "follow_evidence_links": ToolSpec(
        name="follow_evidence_links",
        description=(
            "Walk declared relationships out from evidence you already retrieved.\n\n"
            "Relationships come from foreign keys, not text similarity, so this is how\n"
            "you establish that a change caused an incident or that a runbook was\n"
            "superseded. Every hop re-checks the caller's ACL."
        ),
        params=(
            ToolParam("seed_external_keys", "array", required=True, item_type="string", min_length=1, max_length=20, description='Keys to start from, such as ["INC-2047"].'),
            ToolParam("max_depth", "integer", default=2, minimum=0, maximum=8, description="Relationship hops to follow, 0 to 8."),
            _ROLE_PARAM,
        ),
        returns_description="Each reached record with the relation and depth that reached it.",
        impl=follow_evidence_links_impl,
        http_path="/v1/tools/traverse",
        strands_selectable=True,
    ),
    "compare_sources": ToolSpec(
        name="compare_sources",
        description=(
            "Compare specific records on revision, timing, scope, and relationships.\n\n"
            "Use this to rule a candidate in or out: it shows whether two records share a\n"
            "cluster and incident and whether an explicit relationship joins them."
        ),
        params=(
            ToolParam("external_keys", "array", required=True, item_type="string", min_length=1, max_length=20, description='The records to compare, such as ["CHG-1842", "CHG-1838"].'),
            _ROLE_PARAM,
        ),
        returns_description="Each record's scope and revision, plus the relationships between them.",
        impl=compare_sources_impl,
        http_path="/v1/tools/compare",
        strands_selectable=True,
    ),
    "explain_ranking": ToolSpec(
        name="explain_ranking",
        description=(
            "Show why Aurora ordered a retrieval the way it did.\n\n"
            "Reads the persisted receipt for a run_id returned by search_evidence: each\n"
            "candidate's per-arm positions, its RRF score, its match tier, and the stage\n"
            "timings. Nothing is recomputed and no model is called."
        ),
        params=(
            ToolParam("run_id", "string", required=True, str_format="uuid", description="A run_id from a previous search_evidence call."),
        ),
        returns_description="Per-candidate arm positions and scores, plus stage timings.",
        impl=explain_ranking_impl,
        http_path="/v1/tools/explain-ranking",
        strands_selectable=False,
    ),
    "synthesize_cited_answer": ToolSpec(
        name="synthesize_cited_answer",
        description=(
            "Write the final answer from persisted runs, with validated citations.\n\n"
            "This is the last call. Pass every run_id that supports the compound question,\n"
            "including a bounded retry used to recover reusable guidance. The function\n"
            "reloads the exact visible evidence Aurora persisted, refuses to synthesize if\n"
            "a required evidence kind is missing, and validates every citation against the\n"
            "stored chunk quote and revision. The answer it produces is delivered to the\n"
            "user directly, so you do not need to repeat it."
        ),
        params=(
            ToolParam("question", "string", required=True, min_length=1, max_length=4000, description="The user's original question, verbatim."),
            ToolParam("run_ids", "array", required=True, item_type="string", str_format="uuid", min_length=1, max_length=20, description="All supporting run_ids returned by search_evidence, in call order."),
            ToolParam("limit", "integer", default=8, minimum=1, maximum=8, model_visible=False, description="Evidence rows per run to reload."),
        ),
        returns_description="The validated answer, its numbered citations, and the synthesis mode.",
        impl=synthesize_cited_answer_from_runs_impl,
        http_path="/v1/tools/synthesize",
        strands_selectable=False,
    ),
    "answer_with_citations": ToolSpec(
        name="answer_with_citations",
        description=(
            "Answer an incident question end to end and return a cited answer.\n\n"
            "Runs the whole deterministic loop server-side: decompose, retrieve once per\n"
            "subquestion, escalate within a bounded budget, then synthesize a cited answer\n"
            "from the persisted runs. Exposed to managed transports so a single call\n"
            "reproduces the workbench answer against the same Aurora receipts."
        ),
        params=(
            ToolParam("question", "string", required=True, min_length=1, max_length=4000, description="The incident question, verbatim."),
            ToolParam("incident_id", "string", description="Restrict to one incident, such as INC-2047."),
            ToolParam("cluster_id", "string", description="Restrict to one database cluster."),
            ToolParam("kinds", "array", item_type="string", enum=EVIDENCE_KINDS, description=_KINDS_DESCRIPTION),
            ToolParam("limit", "integer", default=8, minimum=1, maximum=20, description="Evidence rows per retrieval, 1 to 20."),
            *(_param_hidden(p) for p in _search_filter_params()),
            *(_param_hidden(p) for p in _search_knob_params() if p.name != "rerank"),
            ToolParam("rerank", "boolean", default=False, model_visible=False, description="Force Cohere rerank on or off; defaults off for the whole-loop answer."),
            ToolParam("max_tool_calls", "integer", default=12, minimum=1, maximum=50, model_visible=False, description="Tool calls before the loop concludes."),
            ToolParam("max_escalations", "integer", default=2, minimum=0, maximum=10, model_visible=False, description="Uncovered-subquestion re-queries allowed."),
            _ROLE_PARAM,
        ),
        returns_description="The cited answer, its citations, and the agent run receipt.",
        impl=answer_with_citations_impl,
        http_path="/v1/agent/answer",
        strands_selectable=False,
        exposed_via=("mcp", "gateway"),
    ),
}


def strands_tools() -> list[ToolSpec]:
    """The tools the Strands event loop may select, in registry order."""
    return [spec for spec in TOOLS.values() if spec.strands_selectable]


def tools_for(transport: str) -> list[ToolSpec]:
    """The tools exposed on one transport (``strands``, ``mcp``, or ``gateway``)."""
    return [spec for spec in TOOLS.values() if transport in spec.exposed_via]
