from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path


def normalize_row(source_system: str, row: dict) -> dict:
    if source_system == "salesforce":
        external_id = row.get("CaseNumber") or row.get("Id") or row.get("external_id")
        title = row.get("Subject") or row.get("Name") or "Salesforce record"
        body = row.get("Description") or row.get("Comments") or title
        status = row.get("Status") or ""
        priority = row.get("Priority") or ""
        account = row.get("Account.Name") or row.get("AccountName") or ""
    elif source_system == "jira":
        external_id = row.get("key") or row.get("id") or row.get("external_id")
        title = row.get("summary") or row.get("fields.summary") or "Jira issue"
        body = row.get("description") or row.get("fields.description") or title
        status = row.get("status") or row.get("fields.status.name") or ""
        priority = row.get("priority") or row.get("fields.priority.name") or ""
        account = ""
    else:
        external_id = row.get("id") or row.get("Id") or row.get("external_id")
        title = row.get("title") or row.get("name") or row.get("summary") or "Source object"
        body = row.get("body") or row.get("description") or row.get("content") or title
        status = row.get("status") or ""
        priority = row.get("priority") or ""
        account = row.get("account_name") or ""
    return {
        "source_system": source_system,
        "source_type": row.get("source_type") or row.get("type") or "object",
        "external_id": external_id,
        "title": title,
        "url": row.get("url") or "",
        "status": status,
        "priority": priority,
        "owner": row.get("owner") or row.get("assignee") or "",
        "owner_team": row.get("owner_team") or "",
        "account_name": account,
        "project_key": row.get("project_key") or row.get("project") or "",
        "component": row.get("component") or "",
        "environment": row.get("environment") or "",
        "created_at": row.get("created_at") or row.get("CreatedDate") or "",
        "updated_at": row.get("updated_at") or row.get("LastModifiedDate") or "",
        "source_authority": float(row.get("source_authority") or 0.70),
        "acl": {"visibility": "source-system"},
        "metadata": row,
        "body": body,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-system", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with Path(args.input).open("r", encoding="utf-8", newline="") as f:
        rows = [normalize_row(args.source_system, r) for r in csv.DictReader(f)]
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with Path(args.output).open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    print(f"Wrote {len(rows)} normalized rows to {args.output}")

if __name__ == "__main__":
    main()
