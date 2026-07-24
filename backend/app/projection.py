from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Callable, Iterable, Sequence
import uuid

from psycopg.rows import dict_row

from .embeddings import bedrock_embeddings, to_pgvector

EMBEDDING_DIMENSIONS = 1024
RENDERER_VERSION = "casework-renderer-v1"
CHUNKER_VERSION = "paragraph-chunker-v1"
PROJECTION_NAMESPACE = uuid.UUID("2ed19275-d22d-4d84-bd93-d8d2ae99ee5b")


class MissingEmbeddingsError(RuntimeError):
    pass


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    section_title: str
    text: str
    text_hash: str


@dataclass(frozen=True)
class Document:
    evidence_id: uuid.UUID
    evidence_kind: str
    external_key: str
    title: str
    source_system: str
    source_uri: str
    source_revision: str
    source_updated_at: object
    acl: dict
    cluster_id: str | None
    incident_id: str | None
    account_name: str | None
    severity: str | None
    environment: str | None
    occurred_at: object
    metadata: dict
    projection_hash: str
    chunks: tuple[Chunk, ...]


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def chunk_text(text: str, max_chars: int = 1600) -> tuple[Chunk, ...]:
    paragraphs = [" ".join(part.split()) for part in text.split("\n\n") if part.strip()]
    if not paragraphs:
        paragraphs = [""]

    groups: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if current and len(candidate) > max_chars:
            groups.append(current)
            current = paragraph
        else:
            current = candidate
    if current or not groups:
        groups.append(current)

    chunks: list[Chunk] = []
    for ordinal, value in enumerate(groups, start=1):
        chunks.append(
            Chunk(
                ordinal=ordinal,
                section_title="Evidence",
                text=value,
                text_hash=sha256_text(value),
            )
        )
    return tuple(chunks)


class EmbeddingCache:
    def __init__(self, path: Path):
        self.path = path
        self._vectors: dict[str, list[float]] = {}

    @staticmethod
    def key(model_id: str, text_hash: str) -> str:
        return sha256_text(f"{model_id}\0{text_hash}")

    def load(self) -> None:
        self._vectors = {}
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                vector = record.get("embedding")
                if not isinstance(vector, list) or len(vector) != EMBEDDING_DIMENSIONS:
                    raise ValueError(
                        f"{self.path}:{line_number} has an invalid embedding dimension"
                    )
                self._vectors[str(record["key"])] = [float(value) for value in vector]

    def get(self, model_id: str, text_hash: str) -> list[float] | None:
        return self._vectors.get(self.key(model_id, text_hash))

    def put(self, model_id: str, text_hash: str, vector: Sequence[float]) -> None:
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"embedding has {len(vector)} dimensions, expected {EMBEDDING_DIMENSIONS}"
            )
        self._vectors[self.key(model_id, text_hash)] = [float(value) for value in vector]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            for key in sorted(self._vectors):
                handle.write(
                    json.dumps(
                        {
                            "key": key,
                            "dimensions": EMBEDDING_DIMENSIONS,
                            "embedding": self._vectors[key],
                        },
                        separators=(",", ":"),
                    )
                    + "\n"
                )
        temporary.replace(self.path)


def projection_version(model_id: str) -> str:
    return f"{RENDERER_VERSION}:{CHUNKER_VERSION}:{model_id}"


def _load_documents(conn) -> list[Document]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT *
            FROM casework.v_evidence_documents
            ORDER BY evidence_kind, external_key
            """
        )
        rows = cursor.fetchall()

    return [
        Document(
            evidence_id=row["evidence_id"],
            evidence_kind=row["evidence_kind"],
            external_key=row["external_key"],
            title=row["title"],
            source_system=row["source_system"],
            source_uri=row["source_uri"],
            source_revision=row["source_revision"],
            source_updated_at=row["source_updated_at"],
            acl=row["acl"],
            cluster_id=row["cluster_id"],
            incident_id=row["incident_id"],
            account_name=row["account_name"],
            severity=row["severity"],
            environment=row["environment"],
            occurred_at=row["occurred_at"],
            metadata=row["metadata"],
            projection_hash=row["projection_hash"],
            chunks=chunk_text(row["body"]),
        )
        for row in rows
    ]


def _unique_chunks(documents: Iterable[Document]) -> dict[str, str]:
    return {
        chunk.text_hash: chunk.text
        for document in documents
        for chunk in document.chunks
    }


def _resolve_embeddings(
    documents: list[Document],
    cache: EmbeddingCache,
    model_id: str,
    *,
    embed_missing: bool,
    batch_size: int,
    embedder: Callable[[list[str]], list[list[float]]] | None,
) -> tuple[dict[str, list[float]], int, int]:
    unique = _unique_chunks(documents)
    vectors: dict[str, list[float]] = {}
    missing: list[tuple[str, str]] = []
    for text_hash, text in unique.items():
        cached = cache.get(model_id, text_hash)
        if cached is None:
            missing.append((text_hash, text))
        else:
            vectors[text_hash] = cached

    cache_hits = len(vectors)
    if missing and not embed_missing:
        raise MissingEmbeddingsError(
            f"{len(missing)} embedding(s) are absent from {cache.path}; "
            "run with --embed-missing against the configured Bedrock model"
        )

    if missing:
        invoke = embedder or (
            lambda texts: bedrock_embeddings(
                texts,
                dim=EMBEDDING_DIMENSIONS,
                model_id=model_id,
                input_type="search_document",
            )
        )
        for offset in range(0, len(missing), batch_size):
            batch = missing[offset : offset + batch_size]
            embedded = invoke([text for _, text in batch])
            if len(embedded) != len(batch):
                raise ValueError(
                    f"embedding provider returned {len(embedded)} vectors for {len(batch)} texts"
                )
            for (text_hash, _), vector in zip(batch, embedded, strict=True):
                cache.put(model_id, text_hash, vector)
                vectors[text_hash] = [float(value) for value in vector]
        cache.save()

    return vectors, cache_hits, len(missing)


def _document_version_id(document: Document, version: str) -> uuid.UUID:
    return uuid.uuid5(
        PROJECTION_NAMESPACE,
        f"document:{document.evidence_id}:{version}:{document.projection_hash}",
    )


def _chunk_version_id(document_version_id: uuid.UUID, chunk: Chunk) -> uuid.UUID:
    return uuid.uuid5(
        PROJECTION_NAMESPACE,
        f"chunk:{document_version_id}:{chunk.ordinal}:{chunk.text_hash}",
    )


def _create_build(conn, version: str, model_id: str) -> uuid.UUID:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO retrieval.projection_builds(
              projection_version,
              embedding_model,
              embedding_dimensions,
              renderer_version,
              chunker_version,
              status
            )
            VALUES (%s, %s, %s, %s, %s, 'running')
            RETURNING build_id
            """,
            (
                version,
                model_id,
                EMBEDDING_DIMENSIONS,
                RENDERER_VERSION,
                CHUNKER_VERSION,
            ),
        )
        return cursor.fetchone()[0]


def _mark_build_failed(conn, build_id: uuid.UUID, error: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE retrieval.projection_builds
            SET status = 'failed',
                completed_at = now(),
                error = %s
            WHERE build_id = %s
            """,
            (error[:4000], build_id),
        )


def rebuild_projection(
    conn,
    *,
    model_id: str,
    cache_path: Path,
    embed_missing: bool = False,
    batch_size: int = 48,
    embedder: Callable[[list[str]], list[list[float]]] | None = None,
) -> dict:
    version = projection_version(model_id)
    documents = _load_documents(conn)
    build_id = _create_build(conn, version, model_id)
    conn.commit()

    cache = EmbeddingCache(cache_path)
    cache.load()
    try:
        vectors, cache_hits, embedded_count = _resolve_embeddings(
            documents,
            cache,
            model_id,
            embed_missing=embed_missing,
            batch_size=batch_size,
            embedder=embedder,
        )
    except Exception as exc:
        _mark_build_failed(conn, build_id, str(exc))
        conn.commit()
        raise

    document_count = 0
    chunk_count = 0
    skipped_count = 0
    try:
        for document in documents:
            document_id = _document_version_id(document, version)
            with conn.transaction():
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT 1
                        FROM retrieval.documents
                        WHERE document_version_id = %s
                          AND is_current
                          AND index_state = 'ready'
                        """,
                        (document_id,),
                    )
                    if cursor.fetchone():
                        skipped_count += 1
                        continue

                    cursor.execute(
                        """
                        INSERT INTO retrieval.documents(
                          document_version_id,
                          evidence_id,
                          build_id,
                          projection_version,
                          projection_hash,
                          source_revision,
                          evidence_kind,
                          external_key,
                          title,
                          source_system,
                          source_uri,
                          source_updated_at,
                          acl,
                          cluster_id,
                          incident_id,
                          account_name,
                          severity,
                          environment,
                          occurred_at,
                          metadata,
                          index_state,
                          is_current
                        )
                        VALUES (
                          %(document_version_id)s,
                          %(evidence_id)s,
                          %(build_id)s,
                          %(projection_version)s,
                          %(projection_hash)s,
                          %(source_revision)s,
                          %(evidence_kind)s,
                          %(external_key)s,
                          %(title)s,
                          %(source_system)s,
                          %(source_uri)s,
                          %(source_updated_at)s,
                          %(acl)s::jsonb,
                          %(cluster_id)s,
                          %(incident_id)s,
                          %(account_name)s,
                          %(severity)s,
                          %(environment)s,
                          %(occurred_at)s,
                          %(metadata)s::jsonb,
                          'building',
                          false
                        )
                        ON CONFLICT (document_version_id)
                        DO UPDATE SET
                          build_id = EXCLUDED.build_id,
                          index_state = 'building',
                          is_current = false,
                          indexed_at = NULL,
                          superseded_at = NULL
                        """,
                        {
                            "document_version_id": document_id,
                            "evidence_id": document.evidence_id,
                            "build_id": build_id,
                            "projection_version": version,
                            "projection_hash": document.projection_hash,
                            "source_revision": document.source_revision,
                            "evidence_kind": document.evidence_kind,
                            "external_key": document.external_key,
                            "title": document.title,
                            "source_system": document.source_system,
                            "source_uri": document.source_uri,
                            "source_updated_at": document.source_updated_at,
                            "acl": json.dumps(document.acl),
                            "cluster_id": document.cluster_id,
                            "incident_id": document.incident_id,
                            "account_name": document.account_name,
                            "severity": document.severity,
                            "environment": document.environment,
                            "occurred_at": document.occurred_at,
                            "metadata": json.dumps(document.metadata),
                        },
                    )

                    for chunk in document.chunks:
                        chunk_id = _chunk_version_id(document_id, chunk)
                        cursor.execute(
                            """
                            INSERT INTO retrieval.chunks(
                              chunk_version_id,
                              document_version_id,
                              chunk_ordinal,
                              section_title,
                              chunk_text,
                              chunk_hash,
                              embedding,
                              embedding_model,
                              embedding_input_type,
                              embedding_state
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s, 'search_document', 'ready')
                            ON CONFLICT (chunk_version_id)
                            DO UPDATE SET
                              embedding = EXCLUDED.embedding,
                              embedding_model = EXCLUDED.embedding_model,
                              embedding_input_type = EXCLUDED.embedding_input_type,
                              embedding_state = 'ready'
                            """,
                            (
                                chunk_id,
                                document_id,
                                chunk.ordinal,
                                chunk.section_title,
                                chunk.text,
                                chunk.text_hash,
                                to_pgvector(vectors[chunk.text_hash]),
                                model_id,
                            ),
                        )
                        chunk_count += 1

                    cursor.execute(
                        """
                        UPDATE retrieval.documents
                        SET is_current = false,
                            index_state = 'superseded',
                            superseded_at = now()
                        WHERE evidence_id = %s
                          AND is_current
                          AND document_version_id <> %s
                        """,
                        (document.evidence_id, document_id),
                    )
                    cursor.execute(
                        """
                        UPDATE retrieval.documents
                        SET is_current = true,
                            index_state = 'ready',
                            indexed_at = now(),
                            superseded_at = NULL
                        WHERE document_version_id = %s
                        """,
                        (document_id,),
                    )
                    cursor.execute(
                        """
                        UPDATE retrieval.projection_outbox
                        SET status = 'complete',
                            completed_at = now(),
                            error = NULL
                        WHERE evidence_id = %s
                          AND source_revision = %s
                        """,
                        (document.evidence_id, document.source_revision),
                    )
                    document_count += 1

        with conn.transaction():
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE retrieval.documents document
                    SET is_current = false,
                        index_state = 'superseded',
                        superseded_at = now()
                    WHERE document.is_current
                      AND NOT EXISTS (
                        SELECT 1
                        FROM casework.v_evidence_documents source
                        WHERE source.evidence_id = document.evidence_id
                      )
                    """
                )
                cursor.execute(
                    """
                    UPDATE retrieval.projection_builds
                    SET status = 'complete',
                        completed_at = now(),
                        document_count = %s,
                        chunk_count = %s,
                        cache_hit_count = %s,
                        embedded_count = %s
                    WHERE build_id = %s
                    """,
                    (
                        document_count,
                        chunk_count,
                        cache_hits,
                        embedded_count,
                        build_id,
                    ),
                )
    except Exception as exc:
        conn.rollback()
        _mark_build_failed(conn, build_id, str(exc))
        conn.commit()
        raise

    return {
        "build_id": str(build_id),
        "projection_version": version,
        "embedding_model": model_id,
        "documents_projected": document_count,
        "documents_skipped": skipped_count,
        "chunks_projected": chunk_count,
        "embedding_cache_hits": cache_hits,
        "embeddings_created": embedded_count,
    }
