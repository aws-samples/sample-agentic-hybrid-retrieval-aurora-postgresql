"""Deterministic filler corpus for the seed.

The golden thread (6 cited) + near-miss set (4) are 10 named objects. To reach
150 total (30 per system) we add 140 filler objects — realistic operational
noise across other projects so the Orion query has something to rank against.

Everything is seeded from a fixed RNG, so the corpus is byte-identical run to
run. Filler metadata mirrors real source API/export shapes (see connectors/):
Jira fields.*, Slack channel/ts/thread_ts, Salesforce CaseNumber/Account.Name,
Confluence space/version, GitHub number/merged_at.
"""
from __future__ import annotations

import random
from typing import Any

from canonical import CITED, NEAR_MISS, PER_SYSTEM, SYSTEMS

# Named objects already present per system (counted against the 30-per-system quota).
NAMED = CITED + [dict(n=None, **o) for o in NEAR_MISS]

# Non-Orion projects/accounts so filler is plausible but never competes with the
# golden thread for the "Orion" query.
PROJECTS = ["ATLAS", "MERIDIAN", "NOVA", "KEYSTONE", "HELIX", "CALYPSO"]
ACCOUNTS = ["Northwind Traders", "Globex", "Initech", "Umbrella Financial", "Contoso Health", "Soylent Systems"]
COMPONENTS = ["Billing API", "Search Service", "Connector Service", "Data Plane", "Auth Gateway", "Reporting"]
TEAMS = ["Database Platform", "Search Platform", "Customer Engineering", "Support Ops", "Payments", "Identity"]
OWNERS = ["priya.n", "alex.m", "sam.r", "mina.l", "jordan.k", "dana.w", "rafael.o", "lee.c"]

THEMES = [
    "connection pool exhaustion under load",
    "blue/green validation timeout",
    "p95 latency regression after release",
    "read replica promotion runbook update",
    "customer escalation on report freshness",
    "rollback risk noted in design review",
    "batch job retry storm",
    "index bloat on hot table",
    "backfill job pacing",
    "cache stampede on cold start",
    "webhook delivery retries",
    "schema migration lock contention",
]

# Fixed 2026 dates the filler draws from (no Date.now()).
DAYS = [
    "2026-03-04", "2026-03-19", "2026-04-02", "2026-04-15", "2026-04-28",
    "2026-05-06", "2026-05-17", "2026-05-29", "2026-06-03", "2026-06-09",
    "2026-06-15", "2026-06-21", "2026-06-27", "2026-07-01", "2026-07-05",
]


def _iso(rng: random.Random) -> str:
    day = rng.choice(DAYS)
    return f"{day}T{rng.randint(8, 19):02d}:{rng.randint(0, 59):02d}:00-04:00"


def _slack_meta(rng: random.Random, ext: str, ts: str) -> dict[str, Any]:
    chan = rng.choice(["proj-atlas", "proj-nova", "eng-oncall", "release-room", "cust-eng"])
    epoch = 1740000000 + rng.randint(0, 9_000_000)
    return {
        "channel": {"id": f"C0{rng.randint(100000, 999999)}", "name": chan},
        "ts": f"{epoch}.{rng.randint(100000, 999999)}",
        "thread_ts": f"{epoch}.{rng.randint(100000, 999999)}",
        "reply_count": rng.randint(0, 24),
        "reactions": [{"name": "eyes", "count": rng.randint(1, 6)}],
        "permalink": f"https://acme.slack.com/archives/C0/{ext}",
    }


def _jira_meta(rng: random.Random, project: str, status: str, priority: str, component: str) -> dict[str, Any]:
    itype = rng.choice(["Bug", "Task", "Story", "Incident"])
    return {
        "fields": {
            "status": {"name": status},
            "priority": {"name": priority},
            "issuetype": {"name": itype},
            "project": {"key": project},
            "fixVersions": [{"name": f"{project.lower()}/2026.0{rng.randint(4, 7)}"}],
            "components": [{"name": component}],
            "assignee": {"displayName": rng.choice(OWNERS)},
        }
    }


def _confluence_meta(rng: random.Random, project: str) -> dict[str, Any]:
    return {
        "space": {"key": project[:4].upper(), "name": f"{project.title()} Space"},
        "version": {"number": rng.randint(1, 9)},
        "ancestors": [{"id": str(rng.randint(100000, 999999)), "title": "Engineering"}],
        "type": "page",
    }


def _salesforce_meta(rng: random.Random, ext: str, account: str, status: str, priority: str) -> dict[str, Any]:
    return {
        "CaseNumber": ext.split("-")[-1],
        "Subject": None,  # filled from title at emit time
        "Account": {"Name": account},
        "Priority": priority,
        "Status": status,
        "Stage": rng.choice(["New", "Working", "Escalated", "Closed"]),
        "ARR": rng.choice([120000, 240000, 480000, 750000]),
    }


def _github_meta(rng: random.Random, ext: str, merged: bool) -> dict[str, Any]:
    num = int(ext.split("-")[-1])
    return {
        "number": num,
        "merged_at": (_iso(rng) if merged else None),
        "base": {"ref": "release/2026.06"},
        "head": {"ref": f"fix/{rng.choice(THEMES).split()[0]}"},
        "additions": rng.randint(4, 480),
        "deletions": rng.randint(0, 120),
        "labels": [{"name": rng.choice(["bug", "infra", "perf", "chore"])}],
    }


def _body(system: str, title: str, project: str, account: str, component: str, theme: str) -> str:
    if system == "slack":
        return (
            f"#{project.lower()}-release thread\n\n"
            f"Owner: seeing {theme}. Holding until soak is clean.\n"
            f"Reply: linking the runbook and the tracking issue for {component}.\n"
            f"Reply: {account} was notified; no customer-facing change yet."
        )
    return (
        f"{title}\n\n"
        f"Summary: {theme}. Associated with project {project}, account {account}, "
        f"component {component}. Notes cover release timing, owner handoffs, and remediation "
        f"evidence across Slack, Jira, Confluence, Salesforce, and GitHub."
    )


def build_filler(seed: int = 7) -> list[dict[str, Any]]:
    """Return exactly (150 - 10) = 140 filler objects, 30 per system minus named."""
    rng = random.Random(seed)
    named_by_system: dict[str, int] = {s: 0 for s in SYSTEMS}
    for o in NAMED:
        named_by_system[o["source_system"]] += 1

    # Never re-mint an external_id already claimed by a named object.
    used: set[str] = {o["external_id"] for o in NAMED}

    prefix = {"slack": "SLACK", "jira": "FILL", "confluence": "PAGE", "salesforce": "CASE", "github": "PR"}
    counter = {s: 900000 for s in SYSTEMS}
    out: list[dict[str, Any]] = []

    def mint(system: str) -> str:
        while True:
            if system == "jira":
                ext = f"{rng.choice(PROJECTS)}-{rng.randint(1000, 4999)}"
            elif system == "slack":
                counter[system] += 1
                ext = f"{prefix[system]}-{counter[system]:06d}"
            elif system == "confluence":
                ext = f"{prefix[system]}-{rng.randint(2200, 2999)}"
            elif system == "salesforce":
                ext = f"{prefix[system]}-{rng.randint(20000, 29999)}"
            else:  # github
                ext = f"{prefix[system]}-{rng.randint(1300, 1600)}"
            if ext not in used:
                used.add(ext)
                return ext

    for system in SYSTEMS:
        need = PER_SYSTEM - named_by_system[system]
        for _ in range(need):
            account = rng.choice(ACCOUNTS)
            component = rng.choice(COMPONENTS)
            theme = rng.choice(THEMES)
            status = rng.choice(["Open", "In Progress", "Resolved", "Closed"])
            priority = rng.choice(["P2", "P3", "Sev3"])
            when = _iso(rng)

            ext = mint(system)
            project = ext.split("-")[0] if system == "jira" else rng.choice(PROJECTS)

            title = f"{ext} — {theme}"
            source_type = {
                "slack": "Slack thread",
                "jira": "Issue",
                "confluence": "Page",
                "salesforce": "Case",
                "github": "Pull request",
            }[system]

            if system == "slack":
                meta = _slack_meta(rng, ext, when)
            elif system == "jira":
                meta = _jira_meta(rng, project, status, priority, component)
            elif system == "confluence":
                meta = _confluence_meta(rng, project)
            elif system == "salesforce":
                meta = _salesforce_meta(rng, ext, account, status, priority)
                meta["Subject"] = title
            else:
                meta = _github_meta(rng, ext, merged=(status in ("Resolved", "Closed")))

            out.append({
                "source_system": system,
                "source_type": source_type,
                "external_id": ext,
                "title": title,
                "url": f"https://example.internal/{system}/{ext}",
                "status": status,
                "priority": priority,
                "owner": rng.choice(OWNERS),
                "owner_team": rng.choice(TEAMS),
                "account_name": account if system == "salesforce" else None,
                "project_key": project,
                "component": component,
                "environment": rng.choice(["prod", "stage", "dev"]),
                "created_at": when,
                "updated_at": when,
                "source_authority": round(rng.uniform(0.55, 0.75), 2),
                "metadata": meta,
                "body": _body(system, title, project, account, component, theme),
            })
    return out
