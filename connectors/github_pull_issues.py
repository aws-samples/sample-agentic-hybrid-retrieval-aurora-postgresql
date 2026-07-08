from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", default=os.environ.get("GITHUB_OWNER"))
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPO"))
    parser.add_argument("--out", default="data/live/github/source_objects.jsonl")
    args = parser.parse_args()
    if not args.owner or not args.repo:
        raise SystemExit("--owner and --repo are required")
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{args.owner}/{args.repo}/issues"
    resp = requests.get(url, headers=headers, params={"state": "all", "per_page": 100}, timeout=30)
    resp.raise_for_status()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with Path(args.out).open("w", encoding="utf-8") as f:
        for issue in resp.json():
            source_type = "pull_request" if "pull_request" in issue else "issue"
            f.write(json.dumps({
                "source_system": "github",
                "source_type": source_type,
                "external_id": str(issue["number"]),
                "title": issue["title"],
                "url": issue["html_url"],
                "status": issue["state"],
                "priority": "",
                "owner": (issue.get("user") or {}).get("login", ""),
                "owner_team": "",
                "account_name": "",
                "project_key": args.repo.upper(),
                "component": "",
                "environment": "",
                "created_at": issue["created_at"],
                "updated_at": issue["updated_at"],
                "source_authority": 0.80,
                "acl": {"visibility": "source-system"},
                "metadata": issue,
                "body": issue.get("body") or issue["title"],
            }) + "\n")
    print(f"Wrote GitHub source objects to {args.out}")

if __name__ == "__main__":
    main()
