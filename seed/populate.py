"""Populate a Postgres/Aurora `ops` schema with the canonical seed.

Called by generate.py once the schema exists. Writes, idempotently:
  - ops.source_connectors (one per system)
  - ops.source_objects (150) + ops.object_chunks (+ 1024-d embeddings)
  - ops.citations (per chunk) + ops.object_links (canonical golden-thread edges)
  - ops.retrieval_runs (the canonical rr_7f3a9c run) + ops.retrieval_candidates
  - ops.agent_answers (the exact Orion answer) + ops.retrieval_run_metrics
  - ops.evaluation_queries + ops.relevance_judgments

All embeddings are computed offline via the injected embed_text (hash by
default). No Bedrock calls unless provider='bedrock' is explicitly chosen.
"""
from __future__ import annotations

import json
from typing import Any, Callable

import psycopg
from psycopg.rows import dict_row

import canonical as C


def _norm_question(q: str) -> str:
    return " ".join(q.lower().split())


def populate_database(
    database_url: str,
    objs: list[dict],
    provider: str,
    embed_text: Callable[..., list[float]],
    to_pgvector: Callable[[list[float]], str],
    body_hash: Callable[[str], str],
    chunk_text: Callable[[str], list[str]],
) -> None:
    conn = psycopg.connect(database_url, autocommit=True, row_factory=dict_row)
    try:
        with conn.cursor() as cur:
            _connectors(cur)
            ext_to_object_id, ext_to_chunk_ids = _objects_and_chunks(
                cur, objs, provider, embed_text, to_pgvector, body_hash, chunk_text
            )
            _links(cur, ext_to_object_id)
            run_id = _run_and_candidates(cur, ext_to_object_id, ext_to_chunk_ids)
            _agent_answer(cur, run_id, ext_to_object_id)
            _run_metrics(cur, run_id)
            _evaluation(cur)
            print(f"[populate] done — canonical run {run_id}")
    finally:
        conn.close()


def _connectors(cur) -> None:
    for system in C.SYSTEMS:
        cur.execute(
            """
            INSERT INTO ops.source_connectors(source_system, source_name, auth_mode, status)
            VALUES (%s, %s, 'api', 'ready')
            ON CONFLICT(source_system, source_name)
            DO UPDATE SET status = 'ready'
            RETURNING source_id;
            """,
            (system, f"{system}-workshop-seed"),
        )


def _objects_and_chunks(cur, objs, provider, embed_text, to_pgvector, body_hash, chunk_text):
    ext_to_object_id: dict[str, str] = {}
    ext_to_chunk_ids: dict[str, list[str]] = {}
    for o in objs:
        cur.execute(
            "SELECT source_id FROM ops.source_connectors WHERE source_system = %s AND source_name = %s",
            (o["source_system"], f"{o['source_system']}-workshop-seed"),
        )
        row = cur.fetchone()
        source_id = row["source_id"] if row else None
        cur.execute(
            """
            INSERT INTO ops.source_objects(
              source_id, source_system, source_type, external_id, title, url, status, priority,
              owner, owner_team, account_name, project_key, component, environment,
              created_at, updated_at, source_authority, acl, metadata, body_hash
            )
            VALUES (%(source_id)s, %(source_system)s, %(source_type)s, %(external_id)s, %(title)s, %(url)s,
              %(status)s, %(priority)s, %(owner)s, %(owner_team)s, %(account_name)s, %(project_key)s,
              %(component)s, %(environment)s, %(created_at)s::timestamptz, %(updated_at)s::timestamptz,
              %(source_authority)s, %(acl)s::jsonb, %(metadata)s::jsonb, %(body_hash)s)
            ON CONFLICT(source_system, external_id) DO UPDATE SET
              title = EXCLUDED.title, url = EXCLUDED.url, status = EXCLUDED.status,
              priority = EXCLUDED.priority, owner = EXCLUDED.owner, owner_team = EXCLUDED.owner_team,
              account_name = EXCLUDED.account_name, project_key = EXCLUDED.project_key,
              component = EXCLUDED.component, environment = EXCLUDED.environment,
              updated_at = EXCLUDED.updated_at, source_authority = EXCLUDED.source_authority,
              acl = EXCLUDED.acl, metadata = EXCLUDED.metadata, body_hash = EXCLUDED.body_hash
            RETURNING object_id;
            """,
            {
                "source_id": source_id,
                "source_system": o["source_system"],
                "source_type": o["source_type"],
                "external_id": o["external_id"],
                "title": o["title"],
                "url": o.get("url"),
                "status": o.get("status"),
                "priority": o.get("priority"),
                "owner": o.get("owner"),
                "owner_team": o.get("owner_team"),
                "account_name": o.get("account_name"),
                "project_key": o.get("project_key"),
                "component": o.get("component"),
                "environment": o.get("environment"),
                "created_at": o.get("created_at"),
                "updated_at": o.get("updated_at"),
                "source_authority": o.get("source_authority", 0.70),
                "acl": json.dumps(o.get("acl", {})),
                "metadata": json.dumps(o.get("metadata", {})),
                "body_hash": body_hash(o["body"]),
            },
        )
        object_id = cur.fetchone()["object_id"]
        ext_to_object_id[o["external_id"]] = str(object_id)

        chunks = chunk_text(o["body"]) or [o["body"]]
        chunk_ids: list[str] = []
        for idx, chunk in enumerate(chunks, start=1):
            emb = embed_text(chunk, provider=provider, dim=C.EMBEDDING_DIM)
            cur.execute(
                """
                INSERT INTO ops.object_chunks(object_id, chunk_index, section_title, chunk_text, chunk_summary, embedding, metadata)
                VALUES (%s, %s, %s, %s, %s, %s::vector, %s::jsonb)
                ON CONFLICT(object_id, chunk_index) DO UPDATE SET
                  chunk_text = EXCLUDED.chunk_text, chunk_summary = EXCLUDED.chunk_summary,
                  embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata
                RETURNING chunk_id;
                """,
                (object_id, idx, "Body", chunk, chunk[:260], to_pgvector(emb), json.dumps(o.get("metadata", {}))),
            )
            chunk_id = cur.fetchone()["chunk_id"]
            chunk_ids.append(str(chunk_id))
            cur.execute("DELETE FROM ops.citations WHERE chunk_id = %s", (chunk_id,))
            cur.execute(
                """
                INSERT INTO ops.citations(chunk_id, object_id, source_label, source_url, locator, quote_text)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (chunk_id, object_id, f"{o['source_system']}:{o['external_id']}", o.get("url"), f"chunk {idx}", chunk[:500]),
            )
        cur.execute("DELETE FROM ops.object_chunks WHERE object_id = %s AND chunk_index > %s", (object_id, len(chunks)))
        ext_to_chunk_ids[o["external_id"]] = chunk_ids
    return ext_to_object_id, ext_to_chunk_ids


def _links(cur, ext_to_object_id) -> None:
    for frm, to, link_type, confidence in C.LINKS:
        if frm not in ext_to_object_id or to not in ext_to_object_id:
            continue
        cur.execute(
            """
            INSERT INTO ops.object_links(from_object_id, to_object_id, link_type, confidence, metadata)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            ON CONFLICT(from_object_id, to_object_id, link_type) DO UPDATE SET
              confidence = EXCLUDED.confidence, metadata = EXCLUDED.metadata
            """,
            (ext_to_object_id[frm], ext_to_object_id[to], link_type, confidence,
             json.dumps({"strategy": "canonical_golden_thread"})),
        )


def _run_and_candidates(cur, ext_to_object_id, ext_to_chunk_ids) -> str:
    # Deterministic run_id derived from the slug so re-runs are idempotent.
    cur.execute(
        """
        INSERT INTO ops.retrieval_runs(run_id, query_text, filters, retrieval_mode, created_at)
        VALUES (
          ('00000000-0000-0000-0000-0000' || substr(md5(%s), 1, 8))::uuid,
          %s, %s::jsonb, 'hybrid', %s::timestamptz
        )
        ON CONFLICT (run_id) DO UPDATE SET query_text = EXCLUDED.query_text
        RETURNING run_id;
        """,
        (C.CANONICAL_RUN_SLUG, C.CANONICAL_QUESTION,
         json.dumps({"project_key": "ORION", "source_systems": C.SYSTEMS}), C.RUN_FIRED_AT),
    )
    run_id = str(cur.fetchone()["run_id"])

    # Six cited candidates with their exact signal scores.
    for c in C.CITED:
        ext = c["external_id"]
        chunk_ids = ext_to_chunk_ids.get(ext)
        object_id = ext_to_object_id.get(ext)
        if not chunk_ids or not object_id:
            continue
        cur.execute(
            """
            INSERT INTO ops.retrieval_candidates(
              run_id, chunk_id, object_id, text_rank, vector_score, trigram_score,
              rrf_score, final_score, explanation
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT(run_id, chunk_id) DO UPDATE SET
              text_rank = EXCLUDED.text_rank, vector_score = EXCLUDED.vector_score,
              trigram_score = EXCLUDED.trigram_score, rrf_score = EXCLUDED.rrf_score,
              final_score = EXCLUDED.final_score, explanation = EXCLUDED.explanation
            """,
            (run_id, chunk_ids[0], object_id, c.get("text_rank"), c.get("vector_score"),
             c.get("trigram_score"), c.get("rrf_score"), c.get("final_score"),
             json.dumps({"citation_n": c["n"], "cite_meta": c["cite_meta"], "cite_why": c["cite_why"]})),
        )
    return run_id


def _agent_answer(cur, run_id, ext_to_object_id) -> None:
    citations = [
        {
            "n": c["n"],
            "source_system": c["source_system"],
            "external_id": c["external_id"],
            "title": c["title"],
            "url": f"https://example.internal/{c['source_system']}/{c['external_id']}",
            "score": c["final_score"],
            "meta": c["cite_meta"],
            "why": c["cite_why"],
        }
        for c in C.CITED
    ]
    cur.execute(
        """
        INSERT INTO ops.agent_answers(
          run_id, question, question_norm, answer, confidence, source_count, system_count, citations
        ) VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb)
        ON CONFLICT(question_norm) DO UPDATE SET
          run_id = EXCLUDED.run_id, answer = EXCLUDED.answer, confidence = EXCLUDED.confidence,
          source_count = EXCLUDED.source_count, system_count = EXCLUDED.system_count,
          citations = EXCLUDED.citations
        """,
        (run_id, C.CANONICAL_QUESTION, _norm_question(C.CANONICAL_QUESTION),
         json.dumps({"body": C.ANSWER, "plan": C.PLAN}), C.ANSWER_CONFIDENCE,
         C.ANSWER_SOURCE_COUNT, C.ANSWER_SYSTEM_COUNT, json.dumps(citations)),
    )


def _run_metrics(cur, run_id) -> None:
    cur.execute(
        """
        INSERT INTO ops.retrieval_run_metrics(
          run_id, profile, embedding_model, embedding_dim, index_spec, fired_at,
          total_latency_ms, p50_latency_ms, rrf_k, ranker_weights, rerank_cut,
          reranked_count, funnel, stage_timings, metadata
        ) VALUES (%s, %s, %s, %s, %s, %s::timestamptz, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
        ON CONFLICT(run_id) DO UPDATE SET
          profile = EXCLUDED.profile, embedding_model = EXCLUDED.embedding_model,
          index_spec = EXCLUDED.index_spec, total_latency_ms = EXCLUDED.total_latency_ms,
          funnel = EXCLUDED.funnel, stage_timings = EXCLUDED.stage_timings,
          metadata = EXCLUDED.metadata
        """,
        (run_id, C.PROFILE, C.EMBEDDING_MODEL, C.EMBEDDING_DIM, C.INDEX_SPEC, C.RUN_FIRED_AT,
         C.TOTAL_LATENCY_MS, C.P50_LATENCY_MS, C.RRF_K, C.RANKER_WEIGHTS, C.RERANK_CUT,
         C.RERANKED_COUNT, json.dumps(C.FUNNEL), json.dumps(C.STAGE_TIMINGS),
         json.dumps({"diagnostics_rows": C.DIAGNOSTICS_ROWS})),
    )


def _evaluation(cur) -> None:
    cur.execute(
        """
        INSERT INTO ops.evaluation_queries(query_id, query_text, filters, notes)
        VALUES (%s, %s, %s::jsonb, %s)
        ON CONFLICT(query_id) DO UPDATE SET query_text = EXCLUDED.query_text, notes = EXCLUDED.notes
        """,
        (C.EVAL_QUERY_ID, C.CANONICAL_QUESTION, json.dumps({"project_key": "ORION"}),
         "Golden thread for the Orion delay narrative."),
    )
    for ext, relevance, rationale in C.RELEVANCE_JUDGMENTS:
        cur.execute(
            """
            INSERT INTO ops.relevance_judgments(query_id, object_external_id, relevance, rationale)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT(query_id, object_external_id) DO UPDATE SET
              relevance = EXCLUDED.relevance, rationale = EXCLUDED.rationale
            """,
            (C.EVAL_QUERY_ID, ext, relevance, rationale),
        )
