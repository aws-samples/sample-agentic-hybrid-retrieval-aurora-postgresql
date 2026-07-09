from __future__ import annotations
import hashlib
import json
import re
from collections import defaultdict
from typing import Iterable, List, Tuple
from uuid import UUID

from psycopg.rows import dict_row

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


def create_job(source_system: str, source_name: str, object_count: int) -> tuple[str, str]:
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ops.source_connectors(source_system, source_name, auth_mode, status)
                VALUES (%s, %s, 'api', 'syncing')
                ON CONFLICT(source_system, source_name)
                DO UPDATE SET status = 'syncing', last_sync_at = now()
                RETURNING source_id;
            """, (source_system, source_name))
            source_id = str(cur.fetchone()["source_id"])
            cur.execute("""
                INSERT INTO ops.ingest_jobs(source_id, job_type, status, object_count)
                VALUES (%s, 'source_object_ingest', 'running', %s)
                RETURNING job_id;
            """, (source_id, object_count))
            job_id = str(cur.fetchone()["job_id"])
            cur.execute("""
                INSERT INTO ops.ingest_job_events(job_id, step_name, status, message)
                VALUES (%s, 'normalize', 'running', 'Received source objects for ingestion')
            """, (job_id,))
            return source_id, job_id


def upsert_objects(source_id: str, job_id: str, objects: list[SourceObject]) -> dict:
    object_count = 0
    chunk_count = 0
    link_count = 0
    citation_count = 0
    indexed_objects = []
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            for obj in objects:
                cur.execute("""
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
                      body_hash = EXCLUDED.body_hash
                    RETURNING object_id;
                """, {
                    **obj.model_dump(),
                    "source_id": source_id,
                    "acl": json.dumps(obj.acl),
                    "metadata": json.dumps(obj.metadata),
                    "body_hash": body_hash(obj.body),
                })
                object_id = cur.fetchone()["object_id"]
                indexed_objects.append({
                    "object_id": object_id,
                    "source_system": obj.source_system,
                    "project_key": obj.project_key,
                    "component": obj.component,
                    "account_name": obj.account_name,
                    "priority": obj.priority,
                })
                object_count += 1
                chunks = chunk_text(obj.body)
                cur.execute("DELETE FROM ops.citations WHERE object_id = %s", (object_id,))
                for idx, chunk in enumerate(chunks, start=1):
                    cur.execute("""
                        INSERT INTO ops.object_chunks(object_id, chunk_index, section_title, chunk_text, chunk_summary, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                        ON CONFLICT(object_id, chunk_index) DO UPDATE SET
                          chunk_text = EXCLUDED.chunk_text,
                          chunk_summary = EXCLUDED.chunk_summary,
                          metadata = EXCLUDED.metadata
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
                INSERT INTO ops.ingest_job_events(job_id, step_name, status, message, metadata)
                VALUES (%s, 'upsert_postgres', 'complete', 'Objects, chunks, citations, and links upserted', %s::jsonb)
            """, (job_id, json.dumps({"objects": object_count, "chunks": chunk_count, "citations": citation_count, "links": link_count})))
            cur.execute("""
                UPDATE ops.ingest_jobs
                SET status = 'ready', finished_at = now(), object_count = %s, chunk_count = %s, citation_count = %s, link_count = %s
                WHERE job_id = %s
            """, (object_count, chunk_count, citation_count, link_count, job_id))
            cur.execute("""
                UPDATE ops.source_connectors
                SET status = 'ready', last_sync_at = now()
                WHERE source_id = %s
            """, (source_id,))
    return {"job_id": job_id, "source_id": source_id, "objects_indexed": object_count, "chunks_created": chunk_count, "links_created": link_count, "citations_created": citation_count, "ready_for_search": True}
