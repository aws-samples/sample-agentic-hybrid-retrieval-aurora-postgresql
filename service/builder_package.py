"""Downloadable exercise files and the exact implementation patterns they explain."""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from pathlib import Path

REPOSITORY = (
    "https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql"
)
_LINK = re.compile(r"(\]\()([^)\s#]+)(#[^)\s]*)?(\))")
_SCHEME = re.compile(r"[a-z][a-z0-9+.-]*:", re.IGNORECASE)
_COMMIT = re.compile(r"[0-9a-f]{40}")

# Explicitly scoped to public source. Never include environment files, outputs,
# participant work, credentials, or recursively discovered workspace content.
BUILDER_FILES = (
    "docs/build-retrieval-tool.md",
    "docs/use-in-your-app.md",
    "docs/mcp-interoperability.md",
    "docs/security-boundaries.md",
    "examples/call_headphones.py",
    "scripts/check_builder_tool.py",
    # The search path's SQL in install order: the extensions, schemas, types and
    # reference tables the catalog depends on, then every file the guide names.
    "db/sql/00_extensions.sql",
    "db/sql/01_schemas_and_types.sql",
    "db/sql/02_reference_data.sql",
    "db/sql/03_catalog.sql",
    "db/sql/05_evidence.sql",
    "db/sql/06_retrieval_projection.sql",
    "db/sql/07_indexes.sql",
    "db/sql/08_search_channels.sql",
    "labs/lab2_rank/solution/rrf_contribution.sql",
    "labs/lab1_retrieve/solution/hybrid_search.sql",
    "db/sql/09_weighted_fusion.sql",
    "db/sql/10_evidence_search.sql",
    "db/sql/11_query_coverage.sql",
    "db/sql/12_agent_audit.sql",
    "db/sql/13_telemetry.sql",
    "db/config/retrieval.yaml",
    "db/config/agent_tool_contracts.json",
)


def published_links(text: str, relative: str, revision: str) -> str:
    """Point each relative link that leaves the kit at its page in the source repository.

    The repository's own guides link to each other relatively, which a reader of the
    unzipped kit cannot follow for a file the kit does not carry. Those links name the
    revision the running checkout is at, so the reader sees the documents that match the
    kit; a revision that is not a commit ID falls back to the main branch.

    Args:
        text: A Markdown file's text.
        relative: The file's path in the repository, as listed in `BUILDER_FILES`.
        revision: The running checkout's commit ID, or anything else for main.
    """
    ref = revision if _COMMIT.fullmatch(revision) else "main"

    def replace(link: re.Match[str]) -> str:
        target = link[2]
        if _SCHEME.match(target):
            return link[0]
        resolved = posixpath.normpath(
            posixpath.join(posixpath.dirname(relative), target)
        )
        if resolved in BUILDER_FILES or resolved.startswith("../"):
            return link[0]
        return f"{link[1]}{REPOSITORY}/blob/{ref}/{resolved}{link[3] or ''}{link[4]}"

    return _LINK.sub(replace, text)


def build_package(root: Path, revision: str = "main") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "mosaic-builder/README.md",
            "# Mosaic builder kit\n\n"
            "Start with docs/use-in-your-app.md to adapt the implementation. "
            "docs/build-retrieval-tool.md is an optional practice exercise.\n\n"
            "Run these examples from the full Mosaic checkout, which supplies "
            "service modules and pinned dependencies:\n"
            f"{REPOSITORY}\n\n"
            "The included SQL is reference material for adaptation. Use the "
            "checkout's documented Aurora installation sequence to install a database.\n",
        )
        for relative in BUILDER_FILES:
            path = root / relative
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError(f"Builder file escapes source root: {relative}")
            content = path.read_bytes()
            if relative.endswith(".md"):
                content = published_links(content.decode(), relative, revision).encode()
            archive.writestr(f"mosaic-builder/{relative}", content)
    return output.getvalue()
