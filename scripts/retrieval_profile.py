#!/usr/bin/env python3
"""Parse `db/config/retrieval.yaml` — the single source for retrieval numbers.

Before this module the yaml was documentation. `service/config.py` and
`service/models.py` hand-copied its numbers, and `config/workshop.json` held a
third, disagreeing copy that nothing read (LOSS-3). The three live copies agreed
by luck; the dead one did not agree at all.

Precedence is **environment variable > yaml > nothing**. There is no hardcoded
fallback: a missing key is a startup failure naming the key, because a default
that lives in code is exactly the fourth copy the tripwire exists to prevent.

Every value is bounds-checked at load. Phase 1 fixed one instance of an
out-of-range setting reaching the request path (`BUSINESS_WEIGHT=0.15` against a
`le=0.05` bound, which returned an unhandled HTTP 500 on every query). This
module generalizes that fix to the whole profile: a limit of 0 or a negative `k`
refuses to start, in the same error class, with the same message shape.

Usage
-----
    from scripts.retrieval_profile import load_profile
    profile = load_profile()          # env > yaml, validated
    profile.fts_limit                 # 120

    python scripts/retrieval_profile.py          # print the resolved profile
    python scripts/retrieval_profile.py --check  # validate and exit
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
RETRIEVAL_YAML = REPO / "db" / "config" / "retrieval.yaml"


class ProfileError(RuntimeError):
    """The retrieval profile cannot serve a request, so nothing may start.

    Same class of failure as `service.config.ConfigurationError`: refusing at
    load is the difference between one legible startup error and an unhandled
    500 on every query.
    """


def explain(found: str, fix: str) -> str:
    """Render a failure in the house style: offending value, then nearest fix.

    Same contract as `scripts.mission_contract.explain`. Duplicated as one line
    rather than shared, because importing the mission gate here would make the
    config layer depend on a validation script.
    """
    return f"found {found}; fix: {fix}"


@dataclass(frozen=True)
class Bound:
    """A yaml path, the env var that overrides it, and the range it must sit in.

    Attributes:
        path: Dotted path into the yaml, e.g. `candidate_generation.fts_limit`.
        env: Environment variable that overrides the yaml value.
        low: Inclusive lower bound.
        high: Inclusive upper bound.
        cast: `int` or `float`.
    """

    path: str
    env: str | None
    low: float
    high: float
    cast: type[int] | type[float]


# The declared surface of the profile. Bounds match
# `service.models.RetrievalProfile`, which enforces them again per request; two
# layers is deliberate, because the yaml is edited by hand and the request path
# is not.
BOUNDS: tuple[Bound, ...] = (
    Bound("embedding.dimensions", "VECTOR_DIM", 1, 4096, int),
    Bound("candidate_generation.fts_limit", "FTS_CANDIDATE_LIMIT", 1, 1000, int),
    Bound(
        "candidate_generation.trigram_limit", "TRIGRAM_CANDIDATE_LIMIT", 1, 1000, int
    ),
    Bound(
        "candidate_generation.semantic_limit", "SEMANTIC_CANDIDATE_LIMIT", 1, 1000, int
    ),
    Bound("candidate_generation.trigram_threshold", None, 0.01, 1.0, float),
    Bound("fusion.rrf_k", "RRF_K", 1, 10_000, int),
    Bound("fusion.fused_limit", "RERANK_CANDIDATE_LIMIT", 1, 250, int),
    Bound("fusion.business_weight", "BUSINESS_WEIGHT", 0, 0.05, float),
    Bound("fusion.weights.lexical", None, 0, 1, float),
    Bound("fusion.weights.semantic", None, 0, 1, float),
    Bound("fusion.weights.trigram", None, 0, 1, float),
    Bound("rerank.display_limit", None, 1, 100, int),
    Bound("hnsw.m", None, 2, 100, int),
    Bound("hnsw.ef_construction", None, 4, 1000, int),
    Bound("hnsw.ef_search", "HNSW_EF_SEARCH", 1, 1000, int),
    Bound("hnsw.max_scan_tuples", None, 1, 10_000_000, int),
    Bound("hnsw.scan_mem_multiplier", None, 1, 100, float),
)


@dataclass(frozen=True)
class RetrievalProfileConfig:
    """The resolved profile. Field names are the consumers' names, not the yaml's."""

    vector_dimension: int
    fts_limit: int
    trigram_limit: int
    semantic_limit: int
    trigram_threshold: float
    rrf_k: int
    fused_limit: int
    business_weight: float
    weight_lexical: float
    weight_semantic: float
    weight_trigram: float
    display_limit: int
    hnsw_m: int
    hnsw_ef_construction: int
    hnsw_ef_search: int
    hnsw_max_scan_tuples: int
    hnsw_scan_mem_multiplier: float

    def as_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


# yaml path -> profile field.
_FIELD_FOR_PATH: dict[str, str] = {
    "embedding.dimensions": "vector_dimension",
    "candidate_generation.fts_limit": "fts_limit",
    "candidate_generation.trigram_limit": "trigram_limit",
    "candidate_generation.semantic_limit": "semantic_limit",
    "candidate_generation.trigram_threshold": "trigram_threshold",
    "fusion.rrf_k": "rrf_k",
    "fusion.fused_limit": "fused_limit",
    "fusion.business_weight": "business_weight",
    "fusion.weights.lexical": "weight_lexical",
    "fusion.weights.semantic": "weight_semantic",
    "fusion.weights.trigram": "weight_trigram",
    "rerank.display_limit": "display_limit",
    "hnsw.m": "hnsw_m",
    "hnsw.ef_construction": "hnsw_ef_construction",
    "hnsw.ef_search": "hnsw_ef_search",
    "hnsw.max_scan_tuples": "hnsw_max_scan_tuples",
    "hnsw.scan_mem_multiplier": "hnsw_scan_mem_multiplier",
}


def parse_yaml(text: str) -> dict[str, Any]:
    """Parse the indentation-nested scalar subset of YAML this file uses.

    `PyYAML` is not a dependency of this repository, and adding one to read a
    17-line config file is not justified. The subset supported is exactly what
    `retrieval.yaml` contains: two-space indentation, `key: value` scalars, and
    nested mappings. Anything else — lists, anchors, multi-line strings — raises
    rather than being silently misread.

    Raises:
        ProfileError: a line cannot be parsed as a mapping entry.
    """
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("- "):
            raise ProfileError(
                explain(
                    f"a YAML list at {RETRIEVAL_YAML.name}:{number}",
                    "this parser reads scalars and nested mappings only; express "
                    "the value as named keys",
                )
            )
        indent = len(line) - len(line.lstrip())
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", line)
        if not match:
            raise ProfileError(
                explain(
                    f"unparsable line {RETRIEVAL_YAML.name}:{number}: {line.strip()!r}",
                    "use `key: value` or `key:` followed by an indented block",
                )
            )
        key, value = match.group(1), match.group(2).strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if not stack:
            raise ProfileError(
                explain(
                    f"broken indentation at {RETRIEVAL_YAML.name}:{number}",
                    "indent nested keys by two spaces under their parent",
                )
            )
        parent = stack[-1][1]
        if value == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _scalar(value)
    return root


def _scalar(value: str) -> Any:
    text = value.strip().strip("'\"")
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d*\.\d+", text):
        return float(text)
    if text in {"true", "false"}:
        return text == "true"
    return text


def _dig(tree: dict[str, Any], path: str) -> Any:
    node: Any = tree
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _resolve(bound: Bound, tree: dict[str, Any]) -> int | float:
    """Resolve one setting: env if set, else yaml. Never a hardcoded default."""
    source = RETRIEVAL_YAML.name
    raw = _dig(tree, bound.path)
    if bound.env is not None:
        override = os.getenv(bound.env)
        if override is not None and override.strip() != "":
            raw, source = override.strip(), f"${bound.env}"

    if raw is None:
        raise ProfileError(
            explain(
                f"no value for {bound.path!r}",
                f"add `{bound.path.split('.')[-1]}` under "
                f"`{'.'.join(bound.path.split('.')[:-1])}` in "
                f"{RETRIEVAL_YAML.name}"
                + (f", or set ${bound.env}" if bound.env else ""),
            )
        )
    try:
        value = bound.cast(raw)
    except (TypeError, ValueError) as error:
        raise ProfileError(
            explain(
                f"{bound.path}={raw!r} from {source}, which is not a "
                f"{bound.cast.__name__}",
                f"set it to a {bound.cast.__name__} in [{bound.low}, {bound.high}]",
            )
        ) from error
    if not bound.low <= value <= bound.high:
        raise ProfileError(
            explain(
                f"{bound.path}={value} from {source}, outside "
                f"[{bound.low}, {bound.high}]",
                f"set it within [{bound.low}, {bound.high}]; this bound is "
                f"enforced again by service.models.RetrievalProfile, so an "
                f"out-of-range value would fail every request instead of "
                f"failing startup once",
            )
        )
    return value


def load_profile(*, yaml_path: Path | None = None) -> RetrievalProfileConfig:
    """Resolve and validate the profile.

    Args:
        yaml_path: Override the yaml location. For tests only.

    Returns:
        The validated profile.

    Raises:
        ProfileError: the yaml is missing, unparsable, or any value is absent or
            out of range.
    """
    path = yaml_path or RETRIEVAL_YAML
    if not path.exists():
        raise ProfileError(
            explain(
                f"no retrieval config at {path}",
                "restore db/config/retrieval.yaml; it is the single source for "
                "candidate limits, fusion k, and weights",
            )
        )
    tree = parse_yaml(path.read_text(encoding="utf-8"))
    resolved = {
        _FIELD_FOR_PATH[bound.path]: _resolve(bound, tree)
        for bound in BOUNDS
        if bound.path in _FIELD_FOR_PATH
    }
    return RetrievalProfileConfig(**resolved)  # type: ignore[arg-type]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the profile and exit; print nothing on success",
    )
    args = parser.parse_args()
    try:
        profile = load_profile()
    except ProfileError as error:
        print(f"FAIL retrieval profile: {error}", file=sys.stderr)
        return 1
    if not args.check:
        print(json.dumps(profile.as_dict(), indent=2))
    else:
        print(f"retrieval profile: {len(fields(profile))} setting(s) validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
