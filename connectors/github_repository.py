#!/usr/bin/env python3
"""Project selected repository files into the common SourceObject contract.

The local transport reads a packaged checkout while the repository is private.
The GitHub transport reads an immutable remote commit through the GitHub API.
Both emit the same JSONL contract and snapshot cursor for full synchronization.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from pathlib import Path
from urllib.parse import quote

import requests

DEFAULT_PATTERNS = [
    "README.md",
    "docs/architecture.md",
    "docs/ingestion-api.md",
    "docs/live-index-lab.md",
    "backend/app/ingest.py",
    "backend/app/rerank.py",
    "backend/app/search.py",
    "sql/01_schema.sql",
    "sql/03_search_functions.sql",
    "connectors/github_repository.py",
]
DEFAULT_REPOSITORY_URL = "https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql"
GITHUB_API = "https://api.github.com"


def git(repo: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def normalize_repository_url(value: str | None) -> str:
    if not value:
        return DEFAULT_REPOSITORY_URL
    url = value.strip()
    if url.startswith("git@github.com:"):
        url = f"https://github.com/{url.removeprefix('git@github.com:')}"
    if url.endswith(".git"):
        url = url[:-4]
    return url


def repository_slug(repository_url: str, repo: Path) -> str:
    if "github.com/" in repository_url:
        return repository_url.split("github.com/", 1)[1].strip("/")
    return repo.name


def discover_files(repo: Path, patterns: list[str], max_file_bytes: int) -> list[Path]:
    selected: dict[str, Path] = {}
    for pattern in patterns:
        for path in repo.glob(pattern):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(repo).as_posix()
            if any(part.startswith(".") for part in Path(relative).parts):
                continue
            if path.stat().st_size > max_file_bytes:
                continue
            selected[relative] = path
    return [selected[key] for key in sorted(selected)]


def decode_text(raw: bytes) -> str | None:
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def content_title(relative: str, text: str) -> str:
    if relative.endswith(".md"):
        for line in text.splitlines():
            if line.startswith("# "):
                return f"{relative} - {line[2:].strip()}"
    return relative


def language_for(relative: str) -> str:
    suffix = Path(relative).suffix.lower()
    return {
        ".md": "markdown",
        ".py": "python",
        ".sql": "sql",
        ".ts": "typescript",
        ".tsx": "typescript-react",
        ".json": "json",
        ".yml": "yaml",
        ".yaml": "yaml",
    }.get(suffix, suffix.lstrip(".") or "text")


def build_source_object(
    *,
    relative: str,
    text: str,
    repository_url: str,
    slug: str,
    revision: str,
    blob_sha: str,
    updated_at: str,
    author: str,
    project_key: str,
    transport: str,
    content_origin: str,
    citation_url_exact: bool,
) -> dict:
    content_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    revision_for_url = revision if citation_url_exact else "main"
    return {
        "source_system": "github",
        "source_type": "repository_file",
        "external_id": f"{slug}:{relative}",
        "title": content_title(relative, text),
        "url": f"{repository_url}/blob/{revision_for_url}/{quote(relative, safe='/')}",
        "status": "Tracked",
        "priority": "Reference",
        "owner": author,
        "owner_team": "Repository maintainers",
        "account_name": "",
        "project_key": project_key,
        "component": relative.split("/", 1)[0],
        "environment": "source",
        "created_at": updated_at,
        "updated_at": updated_at,
        "source_authority": 0.80,
        "acl": {"visibility": "workshop_lab"},
        "metadata": {
            "connector": "github_repository",
            "transport": transport,
            "content_origin": content_origin,
            "repository": slug,
            "repository_url": repository_url,
            "path": relative,
            "revision": revision,
            "blob_sha": blob_sha,
            "content_sha256": content_sha,
            "citation_url_exact": citation_url_exact,
            "language": language_for(relative),
        },
        "body": (
            f"Repository path: {relative}\n"
            f"Git revision: {revision}\n"
            f"Content SHA-256: {content_sha}\n\n{text}"
        ),
    }


def local_source_object(
    repo: Path,
    path: Path,
    *,
    repository_url: str,
    slug: str,
    revision: str,
    project_key: str,
) -> dict | None:
    raw = path.read_bytes()
    text = decode_text(raw)
    if text is None:
        return None
    relative = path.relative_to(repo).as_posix()
    working_blob_sha = git(repo, "hash-object", "--", relative) or hashlib.sha256(raw).hexdigest()
    committed_blob_sha = git(repo, "rev-parse", f"{revision}:{relative}") if len(revision) == 40 else None
    dirty = committed_blob_sha != working_blob_sha
    updated_at = git(repo, "log", "-1", "--format=%aI", "--", relative)
    author = git(repo, "log", "-1", "--format=%an", "--", relative) or ""
    if dirty or not updated_at:
        updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    item = build_source_object(
        relative=relative,
        text=text,
        repository_url=repository_url,
        slug=slug,
        revision=revision,
        blob_sha=working_blob_sha,
        updated_at=updated_at,
        author=author,
        project_key=project_key,
        transport="local_checkout",
        content_origin="working_tree" if dirty else "git_commit",
        citation_url_exact=not dirty and len(revision) == 40,
    )
    item["metadata"]["committed_blob_sha"] = committed_blob_sha
    item["metadata"]["working_tree_dirty"] = dirty
    return item


def github_headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "verity-repository-connector",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def github_json(session: requests.Session, url: str, token: str | None) -> dict:
    response = session.get(url, headers=github_headers(token), timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"GitHub returned an unexpected payload for {url}")
    return payload


def github_source_objects(
    *,
    repository_url: str,
    slug: str,
    ref: str,
    patterns: list[str],
    project_key: str,
    max_file_bytes: int,
    token: str | None,
) -> tuple[list[dict], str]:
    with requests.Session() as session:
        commit = github_json(session, f"{GITHUB_API}/repos/{slug}/commits/{quote(ref, safe='')}", token)
        revision = str(commit["sha"])
        tree_sha = str(commit["commit"]["tree"]["sha"])
        tree = github_json(
            session,
            f"{GITHUB_API}/repos/{slug}/git/trees/{tree_sha}?recursive=1",
            token,
        )
        if tree.get("truncated"):
            raise RuntimeError("GitHub tree response was truncated; narrow the connector include patterns")
        selected = [
            row
            for row in tree.get("tree", [])
            if row.get("type") == "blob"
            and int(row.get("size") or 0) <= max_file_bytes
            and any(fnmatchcase(str(row.get("path", "")), pattern) for pattern in patterns)
        ]
        selected.sort(key=lambda row: str(row["path"]))
        commit_author = commit.get("author") or {}
        author = str(commit_author.get("login") or commit["commit"]["author"].get("name") or "")
        updated_at = str(commit["commit"]["author"]["date"])
        objects = []
        for row in selected:
            blob_sha = str(row["sha"])
            blob = github_json(session, f"{GITHUB_API}/repos/{slug}/git/blobs/{blob_sha}", token)
            if blob.get("encoding") != "base64":
                continue
            raw = base64.b64decode(str(blob.get("content", "")), validate=False)
            text = decode_text(raw)
            if text is None:
                continue
            objects.append(build_source_object(
                relative=str(row["path"]),
                text=text,
                repository_url=repository_url,
                slug=slug,
                revision=revision,
                blob_sha=blob_sha,
                updated_at=updated_at,
                author=author,
                project_key=project_key,
                transport="github_api",
                content_origin="git_commit",
                citation_url_exact=True,
            ))
    return objects, revision


def export_repository(
    repo: Path,
    *,
    patterns: list[str],
    output: Path,
    manifest_path: Path,
    repository_url: str,
    project_key: str,
    max_file_bytes: int,
    transport: str = "local",
    github_ref: str = "main",
    github_token: str | None = None,
) -> dict:
    repo = repo.resolve()
    repository_url = normalize_repository_url(repository_url or git(repo, "remote", "get-url", "origin"))
    slug = repository_slug(repository_url, repo)
    if transport == "github":
        objects, revision = github_source_objects(
            repository_url=repository_url,
            slug=slug,
            ref=github_ref,
            patterns=patterns,
            project_key=project_key,
            max_file_bytes=max_file_bytes,
            token=github_token,
        )
        dirty_paths: list[str] = []
        manifest_transport = "github_api"
    else:
        revision = git(repo, "rev-parse", "HEAD") or "working-tree"
        objects = []
        for path in discover_files(repo, patterns, max_file_bytes):
            item = local_source_object(
                repo,
                path,
                repository_url=repository_url,
                slug=slug,
                revision=revision,
                project_key=project_key,
            )
            if item:
                objects.append(item)
        dirty_paths = [
            item["metadata"]["path"]
            for item in objects
            if item["metadata"].get("working_tree_dirty")
        ]
        manifest_transport = "local_checkout"

    snapshot_hash = hashlib.sha256(
        "\n".join(
            f"{item['external_id']}:{item['metadata']['content_sha256']}"
            for item in objects
        ).encode("utf-8")
    ).hexdigest()
    manifest = {
        "connector": "github_repository",
        "transport": manifest_transport,
        "repository": slug,
        "repository_url": repository_url,
        "revision": revision,
        "snapshot_sha256": snapshot_hash,
        "working_tree_dirty": bool(dirty_paths),
        "dirty_paths": dirty_paths,
        "object_count": len(objects),
        "include_patterns": patterns,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for item in objects:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--output", default="data/live/github/repository_source_objects.jsonl")
    parser.add_argument("--manifest", default="data/live/github/repository_manifest.json")
    parser.add_argument("--repository-url", default="")
    parser.add_argument("--transport", choices=["local", "github"], default="local")
    parser.add_argument("--github-ref", default="main")
    parser.add_argument("--project-key", default="VERITY")
    parser.add_argument("--include", action="append", dest="patterns")
    parser.add_argument("--max-file-bytes", type=int, default=200_000)
    args = parser.parse_args()
    manifest = export_repository(
        Path(args.repo),
        patterns=args.patterns or DEFAULT_PATTERNS,
        output=Path(args.output),
        manifest_path=Path(args.manifest),
        repository_url=args.repository_url,
        project_key=args.project_key,
        max_file_bytes=args.max_file_bytes,
        transport=args.transport,
        github_ref=args.github_ref,
        github_token=os.environ.get("GITHUB_TOKEN"),
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
