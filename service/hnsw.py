"""Read-only endpoints behind the HNSW instrument.

Three of the four are plain reads. The fourth, `probe`, issues a real query and is
the only one with a cost ceiling worth stating: it never reaches a sequential scan,
because recall is computed against precomputed ground truth rather than by re-running
the exact query. That exact query measures 2,355 ms and 2,300,855 shared buffer hits
on this cluster — one per interaction, times a room of participants, would make an
optional Labs surface a load generator.

Every HNSW setting is applied through `mosaic_search.configure_hnsw`, the same
function served retrieval calls. A probe that reached `set_config` directly would be
measuring a path the request path never takes.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import psycopg

from scripts.retrieval_profile import explain
from scripts.seed_exact_neighbors import (
    UNRESOLVED_MANIFEST,
    StaleGroundTruth,
    load_ground_truth,
)
from service.config import get_settings
from service.db import connect
from service.hnsw_presets import (
    ANCHOR_PREDICATE,
    PRESET_KEYS,
    PRESETS_BY_KEY,
    FilterPreset,
)

ROOT = Path(__file__).resolve().parents[1]
MEASURED_ARTIFACT = ROOT / "data" / "benchmarks" / "hnsw_measured.json"

HNSW_INDEX = "mosaic_search.product_document_embedding_hnsw_cosine_idx"
PRODUCT_DOCUMENT = "mosaic_search.product_document"

# The measured worst case across every enumerated parameter combination is 283 ms.
# Five seconds is far above that and far below anything that holds a connection long
# enough to matter to another participant.
PROBE_STATEMENT_TIMEOUT = "5s"

# Settings worth showing next to the numbers they explain. `work_mem` is here because
# it is half of the memory budget that silently truncates filtered scans.
REPORTED_SETTINGS = (
    "work_mem",
    "maintenance_work_mem",
    "shared_buffers",
    "effective_cache_size",
    "max_parallel_workers_per_gather",
)

PROBE_SQL = """
SELECT product_id
FROM mosaic_search.product_document
WHERE embedding IS NOT NULL{predicate}
ORDER BY embedding <=> %s
LIMIT %s
"""

# halfvec is a cast of the same column, so the query must repeat the cast to reach the
# expression index. Same two bound parameters as fp32.
HALFVEC_PROBE_SQL = """
SELECT product_id
FROM mosaic_search.product_document
WHERE embedding IS NOT NULL{predicate}
ORDER BY embedding::halfvec(1024) <=> %s::halfvec(1024)
LIMIT %s
"""

# Binary is necessarily two-pass. `bit_hamming_ops` has no cosine operator: the first pass
# ranks by bit differences with `<~>`, so a second pass over the fp32 vectors is what
# recovers the ordering. Four bound parameters: vector, overfetch, vector, k.
BINARY_PROBE_SQL = """
SELECT product_id FROM (
    SELECT product_id, embedding
    FROM mosaic_search.product_document
    WHERE embedding IS NOT NULL{predicate}
    ORDER BY binary_quantize(embedding)::bit(1024)
             <~> binary_quantize(%s::vector(1024))::bit(1024)
    LIMIT %s
) AS candidates
ORDER BY candidates.embedding <=> %s
LIMIT %s
"""

REPRESENTATION_SQL: dict[str, str] = {
    "fp32": PROBE_SQL,
    "halfvec": HALFVEC_PROBE_SQL,
    "binary": BINARY_PROBE_SQL,
}

# The index each representation must reach. The probe returns this alongside the plan so a
# reader can check the query landed on the index it claims to be measuring.
REPRESENTATION_INDEX: dict[str, str] = {
    "fp32": "product_document_embedding_hnsw_cosine_idx",
    "halfvec": "product_document_embedding_hnsw_halfvec_idx",
    "binary": "product_document_embedding_hnsw_binary_idx",
}

_PRODUCT_COLUMNS = """
    product_id, title, brand_name, domain::text AS domain, category_key,
    catalog_asset_key, media_tier::text AS media_tier
"""

# The two indexes only `db/sql/19_indexes_quantized.sql` creates. No bootstrap phase
# runs that file, so on a freshly bootstrapped cluster neither exists.
QUANTIZED_REPRESENTATION_INDEXES = (
    REPRESENTATION_INDEX["halfvec"],
    REPRESENTATION_INDEX["binary"],
)

# The Makefile target that builds each representation's index, quoted into the
# refusal so a reader is told the one command that resolves it.
REPRESENTATION_RECOVERY: dict[str, str] = {
    "fp32": "run `make db-drop-invalid-indexes` then `make db-index-concurrent`",
    "halfvec": "run `make db-index-quantized` (roughly 9 minutes for both indexes)",
    "binary": "run `make db-index-quantized` (roughly 9 minutes for both indexes)",
}

# `indisvalid` alone is not enough. An interrupted CREATE INDEX CONCURRENTLY leaves a
# relation that exists, is skipped by IF NOT EXISTS, and cannot serve a scan; the
# planner ignores it while `to_regclass` still finds it. Same shape as
# `service.db.readiness()`, which gates the three required retrieval indexes.
INDEX_STATE_SQL = """
SELECT required.name AS name,
       CASE
           WHEN index_state.indexrelid IS NULL THEN 'missing'
           WHEN index_state.indisvalid AND index_state.indisready THEN 'valid'
           ELSE 'invalid'
       END AS state
FROM unnest(%s::text[]) AS required(name)
LEFT JOIN pg_index AS index_state
  ON index_state.indexrelid = (
      SELECT index_relation.oid
      FROM pg_class AS index_relation
      JOIN pg_namespace AS index_schema
        ON index_schema.oid = index_relation.relnamespace
      WHERE index_schema.nspname = 'mosaic_search'
        AND index_relation.relname = required.name
        AND index_relation.relkind = 'i'
  )
"""


class RepresentationUnavailable(RuntimeError):
    """A representation was requested whose index is missing or not usable."""


def _index_states(connection: Any, names: Sequence[str]) -> dict[str, str]:
    """Catalog state of each named index on an already-open connection."""
    rows = connection.execute(INDEX_STATE_SQL, ([str(name) for name in names],))
    return {row["name"]: row["state"] for row in rows.fetchall()}


def index_states(names: Sequence[str]) -> dict[str, str]:
    """Report each named `mosaic_search` index as `valid`, `invalid`, or `missing`.

    Args:
        names: Bare index relation names, without the schema qualifier.

    Returns:
        One entry per requested name. A name the catalog does not know is
        `missing`; one that exists but is not both valid and ready is `invalid`.
    """
    with connect() as connection:
        return _index_states(connection, names)


def require_representation_index(connection: Any, representation: str) -> None:
    """Refuse to probe a representation whose index cannot serve the query.

    Without this the query still runs: it falls back to a sequential scan over
    3,870 MB of TOASTed vectors, hits the 5s statement timeout, and reports the
    failure as a timeout rather than as the missing index it is.

    Raises:
        RepresentationUnavailable: The index is missing or not valid and ready.
    """
    index_name = REPRESENTATION_INDEX[representation]
    state = _index_states(connection, [index_name]).get(index_name, "missing")
    if state == "valid":
        return
    raise RepresentationUnavailable(
        explain(
            f"index {index_name} for representation {representation!r} is {state}",
            REPRESENTATION_RECOVERY[representation],
        )
    )


def _measured_attribution(provenance: dict[str, Any]) -> dict[str, Any]:
    """Decide whether the committed artifact describes the running system.

    Binding conjunction over exactly two facts, mirroring
    `service.scorecard._attribution`:

        artifact.provenance.source_worktree_dirty == False
        AND artifact.provenance.dataset_manifest_sha256 == the connected corpus,
            with that manifest resolved

    Revision equality is deliberately not in the conjunction, and for the same
    reason it is absent from the scorecard: `scripts/benchmark_hnsw.py` records
    the revision *before* the artifact it writes is committed, so a strict
    equality would read "measured elsewhere" forever. The revision is carried on
    both sides as display and audit evidence.
    """
    settings = get_settings()
    measured_manifest = provenance.get("dataset_manifest_sha256") or ""
    current_manifest = settings.dataset_manifest_sha256 or ""
    measured_dirty = provenance.get("source_worktree_dirty")

    reasons: list[str] = []
    if current_manifest in ("", UNRESOLVED_MANIFEST):
        reasons.append(
            f"the connected corpus reports an unresolved dataset manifest "
            f"{current_manifest!r}"
        )
    elif measured_manifest != current_manifest:
        reasons.append(
            f"a different dataset manifest (measured {measured_manifest[:12]}, "
            f"connected {current_manifest[:12]})"
        )
    if measured_dirty is not False:
        reasons.append(
            f"a dirty worktree at measurement time "
            f"(source_worktree_dirty is {measured_dirty!r})"
        )

    if reasons:
        note = explain(
            "these numbers were measured elsewhere: " + "; ".join(reasons),
            "re-run `make benchmark-hnsw` against the connected corpus from a "
            "clean worktree, or read the panel as a record of another cluster",
        )
    else:
        note = (
            f"Measured on the connected corpus "
            f"({current_manifest[:12]}) from a clean worktree at revision "
            f"{str(provenance.get('source_revision') or '')[:12]}."
        )
    return {
        "measured_source_revision": provenance.get("source_revision"),
        "measured_source_worktree_dirty": measured_dirty,
        "measured_dataset_manifest_sha256": provenance.get("dataset_manifest_sha256"),
        "current_source_revision": settings.source_revision,
        "current_source_worktree_dirty": settings.source_worktree_dirty,
        "current_dataset_manifest_sha256": settings.dataset_manifest_sha256,
        "attributed": not reasons,
        "attribution_note": note,
    }


def _gate_representations(payload: dict[str, Any]) -> dict[str, Any]:
    """Withhold the representation comparison unless both indexes are usable.

    The artifact advertises `..._halfvec_idx` and `..._binary_idx`. Only
    `db/sql/19_indexes_quantized.sql` creates them and no bootstrap phase runs
    it, so on a freshly bootstrapped cluster those rows describe indexes the
    reader cannot EXPLAIN, inspect, or reproduce.
    """
    if "representations" not in payload:
        return payload
    try:
        states = index_states(QUANTIZED_REPRESENTATION_INDEXES)
    except (RuntimeError, psycopg.Error) as error:
        # The two ways this read fails: no DSN configured (`RuntimeError` from
        # `get_pool`), or the cluster refusing the connection or the query.
        # Neither is swallowed -- an unreachable cluster is a different claim
        # from a missing index, and the reason names which one happened. The
        # exception type, never its message: a psycopg connection failure names
        # the host and user, and this string is served to every participant, so
        # it follows the same rule as the `/api/hnsw/substrate` handler.
        return _withhold_representations(
            payload,
            explain(
                f"index state could not be read from the cluster "
                f"({type(error).__name__})",
                "point DATABASE_URL at the workshop cluster and reload",
            ),
        )
    unusable = {name: state for name, state in states.items() if state != "valid"}
    if not unusable:
        return payload
    listed = ", ".join(f"{name} is {state}" for name, state in sorted(unusable.items()))
    return _withhold_representations(
        payload,
        explain(
            f"the connected cluster has no usable quantized index: {listed}",
            "run `make db-index-quantized` (roughly 9 minutes for both indexes), "
            "or read the halfvec and binary rows as a record of another cluster",
        ),
    )


def _withhold_representations(payload: dict[str, Any], reason: str) -> dict[str, Any]:
    """Drop the representation rows, leaving the reason in their place."""
    gated = {key: value for key, value in payload.items() if key != "representations"}
    gated["representations_unavailable_reason"] = reason
    return gated


def measured() -> dict[str, Any]:
    """Serve the committed measured artifact, refusing anything not measured.

    Two things are added to the file on the way out, both about whether its
    numbers describe the cluster the reader is connected to: `attribution`, and
    the gate that withholds `representations` when the indexes they compare do
    not exist here.
    """
    if not MEASURED_ARTIFACT.exists():
        raise RuntimeError(
            explain(
                f"no measured artifact at {MEASURED_ARTIFACT.name}",
                "run `make benchmark-hnsw`",
            )
        )
    payload = json.loads(MEASURED_ARTIFACT.read_text(encoding="utf-8"))
    if payload.get("kind") != "measured":
        raise RuntimeError(
            explain(
                f"artifact kind is {payload.get('kind')!r}, not 'measured'",
                "regenerate with `make benchmark-hnsw`; this payload renders under a "
                "MEASURED badge and must not carry projected values",
            )
        )
    payload["attribution"] = _measured_attribution(payload.get("provenance") or {})
    return _gate_representations(payload)


def substrate() -> dict[str, Any]:
    """Live index anatomy, storage split, and the settings that explain them."""
    with connect() as connection:
        sizes = connection.execute(
            """
            SELECT pg_relation_size(%(table)s::regclass) AS heap_bytes,
                   pg_relation_size(
                       (SELECT reltoastrelid FROM pg_class
                        WHERE oid = %(table)s::regclass)
                   ) AS toast_bytes,
                   pg_indexes_size(%(table)s::regclass) AS all_indexes_bytes,
                   pg_total_relation_size(%(table)s::regclass) AS total_bytes,
                   pg_relation_size(%(index)s::regclass) AS hnsw_bytes,
                   pg_get_indexdef(%(index)s::regclass) AS index_definition
            """,
            {"table": PRODUCT_DOCUMENT, "index": HNSW_INDEX},
        ).fetchone()
        # No `count(DISTINCT embedding)` here, deliberately. Counting distinct
        # 1024-dimension vectors across 500,000 rows sorts roughly 2 GB against a
        # 4 MB work_mem, and on 2026-08-17 it terminated the Aurora backend outright
        # (client saw "SSL error: unexpected eof while reading"; the instance
        # restarted, uptime 26s). Even had it survived, a 2 GB sort per page load is
        # not something a live endpoint may do. The duplicate-vector count belongs in
        # the offline artifact, computed once.
        counts = connection.execute(
            f"""
            SELECT count(*) FILTER (WHERE embedding IS NOT NULL) AS vector_count,
                   count(*) FILTER (WHERE {ANCHOR_PREDICATE}) AS anchor_count,
                   (SELECT vector_dims(embedding) FROM {PRODUCT_DOCUMENT}
                    WHERE embedding IS NOT NULL LIMIT 1) AS dimensions
            FROM {PRODUCT_DOCUMENT}
            """
        ).fetchone()
        settings = {
            name: connection.execute(
                "SELECT current_setting(%s) AS value", (name,)
            ).fetchone()["value"]
            for name in REPORTED_SETTINGS
        }
        aurora = connection.execute(
            """
            SELECT aurora_db_instance_identifier() AS database_instance_id,
                   current_setting('server_version') AS database_version,
                   (SELECT extversion FROM pg_extension WHERE extname = 'vector')
                       AS vector_extension_version
            """
        ).fetchone()

    return _substrate_payload(
        sizes=dict(sizes), counts=dict(counts), settings=settings, aurora=dict(aurora)
    )


def _substrate_payload(
    *,
    sizes: dict[str, Any],
    counts: dict[str, Any],
    settings: dict[str, str],
    aurora: dict[str, Any],
) -> dict[str, Any]:
    """Shape the live substrate read, deriving the index arithmetic explicitly."""
    vectors = max(1, int(counts["vector_count"]))
    hnsw_bytes = int(sizes["hnsw_bytes"])
    payload_bytes = int(counts["dimensions"] or 0) * 4
    per_vector = round(hnsw_bytes / vectors)
    return {
        "index": {
            "name": HNSW_INDEX,
            "definition": sizes["index_definition"],
            "size_bytes": hnsw_bytes,
            "bytes_per_vector": per_vector,
            "fp32_payload_bytes": payload_bytes,
            "overhead_factor": (
                round(per_vector / payload_bytes, 2) if payload_bytes else None
            ),
        },
        "storage": {
            "heap_bytes": int(sizes["heap_bytes"]),
            "toast_bytes": int(sizes["toast_bytes"] or 0),
            "hnsw_bytes": hnsw_bytes,
            "other_indexes_bytes": int(sizes["all_indexes_bytes"]) - hnsw_bytes,
            "total_bytes": int(sizes["total_bytes"]),
        },
        "corpus": {
            "vector_count": int(counts["vector_count"]),
            "anchor_count": int(counts["anchor_count"]),
            "dimensions": counts["dimensions"],
        },
        "aurora": aurora | {"instance_class": get_settings().aurora_instance_class},
        "settings": settings,
    }


def neighborhood_band(distances: list[float]) -> dict[str, float] | None:
    """Distance span of the neighbours, excluding the anchor's own zero distance.

    Measured on anchor 1: neighbours 2 through 10 span 0.3374 to 0.3697, a width of
    0.032. That near-absence of gradient is why HNSW recall is hard on this corpus and
    why it saturates at the served ef_search — a property of the distance
    distribution, not of pgvector's implementation.

    Args:
        distances: Cosine distances in rank order, including the anchor's own 0.0.

    Returns:
        `{"nearest", "kth", "width"}`, or `None` when no neighbour other than the
        anchor itself was returned.
    """
    neighbors = [distance for distance in distances if distance > 0.0]
    if not neighbors:
        return None
    return {
        "nearest": min(neighbors),
        "kth": max(neighbors),
        "width": round(max(neighbors) - min(neighbors), 6),
    }


def anchors() -> list[dict[str, Any]]:
    """The query anchors the instrument offers: the imaged retrieval anchors."""
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT {_PRODUCT_COLUMNS}
            FROM {PRODUCT_DOCUMENT}
            WHERE embedding IS NOT NULL AND {ANCHOR_PREDICATE}
            ORDER BY product_id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def probe_sql(preset: FilterPreset, representation: str = "fp32") -> str:
    """The exact SQL the probe runs, for a preset and a representation.

    `embedding IS NOT NULL` is not optional in any of the three shapes. Every index is
    partial, so a query that drops the predicate cannot use it and falls back to
    Sort + Seq Scan, measured at 2,182 ms against 2.7 ms for identical rows.
    """
    predicate = f" AND {preset.predicate_sql}" if preset.predicate_sql else ""
    template = REPRESENTATION_SQL.get(representation)
    if template is None:
        raise KeyError(
            explain(
                f"representation {representation!r}",
                f"use one of {sorted(REPRESENTATION_SQL)}",
            )
        )
    return template.format(predicate=predicate)


def probe_parameters(request: Any, vector: Any) -> list[Any]:
    """Bound parameters for the probe, which differ by representation.

    fp32 and halfvec take the vector and the limit. Binary takes the vector twice, once
    for the hamming first pass and once for the cosine rerank, plus both limits.
    """
    if request.representation == "binary":
        return [vector, request.overfetch, vector, request.k]
    return [vector, request.k]


def resolve_preset(key: str) -> FilterPreset:
    """Return the preset for `key`, refusing anything not enumerated."""
    preset = PRESETS_BY_KEY.get(key)
    if preset is None:
        raise KeyError(
            explain(f"filter_preset {key!r}", f"use one of {list(PRESET_KEYS)}")
        )
    return preset


def _manifest() -> str:
    """The connected corpus's dataset manifest, refused unless it is resolved.

    This checks one thing and no longer pretends to check two. It previously
    called `assert_manifest_matches` passing this same manifest as both the
    stored and the connected side, which can only ever be equal: it read as a
    corpus check and was not one.

    The corpus check that does exist is the `dataset_manifest_sha256 = %s`
    predicate on every `mosaic_bench.exact_neighbor` join below. Ground truth
    computed against another corpus simply does not match, and the caller raises
    `StaleGroundTruth` rather than reporting recall against the wrong answers.
    An unresolved manifest would defeat that predicate by pinning every corpus to
    the same sentinel, which is what this function refuses.

    Raises:
        StaleGroundTruth: The manifest is empty or the unresolved sentinel.
    """
    manifest = get_settings().dataset_manifest_sha256 or ""
    if not manifest or manifest == UNRESOLVED_MANIFEST:
        raise StaleGroundTruth(
            explain(
                f"the connected corpus reports dataset manifest {manifest!r}",
                "set DATASET_MANIFEST_SHA256, or restore data/full/manifest.json — "
                "ground truth pinned to an unresolved manifest matches any corpus",
            )
        )
    return manifest


def neighborhood(
    anchor_product_id: int, *, preset: str = "none", k: int = 10
) -> dict[str, Any]:
    """Precomputed exact neighbours for one anchor, with their real distances.

    Runs no vector query. The ground truth is already stored, which is what keeps the
    interactive surface off the 2.4-second sequential-scan path.
    """
    resolve_preset(preset)
    manifest = _manifest()
    with connect() as connection:
        anchor = connection.execute(
            f"""
            SELECT {_PRODUCT_COLUMNS}
            FROM {PRODUCT_DOCUMENT}
            WHERE product_id = %s AND {ANCHOR_PREDICATE}
            """,
            (anchor_product_id,),
        ).fetchone()
        if anchor is None:
            raise KeyError(
                explain(
                    f"product {anchor_product_id} is not a retrieval anchor",
                    "choose an anchor from GET /api/hnsw/anchors",
                )
            )
        rows = connection.execute(
            f"""
            SELECT neighbor.neighbor_rank, neighbor.cosine_distance,
                   {_PRODUCT_COLUMNS}
            FROM mosaic_bench.exact_neighbor AS neighbor
            JOIN {PRODUCT_DOCUMENT} AS document
              ON document.product_id = neighbor.neighbor_product_id
            WHERE neighbor.anchor_product_id = %s
              AND neighbor.filter_preset = %s
              AND neighbor.k = %s
              AND neighbor.dataset_manifest_sha256 = %s
            ORDER BY neighbor.neighbor_rank
            """,
            (anchor_product_id, preset, k, manifest),
        ).fetchall()
    if not rows:
        raise StaleGroundTruth(
            explain(
                f"no stored neighbours for anchor {anchor_product_id}, preset "
                f"{preset!r}, k={k} at manifest {manifest}",
                "run `make db-seed-exact-neighbors`",
            )
        )
    neighbors = [dict(row) for row in rows]
    return {
        "anchor": dict(anchor),
        "preset": preset,
        "k": k,
        "neighbors": neighbors,
        "band": neighborhood_band([float(row["cosine_distance"]) for row in neighbors]),
    }


def _plan_index_names(entry: dict[str, Any]) -> list[str]:
    """Every index the plan touched, at any depth.

    Depth matters: the binary two-pass nests its index scan under a Sort and a Subquery
    Scan, so looking only one level below the root reports no index and makes a working
    query look like it missed its index.
    """
    found = [entry["Index Name"]] if entry.get("Index Name") else []
    for child in entry.get("Plans", []):
        found.extend(_plan_index_names(child))
    return found


def _plan_scan_node(entry: dict[str, Any]) -> str:
    """The deepest scan node, which is the one that did the retrieval work."""
    for child in entry.get("Plans", []):
        nested = _plan_scan_node(child)
        if nested:
            return nested
    node_type = entry.get("Node Type", "")
    return node_type if "Scan" in node_type else ""


#: Which of the probe's two executions these numbers came from. `probe()` runs the
#: ANN statement once for its rows and a second time under EXPLAIN (ANALYZE), so the
#: rows and recall come from run one while every timing and buffer count here comes
#: from run two, against a cache the first run already warmed.
EXPLAIN_EXECUTION_NOTE = (
    "second execution of the same statement on this connection; the first "
    "returned the rows, so buffers were already warm"
)


def _explain_probe(connection: Any, sql: str, parameters: list[Any]) -> dict[str, Any]:
    """The server's own view of a *second* execution: time, buffers, plan shape.

    EXPLAIN (ANALYZE) runs the statement again. It is not an annotation of the
    run that produced the returned rows, and `execution` says so on every
    response rather than leaving the reader to assume one query was measured.
    """
    plan = connection.execute(
        f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}", parameters
    ).fetchone()["QUERY PLAN"][0]
    node = plan["Plan"]
    indexes = _plan_index_names(node)
    return {
        "execution": EXPLAIN_EXECUTION_NOTE,
        "node": _plan_scan_node(node) or node["Node Type"],
        "index_name": indexes[0] if indexes else None,
        "indexes_used": indexes,
        "server_ms": round(plan["Execution Time"], 3),
        "shared_hit_blocks": node["Shared Hit Blocks"],
        "shared_read_blocks": node["Shared Read Blocks"],
        "estimated_total_cost": node["Total Cost"],
        "estimated_rows": node["Plan Rows"],
    }


def require_probe_ground_truth(
    truth: dict[tuple[int, str], list[int]],
    *,
    anchor_product_id: int,
    preset_key: str,
    k: int,
    manifest_sha256: str,
) -> list[int]:
    """Return the probe's exact neighbors or refuse to report synthetic recall."""
    expected = truth.get((anchor_product_id, preset_key), [])[:k]
    if not expected:
        raise StaleGroundTruth(
            explain(
                f"no stored neighbours for anchor {anchor_product_id}, preset "
                f"{preset_key!r}, k={k} at manifest {manifest_sha256}",
                "run `make db-seed-exact-neighbors`",
            )
        )
    return expected


def probe(request: Any) -> dict[str, Any]:
    """Run the same ANN query twice and report what the server actually did.

    Two executions of one statement, deliberately, and the response says which
    numbers came from which. The first returns the rows, which is what recall and
    the returned products are computed from. The second runs under
    EXPLAIN (ANALYZE, BUFFERS), which is where `plan.server_ms` and the buffer
    counts come from — against a cache the first execution already warmed, so
    they are not the cost of a cold query. `plan.execution` carries that
    sentence onto every response.

    Recall is computed against `mosaic_bench.exact_neighbor`, never by re-running the
    exact scan, so the cost ceiling of this endpoint is two filtered HNSW scans.
    """
    preset = resolve_preset(request.filter_preset)
    manifest = _manifest()
    sql = probe_sql(preset, request.representation)

    with connect() as connection:
        anchor = connection.execute(
            f"""
            SELECT {_PRODUCT_COLUMNS}, embedding
            FROM {PRODUCT_DOCUMENT}
            WHERE product_id = %s AND {ANCHOR_PREDICATE} AND embedding IS NOT NULL
            """,
            (request.anchor_product_id,),
        ).fetchone()
        if anchor is None:
            raise KeyError(
                explain(
                    f"product {request.anchor_product_id} is not a retrieval anchor",
                    "choose an anchor from GET /api/hnsw/anchors",
                )
            )
        require_representation_index(connection, request.representation)
        truth = require_probe_ground_truth(
            load_ground_truth(connection, manifest_sha256=manifest, k=request.k),
            anchor_product_id=request.anchor_product_id,
            preset_key=preset.key,
            k=request.k,
            manifest_sha256=manifest,
        )

        # One real transaction. A nested block would degrade to a SAVEPOINT, and
        # SET LOCAL survives its release — the mechanism that once made a whole
        # measurement sweep silently run sequential scans and report recall 1.0.
        with connection.transaction():
            connection.execute(
                f"SET LOCAL statement_timeout = '{PROBE_STATEMENT_TIMEOUT}'"
            )
            connection.execute(
                """
                SELECT mosaic_search.configure_hnsw(
                    %s::integer, %s::text, %s::integer, %s::real
                )
                """,
                (
                    request.ef_search,
                    request.iterative_scan,
                    request.max_scan_tuples,
                    request.scan_mem_multiplier,
                ),
            )
            parameters = probe_parameters(request, anchor["embedding"])
            found = connection.execute(sql, parameters).fetchall()
            plan = _explain_probe(connection, sql, parameters)

        returned = [int(row["product_id"]) for row in found]
        products = (
            connection.execute(
                f"""
                SELECT {_PRODUCT_COLUMNS},
                       (embedding <=> (
                           SELECT embedding FROM {PRODUCT_DOCUMENT}
                           WHERE product_id = %s
                       )) AS cosine_distance
                FROM {PRODUCT_DOCUMENT}
                WHERE product_id = ANY(%s)
                ORDER BY cosine_distance
                """,
                (request.anchor_product_id, returned),
            ).fetchall()
            if returned
            else []
        )

    expected = truth
    return {
        "anchor": {
            key: value for key, value in dict(anchor).items() if key != "embedding"
        },
        "preset": preset.key,
        "representation": request.representation,
        "expected_index": REPRESENTATION_INDEX[request.representation],
        "settings": {
            "representation": request.representation,
            "overfetch": (
                request.overfetch if request.representation == "binary" else None
            ),
            "ef_search": request.ef_search,
            "iterative_scan": request.iterative_scan,
            "scan_mem_multiplier": request.scan_mem_multiplier,
            "max_scan_tuples": request.max_scan_tuples,
            "k": request.k,
        },
        "sql": sql.strip(),
        "rows_returned": len(returned),
        "exact_rows_available": len(expected),
        "recall_at_k": (
            round(len(set(returned) & set(expected)) / len(expected), 4)
            if expected
            else 0.0
        ),
        "missed": [pid for pid in expected if pid not in set(returned)],
        "unexpected": [pid for pid in returned if pid not in set(expected)],
        "plan": plan,
        "products": [dict(row) for row in products],
    }
