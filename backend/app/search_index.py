from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Callable, Iterable, Sequence
import uuid

from psycopg.rows import dict_row, tuple_row

from .embeddings import bedrock_embeddings, to_pgvector

EMBEDDING_DIMENSIONS = 1024
RENDERER_VERSION = "casework-renderer-v1"
CHUNKER_VERSION = "paragraph-chunker-v1"
ANALYZE_AFTER_INDEXED_DOCUMENTS = 1000
INDEX_BULK_THRESHOLD = 100
INDEX_WRITE_BATCH_SIZE = 500
SEARCH_INDEX_NAMESPACE = uuid.UUID("2ed19275-d22d-4d84-bd93-d8d2ae99ee5b")


class MissingEmbeddingsError(RuntimeError):
    pass


class EmbeddingCacheIntegrityError(RuntimeError):
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
    service_name: str | None
    engine_version: str | None
    aws_region: str | None
    occurred_at: object
    metadata: dict
    search_document_hash: str
    chunks: tuple[Chunk, ...]


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _split_long_paragraph(paragraph: str, max_chars: int) -> list[str]:
    if len(paragraph) <= max_chars:
        return [paragraph]

    pieces: list[str] = []
    remaining = paragraph
    while len(remaining) > max_chars:
        split_at = remaining.rfind(" ", 0, max_chars + 1)
        if split_at <= 0:
            split_at = max_chars
        pieces.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        pieces.append(remaining)
    return pieces


def chunk_text(text: str, max_chars: int = 1600) -> tuple[Chunk, ...]:
    paragraphs = [
        piece
        for part in text.split("\n\n")
        if part.strip()
        for piece in _split_long_paragraph(" ".join(part.split()), max_chars)
    ]
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

    @property
    def manifest_path(self) -> Path:
        return self.path.with_name(f"{self.path.name}.manifest.json")

    def digest(self) -> str:
        """Digest the cache contents, not the file bytes.

        Returns:
            A hex SHA-256 over every key and vector in sorted key order, so the
            value is independent of JSON formatting and line order.
        """
        accumulator = hashlib.sha256()
        for key in sorted(self._vectors):
            accumulator.update(key.encode("utf-8"))
            accumulator.update(b"\0")
            accumulator.update(
                ",".join(repr(value) for value in self._vectors[key]).encode("utf-8")
            )
            accumulator.update(b"\n")
        return accumulator.hexdigest()

    def verify(self) -> dict[str, object]:
        """Check the loaded cache against its shipped manifest.

        Every workshop account loads the same artifact, so a truncated or edited
        cache would silently change ranking for one account only. This turns that
        into a load-time failure.

        Returns:
            The manifest that was verified.

        Raises:
            EmbeddingCacheIntegrityError: The manifest is absent, unreadable, or
                disagrees with the loaded cache.
        """
        if not self.manifest_path.exists():
            raise EmbeddingCacheIntegrityError(
                f"{self.manifest_path} is missing; regenerate it with "
                "backend/scripts/build_search_index.py --write-cache-manifest"
            )
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise EmbeddingCacheIntegrityError(
                f"{self.manifest_path} is not valid JSON: {error}"
            ) from error
        for field in ("entry_count", "dimensions", "content_sha256"):
            if field not in manifest:
                raise EmbeddingCacheIntegrityError(
                    f"{self.manifest_path} is missing the {field!r} field"
                )
        if manifest["dimensions"] != EMBEDDING_DIMENSIONS:
            raise EmbeddingCacheIntegrityError(
                f"{self.manifest_path} declares {manifest['dimensions']} dimensions, "
                f"but this build embeds at {EMBEDDING_DIMENSIONS}"
            )
        if manifest["entry_count"] != len(self._vectors):
            raise EmbeddingCacheIntegrityError(
                f"{self.path} holds {len(self._vectors)} embeddings, but "
                f"{self.manifest_path} declares {manifest['entry_count']}"
            )
        actual = self.digest()
        if manifest["content_sha256"] != actual:
            raise EmbeddingCacheIntegrityError(
                f"{self.path} content digest {actual} does not match "
                f"{manifest['content_sha256']} in {self.manifest_path}"
            )
        return manifest

    def write_manifest(self, *, model_id: str) -> dict[str, object]:
        manifest = {
            "cache": self.path.name,
            "model_id": model_id,
            "dimensions": EMBEDDING_DIMENSIONS,
            "entry_count": len(self._vectors),
            "content_sha256": self.digest(),
        }
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest

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

    def retain(self, model_id: str, text_hashes: Iterable[str]) -> int:
        retained_keys = {self.key(model_id, text_hash) for text_hash in text_hashes}
        removed = len(self._vectors) - len(self._vectors.keys() & retained_keys)
        self._vectors = {
            key: vector
            for key, vector in self._vectors.items()
            if key in retained_keys
        }
        return removed

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


def search_index_version(model_id: str) -> str:
    return f"{RENDERER_VERSION}:{CHUNKER_VERSION}:{model_id}"


def _load_documents(
    conn,
    source_systems: Sequence[str] | None = None,
) -> list[Document]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT *
            FROM casework.v_evidence_documents
            WHERE (%s::text[] IS NULL OR source_system = ANY(%s::text[]))
            ORDER BY evidence_kind, external_key
            """,
            (source_systems, source_systems),
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
            service_name=row["service_name"],
            engine_version=row["engine_version"],
            aws_region=row["aws_region"],
            occurred_at=row["occurred_at"],
            metadata=row["metadata"],
            search_document_hash=row["search_document_hash"],
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
    prune_unused: bool,
) -> tuple[dict[str, list[float]], int, int, int]:
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

    pruned_count = cache.retain(model_id, unique) if prune_unused else 0
    if missing or pruned_count:
        cache.save()

    return vectors, cache_hits, len(missing), pruned_count


def _document_version_id(document: Document, version: str) -> uuid.UUID:
    return uuid.uuid5(
        SEARCH_INDEX_NAMESPACE,
        f"document:{document.evidence_id}:{version}:{document.search_document_hash}",
    )


def _chunk_version_id(document_version_id: uuid.UUID, chunk: Chunk) -> uuid.UUID:
    return uuid.uuid5(
        SEARCH_INDEX_NAMESPACE,
        f"chunk:{document_version_id}:{chunk.ordinal}:{chunk.text_hash}",
    )


def _create_build(conn, version: str, model_id: str) -> uuid.UUID:
    with conn.cursor(row_factory=tuple_row) as cursor:
        cursor.execute(
            """
            INSERT INTO retrieval.search_index_builds(
              search_index_version,
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
            UPDATE retrieval.search_index_builds
            SET status = 'failed',
                completed_at = now(),
                error = %s
            WHERE build_id = %s
            """,
            (error[:4000], build_id),
        )


def _complete_document_versions(conn) -> set[uuid.UUID]:
    with conn.cursor(row_factory=tuple_row) as cursor:
        cursor.execute(
            """
            SELECT document.document_version_id
            FROM retrieval.documents document
            JOIN retrieval.search_index_builds build
              ON build.build_id = document.build_id
            WHERE document.is_current
              AND document.index_state = 'ready'
              AND build.status = 'complete'
            """
        )
        return {row[0] for row in cursor.fetchall()}


def _write_index_batch(
    cursor,
    batch: Sequence[tuple[Document, uuid.UUID]],
    *,
    build_id: uuid.UUID,
    version: str,
    model_id: str,
    vectors: dict[str, list[float]],
) -> None:
    cursor.executemany(
        """
        INSERT INTO retrieval.documents(
          document_version_id,
          evidence_id,
          build_id,
          search_index_version,
          search_document_hash,
          source_revision,
          evidence_kind,
          external_key,
          title,
          source_system,
          source_uri,
          source_updated_at,
          acl,
          acl_visibility,
          acl_principals,
          cluster_id,
          incident_id,
          account_name,
          severity,
          environment,
          service_name,
          engine_version,
          aws_region,
          occurred_at,
          metadata,
          index_state,
          is_current
        )
        VALUES (
          %(document_version_id)s,
          %(evidence_id)s,
          %(build_id)s,
          %(search_index_version)s,
          %(search_document_hash)s,
          %(source_revision)s,
          %(evidence_kind)s,
          %(external_key)s,
          %(title)s,
          %(source_system)s,
          %(source_uri)s,
          %(source_updated_at)s,
          %(acl)s::jsonb,
          %(acl_visibility)s,
          %(acl_principals)s::text[],
          %(cluster_id)s,
          %(incident_id)s,
          %(account_name)s,
          %(severity)s,
          %(environment)s,
          %(service_name)s,
          %(engine_version)s,
          %(aws_region)s,
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
        (
            {
                "document_version_id": document_id,
                "evidence_id": document.evidence_id,
                "build_id": build_id,
                "search_index_version": version,
                "search_document_hash": document.search_document_hash,
                "source_revision": document.source_revision,
                "evidence_kind": document.evidence_kind,
                "external_key": document.external_key,
                "title": document.title,
                "source_system": document.source_system,
                "source_uri": document.source_uri,
                "source_updated_at": document.source_updated_at,
                "acl": json.dumps(document.acl),
                "acl_visibility": document.acl.get(
                    "visibility",
                    "restricted",
                ),
                "acl_principals": list(document.acl.get("principals") or []),
                "cluster_id": document.cluster_id,
                "incident_id": document.incident_id,
                "account_name": document.account_name,
                "severity": document.severity,
                "environment": document.environment,
                "service_name": document.service_name,
                "engine_version": document.engine_version,
                "aws_region": document.aws_region,
                "occurred_at": document.occurred_at,
                "metadata": json.dumps(document.metadata),
            }
            for document, document_id in batch
        ),
    )
    cursor.executemany(
        """
        INSERT INTO retrieval.chunks(
          chunk_version_id,
          document_version_id,
          evidence_id,
          chunk_ordinal,
          section_title,
          chunk_text,
          chunk_hash,
          embedding,
          embedding_model,
          embedding_input_type,
          embedding_state,
          is_current,
          evidence_kind,
          source_system,
          source_updated_at,
          occurred_at,
          acl,
          acl_visibility,
          acl_principals,
          cluster_id,
          incident_id,
          account_name,
          severity,
          environment,
          service_name,
          engine_version,
          aws_region
        )
        VALUES (
          %s, %s, %s, %s, %s, %s, %s, %s::vector, %s,
          'search_document', 'ready', false, %s, %s, %s, %s,
          %s::jsonb, %s, %s::text[], %s, %s, %s, %s, %s,
          %s, %s, %s
        )
        ON CONFLICT (chunk_version_id)
        DO UPDATE SET
          embedding = EXCLUDED.embedding,
          embedding_model = EXCLUDED.embedding_model,
          embedding_input_type = EXCLUDED.embedding_input_type,
          embedding_state = 'ready',
          is_current = false,
          evidence_kind = EXCLUDED.evidence_kind,
          source_system = EXCLUDED.source_system,
          source_updated_at = EXCLUDED.source_updated_at,
          occurred_at = EXCLUDED.occurred_at,
          acl = EXCLUDED.acl,
          acl_visibility = EXCLUDED.acl_visibility,
          acl_principals = EXCLUDED.acl_principals,
          cluster_id = EXCLUDED.cluster_id,
          incident_id = EXCLUDED.incident_id,
          account_name = EXCLUDED.account_name,
          severity = EXCLUDED.severity,
          environment = EXCLUDED.environment,
          service_name = EXCLUDED.service_name,
          engine_version = EXCLUDED.engine_version,
          aws_region = EXCLUDED.aws_region
        """,
        (
            (
                _chunk_version_id(document_id, chunk),
                document_id,
                document.evidence_id,
                chunk.ordinal,
                chunk.section_title,
                chunk.text,
                chunk.text_hash,
                to_pgvector(vectors[chunk.text_hash]),
                model_id,
                document.evidence_kind,
                document.source_system,
                document.source_updated_at,
                document.occurred_at,
                json.dumps(document.acl),
                document.acl.get("visibility", "restricted"),
                list(document.acl.get("principals") or []),
                document.cluster_id,
                document.incident_id,
                document.account_name,
                document.severity,
                document.environment,
                document.service_name,
                document.engine_version,
                document.aws_region,
            )
            for document, document_id in batch
            for chunk in document.chunks
        ),
    )


def _persist_search_index_bulk(
    conn,
    *,
    documents: list[Document],
    vectors: dict[str, list[float]],
    build_id: uuid.UUID,
    version: str,
    model_id: str,
    cache_hits: int,
    embedded_count: int,
    source_systems: Sequence[str] | None,
) -> dict:
    reusable = _complete_document_versions(conn)
    conn.commit()
    pending = [
        (document, _document_version_id(document, version))
        for document in documents
        if _document_version_id(document, version) not in reusable
    ]
    skipped_count = len(documents) - len(pending)
    document_count = len(pending)
    chunk_count = sum(
        len(document.chunks)
        for document, _document_id in pending
    )

    try:
        with conn.transaction():
            with conn.cursor() as cursor:
                for offset in range(0, len(pending), INDEX_WRITE_BATCH_SIZE):
                    _write_index_batch(
                        cursor,
                        pending[offset : offset + INDEX_WRITE_BATCH_SIZE],
                        build_id=build_id,
                        version=version,
                        model_id=model_id,
                        vectors=vectors,
                    )

                cursor.execute(
                    """
                    UPDATE retrieval.documents previous
                    SET is_current = false,
                        index_state = 'superseded',
                        superseded_at = now()
                    WHERE previous.is_current
                      AND EXISTS (
                        SELECT 1
                        FROM retrieval.documents replacement
                        WHERE replacement.build_id = %s
                          AND replacement.evidence_id = previous.evidence_id
                          AND replacement.document_version_id <>
                              previous.document_version_id
                      )
                    """,
                    (build_id,),
                )
                cursor.execute(
                    """
                    UPDATE retrieval.chunks previous
                    SET is_current = false
                    WHERE previous.is_current
                      AND EXISTS (
                        SELECT 1
                        FROM retrieval.documents replacement
                        WHERE replacement.build_id = %s
                          AND replacement.evidence_id = previous.evidence_id
                          AND replacement.document_version_id <>
                              previous.document_version_id
                      )
                    """,
                    (build_id,),
                )
                cursor.execute(
                    """
                    UPDATE retrieval.documents
                    SET is_current = true,
                        index_state = 'ready',
                        indexed_at = now(),
                        superseded_at = NULL
                    WHERE build_id = %s
                    """,
                    (build_id,),
                )
                cursor.execute(
                    """
                    UPDATE retrieval.chunks chunk
                    SET is_current = true
                    FROM retrieval.documents document
                    WHERE document.build_id = %s
                      AND document.document_version_id =
                          chunk.document_version_id
                      AND chunk.embedding_state = 'ready'
                    """,
                    (build_id,),
                )
                cursor.execute(
                    """
                    UPDATE retrieval.search_index_queue queue
                    SET status = 'complete',
                        completed_at = now(),
                        error = NULL
                    FROM retrieval.documents document
                    JOIN retrieval.search_index_builds build
                      ON build.build_id = document.build_id
                    WHERE document.evidence_id = queue.evidence_id
                      AND document.source_revision = queue.source_revision
                      AND document.is_current
                      AND document.index_state = 'ready'
                      AND (
                        build.status = 'complete'
                        OR build.build_id = %s
                      )
                    """,
                    (build_id,),
                )
                cursor.execute(
                    """
                    WITH current_sources AS MATERIALIZED (
                      SELECT evidence_id
                      FROM casework.v_evidence_documents
                      WHERE (%s::text[] IS NULL OR source_system = ANY(%s::text[]))
                    )
                    UPDATE retrieval.documents document
                    SET is_current = false,
                        index_state = 'superseded',
                        superseded_at = now()
                    WHERE document.is_current
                      AND (
                        %s::text[] IS NULL
                        OR document.source_system = ANY(%s::text[])
                      )
                      AND NOT EXISTS (
                        SELECT 1
                        FROM current_sources source
                        WHERE source.evidence_id = document.evidence_id
                      )
                    """,
                    (
                        source_systems,
                        source_systems,
                        source_systems,
                        source_systems,
                    ),
                )
                superseded_count = cursor.rowcount
                cursor.execute(
                    """
                    UPDATE retrieval.chunks chunk
                    SET is_current = false
                    WHERE chunk.is_current
                      AND NOT EXISTS (
                        SELECT 1
                        FROM retrieval.documents document
                        WHERE document.document_version_id =
                            chunk.document_version_id
                          AND document.is_current
                          AND document.index_state = 'ready'
                      )
                    """
                )
                cursor.execute(
                    """
                    UPDATE retrieval.search_index_queue queue
                    SET status = 'complete',
                        completed_at = now(),
                        error = NULL
                    FROM casework.evidence_items source
                    WHERE source.evidence_id = queue.evidence_id
                      AND source.is_deleted
                      AND (
                        %s::text[] IS NULL
                        OR source.source_system = ANY(%s::text[])
                      )
                      AND queue.status IN ('pending', 'claimed')
                    """,
                    (source_systems, source_systems),
                )
                cursor.execute(
                    """
                    UPDATE retrieval.search_index_builds
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
                if document_count >= ANALYZE_AFTER_INDEXED_DOCUMENTS:
                    cursor.execute("ANALYZE retrieval.documents")
                    cursor.execute("ANALYZE retrieval.chunks")

    except BaseException as exc:
        conn.rollback()
        _mark_build_failed(conn, build_id, str(exc) or type(exc).__name__)
        conn.commit()
        raise

    return {
        "build_id": str(build_id),
        "search_index_version": version,
        "embedding_model": model_id,
        "documents_indexed": document_count,
        "documents_skipped": skipped_count,
        "documents_superseded": superseded_count,
        "chunks_indexed": chunk_count,
        "embedding_cache_hits": cache_hits,
        "embeddings_created": embedded_count,
        "statistics_refreshed": (
            document_count >= ANALYZE_AFTER_INDEXED_DOCUMENTS
        ),
    }


def rebuild_search_index(
    conn,
    *,
    model_id: str,
    cache_path: Path,
    embed_missing: bool = False,
    batch_size: int = 48,
    embedder: Callable[[list[str]], list[list[float]]] | None = None,
    verify_cache: bool = False,
    prune_unused_cache_entries: bool = False,
    source_systems: Sequence[str] | None = None,
) -> dict:
    if source_systems is not None and not source_systems:
        raise ValueError("source_systems must be null or contain at least one value")
    if source_systems is not None and prune_unused_cache_entries:
        raise ValueError(
            "a source-scoped build cannot prune a cache shared by other sources"
        )
    version = search_index_version(model_id)
    documents = _load_documents(conn, source_systems)
    build_id = _create_build(conn, version, model_id)
    conn.commit()

    cache = EmbeddingCache(cache_path)
    cache.load()
    try:
        if verify_cache:
            cache.verify()
        vectors, cache_hits, embedded_count, pruned_count = _resolve_embeddings(
            documents,
            cache,
            model_id,
            embed_missing=embed_missing,
            batch_size=batch_size,
            embedder=embedder,
            prune_unused=prune_unused_cache_entries,
        )
    except Exception as exc:
        _mark_build_failed(conn, build_id, str(exc))
        conn.commit()
        raise

    if len(documents) >= INDEX_BULK_THRESHOLD:
        result = _persist_search_index_bulk(
            conn,
            documents=documents,
            vectors=vectors,
            build_id=build_id,
            version=version,
            model_id=model_id,
            cache_hits=cache_hits,
            embedded_count=embedded_count,
            source_systems=source_systems,
        )
        result["embedding_cache_entries_pruned"] = pruned_count
        result["source_systems"] = (
            list(source_systems) if source_systems else None
        )
        return result

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
                        cursor.execute(
                            """
                            UPDATE retrieval.search_index_queue
                            SET status = 'complete',
                                completed_at = now(),
                                error = NULL
                            WHERE evidence_id = %s
                              AND source_revision = %s
                            """,
                            (document.evidence_id, document.source_revision),
                        )
                        skipped_count += 1
                        continue

                    cursor.execute(
                        """
                        INSERT INTO retrieval.documents(
                          document_version_id,
                          evidence_id,
                          build_id,
                          search_index_version,
                          search_document_hash,
                          source_revision,
                          evidence_kind,
                          external_key,
                          title,
                          source_system,
                          source_uri,
                          source_updated_at,
                          acl,
                          acl_visibility,
                          acl_principals,
                          cluster_id,
                          incident_id,
                          account_name,
                          severity,
                          environment,
                          service_name,
                          engine_version,
                          aws_region,
                          occurred_at,
                          metadata,
                          index_state,
                          is_current
                        )
                        VALUES (
                          %(document_version_id)s,
                          %(evidence_id)s,
                          %(build_id)s,
                          %(search_index_version)s,
                          %(search_document_hash)s,
                          %(source_revision)s,
                          %(evidence_kind)s,
                          %(external_key)s,
                          %(title)s,
                          %(source_system)s,
                          %(source_uri)s,
                          %(source_updated_at)s,
                          %(acl)s::jsonb,
                          %(acl_visibility)s,
                          %(acl_principals)s::text[],
                          %(cluster_id)s,
                          %(incident_id)s,
                          %(account_name)s,
                          %(severity)s,
                          %(environment)s,
                          %(service_name)s,
                          %(engine_version)s,
                          %(aws_region)s,
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
                            "search_index_version": version,
                            "search_document_hash": document.search_document_hash,
                            "source_revision": document.source_revision,
                            "evidence_kind": document.evidence_kind,
                            "external_key": document.external_key,
                            "title": document.title,
                            "source_system": document.source_system,
                            "source_uri": document.source_uri,
                            "source_updated_at": document.source_updated_at,
                            "acl": json.dumps(document.acl),
                            "acl_visibility": document.acl.get(
                                "visibility",
                                "restricted",
                            ),
                            "acl_principals": list(
                                document.acl.get("principals") or []
                            ),
                            "cluster_id": document.cluster_id,
                            "incident_id": document.incident_id,
                            "account_name": document.account_name,
                            "severity": document.severity,
                            "environment": document.environment,
                            "service_name": document.service_name,
                            "engine_version": document.engine_version,
                            "aws_region": document.aws_region,
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
                              evidence_id,
                              chunk_ordinal,
                              section_title,
                              chunk_text,
                              chunk_hash,
                              embedding,
                              embedding_model,
                              embedding_input_type,
                              embedding_state,
                              is_current,
                              evidence_kind,
                              source_system,
                              source_updated_at,
                              occurred_at,
                              acl,
                              acl_visibility,
                              acl_principals,
                              cluster_id,
                              incident_id,
                              account_name,
                              severity,
                              environment,
                              service_name,
                              engine_version,
                              aws_region
                            )
                            VALUES (
                              %s, %s, %s, %s, %s, %s, %s, %s::vector, %s,
                              'search_document', 'ready', false, %s, %s, %s, %s,
                              %s::jsonb, %s, %s::text[], %s, %s, %s, %s, %s,
                              %s, %s, %s
                            )
                            ON CONFLICT (chunk_version_id)
                            DO UPDATE SET
                              embedding = EXCLUDED.embedding,
                              embedding_model = EXCLUDED.embedding_model,
                              embedding_input_type = EXCLUDED.embedding_input_type,
                              embedding_state = 'ready',
                              evidence_kind = EXCLUDED.evidence_kind,
                              source_system = EXCLUDED.source_system,
                              source_updated_at = EXCLUDED.source_updated_at,
                              occurred_at = EXCLUDED.occurred_at,
                              acl = EXCLUDED.acl,
                              acl_visibility = EXCLUDED.acl_visibility,
                              acl_principals = EXCLUDED.acl_principals,
                              cluster_id = EXCLUDED.cluster_id,
                              incident_id = EXCLUDED.incident_id,
                              account_name = EXCLUDED.account_name,
                              severity = EXCLUDED.severity,
                              environment = EXCLUDED.environment,
                              service_name = EXCLUDED.service_name,
                              engine_version = EXCLUDED.engine_version,
                              aws_region = EXCLUDED.aws_region
                            """,
                            (
                                chunk_id,
                                document_id,
                                document.evidence_id,
                                chunk.ordinal,
                                chunk.section_title,
                                chunk.text,
                                chunk.text_hash,
                                to_pgvector(vectors[chunk.text_hash]),
                                model_id,
                                document.evidence_kind,
                                document.source_system,
                                document.source_updated_at,
                                document.occurred_at,
                                json.dumps(document.acl),
                                document.acl.get("visibility", "restricted"),
                                list(document.acl.get("principals") or []),
                                document.cluster_id,
                                document.incident_id,
                                document.account_name,
                                document.severity,
                                document.environment,
                                document.service_name,
                                document.engine_version,
                                document.aws_region,
                            ),
                        )
                        chunk_count += 1

                    cursor.execute(
                        """
                        UPDATE retrieval.chunks
                        SET is_current = false
                        WHERE evidence_id = %s
                          AND is_current
                          AND document_version_id <> %s
                        """,
                        (document.evidence_id, document_id),
                    )
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
                        UPDATE retrieval.chunks
                        SET is_current = true
                        WHERE document_version_id = %s
                          AND embedding_state = 'ready'
                        """,
                        (document_id,),
                    )
                    cursor.execute(
                        """
                        UPDATE retrieval.search_index_queue
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
                      AND (
                        %s::text[] IS NULL
                        OR document.source_system = ANY(%s::text[])
                      )
                      AND NOT EXISTS (
                        SELECT 1
                        FROM casework.v_evidence_documents source
                        WHERE source.evidence_id = document.evidence_id
                      )
                    """,
                    (source_systems, source_systems),
                )
                superseded_count = cursor.rowcount
                cursor.execute(
                    """
                    UPDATE retrieval.chunks chunk
                    SET is_current = false
                    WHERE chunk.is_current
                      AND NOT EXISTS (
                        SELECT 1
                        FROM retrieval.documents document
                        WHERE document.document_version_id = chunk.document_version_id
                          AND document.is_current
                          AND document.index_state = 'ready'
                      )
                    """
                )
                cursor.execute(
                    """
                    UPDATE retrieval.search_index_queue queue
                    SET status = 'complete',
                        completed_at = now(),
                        error = NULL
                    FROM casework.evidence_items source
                    WHERE source.evidence_id = queue.evidence_id
                      AND source.is_deleted
                      AND (
                        %s::text[] IS NULL
                        OR source.source_system = ANY(%s::text[])
                      )
                      AND queue.status IN ('pending', 'claimed')
                    """,
                    (source_systems, source_systems),
                )
                cursor.execute(
                    """
                    UPDATE retrieval.search_index_builds
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
                if document_count >= ANALYZE_AFTER_INDEXED_DOCUMENTS:
                    cursor.execute("ANALYZE retrieval.documents")
                    cursor.execute("ANALYZE retrieval.chunks")

    except Exception as exc:
        conn.rollback()
        _mark_build_failed(conn, build_id, str(exc))
        conn.commit()
        raise

    return {
        "build_id": str(build_id),
        "search_index_version": version,
        "embedding_model": model_id,
        "documents_indexed": document_count,
        "documents_skipped": skipped_count,
        "documents_superseded": superseded_count,
        "chunks_indexed": chunk_count,
        "embedding_cache_hits": cache_hits,
        "embeddings_created": embedded_count,
        "embedding_cache_entries_pruned": pruned_count,
        "statistics_refreshed": (
            document_count >= ANALYZE_AFTER_INDEXED_DOCUMENTS
        ),
        "source_systems": list(source_systems) if source_systems else None,
    }
