"""Build a locked ARM64 Python ZIP without copying credentials or local caches."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = (
    "service",
    "db",
    "scripts",
    "data/evals",
    "skills/mosaic-hybrid-retrieval",
    "deploy/agentcore",
    "labs/lab3",
)
FILES = (
    "pyproject.toml",
    "uv.lock",
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
    """Use explicit source roots; dotfiles and symlinks never enter the archive."""
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


def package(root: Path, output: Path, cache: Path) -> None:
    """Reuse the dependency ZIP only while the committed lock remains identical."""
    lock_hash = hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest()
    cache.mkdir(parents=True, exist_ok=True)
    dependency_zip = cache / f"dependencies-{lock_hash}.zip"
    if not dependency_zip.exists():
        requirements = cache / "requirements.txt"
        subprocess.run(
            [
                "uv",
                "export",
                "--frozen",
                "--no-dev",
                "--no-emit-project",
                "--output-file",
                str(requirements),
            ],
            cwd=root,
            check=True,
        )
        dependencies = cache / "dependencies"
        if dependencies.exists():
            shutil.rmtree(dependencies)
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python-platform",
                "aarch64-manylinux_2_28",
                "--python-version",
                "3.13",
                "--target",
                str(dependencies),
                "--only-binary=:all:",
                "--require-hashes",
                "-r",
                str(requirements),
            ],
            cwd=root,
            check=True,
        )
        staged = dependency_zip.with_suffix(".tmp")
        with ZipFile(staged, "w", ZIP_DEFLATED) as archive:
            for path in sorted(dependencies.rglob("*")):
                if (
                    path.is_file()
                    and "__pycache__" not in path.parts
                    and path.suffix != ".pyc"
                ):
                    archive.write(path, path.relative_to(dependencies))
        staged.replace(dependency_zip)
        shutil.rmtree(dependencies)
    output.parent.mkdir(parents=True, exist_ok=True)
    certificate = cache / "rds-ca-bundle.pem"
    if not certificate.exists():
        with urlopen(
            "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem",
            timeout=30,
        ) as response:
            certificate.write_bytes(response.read())
    shutil.copyfile(dependency_zip, output)
    with ZipFile(output, "a", ZIP_DEFLATED) as archive:
        archive.write(certificate, "rds-ca-bundle.pem")
        for path in application_files(root):
            archive.write(path, path.relative_to(root))
    print(f"Runtime package ready: {output.name} ({output.stat().st_size:,} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".local/agentcore/mosaic.zip"
    )
    args = parser.parse_args()
    package(ROOT, args.output, ROOT / ".local/agentcore")


if __name__ == "__main__":
    main()
