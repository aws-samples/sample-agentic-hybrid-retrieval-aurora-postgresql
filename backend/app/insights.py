"""Derived retrieval insights served live from Aurora — timeline, graph, fusion SQL.

Everything here reads rows that already exist in the seeded `ops` schema (source
objects, object links, the deployed search function) and derives the three pieces
the AuraLens UI needs but that were previously hard-coded in the frontend:

  * timeline  — the cross-system sequence of cited objects, time-ordered, with the
                outbound object_links that connect them (what traverse_links walks).
  * graph     — the object_links among the cited set, for the evidence mini-graph.
  * fusion_sql — the ACTUAL deployed ops.hybrid_search definition (pg_get_functiondef),
                so "the fusion query, verbatim" is the real function, not a mockup.

No content lives here and nothing is regenerated: these are pure reads over the
committed seed, so behavior is identical on a laptop pointed at Aurora and in every
Workshop Studio account that restored the same dump.
"""
from __future__ import annotations

from typing import Any

from .db import get_dict_conn

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

    This is the live backing for the Timeline page: each cited object becomes an
    event ordered by its source timestamp, carrying the outbound links (the edges
    traverse_links would follow) so the UI can render the hops between systems.
    """
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            resolved = _resolve_run_id(cur, run_id)
            if not resolved:
                return {"run_id": run_id, "events": [], "systems": [], "edge_count": 0}
            objs = _cited_objects(cur, resolved)
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

    Nodes are the cited objects; edges are the real links between them. Directed
    reverse duplicates (A references B / B referenced_by A) are collapsed to a
    single representative edge so the graph reads cleanly.
    """
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            resolved = _resolve_run_id(cur, run_id)
            if not resolved:
                return {"run_id": run_id, "nodes": [], "edges": [], "system_count": 0, "link_count": 0}
            objs = _cited_objects(cur, resolved)
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


# The functions whose live definitions make up the "fusion query, verbatim" panel.
# ops.hybrid_search is the fused ranker; ops.to_or_tsquery is the OR-combine
# invariant the lexical arm depends on (the FTS teaching moment).
FUSION_FUNCTIONS = ["ops.hybrid_search", "ops.to_or_tsquery", "ops.rrf"]


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
