from __future__ import annotations
import hashlib
import json
import re
from collections import defaultdict
from typing import List

from .db import get_dict_conn
from .models import SourceObject


def body_hash(body: str) -> str:
    return hashlib.sha256((body or "").encode("utf-8")).hexdigest()


def chunk_text(text: str, max_chars: int = 1000) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]
    chunks: List[str] = []
    current = ""
    for p in paragraphs:
        if current and len(current) + len(p) + 2 > max_chars:
            chunks.append(current)
            current = p
        else:
            current = f"{current}\n\n{p}".strip()
    if current:
        chunks.append(current)
    return chunks


def create_job(
    source_system: str,
    source_name: str,
    object_count: int,
    *,
    sync_mode: str = "upsert",
    sync_cursor: dict | None = None,
) -> tuple[str, str]:
    if sync_mode not in {"upsert", "full"}:
        raise ValueError(f"unsupported sync mode: {sync_mode}")
    cursor = sync_cursor or {}
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ops.source_connectors(source_system, source_name, auth_mode, status)
                VALUES (%s, %s, 'api', 'syncing')
                ON CONFLICT(source_system, source_name)
                DO UPDATE SET status = 'syncing'
                RETURNING source_id;
            """, (source_system, source_name))
            source_id = str(cur.fetchone()["source_id"])
            cur.execute("""
                INSERT INTO ops.ingest_jobs(source_id, job_type, status, object_count, metadata)
                VALUES (%s, 'source_object_ingest', 'running', %s, %s::jsonb)
                RETURNING job_id;
            """, (source_id, object_count, json.dumps({"sync_mode": sync_mode, "sync_cursor": cursor})))
            job_id = str(cur.fetchone()["job_id"])
            cur.execute("""
                INSERT INTO ops.ingest_job_events(job_id, step_name, status, message, metadata)
                VALUES (%s, 'normalize', 'running', 'Received source objects for ingestion', %s::jsonb)
            """, (job_id, json.dumps({"sync_mode": sync_mode, "object_count": object_count, "sync_cursor": cursor})))
            return source_id, job_id


def upsert_objects(
    source_id: str,
    job_id: str,
    objects: list[SourceObject],
    *,
    sync_mode: str = "upsert",
    sync_cursor: dict | None = None,
) -> dict:
    if sync_mode not in {"upsert", "full"}:
        raise ValueError(f"unsupported sync mode: {sync_mode}")
    cursor = sync_cursor or {}
    object_count = 0
    inserted_count = 0
    changed_count = 0
    unchanged_count = 0
    deactivated_count = 0
    chunk_count = 0
    link_count = 0
    citation_count = 0
    indexed_objects = []
    external_ids: list[str] = []
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            for obj in objects:
                next_body_hash = body_hash(obj.body)
                cur.execute("""
                    SELECT object_id, body_hash
                    FROM ops.source_objects
                    WHERE source_system = %s AND external_id = %s
                """, (obj.source_system, obj.external_id))
                existing = cur.fetchone()
                content_changed = existing is None or existing["body_hash"] != next_body_hash
                cur.execute("""
                    INSERT INTO ops.source_objects(
                      source_id, source_system, source_type, external_id, title, url, status, priority,
                      owner, owner_team, account_name, project_key, component, environment,
                      created_at, updated_at, source_authority, acl, metadata, body_hash,
                      is_active, source_deleted_at
                    )
                    VALUES (%(source_id)s, %(source_system)s, %(source_type)s, %(external_id)s, %(title)s, %(url)s,
                      %(status)s, %(priority)s, %(owner)s, %(owner_team)s, %(account_name)s, %(project_key)s,
                      %(component)s, %(environment)s, %(created_at)s::timestamptz, %(updated_at)s::timestamptz,
                      %(source_authority)s, %(acl)s::jsonb, %(metadata)s::jsonb, %(body_hash)s, true, NULL)
                    ON CONFLICT(source_system, external_id) DO UPDATE SET
                      source_id = EXCLUDED.source_id,
                      source_type = EXCLUDED.source_type,
                      title = EXCLUDED.title,
                      url = EXCLUDED.url,
                      status = EXCLUDED.status,
                      priority = EXCLUDED.priority,
                      owner = EXCLUDED.owner,
                      owner_team = EXCLUDED.owner_team,
                      account_name = EXCLUDED.account_name,
                      project_key = EXCLUDED.project_key,
                      component = EXCLUDED.component,
                      environment = EXCLUDED.environment,
                      updated_at = EXCLUDED.updated_at,
                      source_authority = EXCLUDED.source_authority,
                      acl = EXCLUDED.acl,
                      metadata = EXCLUDED.metadata,
                      body_hash = EXCLUDED.body_hash,
                      is_active = true,
                      source_deleted_at = NULL
                    RETURNING object_id;
                """, {
                    **obj.model_dump(),
                    "source_id": source_id,
                    "acl": json.dumps(obj.acl),
                    "metadata": json.dumps(obj.metadata),
                    "body_hash": next_body_hash,
                })
                object_id = cur.fetchone()["object_id"]
                external_ids.append(obj.external_id)
                indexed_objects.append({
                    "object_id": object_id,
                    "source_system": obj.source_system,
                    "project_key": obj.project_key,
                    "component": obj.component,
                    "account_name": obj.account_name,
                    "priority": obj.priority,
                })
                object_count += 1
                if existing is None:
                    inserted_count += 1
                elif content_changed:
                    changed_count += 1
                else:
                    unchanged_count += 1
                if not content_changed:
                    continue
                chunks = chunk_text(obj.body)
                cur.execute("DELETE FROM ops.citations WHERE object_id = %s", (object_id,))
                for idx, chunk in enumerate(chunks, start=1):
                    cur.execute("""
                        INSERT INTO ops.object_chunks(object_id, chunk_index, section_title, chunk_text, chunk_summary, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                        ON CONFLICT(object_id, chunk_index) DO UPDATE SET
                          section_title = EXCLUDED.section_title,
                          chunk_text = EXCLUDED.chunk_text,
                          chunk_summary = EXCLUDED.chunk_summary,
                          metadata = EXCLUDED.metadata,
                          embedding = CASE
                            WHEN object_chunks.chunk_text IS DISTINCT FROM EXCLUDED.chunk_text THEN NULL
                            ELSE object_chunks.embedding
                          END
                        RETURNING chunk_id;
                    """, (object_id, idx, "Body", chunk, chunk[:260], json.dumps(obj.metadata)))
                    chunk_id = cur.fetchone()["chunk_id"]
                    chunk_count += 1
                    cur.execute("""
                        INSERT INTO ops.citations(chunk_id, object_id, source_label, source_url, locator, quote_text)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (chunk_id, object_id, f"{obj.source_system}:{obj.external_id}", obj.url, f"chunk {idx}", chunk[:500]))
                    citation_count += 1
                cur.execute("DELETE FROM ops.object_chunks WHERE object_id = %s AND chunk_index > %s", (object_id, len(chunks)))

            if sync_mode == "full":
                if external_ids:
                    cur.execute("""
                        UPDATE ops.source_objects
                        SET is_active = false,
                            source_deleted_at = coalesce(source_deleted_at, now())
                        WHERE source_id = %s
                          AND is_active
                          AND NOT (external_id = ANY(%s))
                    """, (source_id, external_ids))
                else:
                    cur.execute("""
                        UPDATE ops.source_objects
                        SET is_active = false,
                            source_deleted_at = coalesce(source_deleted_at, now())
                        WHERE source_id = %s AND is_active
                    """, (source_id,))
                deactivated_count = cur.rowcount
                cur.execute("""
                    INSERT INTO ops.ingest_job_events(job_id, step_name, status, message, metadata)
                    VALUES (%s, 'reconcile_snapshot', 'complete',
                            'Objects missing from the authoritative snapshot were tombstoned',
                            %s::jsonb)
                """, (job_id, json.dumps({"deactivated": deactivated_count, "active_snapshot": len(external_ids)})))

            object_ids = [row["object_id"] for row in indexed_objects]
            if object_ids:
                cur.execute("DELETE FROM ops.object_links WHERE from_object_id = ANY(%s)", (object_ids,))
            by_project: dict[str, list[dict]] = defaultdict(list)
            for row in indexed_objects:
                if row["project_key"]:
                    by_project[row["project_key"]].append(row)
            for group in by_project.values():
                for src in group:
                    candidates = [
                        dst for dst in group
                        if dst["object_id"] != src["object_id"] and dst["source_system"] != src["source_system"]
                    ]
                    candidates.sort(key=lambda dst: (
                        dst["component"] != src["component"],
                        dst["account_name"] != src["account_name"],
                        dst["priority"] not in {"P0", "P1", "Sev1", "Sev2"},
                    ))
                    for dst in candidates[:3]:
                        confidence = 0.92 if dst["component"] == src["component"] else 0.78
                        cur.execute("""
                            INSERT INTO ops.object_links(from_object_id, to_object_id, link_type, confidence, metadata)
                            VALUES (%s, %s, 'same_project_evidence', %s, %s::jsonb)
                            ON CONFLICT(from_object_id, to_object_id, link_type) DO UPDATE SET
                              confidence = EXCLUDED.confidence,
                              metadata = EXCLUDED.metadata
                        """, (
                            src["object_id"],
                            dst["object_id"],
                            confidence,
                            json.dumps({"strategy": "same_project_cross_system", "project_key": src["project_key"]}),
                        ))
                        link_count += 1
            cur.execute("""
                SELECT count(*) AS count
                FROM ops.object_chunks c
                JOIN ops.source_objects o ON o.object_id = c.object_id
                WHERE o.source_id = %s AND o.is_active AND c.embedding IS NULL
            """, (source_id,))
            embeddings_pending = cur.fetchone()["count"]
            cur.execute("""
                INSERT INTO ops.ingest_job_events(job_id, step_name, status, message, metadata)
                VALUES (%s, 'upsert_postgres', 'complete', 'Objects, chunks, citations, and links upserted', %s::jsonb)
            """, (job_id, json.dumps({
                "objects": object_count,
                "inserted": inserted_count,
                "changed": changed_count,
                "unchanged": unchanged_count,
                "deactivated": deactivated_count,
                "chunks_written": chunk_count,
                "citations": citation_count,
                "links": link_count,
                "embeddings_pending": embeddings_pending,
            })))
            cur.execute("""
                UPDATE ops.ingest_jobs
                SET status = %s,
                    finished_at = CASE WHEN %s = 'ready' THEN now() ELSE NULL END,
                    object_count = %s,
                    chunk_count = %s,
                    citation_count = %s,
                    link_count = %s,
                    metadata = metadata || %s::jsonb
                WHERE job_id = %s
            """, (
                "ready" if embeddings_pending == 0 else "indexing",
                "ready" if embeddings_pending == 0 else "indexing",
                object_count,
                chunk_count,
                citation_count,
                link_count,
                json.dumps({
                    "inserted": inserted_count,
                    "changed": changed_count,
                    "unchanged": unchanged_count,
                    "deactivated": deactivated_count,
                    "embeddings_pending": embeddings_pending,
                }),
                job_id,
            ))
            cur.execute("""
                UPDATE ops.source_connectors
                SET status = %s,
                    last_sync_at = now(),
                    sync_cursor = %s::jsonb
                WHERE source_id = %s
            """, (
                "ready" if embeddings_pending == 0 else "indexing",
                json.dumps(cursor),
                source_id,
            ))
    return {
        "job_id": job_id,
        "source_id": source_id,
        "sync_mode": sync_mode,
        "sync_cursor": cursor,
        "objects_indexed": object_count,
        "objects_inserted": inserted_count,
        "objects_changed": changed_count,
        "objects_unchanged": unchanged_count,
        "objects_deactivated": deactivated_count,
        "chunks_written": chunk_count,
        "links_created": link_count,
        "citations_created": citation_count,
        "embeddings_pending": embeddings_pending,
        "ready_for_lexical_search": True,
        "ready_for_semantic_search": embeddings_pending == 0,
    }
