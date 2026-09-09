"""Downloadable exercise files and the exact implementation patterns they explain."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

# Explicitly scoped to public source. Never include environment files, outputs,
# participant work, credentials, or recursively discovered workspace content.
BUILDER_FILES = (
    "docs/build-retrieval-tool.md",
    "docs/use-in-your-app.md",
    "examples/call_headphones.py",
    "scripts/check_builder_tool.py",
    "db/sql/03_catalog.sql",
    "db/sql/05_evidence.sql",
    "db/sql/06_retrieval_projection.sql",
    "db/sql/07_indexes.sql",
    "db/sql/09_search_functions.sql",
    "db/config/retrieval.yaml",
    "db/config/agent_tool_contracts.json",
)


def build_package(root: Path) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "mosaic-builder/README.md",
            "# Mosaic builder kit\n\n"
            "Read docs/build-retrieval-tool.md, then docs/use-in-your-app.md.\n\n"
            "Run these examples from the full Mosaic checkout, which supplies "
            "service modules and pinned dependencies:\n"
            "https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql\n\n"
            "The included SQL is reference material for adaptation. Use the "
            "checkout's documented Aurora installation sequence to install a database.\n",
        )
        for relative in BUILDER_FILES:
            path = root / relative
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError(f"Builder file escapes source root: {relative}")
            archive.writestr(f"mosaic-builder/{relative}", path.read_bytes())
    return output.getvalue()
