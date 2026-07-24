from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any
import uuid

CORPUS_NAMESPACE = uuid.UUID("d94fc53f-ed5d-4c30-8764-f43bc0bbdd62")
WORKSHOP_ACL = {"visibility": "workshop", "principals": []}
RESTRICTED_ACL = {"visibility": "restricted", "principals": ["support-lead"]}


def evidence_id(kind: str, external_key: str) -> uuid.UUID:
    return uuid.uuid5(CORPUS_NAMESPACE, f"{kind}:{external_key}")


def _iso_revision(prefix: str, ordinal: int = 1) -> str:
    return f"{prefix.lower()}-revision-{ordinal}"


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _canonical_rows() -> dict[str, list[tuple]]:
    clusters = [
        (
            "orders-prod-1",
            "aurora-postgresql",
            "17.5",
            "us-east-1",
            "production",
            "checkout-writer",
            "orders-prod-1.cluster.local",
            _json({"workload": "transactional", "tier": "critical"}),
        ),
        (
            "identity-prod-1",
            "aurora-postgresql",
            "17.5",
            "us-east-1",
            "production",
            "identity-api",
            "identity-prod-1.cluster.local",
            _json({"workload": "transactional", "tier": "critical"}),
        ),
        (
            "billing-prod-2",
            "aurora-postgresql",
            "16.8",
            "us-west-2",
            "production",
            "billing-ledger",
            "billing-prod-2.cluster.local",
            _json({"workload": "transactional", "tier": "critical"}),
        ),
        (
            "catalog-prod-1",
            "aurora-postgresql",
            "16.8",
            "eu-west-1",
            "production",
            "catalog-api",
            "catalog-prod-1.cluster.local",
            _json({"workload": "mixed", "tier": "standard"}),
        ),
        (
            "orders-staging-1",
            "aurora-postgresql",
            "17.5",
            "us-east-1",
            "staging",
            "checkout-writer",
            "orders-staging-1.cluster.local",
            _json({"workload": "test", "tier": "nonproduction"}),
        ),
    ]

    evidence: list[tuple] = []
    incidents: list[tuple] = []
    changes: list[tuple] = []
    cases: list[tuple] = []
    runbooks: list[tuple] = []
    lock_evidence: list[tuple] = []
    incident_changes: list[tuple] = []
    incident_cases: list[tuple] = []
    incident_runbooks: list[tuple] = []

    def add_evidence(
        kind: str,
        key: str,
        title: str,
        source_system: str,
        source_uri: str,
        updated_at: datetime,
        *,
        revision: str | None = None,
        acl: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        item_id = evidence_id(kind, key)
        evidence.append(
            (
                item_id,
                kind,
                key,
                title,
                source_system,
                source_uri,
                revision or _iso_revision(key),
                updated_at,
                _json(acl or WORKSHOP_ACL),
            )
        )
        return item_id

    incident_started = datetime(2026, 7, 18, 14, 4, tzinfo=timezone.utc)
    incident = add_evidence(
        "incident",
        "INC-2047",
        "Checkout writes stalled during customer index deployment",
        "incident_management",
        "workshop://incidents/INC-2047",
        incident_started + timedelta(hours=4),
        revision="inc-2047-final",
    )
    incidents.append(
        (
            incident,
            "INC-2047",
            "orders-prod-1",
            "SEV-1",
            "resolved",
            incident_started,
            incident_started + timedelta(minutes=18),
            incident_started + timedelta(hours=4),
            (
                "Checkout INSERT and UPDATE statements accumulated relation-lock waits "
                "immediately after an online schema change began."
            ),
            (
                "EU checkout writes timed out for 14 minutes. Read-only order history "
                "remained available because the index build did not conflict with ordinary SELECT."
            ),
            (
                "The team cancelled the blocking index build, drained queued writers, "
                "and later created the index concurrently under a controlled change."
            ),
        )
    )

    change = add_evidence(
        "change",
        "CHG-1842",
        "Add customer-created-at index to orders",
        "change_control",
        "workshop://changes/CHG-1842",
        incident_started + timedelta(minutes=20),
        revision="chg-1842-closed",
    )
    changes.append(
        (
            change,
            "CHG-1842",
            "orders-prod-1",
            "ddl",
            "cancelled",
            incident_started,
            incident_started + timedelta(minutes=16),
            "checkout-database",
            (
                "CREATE INDEX idx_orders_customer_created "
                "ON orders (customer_id, created_at DESC);"
            ),
            (
                "The migration used ordinary CREATE INDEX on the production writer. "
                "PostgreSQL permits reads during this operation but blocks writes to the table."
            ),
            (
                "Cancel the index build, confirm queued writers recover, remove an invalid "
                "index if present, and reschedule with CREATE INDEX CONCURRENTLY outside "
                "a transaction block."
            ),
        )
    )
    incident_changes.append(
        (
            incident,
            change,
            "confirmed",
            (
                "The change start timestamp matches the first Lock:relation wait, and "
                "pg_blocking_pids identified the CREATE INDEX backend as the blocker."
            ),
            "database-on-call",
        )
    )

    ruled_out_change = add_evidence(
        "change",
        "CHG-1838",
        "Raise checkout API worker count",
        "change_control",
        "workshop://changes/CHG-1838",
        incident_started - timedelta(hours=2),
        revision="chg-1838-complete",
    )
    changes.append(
        (
            ruled_out_change,
            "CHG-1838",
            "orders-prod-1",
            "configuration",
            "completed",
            incident_started - timedelta(hours=3),
            incident_started - timedelta(hours=2, minutes=55),
            "checkout-platform",
            None,
            "Raised application worker count from 48 to 56 after a planned load test.",
            "Restore the worker count to 48 and recycle the application deployment.",
        )
    )
    incident_changes.append(
        (
            incident,
            ruled_out_change,
            "ruled_out",
            (
                "Connection count and CPU remained inside the pre-change envelope; "
                "the blocked sessions were waiting on a relation lock."
            ),
            "incident-commander",
        )
    )

    case_acme = add_evidence(
        "support_case",
        "CASE-7419",
        "Acme Retail checkout writes timing out",
        "customer_support",
        "workshop://support-cases/CASE-7419",
        incident_started + timedelta(minutes=8),
        revision="case-7419-update-3",
    )
    cases.append(
        (
            case_acme,
            "CASE-7419",
            "Acme Retail",
            "Enterprise",
            "urgent",
            "resolved",
            incident_started + timedelta(minutes=3),
            incident_started + timedelta(minutes=33),
            "Checkout writes time out while order history remains readable",
            (
                "The customer reported failed order submissions in eu-west storefronts. "
                "Application traces showed database statements waiting until statement_timeout."
            ),
            "Provide a root-cause update within 30 minutes and confirm the recovery window.",
        )
    )
    incident_cases.append(
        (
            incident,
            case_acme,
            "affected",
            "The case timestamps and checkout writer cluster match the incident window.",
        )
    )

    case_restricted = add_evidence(
        "support_case",
        "CASE-7421",
        "Northstar Foods premium checkout escalation",
        "customer_support",
        "workshop://support-cases/CASE-7421",
        incident_started + timedelta(minutes=12),
        revision="case-7421-update-2",
        acl=RESTRICTED_ACL,
    )
    cases.append(
        (
            case_restricted,
            "CASE-7421",
            "Northstar Foods",
            "Enterprise",
            "urgent",
            "resolved",
            incident_started + timedelta(minutes=6),
            incident_started + timedelta(minutes=36),
            "Premium checkout escalation during write stall",
            (
                "A restricted support escalation recorded failed order submissions during "
                "the same production relation-lock window."
            ),
            "Support leadership must approve the customer-facing incident narrative.",
        )
    )
    incident_cases.append(
        (
            incident,
            case_restricted,
            "affected",
            "The restricted case names the same cluster, service, and incident interval.",
        )
    )

    case_unaffected = add_evidence(
        "support_case",
        "CASE-7424",
        "Catalog search latency in eu-west-1",
        "customer_support",
        "workshop://support-cases/CASE-7424",
        incident_started + timedelta(minutes=40),
        revision="case-7424-update-1",
    )
    cases.append(
        (
            case_unaffected,
            "CASE-7424",
            "Contoso Home",
            "Business",
            "high",
            "open",
            incident_started + timedelta(minutes=22),
            incident_started + timedelta(hours=4),
            "Catalog search latency increased",
            (
                "The customer reported slow read-only catalog queries on catalog-prod-1. "
                "No checkout writes or orders tables were involved."
            ),
            "Provide query-plan findings by the next business day.",
        )
    )
    incident_cases.append(
        (
            incident,
            case_unaffected,
            "not_affected",
            "The case is on a different cluster and read-only service.",
        )
    )

    runbook = add_evidence(
        "runbook",
        "RB-017",
        "Build PostgreSQL indexes without blocking application writes",
        "engineering_knowledge",
        "https://www.postgresql.org/docs/current/sql-createindex.html",
        incident_started - timedelta(days=35),
        revision="rb-017-v4",
    )
    runbooks.append(
        (
            runbook,
            "RB-017",
            4,
            "current",
            "database-reliability",
            "aurora-postgresql",
            "[14,19)",
            (
                "Before creating an index on a write-active production table, inspect long-running "
                "transactions and estimate build duration. Use CREATE INDEX CONCURRENTLY when writes "
                "must continue. Run it outside a transaction block. Monitor pg_stat_progress_create_index, "
                "pg_stat_activity, pg_locks, and application latency. If cancelled or failed, inspect for "
                "an invalid index before retrying."
            ),
            (
                "Concurrent builds perform additional work, take longer, and can leave an INVALID index "
                "after failure. They are not a substitute for change control or capacity validation."
            ),
        )
    )
    incident_runbooks.append(
        (
            incident,
            runbook,
            "used",
            "The response followed the blocker-identification and concurrent rebuild procedure.",
        )
    )

    lock_1 = add_evidence(
        "lock_evidence",
        "LOCK-2047-001",
        "Relation-lock snapshot for blocked checkout writer",
        "database_snapshot",
        "workshop://database-insights/INC-2047/2026-07-18T14:09:00Z",
        incident_started + timedelta(minutes=5),
        revision="lock-2047-capture-1",
    )
    lock_evidence.append(
        (
            lock_1,
            "LOCK-2047-001",
            incident,
            incident_started + timedelta(minutes=5),
            "public.orders",
            48122,
            47901,
            "Lock",
            "relation",
            (
                "UPDATE orders SET payment_state = $1, updated_at = now() "
                "WHERE order_id = $2"
            ),
            (
                "CREATE INDEX idx_orders_customer_created "
                "ON orders (customer_id, created_at DESC)"
            ),
            _json(
                {
                    "db_load_by_wait": {"Lock:relation": 38.4, "CPU": 2.1},
                    "sample_window_seconds": 60,
                    "source": "controlled Aurora PostgreSQL fixture",
                }
            ),
        )
    )

    lock_2 = add_evidence(
        "lock_evidence",
        "LOCK-2047-002",
        "Blocking PID confirmation from pg_blocking_pids",
        "database_snapshot",
        "workshop://pg-stat-activity/INC-2047/2026-07-18T14:10:00Z",
        incident_started + timedelta(minutes=6),
        revision="lock-2047-capture-2",
    )
    lock_evidence.append(
        (
            lock_2,
            "LOCK-2047-002",
            incident,
            incident_started + timedelta(minutes=6),
            "public.orders",
            48135,
            47901,
            "Lock",
            "relation",
            "INSERT INTO orders(order_id, customer_id, created_at) VALUES ($1, $2, now())",
            (
                "CREATE INDEX idx_orders_customer_created "
                "ON orders (customer_id, created_at DESC)"
            ),
            _json(
                {
                    "pg_blocking_pids": [47901],
                    "blocked_sessions": 47,
                    "source": "controlled Aurora PostgreSQL fixture",
                }
            ),
        )
    )

    second_incident_started = datetime(2026, 6, 9, 9, 20, tzinfo=timezone.utc)
    second_incident = add_evidence(
        "incident",
        "INC-2031",
        "Identity API connection pool saturated",
        "incident_management",
        "workshop://incidents/INC-2031",
        second_incident_started + timedelta(hours=2),
        revision="inc-2031-final",
    )
    incidents.append(
        (
            second_incident,
            "INC-2031",
            "identity-prod-1",
            "SEV-2",
            "resolved",
            second_incident_started,
            second_incident_started + timedelta(minutes=24),
            second_incident_started + timedelta(hours=2),
            "Identity requests queued after an application release opened more database sessions.",
            "Authentication latency increased; no relation-lock waits were observed.",
            "The team restored the previous pool limit and rolled out bounded connection acquisition.",
        )
    )

    second_runbook = add_evidence(
        "runbook",
        "RB-009",
        "Diagnose application connection saturation",
        "engineering_knowledge",
        "workshop://runbooks/RB-009",
        second_incident_started - timedelta(days=20),
        revision="rb-009-v2",
    )
    runbooks.append(
        (
            second_runbook,
            "RB-009",
            2,
            "current",
            "database-reliability",
            "aurora-postgresql",
            "[14,19)",
            (
                "Compare application pool limits with DatabaseConnections, active sessions, "
                "transaction duration, and rejected connection errors. Reduce pool fan-out before "
                "raising database limits, and consider RDS Proxy where connection churn is the problem."
            ),
            "Connection count alone does not identify lock contention or CPU saturation.",
        )
    )
    incident_runbooks.append(
        (
            second_incident,
            second_runbook,
            "used",
            "The runbook matched a connection-saturation incident without relation-lock evidence.",
        )
    )

    return {
        "clusters": clusters,
        "evidence": evidence,
        "incidents": incidents,
        "changes": changes,
        "cases": cases,
        "runbooks": runbooks,
        "lock_evidence": lock_evidence,
        "incident_changes": incident_changes,
        "incident_cases": incident_cases,
        "incident_runbooks": incident_runbooks,
    }


def _background_rows(document_target: int) -> dict[str, list[tuple]]:
    rows = {
        "clusters": [],
        "evidence": [],
        "incidents": [],
        "changes": [],
        "cases": [],
        "runbooks": [],
        "lock_evidence": [],
        "incident_changes": [],
        "incident_cases": [],
        "incident_runbooks": [],
    }
    if document_target <= 0:
        return rows

    clusters = [
        "orders-prod-1",
        "identity-prod-1",
        "billing-prod-2",
        "catalog-prod-1",
        "orders-staging-1",
    ]
    causes = [
        (
            "index build",
            "ordinary CREATE INDEX blocked table writes",
            "CREATE INDEX idx_event_lookup ON event_log (tenant_id, created_at)",
            "Use CREATE INDEX CONCURRENTLY outside a transaction block when writes must continue.",
        ),
        (
            "schema lock",
            "ALTER TABLE waited for and then held an ACCESS EXCLUSIVE lock",
            "ALTER TABLE event_log ADD COLUMN trace_token text",
            "Inspect blockers and schedule ACCESS EXCLUSIVE operations in a controlled window.",
        ),
        (
            "transaction blocker",
            "an open transaction held a conflicting relation lock",
            "UPDATE event_log SET state = 'processing' WHERE event_id = $1",
            "Find the blocker with pg_blocking_pids and end the transaction through change control.",
        ),
        (
            "migration queue",
            "a waiting DDL request caused later write requests to queue",
            "ALTER TABLE event_log ALTER COLUMN state SET NOT NULL",
            "Cancel unsafe DDL, drain the queue, and validate the migration against production-like load.",
        ),
    ]
    services = ["checkout", "identity", "billing", "catalog", "fulfillment"]
    accounts = [f"Tenant-{index:03d}" for index in range(1, 101)]
    base_time = datetime(2025, 1, 1, 8, 0, tzinfo=timezone.utc)
    group_count = (document_target + 4) // 5

    for index in range(1, group_count + 1):
        cluster_id = clusters[index % len(clusters)]
        cause_name, cause_summary, statement, recommendation = causes[index % len(causes)]
        service = services[index % len(services)]
        account = accounts[index % len(accounts)]
        relation_name = f"archive_{index % 50:02d}.event_log"
        started = base_time + timedelta(hours=index * 3)

        incident_key = f"INC-BG-{index:05d}"
        change_key = f"CHG-BG-{index:05d}"
        case_key = f"CASE-BG-{index:05d}"
        runbook_key = f"RB-BG-{index:05d}"
        lock_key = f"LOCK-BG-{index:05d}"

        incident = evidence_id("incident", incident_key)
        change = evidence_id("change", change_key)
        case = evidence_id("support_case", case_key)
        runbook = evidence_id("runbook", runbook_key)
        lock = evidence_id("lock_evidence", lock_key)

        common_evidence = [
            (
                incident,
                "incident",
                incident_key,
                f"{service.title()} write delay associated with {cause_name}",
                "incident_management",
                f"workshop://background/incidents/{incident_key}",
                _iso_revision(incident_key),
                started + timedelta(hours=1),
                _json(WORKSHOP_ACL),
            ),
            (
                change,
                "change",
                change_key,
                f"{service.title()} database maintenance",
                "change_control",
                f"workshop://background/changes/{change_key}",
                _iso_revision(change_key),
                started + timedelta(minutes=30),
                _json(WORKSHOP_ACL),
            ),
            (
                case,
                "support_case",
                case_key,
                f"{account} reported {service} write latency",
                "customer_support",
                f"workshop://background/cases/{case_key}",
                _iso_revision(case_key),
                started + timedelta(minutes=20),
                _json(WORKSHOP_ACL),
            ),
            (
                runbook,
                "runbook",
                runbook_key,
                f"Response procedure for {cause_name}",
                "engineering_knowledge",
                f"workshop://background/runbooks/{runbook_key}",
                _iso_revision(runbook_key),
                started - timedelta(days=30),
                _json(WORKSHOP_ACL),
            ),
            (
                lock,
                "lock_evidence",
                lock_key,
                f"Lock snapshot for {relation_name}",
                "database_snapshot",
                f"workshop://background/telemetry/{lock_key}",
                _iso_revision(lock_key),
                started + timedelta(minutes=5),
                _json(WORKSHOP_ACL),
            ),
        ]
        remaining = max(0, document_target - len(rows["evidence"]))
        rows["evidence"].extend(common_evidence[:remaining])
        if remaining <= 0:
            break

        rows["incidents"].append(
            (
                incident,
                incident_key,
                cluster_id,
                "SEV-2",
                "resolved",
                started,
                started + timedelta(minutes=20),
                started + timedelta(hours=1),
                f"{service.title()} writes slowed while {cause_summary}.",
                f"A bounded set of {service} requests exceeded their latency target.",
                "The unsafe operation was stopped and queued writes recovered.",
            )
        )
        rows["changes"].append(
            (
                change,
                change_key,
                cluster_id,
                "ddl",
                "cancelled",
                started,
                started + timedelta(minutes=18),
                f"{service}-database",
                statement,
                f"Maintenance on {relation_name}; review found that {cause_summary}.",
                recommendation,
            )
        )
        rows["cases"].append(
            (
                case,
                case_key,
                account,
                "Business",
                "high",
                "resolved",
                started + timedelta(minutes=3),
                started + timedelta(hours=4),
                f"{service.title()} writes exceeded latency target",
                f"{account} reported a bounded write delay on the {service} service.",
                "Provide a technical summary after incident resolution.",
            )
        )
        rows["runbooks"].append(
            (
                runbook,
                runbook_key,
                1,
                "current",
                "database-reliability",
                "aurora-postgresql",
                "[14,19)",
                recommendation,
                "Validate lock compatibility, transaction boundaries, and rollback before execution.",
            )
        )
        rows["lock_evidence"].append(
            (
                lock,
                lock_key,
                incident,
                started + timedelta(minutes=5),
                relation_name,
                50000 + (index % 1000),
                40000 + (index % 1000),
                "Lock",
                "relation",
                f"UPDATE {relation_name} SET state = $1 WHERE event_id = $2",
                statement,
                _json(
                    {
                        "db_load_by_wait": {"Lock:relation": 4 + (index % 20)},
                        "sample_window_seconds": 60,
                        "source": "generated workshop distractor",
                    }
                ),
            )
        )
        rows["incident_changes"].append(
            (
                incident,
                change,
                "confirmed",
                "The operation and first relation-lock wait share the same timestamp.",
                "background-generator",
            )
        )
        rows["incident_cases"].append(
            (
                incident,
                case,
                "affected",
                "The case references the same service and incident interval.",
            )
        )
        rows["incident_runbooks"].append(
            (
                incident,
                runbook,
                "recommended",
                "The procedure covers the observed lock pattern.",
            )
        )

    valid_ids = {row[0] for row in rows["evidence"]}
    for name in ("incidents", "changes", "cases", "runbooks", "lock_evidence"):
        rows[name] = [row for row in rows[name] if row[0] in valid_ids]
    rows["incident_changes"] = [
        row for row in rows["incident_changes"] if row[0] in valid_ids and row[1] in valid_ids
    ]
    rows["incident_cases"] = [
        row for row in rows["incident_cases"] if row[0] in valid_ids and row[1] in valid_ids
    ]
    rows["incident_runbooks"] = [
        row for row in rows["incident_runbooks"] if row[0] in valid_ids and row[1] in valid_ids
    ]
    return rows


def _merge_rows(target: dict[str, list[tuple]], addition: dict[str, list[tuple]]) -> None:
    for key, values in addition.items():
        target[key].extend(values)


def load_casework(conn, *, background_documents: int = 12000) -> dict[str, int]:
    rows = _canonical_rows()
    _merge_rows(rows, _background_rows(background_documents))

    with conn.transaction():
        with conn.cursor() as cursor:
            cursor.execute(
                """
                TRUNCATE TABLE
                  proof.answer_citations,
                  proof.agent_answers,
                  proof.run_stages,
                  proof.retrieval_candidates,
                  proof.retrieval_runs,
                  proof.relevance_judgments,
                  proof.evaluation_queries,
                  retrieval.inferred_edges,
                  retrieval.chunks,
                  retrieval.documents,
                  retrieval.projection_builds,
                  retrieval.projection_outbox,
                  casework.incident_runbooks,
                  casework.incident_support_cases,
                  casework.incident_changes,
                  casework.lock_evidence,
                  casework.runbooks,
                  casework.support_cases,
                  casework.changes,
                  casework.incidents,
                  casework.evidence_items,
                  casework.database_clusters
                RESTART IDENTITY
                """
            )
            cursor.executemany(
                """
                INSERT INTO casework.database_clusters(
                  cluster_id, engine, engine_version, aws_region, environment,
                  service_name, writer_endpoint_alias, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                rows["clusters"],
            )
            cursor.executemany(
                """
                INSERT INTO casework.evidence_items(
                  evidence_id, evidence_kind, external_key, title, source_system,
                  source_uri, source_revision, source_updated_at, acl
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                rows["evidence"],
            )
            cursor.executemany(
                """
                INSERT INTO casework.incidents(
                  evidence_id, incident_id, cluster_id, severity, status, started_at,
                  mitigated_at, resolved_at, summary, customer_impact, resolution
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                rows["incidents"],
            )
            cursor.executemany(
                """
                INSERT INTO casework.changes(
                  evidence_id, change_id, cluster_id, change_type, status, started_at,
                  completed_at, owner_team, execution_sql, description, rollback_plan
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                rows["changes"],
            )
            cursor.executemany(
                """
                INSERT INTO casework.support_cases(
                  evidence_id, case_id, account_name, support_tier, severity, status,
                  opened_at, sla_due_at, subject, description, customer_commitment
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                rows["cases"],
            )
            cursor.executemany(
                """
                INSERT INTO casework.runbooks(
                  evidence_id, runbook_id, version, status, owner_team,
                  applies_to_engine, applies_to_major_versions, procedure_text, caveats
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::int4range, %s, %s)
                """,
                rows["runbooks"],
            )
            cursor.executemany(
                """
                INSERT INTO casework.lock_evidence(
                  evidence_id, observation_id, incident_evidence_id, captured_at,
                  relation_name, blocked_pid, blocking_pid, wait_event_type, wait_event,
                  blocked_statement, blocking_statement, database_insights_slice
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                rows["lock_evidence"],
            )
            cursor.executemany(
                """
                INSERT INTO casework.incident_changes(
                  incident_evidence_id, change_evidence_id, relationship,
                  rationale, confirmed_by
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                rows["incident_changes"],
            )
            cursor.executemany(
                """
                INSERT INTO casework.incident_support_cases(
                  incident_evidence_id, case_evidence_id, impact, rationale
                )
                VALUES (%s, %s, %s, %s)
                """,
                rows["incident_cases"],
            )
            cursor.executemany(
                """
                INSERT INTO casework.incident_runbooks(
                  incident_evidence_id, runbook_evidence_id, applicability, rationale
                )
                VALUES (%s, %s, %s, %s)
                """,
                rows["incident_runbooks"],
            )
            cursor.execute(
                """
                INSERT INTO retrieval.projection_outbox(evidence_id, source_revision)
                SELECT evidence_id, source_revision
                FROM casework.evidence_items
                WHERE NOT is_deleted
                """
            )

            evaluation_queries = [
                (
                    "exact-change",
                    "Why did CHG-1842 block writes on orders-prod-1?",
                    _json({"cluster_id": "orders-prod-1"}),
                    "Exact change and cluster identifiers require lexical recall.",
                ),
                (
                    "semantic-symptom",
                    "Customers could read order history but new checkouts timed out after maintenance",
                    _json({"environment": "production"}),
                    "A paraphrase should find the incident, telemetry, and runbook.",
                ),
                (
                    "fuzzy-cluster",
                    "ordres-prod-1 indx bild blocked checkout",
                    _json({"environment": "production"}),
                    "Controlled misspellings exercise pg_trgm without making it the primary ranker.",
                ),
                (
                    "customer-impact",
                    "Which customer commitments were affected by INC-2047?",
                    _json({"incident_id": "INC-2047"}),
                    "Retrieval plus relational traversal should surface visible support cases.",
                ),
            ]
            cursor.executemany(
                """
                INSERT INTO proof.evaluation_queries(query_id, query_text, filters, notes)
                VALUES (%s, %s, %s::jsonb, %s)
                """,
                evaluation_queries,
            )

            canonical_ids = {
                key: evidence_id(kind, key)
                for kind, key in (
                    ("incident", "INC-2047"),
                    ("change", "CHG-1842"),
                    ("change", "CHG-1838"),
                    ("support_case", "CASE-7419"),
                    ("support_case", "CASE-7421"),
                    ("support_case", "CASE-7424"),
                    ("runbook", "RB-017"),
                    ("lock_evidence", "LOCK-2047-001"),
                    ("lock_evidence", "LOCK-2047-002"),
                )
            }
            judgments = [
                ("exact-change", canonical_ids["CHG-1842"], 3, "The named change is the confirmed cause."),
                ("exact-change", canonical_ids["INC-2047"], 3, "The incident records the impact and resolution."),
                ("exact-change", canonical_ids["LOCK-2047-001"], 3, "The lock snapshot proves the blocker."),
                ("exact-change", canonical_ids["RB-017"], 2, "The runbook explains the safe alternative."),
                ("exact-change", canonical_ids["CHG-1838"], 0, "This nearby change was explicitly ruled out."),
                ("semantic-symptom", canonical_ids["INC-2047"], 3, "The incident matches the read/write symptom split."),
                ("semantic-symptom", canonical_ids["LOCK-2047-002"], 3, "The observation captures queued writes."),
                ("semantic-symptom", canonical_ids["CHG-1842"], 3, "The maintenance statement is the confirmed cause."),
                ("semantic-symptom", canonical_ids["RB-017"], 2, "The runbook supplies the remediation."),
                ("fuzzy-cluster", canonical_ids["INC-2047"], 3, "The incident title and cluster tolerate the typo."),
                ("fuzzy-cluster", canonical_ids["CHG-1842"], 3, "The index-build change matches the misspelled query."),
                ("fuzzy-cluster", canonical_ids["LOCK-2047-001"], 2, "The lock snapshot confirms blocked checkout writes."),
                ("customer-impact", canonical_ids["INC-2047"], 3, "The incident anchors the relationship traversal."),
                ("customer-impact", canonical_ids["CASE-7419"], 3, "This visible case contains the customer commitment."),
                ("customer-impact", canonical_ids["CASE-7421"], 3, "Relevant but restricted; ACL tests must hide it by default."),
                ("customer-impact", canonical_ids["CASE-7424"], 0, "Explicitly unrelated to the incident."),
            ]
            cursor.executemany(
                """
                INSERT INTO proof.relevance_judgments(
                  query_id, evidence_id, relevance, rationale
                )
                VALUES (%s, %s, %s, %s)
                """,
                judgments,
            )

    return {
        "clusters": len(rows["clusters"]),
        "evidence_items": len(rows["evidence"]),
        "incidents": len(rows["incidents"]),
        "changes": len(rows["changes"]),
        "support_cases": len(rows["cases"]),
        "runbooks": len(rows["runbooks"]),
        "lock_evidence": len(rows["lock_evidence"]),
        "relationships": (
            len(rows["incident_changes"])
            + len(rows["incident_cases"])
            + len(rows["incident_runbooks"])
        ),
    }
