from __future__ import annotations
import argparse
import datetime as dt
import json
import random
from pathlib import Path

PROJECTS = ["ORION", "ATLAS", "MERIDIAN", "NOVA", "KEYSTONE"]
ACCOUNTS = ["Acme Corp", "Northwind Traders", "Globex", "Initech", "Umbrella Financial", "Contoso Health"]
COMPONENTS = ["PostgreSQL", "Search Service", "Connector Service", "Billing API", "Data Plane"]
TEAMS = ["Database Platform", "Search Platform", "Customer Engineering", "Release Engineering", "Support Ops"]

SOURCE_TYPES = {
    "slack": ["channel_thread", "incident_thread", "release_thread"],
    "jira": ["issue", "bug", "epic", "task"],
    "confluence": ["page", "runbook", "postmortem", "design_doc"],
    "salesforce": ["case", "account_note", "customer_commitment"],
    "servicenow": ["incident", "problem", "change_request"],
    "github": ["pull_request", "issue", "release_note"],
}

THEMES = [
    "read replica lag causing delayed cutover",
    "Blue/Green deployment validation failed",
    "customer-visible latency after May release",
    "Slack release thread decided to hold cutover",
    "Salesforce escalation linked to delayed report generation",
    "Confluence design notes mention rollback risk",
    "GitHub pull request improves connection pooling",
    "release readiness review identifies unresolved dependency",
    "runbook missing failover verification steps",
    "customer commitment depends on migration timeline",
    "P1 bug blocks production release",
]

STATUSES = ["Open", "In Progress", "Escalated", "Blocked", "Resolved", "Closed"]
PRIORITIES = ["P0", "P1", "P2", "P3", "Sev1", "Sev2"]


def iso_date(days_back=120):
    now = dt.datetime.now(dt.timezone.utc)
    return (now - dt.timedelta(days=random.randint(0, days_back), hours=random.randint(0, 23))).isoformat()


def make_body(system: str, title: str, project: str, account: str, component: str) -> str:
    if system == "slack":
        return (
            f"#proj-{project.lower()}-release thread\n\n"
            f"Priya: Replica lag is still above threshold; hold cutover until soak results are clean.\n"
            f"Alex: Customer Engineering says {account} needs an update before EOD.\n"
            f"Mina: Linking the runbook and Jira blocker. We should not proceed without validation.\n"
            f"Sam: PR is merged but we need one more load test. Component: {component}.\n"
            f"Decision: delay the cutover and publish customer-facing status once the lag is under threshold."
        )
    return (
        f"{title}\n\n"
        f"Summary: {random.choice(THEMES)}. This record is associated with Project {project}, account {account}, and component {component}. "
        f"Operational notes mention release timing, customer impact, owner handoffs, Slack decisions, runbook validation, and remediation evidence. "
        f"The current discussion includes terms such as failover, latency, rollback, replica lag, deployment readiness, and customer commitment. "
        f"Evidence should be compared across Slack threads, Jira blockers, Confluence pages, Salesforce cases, ServiceNow incidents, and GitHub pull requests."
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--objects", type=int, default=2000)
    parser.add_argument("--out", default="data/generated")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    random.seed(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for i in range(1, args.objects + 1):
        system = random.choice(list(SOURCE_TYPES))
        source_type = random.choice(SOURCE_TYPES[system])
        project = random.choice(PROJECTS)
        # Bias enough rows to Orion so the workshop query works.
        if i % 4 == 0:
            project = "ORION"
        account = random.choice(ACCOUNTS)
        component = random.choice(COMPONENTS)
        prefix = {"slack": "SLACK", "jira": project, "confluence": "PAGE", "salesforce": "CASE", "servicenow": "INC", "github": "PR"}[system]
        external_id = f"{prefix}-{i:06d}"
        title = f"{external_id}: {random.choice(THEMES).title()}"
        body = make_body(system, title, project, account, component)
        rows.append({
            "source_system": system,
            "source_type": source_type,
            "external_id": external_id,
            "title": title,
            "url": f"https://example.internal/{system}/{external_id}",
            "status": random.choice(STATUSES),
            "priority": random.choice(PRIORITIES),
            "owner": random.choice(["Priya N.", "Alex M.", "Sam R.", "Mina L.", "Jordan K."]),
            "owner_team": random.choice(TEAMS),
            "account_name": account,
            "project_key": project,
            "component": component,
            "environment": random.choice(["prod", "stage", "dev"]),
            "created_at": iso_date(180),
            "updated_at": iso_date(30),
            "source_authority": round(random.uniform(0.60, 0.98), 2),
            "acl": {"visibility": "workshop_lab", "allowed_teams": random.sample(TEAMS, k=2)},
            "metadata": {"workshop_seed": True, "labels": random.sample(["database", "latency", "failover", "release", "customer-impact", "migration", "runbook", "slack-decision"], 3)},
            "body": body,
        })

    path = out / "source_objects.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    (out / "manifest.json").write_text(json.dumps({"objects": len(rows), "workshop_seed": True}, indent=2), encoding="utf-8")
    print(f"Wrote {len(rows)} objects to {path}")

if __name__ == "__main__":
    main()
