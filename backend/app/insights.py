"""Derived retrieval insights served live from Aurora — timeline, graph, fusion SQL.

Everything here reads rows that already exist in the seeded `ops` schema (source
objects, object links, the deployed search function) and derives the three pieces
the Verity UI needs but that were previously hard-coded in the frontend:

  * timeline  — the cross-system sequence of cited objects, time-ordered, with the
                outbound object_links that connect them, assembled by walking
                ops.traverse_links out from the cited set.
  * graph     — the object_links among the traversal-reachable set, for the
                evidence mini-graph.
  * fusion_sql — the ACTUAL deployed ops.hybrid_search definition (pg_get_functiondef),
                so "the fusion query, verbatim" is the real function, not a mockup.

The graph and timeline both derive their working set through ops.traverse_links
(sql/11): starting from the run's cited objects, it walks object_links breadth-first
with cycle protection and returns every reachable object. Confined to the cited set,
a closed component (every link's endpoints cited, as the canonical Orion run is)
reaches exactly the cited objects, so the flagship graph stays byte-identical while
the traversal is genuinely doing the work the UI credits it with.

No content lives here and nothing is regenerated: these are pure reads over the
committed seed, so behavior is identical on a laptop pointed at Aurora and in every
Workshop Studio account that restored the same dump.
"""
from __future__ import annotations

from typing import Any

from .config import get_settings
from .db import get_dict_conn
from .embeddings import embed_text, to_pgvector

# The canonical run is the one the seed persists with its cited candidates. When a
# caller does not have a specific run in hand (e.g. the demo deep-links straight to
# Timeline), fall back to the most recent run that actually has cited candidates.
CANONICAL_RUN_ID = "00000000-0000-0000-0000-00000f4696ae"


def _resolve_run_id(cur, run_id: str | None) -> str | None:
    """Return a run_id that has candidates, preferring the requested one."""
    if run_id:
        cur.execute(
            "SELECT 1 FROM ops.retrieval_candidates WHERE run_id = %s LIMIT 1",
            (run_id,),
        )
        if cur.fetchone():
            return run_id
    # Prefer the canonical run if it is present.
    cur.execute(
        "SELECT 1 FROM ops.retrieval_candidates WHERE run_id = %s LIMIT 1",
        (CANONICAL_RUN_ID,),
    )
    if cur.fetchone():
        return CANONICAL_RUN_ID
    # Otherwise the most recent run that produced candidates.
    cur.execute(
        """
        SELECT c.run_id
        FROM ops.retrieval_candidates c
        JOIN ops.retrieval_runs r ON r.run_id = c.run_id
        GROUP BY c.run_id, r.created_at
        ORDER BY r.created_at DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    return str(row["run_id"]) if row else None


def _cited_objects(cur, run_id: str) -> list[dict[str, Any]]:
    """The run's candidate objects, richest-first, with the fields the UI renders."""
    cur.execute(
        """
        SELECT o.object_id, o.source_system, o.source_type, o.external_id, o.title,
               o.url, o.status, o.priority, o.owner, o.owner_team, o.account_name,
               o.project_key, o.component, o.environment, o.created_at, o.updated_at,
               c.rerank_score, c.final_score,
               (c.explanation ->> 'citation_n')::int AS citation_n,
               c.explanation ->> 'cite_meta'         AS cite_meta,
               c.explanation ->> 'cite_why'          AS cite_why,
               left(regexp_replace(ch.chunk_text, '\\s+', ' ', 'g'), 320) AS snippet
        FROM ops.retrieval_candidates c
        JOIN ops.source_objects o ON o.object_id = c.object_id
        LEFT JOIN LATERAL (
            SELECT chunk_text FROM ops.object_chunks
            WHERE object_id = o.object_id ORDER BY chunk_index LIMIT 1
        ) ch ON TRUE
        WHERE c.run_id = %s
        ORDER BY
          CASE WHEN c.rerank_score IS NULL THEN 1 ELSE 0 END,
          c.rerank_score DESC NULLS LAST,
          c.final_score DESC NULLS LAST
        """,
        (run_id,),
    )
    return cur.fetchall()


# How far ops.traverse_links walks out from the cited seeds when computing the
# reachable evidence set. Small corpus, cycle-protected recursion — a handful of
# hops covers the whole connected component (the deepest real chain, Slack -> Jira
# -> Salesforce, is two hops) with headroom to spare.
_REACH_MAX_DEPTH = 5


def _reachable_objects(cur, seed_ids: list[str]) -> list[dict[str, Any]]:
    """Objects reachable from the cited seeds by walking object_links (traverse_links).

    Seeds the recursive ops.traverse_links walk from the run's cited objects and
    returns every object it reaches (the seeds themselves at depth 0, plus anything
    linked out to within the depth bound), each with the depth and external_id path
    it was reached by. For a closed component — every link's endpoints already cited,
    as the canonical Orion run is — this returns exactly the cited objects, so the
    derived graph is unchanged. For a live run that retrieved only part of a linked
    cluster, it surfaces the linked-but-not-retrieved objects the graph should show.
    """
    if not seed_ids:
        return []
    cur.execute(
        """
        SELECT object_id, external_id, source_system, source_type, title,
               depth, path, via_link_type, via_confidence
        FROM ops.traverse_links(%s::uuid[], %s::int, NULL)
        ORDER BY depth, via_confidence DESC NULLS LAST, external_id
        """,
        (seed_ids, _REACH_MAX_DEPTH),
    )
    return cur.fetchall()


def _objects_by_ids(cur, object_ids: list[str]) -> list[dict[str, Any]]:
    """Rich object rows for a set of object_ids, in the same shape as _cited_objects.

    Used for objects the link traversal reached that were NOT in the run's candidate
    set, so they carry no rerank/final score and no citation number. Everything else
    (metadata + lead snippet) matches _cited_objects so the graph/timeline render
    them identically to cited nodes.
    """
    if not object_ids:
        return []
    cur.execute(
        """
        SELECT o.object_id, o.source_system, o.source_type, o.external_id, o.title,
               o.url, o.status, o.priority, o.owner, o.owner_team, o.account_name,
               o.project_key, o.component, o.environment, o.created_at, o.updated_at,
               NULL::numeric AS rerank_score, NULL::numeric AS final_score,
               NULL::int     AS citation_n,
               NULL::text    AS cite_meta,
               NULL::text    AS cite_why,
               left(regexp_replace(ch.chunk_text, '\\s+', ' ', 'g'), 320) AS snippet
        FROM ops.source_objects o
        LEFT JOIN LATERAL (
            SELECT chunk_text FROM ops.object_chunks
            WHERE object_id = o.object_id ORDER BY chunk_index LIMIT 1
        ) ch ON TRUE
        WHERE o.object_id = ANY(%s::uuid[])
        """,
        (object_ids,),
    )
    return cur.fetchall()


def _expand_to_reachable(cur, cited: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cited objects plus everything reachable from them via ops.traverse_links.

    Returns the cited objects first, in their presentation order (so a cited-only
    working set is byte-identical to before), followed by any object the link walk
    reached that was not itself cited. For a closed component — every link's
    endpoints already cited, as the canonical Orion run is — nothing is appended and
    this is exactly the cited list; for a live run it pulls in linked-but-not-
    retrieved evidence (the PR that fixes the ticket, the case it impacts).
    """
    cited_ids = [str(o["object_id"]) for o in cited]
    reached = _reachable_objects(cur, cited_ids)
    cited_set = set(cited_ids)
    extra_ids = [str(r["object_id"]) for r in reached if str(r["object_id"]) not in cited_set]
    if not extra_ids:
        return cited
    return cited + _objects_by_ids(cur, extra_ids)


def _links_among(cur, object_ids: list[str]) -> list[dict[str, Any]]:
    """Every object_link whose endpoints are both in the given set."""
    if not object_ids:
        return []
    cur.execute(
        """
        SELECT l.link_id, l.link_type, l.confidence,
               fo.object_id   AS from_object_id,
               fo.source_system AS from_system,
               fo.external_id AS from_external_id,
               fo.title       AS from_title,
               fo.source_type AS from_type,
               to_.object_id  AS to_object_id,
               to_.source_system AS to_system,
               to_.external_id AS to_external_id,
               to_.title      AS to_title,
               to_.source_type AS to_type
        FROM ops.object_links l
        JOIN ops.source_objects fo ON fo.object_id = l.from_object_id
        JOIN ops.source_objects to_ ON to_.object_id = l.to_object_id
        WHERE l.from_object_id = ANY(%s::uuid[])
          AND l.to_object_id = ANY(%s::uuid[])
        ORDER BY l.confidence DESC
        """,
        (object_ids, object_ids),
    )
    return cur.fetchall()


def run_timeline(run_id: str | None) -> dict[str, Any]:
    """Time-ordered cross-system sequence of the run's cited objects + their links.

    This is the live backing for the Timeline page: the run's cited objects plus
    anything ops.traverse_links reaches from them become events ordered by their
    source timestamp, each carrying the outbound links traverse_links followed, so
    the UI can render the hops between systems. For the canonical closed component
    the reachable set is exactly the cited objects (byte-identical output).
    """
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            resolved = _resolve_run_id(cur, run_id)
            if not resolved:
                return {"run_id": run_id, "events": [], "systems": [], "edge_count": 0}
            objs = _expand_to_reachable(cur, _cited_objects(cur, resolved))
            ids = [str(o["object_id"]) for o in objs]
            links = _links_among(cur, ids)

    # Group outbound links by source object so each event carries its own edges.
    by_from: dict[str, list[dict[str, Any]]] = {}
    for link in links:
        by_from.setdefault(str(link["from_object_id"]), []).append(link)

    def sort_key(o: dict[str, Any]):
        # Order by the object's own timeline moment; updated_at, then created_at.
        return (o.get("updated_at") or o.get("created_at") or "", o.get("external_id") or "")

    events: list[dict[str, Any]] = []
    for obj in sorted(objs, key=sort_key):
        edges = [
            {
                "link_type": l["link_type"],
                "to_external_id": l["to_external_id"],
                "to_title": l["to_title"],
                "to_system": l["to_system"],
                "confidence": float(l["confidence"]) if l["confidence"] is not None else None,
            }
            for l in by_from.get(str(obj["object_id"]), [])
        ]
        events.append(
            {
                "object_id": str(obj["object_id"]),
                "external_id": obj["external_id"],
                "source_system": obj["source_system"],
                "source_type": obj["source_type"],
                "title": obj["title"],
                "snippet": obj["snippet"],
                "status": obj["status"],
                "owner": obj["owner"],
                "component": obj["component"],
                "created_at": obj["created_at"].isoformat() if obj.get("created_at") else None,
                "updated_at": obj["updated_at"].isoformat() if obj.get("updated_at") else None,
                "citation_n": obj["citation_n"],
                "rerank_score": float(obj["rerank_score"]) if obj["rerank_score"] is not None else None,
                "final_score": float(obj["final_score"]) if obj["final_score"] is not None else None,
                "edges": edges,
            }
        )

    systems = sorted({o["source_system"] for o in objs})
    return {
        "run_id": resolved,
        "events": events,
        "systems": systems,
        "edge_count": len(links),
    }


def run_graph(run_id: str | None) -> dict[str, Any]:
    """The object_links among the run's cited objects — the evidence mini-graph.

    Nodes are the cited objects plus anything ops.traverse_links reaches from them;
    edges are the real links between those nodes. Directed reverse duplicates (A
    references B / B referenced_by A) are collapsed to a single representative edge
    so the graph reads cleanly. For the canonical closed component the reachable set
    is exactly the cited objects (byte-identical output).
    """
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            resolved = _resolve_run_id(cur, run_id)
            if not resolved:
                return {"run_id": run_id, "nodes": [], "edges": [], "system_count": 0, "link_count": 0}
            objs = _expand_to_reachable(cur, _cited_objects(cur, resolved))
            ids = [str(o["object_id"]) for o in objs]
            links = _links_among(cur, ids)

    nodes = [
        {
            "object_id": str(o["object_id"]),
            "external_id": o["external_id"],
            "source_system": o["source_system"],
            "source_type": o["source_type"],
            "title": o["title"],
            "citation_n": o["citation_n"],
        }
        for o in objs
    ]

    # Collapse mirror edges: keep one direction per unordered object pair, favoring
    # the higher-confidence / forward-sounding relation.
    seen_pairs: set[frozenset[str]] = set()
    edges: list[dict[str, Any]] = []
    for l in links:
        pair = frozenset({str(l["from_object_id"]), str(l["to_object_id"])})
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        edges.append(
            {
                "link_id": str(l["link_id"]),
                "relation": l["link_type"],
                "confidence": float(l["confidence"]) if l["confidence"] is not None else None,
                "from": {
                    "system": l["from_system"],
                    "external_id": l["from_external_id"],
                    "title": l["from_title"],
                },
                "to": {
                    "system": l["to_system"],
                    "external_id": l["to_external_id"],
                    "title": l["to_title"],
                },
            }
        )

    return {
        "run_id": resolved,
        "nodes": nodes,
        "edges": edges,
        "system_count": len({o["source_system"] for o in objs}),
        "link_count": len(links),
    }


def follow_links(seed_external_ids: list[str], max_depth: int = 3) -> dict[str, Any]:
    """Walk object_links out from seed objects (by external_id) via ops.traverse_links.

    Resolves each seed external_id to its object, then runs the unconfined recursive
    walk so the result reaches beyond the seeds into linked evidence across systems.
    Returns each reached object with the depth and external_id path it was reached by
    — the multi-hop chain the agent uses to pull in linked evidence a single
    retrieval arm would miss (e.g. from a Slack thread to the Jira ticket it
    references to the Salesforce case that ticket impacts). The seeds themselves come
    back at depth 0; anything linked comes back at depth >= 1.
    """
    seeds = [s for s in (seed_external_ids or []) if s]
    if not seeds:
        return {"seeds": [], "max_depth": max_depth, "reached": [], "system_count": 0}
    depth = max(1, min(int(max_depth), 6))
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT object_id, external_id FROM ops.source_objects WHERE external_id = ANY(%s)",
                (seeds,),
            )
            seed_ids = [str(r["object_id"]) for r in cur.fetchall()]
            if not seed_ids:
                return {"seeds": seeds, "max_depth": depth, "reached": [], "system_count": 0}
            cur.execute(
                """
                SELECT external_id, source_system, source_type, title,
                       depth, path, via_link_type, via_confidence
                FROM ops.traverse_links(%s::uuid[], %s::int, NULL)
                ORDER BY depth, via_confidence DESC NULLS LAST, external_id
                """,
                (seed_ids, depth),
            )
            reached = cur.fetchall()
    return {
        "seeds": seeds,
        "max_depth": depth,
        "reached": [
            {
                "external_id": r["external_id"],
                "source_system": r["source_system"],
                "source_type": r["source_type"],
                "title": r["title"],
                "depth": r["depth"],
                "path": r["path"],
                "via_link_type": r["via_link_type"],
                "via_confidence": float(r["via_confidence"]) if r["via_confidence"] is not None else None,
            }
            for r in reached
        ],
        "system_count": len({r["source_system"] for r in reached}),
    }


# The functions whose live definitions make up the "fusion query, verbatim" panel.
# ops.hybrid_search is the fused ranker; ops.to_or_tsquery is the OR-combine
# invariant the lexical arm depends on (the FTS teaching moment).
FUSION_FUNCTIONS = ["ops.hybrid_search", "ops.to_or_tsquery", "ops.rrf", "ops.acl_visible"]


def fusion_sql() -> dict[str, Any]:
    """Serve the ACTUAL deployed fusion SQL — the real function definitions.

    Reads pg_get_functiondef for the deployed ops.hybrid_search (+ the helpers it
    depends on) so the Diagnostics "fusion query, verbatim" panel shows the exact
    SQL running in this Aurora, not an authored snippet. If the functions are not
    present (schema not applied), returns an empty payload rather than raising.
    """
    definitions: list[dict[str, Any]] = []
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            for fqname in FUSION_FUNCTIONS:
                schema, _, proname = fqname.partition(".")
                # Look up the deployed function by name (highest-arity overload) and
                # ask Postgres for its exact source via pg_get_functiondef.
                cur.execute(
                    """
                    SELECT pg_get_functiondef(p.oid) AS def
                    FROM pg_proc p
                    JOIN pg_namespace n ON n.oid = p.pronamespace
                    WHERE n.nspname = %s AND p.proname = %s
                    ORDER BY p.pronargs DESC
                    LIMIT 1
                    """,
                    (schema, proname),
                )
                row = cur.fetchone()
                if row and row.get("def"):
                    definitions.append({"name": fqname, "definition": row["def"]})
    return {
        "engine": "Amazon Aurora PostgreSQL",
        "primary": "ops.hybrid_search",
        "functions": definitions,
    }


# The retrieval arms whose real query bodies ops.query_plan EXPLAINs. 'hybrid' runs
# all three (the fused ranker executes each arm), so it maps to the full set.
_PLAN_ARMS = ["lexical", "semantic", "fuzzy"]

# Plan node types that represent a table/index access — the teaching moment ("did
# the planner use the GIN/HNSW index or fall back to a Seq Scan?"). The root of each
# arm plan is a Limit, so headlining its Node Type would hide the scan underneath.
_SCAN_NODES = {"Seq Scan", "Index Scan", "Index Only Scan", "Bitmap Heap Scan", "Bitmap Index Scan"}


def _collect_scans(node: dict[str, Any], out: list[dict[str, Any]]) -> None:
    """Walk a plan tree, appending each table/index access node's summary to `out`.

    Each entry names the relation and, for an index scan, the index — so the UI can
    show "Seq Scan on object_chunks" (index rejected at this size) or "Index Scan
    using idx_chunks_embedding_hnsw" per table the arm touched, in plan order.
    """
    if not isinstance(node, dict):
        return
    if node.get("Node Type") in _SCAN_NODES:
        out.append({
            "node_type": node.get("Node Type"),
            "relation": node.get("Relation Name"),
            "index": node.get("Index Name"),
        })
    for child in node.get("Plans", []) or []:
        _collect_scans(child, out)


def _arm_plan(cur, arm: str, query: str, embedding: str | None, limit: int,
              source_systems: list[str] | None, project_key: str | None) -> dict[str, Any]:
    """EXPLAIN one retrieval arm via ops.query_plan and summarize the plan.

    Returns the raw EXPLAIN JSON plus a compact summary: total measured time and
    buffers from the plan root, and every SCAN node (type + relation + index) the
    arm touched, so the UI can show which index the planner used or rejected without
    walking the tree. The semantic arm needs the query embedding; the others do not.
    """
    cur.execute(
        "SELECT ops.query_plan(%(arm)s, %(query)s, %(embedding)s::vector, %(limit)s::int,"
        " %(systems)s, %(project)s) AS plan",
        {
            "arm": arm,
            "query": query,
            "embedding": embedding if arm == "semantic" else None,
            "limit": limit,
            "systems": source_systems,
            "project": project_key,
        },
    )
    payload = cur.fetchone()["plan"]
    root = ((payload.get("plan") or {}).get("Plan")) or {}
    scans: list[dict[str, Any]] = []
    _collect_scans(root, scans)
    return {
        "arm": arm,
        "statement": payload.get("statement"),
        "summary": {
            "scans": scans,
            "actual_total_time_ms": root.get("Actual Total Time"),
            "actual_rows": root.get("Actual Rows"),
            "shared_hit_blocks": root.get("Shared Hit Blocks"),
            "shared_read_blocks": root.get("Shared Read Blocks"),
        },
        "plan": payload.get("plan"),
    }


def query_plan(arm: str, query: str, limit: int = 10,
               source_systems: list[str] | None = None,
               project_key: str | None = None) -> dict[str, Any]:
    """EXPLAIN ANALYZE the retrieval arm(s) for a query against live Aurora.

    Embeds the query with the deployed provider (so the semantic arm plans the real
    HNSW distance search), then calls ops.query_plan for each requested arm. 'hybrid'
    returns all three arm plans because the fused ranker executes each of them. The
    plans are honest: at small corpus size the planner rejects the GIN / HNSW indexes
    in favor of a Seq Scan, and that shows up here rather than being hidden.
    """
    settings = get_settings()
    arms = _PLAN_ARMS if arm == "hybrid" else [arm]
    embedding = to_pgvector(
        embed_text(query, provider=settings.embed_provider, dim=settings.embed_dim, input_type="search_query")
    )
    plans: list[dict[str, Any]] = []
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            for a in arms:
                plans.append(_arm_plan(cur, a, query, embedding, limit, source_systems, project_key))
    return {
        "arm": arm,
        "query": query,
        "explain": "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)",
        "note": (
            "Plans are of the real retrieval arm query bodies, not the SQL function "
            "wrappers (an SRF EXPLAINs to an opaque Function Scan). At small corpus "
            "size the planner may reject the GIN/HNSW index for a Seq Scan — that is "
            "expected and shown honestly."
        ),
        "arms": plans,
    }


def index_usage() -> dict[str, Any]:
    """Live index scan counts and sizes for the ops schema (ops.v_index_usage)."""
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM ops.v_index_usage")
            return {"indexes": cur.fetchall()}


def slow_queries() -> dict[str, Any]:
    """Retrieval queries ranked by mean execution time (ops.v_slow_queries)."""
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM ops.v_slow_queries")
            return {"statements": cur.fetchall()}
