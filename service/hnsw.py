"""Read-only endpoints behind the HNSW instrument.

Three of the four are plain reads. The fourth, `probe`, issues a real query and is
the only one with a cost ceiling worth stating: it never reaches a sequential scan,
because recall is computed against precomputed ground truth rather than by re-running
the exact query. An exact query is a scan over every stored vector; one per
interaction, times a room of participants, would make an optional Labs surface a
load generator.

Every HNSW setting is applied through the served catalog's `configure_hnsw`, the
same function served retrieval calls. A probe that reached `set_config` directly
would be measuring a path the request path never takes.

The instrument serves whichever catalog the service serves. Product rows come from
`service.catalog_runtime.product_document()`, the index it inspects from
`catalog_indexes()`, its query anchors from the committed anchor set, and its corpus
identity from `service.hnsw_corpus`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg

from scripts.retrieval_profile import explain
from scripts.seed_exact_neighbors import load_ground_truth
from service.catalog_runtime import (
    CatalogIndexes,
    active_dataset,
    catalog_indexes,
    product_document,
    search_schema,
)
from service.config import get_settings
from service.db import connect, index_states_on
from service.hnsw_anchors import (
    AnchorSet,
    AnchorSetError,
    require_anchor_set_for_served_catalog,
)
from service.hnsw_corpus import StaleGroundTruth, corpus_manifest
from service.hnsw_presets import PRESET_KEYS, PRESETS_BY_KEY, FilterPreset

ROOT = Path(__file__).resolve().parents[1]
MEASURED_ARTIFACT = ROOT / "data" / "benchmarks" / "hnsw_measured.json"

# The measured worst case across every enumerated parameter combination on the
# legacy catalog was 283 ms. Five seconds is far above that and far below anything
# that holds a connection long enough to matter to another participant.
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

# `{relation}` is the served catalog's product relation. `embedding IS NOT NULL`
# is kept in every shape: the legacy indexes are partial on it, and on a total
# index it is a no-op predicate that keeps the two catalogs' plans comparable.
PROBE_SQL = """
SELECT product_id
FROM {relation}
WHERE embedding IS NOT NULL{predicate}
ORDER BY embedding <=> %s
LIMIT %s
"""

# halfvec is a cast of the same column, so the query must repeat the cast to reach the
# expression index. Same two bound parameters as fp32.
HALFVEC_PROBE_SQL = """
SELECT product_id
FROM {relation}
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
    FROM {relation}
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

REPRESENTATIONS: tuple[str, ...] = tuple(REPRESENTATION_SQL)

_PRODUCT_COLUMNS = """
    product_id, title, brand_name, domain::text AS domain, category_key,
    catalog_asset_key, media_tier::text AS media_tier
"""


class RepresentationUnavailable(RuntimeError):
    """A representation was requested whose index is missing or not usable."""


def representation_index(
    representation: str, indexes: CatalogIndexes | None = None
) -> str:
    """The bare index name a representation must reach on the served catalog."""
    indexes = indexes or catalog_indexes()
    try:
        return {
            "fp32": indexes.fp32,
            "halfvec": indexes.halfvec,
            "binary": indexes.binary,
        }[representation]
    except KeyError:
        raise KeyError(
            explain(
                f"representation {representation!r}",
                f"use one of {sorted(REPRESENTATION_SQL)}",
            )
        ) from None


def representation_recovery(representation: str) -> str:
    """The one command that builds a representation's index on the served catalog."""
    if active_dataset():
        if representation == "fp32":
            return (
                "rebuild the catalog projection with "
                "`scripts/prepare_staged_catalog_search.py`, which creates the index"
            )
        return (
            "run `make db-index-quantized-catalog` to build the halfvec and binary "
            "indexes on the served catalog (a few minutes each)"
        )
    if representation == "fp32":
        return "run `make db-drop-invalid-indexes` then `make db-index-concurrent`"
    return "run `make db-index-quantized` (roughly 9 minutes for both indexes)"


def require_representation_index(connection: Any, representation: str) -> None:
    """Refuse to probe a representation whose index cannot serve the query.

    Without this the query still runs: it falls back to a sequential scan over
    the TOASTed vectors, hits the 5s statement timeout, and reports the
    failure as a timeout rather than as the missing index it is.

    "Usable" is `service.db.index_states_on`'s answer, the same rule
    `service.db.readiness()` reports the required retrieval indexes with.

    Raises:
        RepresentationUnavailable: The index is missing or not valid and ready.
    """
    indexes = catalog_indexes()
    index_name = representation_index(representation, indexes)
    state = index_states_on(connection, [index_name], schema=indexes.schema).get(
        index_name, "missing"
    )
    if state == "valid":
        return
    raise RepresentationUnavailable(
        explain(
            f"index {index_name} for representation {representation!r} is {state}",
            representation_recovery(representation),
        )
    )


def _measured_attribution(
    provenance: dict[str, Any], *, connected_manifest: str | None, detail: str | None
) -> dict[str, Any]:
    """Decide whether the committed artifact describes the running system.

    Binding conjunction over exactly two facts, mirroring
    `service.scorecard._attribution`:

        artifact.provenance.source_worktree_dirty == False
        AND artifact.provenance.dataset_manifest_sha256 == the connected corpus,
            with that corpus identity resolved

    Revision equality is deliberately not in the conjunction, and for the same
    reason it is absent from the scorecard: the benchmark records the revision
    *before* the artifact it writes is committed, so a strict equality would
    read "measured elsewhere" forever. The revision is carried on both sides as
    display and audit evidence.

    Args:
        provenance: The artifact's `provenance` block.
        connected_manifest: The connected corpus identity, or `None` when it
            could not be read.
        detail: Why it could not be read, as an exception type name only.
    """
    settings = get_settings()
    measured_manifest = provenance.get("dataset_manifest_sha256") or ""
    current_manifest = connected_manifest or ""
    measured_dirty = provenance.get("source_worktree_dirty")

    # Prose, not `explain(found, fix)`. The note is rendered as body copy on the
    # Performance page, where error-message scaffolding reads as a fault in the
    # page rather than as a statement about where the numbers came from. Each
    # reason is a complete sentence so any subset of them still reads.
    reasons: list[str] = []
    if not current_manifest:
        reasons.append(
            "The connected catalog's data version could not be read"
            + (f" ({detail})" if detail else "")
            + ", so these measurements cannot be matched to it."
        )
    elif measured_manifest != current_manifest:
        reasons.append(
            f"These numbers were measured on a different catalog version "
            f"({measured_manifest[:12]} measured, {current_manifest[:12]} connected)."
        )
    if measured_dirty is not False:
        reasons.append(
            f"The measurement was taken with code changes that were not saved in Git "
            f"(source_worktree_dirty is {measured_dirty!r}), so its recorded "
            f"revision does not describe the code that produced these numbers."
        )

    if reasons:
        recovery = (
            "Save the code changes in Git, then run `make benchmark-hnsw` against "
            "the connected catalog to measure it, or read this "
            "panel as a record of another cluster."
        )
        note = " ".join([*reasons, recovery])
    else:
        note = (
            f"Measured on the connected catalog "
            f"({current_manifest[:12]}), with all code changes saved at version "
            f"{str(provenance.get('source_revision') or '')[:12]}."
        )
    return {
        "measured_source_revision": provenance.get("source_revision"),
        "measured_source_worktree_dirty": measured_dirty,
        "measured_dataset_manifest_sha256": provenance.get("dataset_manifest_sha256"),
        "current_source_revision": settings.source_revision,
        "current_source_worktree_dirty": settings.source_worktree_dirty,
        "current_dataset_manifest_sha256": current_manifest,
        "attributed": not reasons,
        "attribution_note": note,
    }


def _gate_representations(
    payload: dict[str, Any], states: dict[str, str] | None, detail: str | None
) -> dict[str, Any]:
    """Withhold the representation comparison unless both quantized indexes are usable.

    The artifact may advertise halfvec and binary rows. Only a cluster that
    holds those indexes can EXPLAIN, inspect, or reproduce them, so on any
    other cluster the rows are replaced by the reason.

    The reason is prose plus the command that fixes it, for the same reason
    `_measured_attribution`'s note is: the Performance page renders it as body
    copy under a heading, where `found:`/`fix:` scaffolding reads as a fault in
    the page rather than as a statement about this cluster.
    """
    if "representations" not in payload:
        return payload
    if states is None:
        # The two ways this read fails: no DSN configured (`RuntimeError` from
        # `get_pool`), or the cluster refusing the connection or the query.
        # Neither is swallowed -- an unreachable cluster is a different claim
        # from a missing index, and the reason names which one happened. The
        # exception type, never its message: a psycopg connection failure names
        # the host and user, and this string is served to every participant.
        return _withhold_representations(
            payload,
            f"The index state could not be read from the cluster "
            f"({detail}), so nothing here can say whether the "
            f"halfvec and binary indexes exist. Point DATABASE_URL at the "
            f"workshop cluster and reload.",
        )
    unusable = {name: state for name, state in states.items() if state != "valid"}
    if not unusable:
        return payload
    listed = ", ".join(f"{name} is {state}" for name, state in sorted(unusable.items()))
    return _withhold_representations(
        payload,
        f"This cluster has no usable quantized index ({listed}), so the "
        f"comparison would describe indexes you cannot inspect here. "
        f"{representation_recovery('halfvec').capitalize()}, or read "
        f"the halfvec and binary rows as a record of another cluster.",
    )


def _withhold_representations(payload: dict[str, Any], reason: str) -> dict[str, Any]:
    """Drop the representation rows, leaving the reason in their place."""
    gated = {key: value for key, value in payload.items() if key != "representations"}
    gated["representations_unavailable_reason"] = reason
    return gated


def _connected_facts() -> tuple[str | None, dict[str, str] | None, str | None]:
    """One cluster read for `measured()`: corpus identity and quantized index states.

    Returns `(manifest, states, detail)`; a failed read leaves the first two
    `None` and names the exception type in `detail`.
    """
    indexes = catalog_indexes()
    try:
        with connect() as connection:
            manifest = corpus_manifest(connection)
            states = index_states_on(
                connection, [indexes.halfvec, indexes.binary], schema=indexes.schema
            )
    except (RuntimeError, psycopg.Error) as error:
        return None, None, type(error).__name__
    return manifest, states, None


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
    manifest, states, detail = _connected_facts()
    payload["attribution"] = _measured_attribution(
        payload.get("provenance") or {}, connected_manifest=manifest, detail=detail
    )
    return _gate_representations(payload, states, detail)


def anchor_set() -> AnchorSet:
    """The committed anchor set, refused when it belongs to another catalog."""
    return require_anchor_set_for_served_catalog()


def substrate() -> dict[str, Any]:
    """Live index anatomy, storage split, and the settings that explain them."""
    indexes = catalog_indexes()
    anchors = anchor_set()
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
            {
                "table": indexes.qualified_table,
                "index": indexes.qualified(indexes.fp32),
            },
        ).fetchone()
        # No `count(DISTINCT embedding)` here, deliberately. Counting distinct
        # 1024-dimension vectors across half a million rows sorts roughly 2 GB
        # against a 4 MB work_mem, and on 2026-08-17 it terminated the Aurora
        # backend outright (the instance restarted, uptime 26s). A 2 GB sort per
        # page load is not something a live endpoint may do.
        counts = connection.execute(
            f"""
            SELECT count(*) FILTER (WHERE embedding IS NOT NULL) AS vector_count,
                   count(*) FILTER (WHERE product_id = ANY(%s)) AS anchor_count,
                   (SELECT vector_dims(embedding) FROM {product_document()}
                    WHERE embedding IS NOT NULL LIMIT 1) AS dimensions
            FROM {product_document()}
            """,
            (list(anchors.product_ids),),
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
        sizes=dict(sizes),
        counts=dict(counts),
        settings=settings,
        aurora=dict(aurora),
        index_name=indexes.qualified(indexes.fp32),
        anchor_set_sha256=anchors.sha256,
    )


def _substrate_payload(
    *,
    sizes: dict[str, Any],
    counts: dict[str, Any],
    settings: dict[str, str],
    aurora: dict[str, Any],
    index_name: str,
    anchor_set_sha256: str | None = None,
) -> dict[str, Any]:
    """Shape the live substrate read, deriving the index arithmetic explicitly."""
    vectors = max(1, int(counts["vector_count"]))
    hnsw_bytes = int(sizes["hnsw_bytes"])
    payload_bytes = int(counts["dimensions"] or 0) * 4
    per_vector = round(hnsw_bytes / vectors)
    definition = str(sizes["index_definition"])
    return {
        "index": {
            "name": index_name,
            "definition": definition,
            "partial": " WHERE " in definition,
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
            "anchor_set_sha256": anchor_set_sha256,
            "dimensions": counts["dimensions"],
        },
        "aurora": aurora | {"instance_class": get_settings().aurora_instance_class},
        "settings": settings,
        "retrieval": {"ef_search": get_settings().hnsw_ef_search},
    }


def neighborhood_band(distances: list[float]) -> dict[str, float] | None:
    """Distance span of the neighbours, excluding the anchor's own zero distance.

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
    """The query anchors the instrument offers: the committed anchor set's products.

    Raises:
        AnchorSetError: An anchor is not in the served catalog with a vector,
            which means the set was selected from another catalog.
    """
    selected = anchor_set()
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT {_PRODUCT_COLUMNS}
            FROM {product_document()}
            WHERE embedding IS NOT NULL AND product_id = ANY(%s)
            ORDER BY product_id
            """,
            (list(selected.product_ids),),
        ).fetchall()
    found = {int(row["product_id"]) for row in rows}
    missing = [item for item in selected.product_ids if item not in found]
    if missing:
        raise AnchorSetError(
            explain(
                f"anchors {missing[:10]} are not in the served catalog with a vector",
                "select anchors from the served catalog with `make select-hnsw-anchors`",
            )
        )
    return [dict(row) for row in rows]


def probe_sql(preset: FilterPreset, representation: str = "fp32") -> str:
    """The exact SQL the probe runs, for a preset and a representation.

    `embedding IS NOT NULL` is not optional in any of the three shapes. The
    legacy indexes are partial, so a query that drops the predicate cannot use
    them and falls back to a sequential scan; on a total index the predicate
    costs nothing and keeps the plans comparable across catalogs.
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
    return template.format(relation=product_document(), predicate=predicate)


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


def _require_anchor(connection: Any, selected: AnchorSet, product_id: int) -> Any:
    """The anchor's product row, refused when the id is not an anchor."""
    if product_id not in selected:
        raise KeyError(
            explain(
                f"product {product_id} is not a query anchor",
                "choose an anchor from GET /api/hnsw/anchors",
            )
        )
    row = connection.execute(
        f"""
        SELECT {_PRODUCT_COLUMNS}, embedding
        FROM {product_document()}
        WHERE product_id = %s AND embedding IS NOT NULL
        """,
        (product_id,),
    ).fetchone()
    if row is None:
        raise StaleGroundTruth(
            explain(
                f"anchor {product_id} is not in the served catalog with a vector",
                "select anchors from the served catalog with `make select-hnsw-anchors`",
            )
        )
    return row


def neighborhood(
    anchor_product_id: int, *, preset: str = "none", k: int = 10
) -> dict[str, Any]:
    """Precomputed exact neighbours for one anchor, with their real distances.

    Runs no vector query. The ground truth is already stored, which is what keeps the
    interactive surface off the exact-scan path.
    """
    chosen = resolve_preset(preset)
    selected = anchor_set()
    with connect() as connection:
        manifest = corpus_manifest(connection)
        anchor = _require_anchor(connection, selected, anchor_product_id)
        rows = connection.execute(
            f"""
            SELECT neighbor.neighbor_rank, neighbor.cosine_distance,
                   {_PRODUCT_COLUMNS}
            FROM mosaic_bench.exact_neighbor AS neighbor
            JOIN {product_document()} AS document
              ON document.product_id = neighbor.neighbor_product_id
            WHERE neighbor.anchor_product_id = %s
              AND neighbor.filter_preset = %s
              AND neighbor.predicate_sha256 = %s
              AND neighbor.anchor_set_sha256 = %s
              AND neighbor.dataset_manifest_sha256 = %s
              AND neighbor.neighbor_rank <= %s
            ORDER BY neighbor.neighbor_rank
            """,
            (
                anchor_product_id,
                chosen.key,
                chosen.predicate_sha256,
                selected.sha256,
                manifest,
                k,
            ),
        ).fetchall()
        seeded = connection.execute(
            """
            SELECT count(*) AS pairs FROM mosaic_bench.exact_neighbor
            WHERE dataset_manifest_sha256 = %s AND anchor_set_sha256 = %s
            """,
            (manifest, selected.sha256),
        ).fetchone()["pairs"]
    if not rows and not seeded:
        raise StaleGroundTruth(
            explain(
                f"no stored neighbours for anchor {anchor_product_id}, preset "
                f"{preset!r}, k={k} at corpus {manifest[:12]} and anchor set "
                f"{selected.sha256[:12]}",
                "run `make db-seed-exact-neighbors`",
            )
        )
    neighbors = [dict(row) for row in rows]
    return {
        "anchor": {
            key: value for key, value in dict(anchor).items() if key != "embedding"
        },
        "preset": preset,
        "k": k,
        "exact_rows_available": len(neighbors),
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
                f"{preset_key!r}, k={k} at corpus {manifest_sha256}",
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
    counts come from, measured against a cache the first execution already
    warmed, so they are not the cost of a cold query. `plan.execution` carries
    that sentence onto every response.

    Recall is computed against `mosaic_bench.exact_neighbor`, never by re-running the
    exact scan, so the cost ceiling of this endpoint is two filtered HNSW scans.
    """
    preset = resolve_preset(request.filter_preset)
    selected = anchor_set()
    sql = probe_sql(preset, request.representation)

    with connect() as connection:
        manifest = corpus_manifest(connection)
        anchor = _require_anchor(connection, selected, request.anchor_product_id)
        require_representation_index(connection, request.representation)
        truth = require_probe_ground_truth(
            load_ground_truth(
                connection,
                manifest_sha256=manifest,
                k=request.k,
                anchor_set_sha256=selected.sha256,
            ),
            anchor_product_id=request.anchor_product_id,
            preset_key=preset.key,
            k=request.k,
            manifest_sha256=manifest,
        )

        # Three statements have already run on this connection, so psycopg has
        # an implicit transaction open and this block is a SAVEPOINT, not a new
        # transaction. SET LOCAL survives RELEASE SAVEPOINT and persists until
        # the outer commit at the end of the checkout, which is harmless here
        # because nothing else runs on this connection afterwards. Do not add a
        # second probe inside the same checkout without resetting hnsw.* first;
        # that leak is the mechanism that once made a whole measurement sweep
        # silently run sequential scans and report recall 1.0.
        with connection.transaction():
            connection.execute(
                f"SET LOCAL statement_timeout = '{PROBE_STATEMENT_TIMEOUT}'"
            )
            connection.execute(
                f"""
                SELECT {search_schema()}.configure_hnsw(
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
                           SELECT embedding FROM {product_document()}
                           WHERE product_id = %s
                       )) AS cosine_distance
                FROM {product_document()}
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
        "expected_index": representation_index(request.representation),
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
