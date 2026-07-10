"""Real source-format metadata for the ten named objects.

Mirrors the actual API/export shapes each connector normalizes from, so a
workshop attendee inspecting ops.source_objects.metadata sees exactly what a
live Jira/Slack/Salesforce/Confluence/GitHub sync would have written.
"""
from __future__ import annotations

from typing import Any

# external_id -> metadata jsonb (real source shape)
REAL_METADATA: dict[str, dict[str, Any]] = {
    "SLACK-000271": {
        "channel": {"id": "C0PROJORION", "name": "proj-orion"},
        "ts": "1750708320.000271",
        "thread_ts": "1750708320.000271",
        "reply_count": 14,
        "reactions": [{"name": "white_check_mark", "count": 9}, {"name": "eyes", "count": 5}],
        "permalink": "https://acme.slack.com/archives/C0PROJORION/p1750708320000271",
        "user": {"id": "U0PRIYA", "real_name": "Priya Mehta"},
    },
    "ORION-1473": {
        "fields": {
            "status": {"name": "Resolved", "statusCategory": {"key": "done"}},
            "priority": {"name": "P1"},
            "issuetype": {"name": "Bug"},
            "project": {"key": "ORION", "name": "Orion"},
            "fixVersions": [{"name": "orion/2026.07"}],
            "components": [{"name": "Events pipeline"}],
            "assignee": {"displayName": "Rafael Ortiz", "accountId": "acc:rortiz"},
            "labels": ["replication-lag", "ga-blocker"],
        },
        "key": "ORION-1473",
    },
    "CASE-0012345": {
        "CaseNumber": "0012345",
        "Subject": "Acme Corp go-live commitment at risk",
        "Account": {"Name": "Acme Corp", "Id": "001ACME"},
        "Priority": "Tier 1",
        "Status": "Working",
        "Stage": "Escalated",
        "ARR": 1200000,
        "ContractGoLive": "2026-07-08",
        "Owner": {"Name": "Dana Whitfield"},
    },
    "PAGE-2112": {
        "space": {"key": "ORION", "name": "Orion Release"},
        "version": {"number": 7, "when": "2026-06-18T14:00:00-04:00"},
        "ancestors": [{"id": "210001", "title": "Release Engineering"}],
        "type": "page",
        "labels": ["runbook", "release-gate"],
    },
    "ORION-1489": {
        "fields": {
            "status": {"name": "Resolved", "statusCategory": {"key": "done"}},
            "priority": {"name": "Sev2"},
            "issuetype": {"name": "Incident"},
            "project": {"key": "ORION", "name": "Orion"},
            "fixVersions": [{"name": "orion/2026.07"}],
            "components": [{"name": "Events pipeline"}],
            "assignee": {"displayName": "SRE on-call", "accountId": "acc:sre-oncall"},
            "labels": ["paging", "replication_lag_seconds", "eu-west-1"],
        },
        "key": "ORION-1489",
        "auto_filed_by": "alerting-bot",
    },
    "PR-1287": {
        "number": 1287,
        "merged_at": "2026-07-02T19:47:00-04:00",
        "base": {"ref": "release/2026.07"},
        "head": {"ref": "fix/partition-wal-by-region"},
        "additions": 214,
        "deletions": 63,
        "labels": [{"name": "infra"}, {"name": "perf"}],
        "merged_by": {"login": "rafael-ortiz"},
    },
    # near-miss
    "SLACK-000288": {
        "channel": {"id": "C0PROJORION", "name": "proj-orion"},
        "ts": "1750762500.000288",
        "thread_ts": "1750762500.000288",
        "reply_count": 6,
        "reactions": [{"name": "eyes", "count": 3}],
        "permalink": "https://acme.slack.com/archives/C0PROJORION/p1750762500000288",
    },
    "PAGE-2044": {
        "space": {"key": "ORION", "name": "Orion Release"},
        "version": {"number": 3, "when": "2026-05-14T10:00:00-04:00"},
        "ancestors": [{"id": "210001", "title": "Release Engineering"}],
        "type": "page",
        "labels": ["postmortem", "backpressure"],
    },
    "ORION-1502": {
        "fields": {
            "status": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
            "priority": {"name": "P3"},
            "issuetype": {"name": "Task"},
            "project": {"key": "ORION", "name": "Orion"},
            "components": [{"name": "Dashboards"}],
            "assignee": {"displayName": "Sam Ridley"},
        },
        "key": "ORION-1502",
    },
    "PR-1244": {
        "number": 1244,
        "merged_at": None,
        "base": {"ref": "release/2026.06"},
        "head": {"ref": "fix/consumer-scale-out"},
        "additions": 88,
        "deletions": 12,
        "labels": [{"name": "infra"}, {"name": "reverted"}],
        "state": "closed",
    },
}
