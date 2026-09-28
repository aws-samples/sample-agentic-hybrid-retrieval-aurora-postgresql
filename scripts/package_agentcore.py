"""Stage an allowlisted ARM64 image context without credentials or local caches."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = (
    "service",
    "db",
    "scripts",
    "data/evals",
    "skills/mosaic-hybrid-retrieval",
    "deploy/agentcore",
    "labs",
)
FILES = (
    "pyproject.toml",
    "uv.lock",
    "deploy/agentcore/Dockerfile",
    "data/full/manifest.json",
    "data/benchmarks/hnsw_anchors.json",
    "data/benchmarks/hnsw_measured.json",
    "data/benchmarks/scale_projection.json",
    "data/media/asset_labels_200.json",
    "data/media/workspace_collection.json",
    "docs/build-retrieval-tool.md",
    "docs/use-in-your-app.md",
    "examples/call_headphones.py",
)
SUFFIXES = {".py", ".sql", ".json", ".jsonl", ".yaml", ".yml", ".md", ".csv", ".txt"}


def application_files(root: Path = ROOT) -> list[Path]:
    """Use explicit source roots; dotfiles and symlinks never enter the image context."""
    files = [root / name for name in FILES]
    for directory in DIRECTORIES:
        files.extend(
            path
            for path in (root / directory).rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and path.suffix in SUFFIXES
            and not any(
                part.startswith(".") or part == "__pycache__"
                for part in path.relative_to(root).parts
            )
        )
    for path in files:
        if not path.is_file() or path.is_symlink():
            raise ValueError(
                f"Runtime package rule: missing source file {path.relative_to(root)}; restore it before deploying."
            )
    return sorted(set(files))


def package(root: Path, output: Path) -> str:
    """Stage only runtime inputs and return their content hash.

    Args:
        root: Participant source checkout, including their current lab edits.
        output: Empty build-context directory, normally a temporary directory.

    Returns:
        SHA-256 over file names and bytes, independent of local timestamps.
    """
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError(
            "Runtime image rule: build context is not empty; use a fresh temporary directory."
        )
    digest = hashlib.sha256()
    for path in application_files(root):
        relative = path.relative_to(root)
        content = path.read_bytes()
        digest.update(relative.as_posix().encode() + b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(f"Runtime image context ready: {package(ROOT, args.output)}")


if __name__ == "__main__":
    main()
