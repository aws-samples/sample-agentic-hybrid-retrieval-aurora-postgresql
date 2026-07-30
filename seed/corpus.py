from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any
import uuid

from .capture import validate_capture_bundle


CORPUS_NAMESPACE = uuid.UUID("d94fc53f-ed5d-4c30-8764-f43bc0bbdd62")
# The only classification axis (A7). acl_visibility carries it; the predicate in
# sql/03_search_functions.sql and the RLS policies in sql/11_roles_rls.sql both
# read 'workshop' vs anything-else, and the fail-closed schema default is
# 'restricted' (sql/01_schema.sql:926,942,948,1010).
#
# 'principals' stays as an empty list rather than being deleted: the
# retrieval.documents.acl_principals column and its GIN indexes
# (sql/02_indexes.sql:67-68,119-120) are still populated by the projection at
# backend/app/search_index.py:525, and dropping them is schema churn outside this
# plan. Nothing reads them after Task 9.
WORKSHOP_ACL = {"visibility": "workshop", "principals": []}
RESTRICTED_ACL = {"visibility": "restricted", "principals": []}


def evidence_id(kind: str, external_key: str) -> uuid.UUID:
    return uuid.uuid5(CORPUS_NAMESPACE, f"{kind}:{external_key}")


def _stable_id(kind: str, external_key: str) -> uuid.UUID:
    return uuid.uuid5(CORPUS_NAMESPACE, f"{kind}:{external_key}")


def _json(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"), sort_keys=True)


def _as_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _empty_rows() -> dict[str, list[dict[str, Any]]]:
    return {
        "clusters": [],
        "evidence": [],
        "incidents": [],
        "changes": [],
        "cases": [],
        "runbooks": [],
        "captures": [],
        "lock_evidence": [],
        "activity_samples": [],
        "lock_samples": [],
        "blocking_samples": [],
        "statement_samples": [],
        "cloudwatch_samples": [],
        "database_insights_samples": [],
        "commitments": [],
        "postmortems": [],
        "incident_changes": [],
        "incident_cases": [],
        "incident_runbooks": [],
        "change_runbooks": [],
        "case_commitments": [],
        "inferred_edges": [],
    }


def _canonical_rows(capture_bundle: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    validate_capture_bundle(capture_bundle)
    rows = _empty_rows()
    capture = capture_bundle["capture"]
    captured_started = _as_datetime(capture["capture_started_at"])
    captured_ended = _as_datetime(capture["capture_ended_at"])
    incident_started = captured_started
    incident_declared = incident_started + timedelta(minutes=7)
    incident_resolved = max(
        captured_ended,
        incident_started + timedelta(minutes=18),
    )

    rows["clusters"].extend(
        [
            {
                "cluster_id": "checkout-prod-cluster-01",
                "engine": "aurora-postgresql",
                "engine_version": "18.3",
                "aws_region": "us-east-1",
                "environment": "production",
                "service_name": "checkout",
                "writer_endpoint_alias": "checkout-prod-cluster-01.cluster.local",
                "instance_class": "db.r8g.xlarge",
                "database_insights_mode": "advanced",
                "metadata": {
                    "synthetic": True,
                    "workload": "transactional",
                    "fixture_profile": "DAT410-core",
                },
            },
            {
                "cluster_id": "checkout-staging-01",
                "engine": "aurora-postgresql",
                "engine_version": "18.3",
                "aws_region": "us-east-1",
                "environment": "staging",
                "service_name": "checkout",
                "writer_endpoint_alias": "checkout-staging-01.cluster.local",
                "instance_class": "db.r8g.large",
                "database_insights_mode": "advanced",
                "metadata": {
                    "synthetic": True,
                    "workload": "preproduction",
                    "distractor": "wrong-environment",
                },
            },
            {
                "cluster_id": "catalog-prod-01",
                "engine": "aurora-postgresql",
                "engine_version": "17.5",
                "aws_region": "us-east-1",
                "environment": "production",
                "service_name": "catalog",
                "writer_endpoint_alias": "catalog-prod-01.cluster.local",
                "instance_class": "db.r8g.large",
                "database_insights_mode": "advanced",
                "metadata": {
                    "synthetic": True,
                    "workload": "read-heavy",
                },
            },
        ]
    )

    def add_evidence(
        kind: str,
        key: str,
        title: str,
        source_system: str,
        updated_at: datetime,
        *,
        revision: str,
        acl: dict[str, Any] | None = None,
        source_uri: str | None = None,
    ) -> uuid.UUID:
        item_id = evidence_id(kind, key)
        rows["evidence"].append(
            {
                "evidence_id": item_id,
                "evidence_kind": kind,
                "external_key": key,
                "title": title,
                "source_system": source_system,
                "source_uri": source_uri
                or f"workshop://synthetic/{kind}/{key}",
                "source_revision": revision,
                "source_updated_at": updated_at,
                "acl": acl or WORKSHOP_ACL,
            }
        )
        return item_id

    incident = add_evidence(
        "incident",
        "INC-2047",
        "Checkout writes queued while reads continued",
        "synthetic_incident_management",
        incident_resolved,
        revision="inc-2000-final-1",
    )
    rows["incidents"].append(
        {
            "evidence_id": incident,
            "incident_id": "INC-2047",
            "cluster_id": "checkout-prod-cluster-01",
            "severity": "SEV-2",
            "status": "resolved",
            "started_at": incident_started,
            "mitigated_at": captured_ended,
            "resolved_at": incident_resolved,
            "summary": (
                "Checkout INSERT and UPDATE statements queued on relation locks "
                "after a production index migration began. SELECT traffic continued."
            ),
            "customer_impact": (
                "Fictional Acme Retail could read order history but could not submit "
                "new orders during the controlled incident window."
            ),
            "resolution": (
                "The ordinary index build was cancelled, queued DML recovered, and "
                "the replacement was scheduled with CREATE INDEX CONCURRENTLY."
            ),
        }
    )

    confirmed_change = add_evidence(
        "change",
        "CHG-1842",
        "Create customer and timestamp index on orders",
        "synthetic_change_management",
        captured_ended,
        revision="chg-1000-closed-1",
    )
    rows["changes"].append(
        {
            "evidence_id": confirmed_change,
            "change_id": "CHG-1842",
            "cluster_id": "checkout-prod-cluster-01",
            "change_type": "ddl",
            "status": "cancelled",
            "started_at": captured_started,
            "completed_at": captured_ended,
            "owner_team": "checkout-database",
            "execution_sql": (
                "CREATE INDEX idx_orders_customer_created "
                "ON orders (customer_id, created_at DESC);"
            ),
            "description": (
                "CHG-1842 caused checkout writes to block on checkout-prod-cluster-01 while "
                "reads continued. The migration used plain CREATE INDEX on a "
                "write-active production table. PostgreSQL acquired ShareLock, which "
                "permits AccessShareLock readers but conflicts with writers requesting "
                "RowExclusiveLock."
            ),
            "rollback_plan": (
                "Cancel the build, verify queued writers drain, then inspect and remove "
                "any unusable index artifact before a controlled retry."
            ),
        }
    )
    rows["incident_changes"].append(
        {
            "incident_evidence_id": incident,
            "change_evidence_id": confirmed_change,
            "relationship": "confirmed",
            "rationale": (
                "The captured CREATE INDEX backend held granted ShareLock while both "
                "writers waited for RowExclusiveLock on the same relation OID."
            ),
            "confirmed_by": "captured PostgreSQL lock catalogs",
        }
    )

    ruled_out_change = add_evidence(
        "change",
        "CHG-1838",
        "Resize checkout worker pool",
        "synthetic_change_management",
        incident_started - timedelta(minutes=5),
        revision="chg-1001-complete-1",
    )
    rows["changes"].append(
        {
            "evidence_id": ruled_out_change,
            "change_id": "CHG-1838",
            "cluster_id": "checkout-prod-cluster-01",
            "change_type": "configuration",
            "status": "completed",
            "started_at": incident_started - timedelta(minutes=12),
            "completed_at": incident_started - timedelta(minutes=5),
            "owner_team": "checkout-platform",
            "execution_sql": None,
            "description": (
                "The application worker pool increased from 24 to 32. This change "
                "does not acquire a PostgreSQL relation lock."
            ),
            "rollback_plan": "Restore the worker count to 24 and recycle the deployment.",
        }
    )
    rows["incident_changes"].append(
        {
            "incident_evidence_id": incident,
            "change_evidence_id": ruled_out_change,
            "relationship": "ruled_out",
            "rationale": (
                "The blocking PID belongs to CHG-1842, and both waiting sessions name "
                "that backend through pg_blocking_pids()."
            ),
            "confirmed_by": "incident commander",
        }
    )

    safe_change = add_evidence(
        "change",
        "CHG-1907",
        "Rebuild orders index concurrently",
        "synthetic_change_management",
        incident_resolved + timedelta(hours=2),
        revision="chg-1002-approved-1",
    )
    rows["changes"].append(
        {
            "evidence_id": safe_change,
            "change_id": "CHG-1907",
            "cluster_id": "checkout-prod-cluster-01",
            "change_type": "ddl",
            "status": "scheduled",
            "started_at": incident_resolved + timedelta(hours=2),
            "completed_at": None,
            "owner_team": "checkout-database",
            "execution_sql": (
                "CREATE INDEX CONCURRENTLY idx_orders_customer_created "
                "ON orders (customer_id, created_at DESC);"
            ),
            "description": (
                "Preventive follow-up uses ShareUpdateExclusiveLock so ordinary DML "
                "can continue. The build is run outside a transaction block."
            ),
            "rollback_plan": (
                "Monitor pg_stat_progress_create_index. If the build fails, inspect "
                "pg_index.indisvalid and drop the INVALID index before retrying."
            ),
        }
    )

    current_runbook = add_evidence(
        "runbook",
        "RB-017",
        "Online index builds on production writers",
        "synthetic_runbook_store",
        incident_started - timedelta(days=30),
        revision="rb-5000-v4",
        source_uri="https://www.postgresql.org/docs/current/sql-createindex.html",
    )
    rows["runbooks"].append(
        {
            "evidence_id": current_runbook,
            "runbook_id": "RB-017",
            "version": 4,
            "status": "current",
            "owner_team": "database-reliability",
            "applies_to_engine": "aurora-postgresql",
            "applies_to_major_versions": "[14,19)",
            "procedure_text": (
                "For a write-active relation, use CREATE INDEX CONCURRENTLY outside "
                "a transaction block. Monitor pg_stat_progress_create_index and "
                "pg_stat_activity. The concurrent form takes ShareUpdateExclusiveLock, "
                "which does not conflict with RowExclusiveLock."
            ),
            "caveats": (
                "The concurrent form performs two table scans, usually takes longer, "
                "cannot run inside a transaction block, and can leave an INVALID index "
                "if it fails partway."
            ),
        }
    )
    rows["incident_runbooks"].append(
        {
            "incident_evidence_id": incident,
            "runbook_evidence_id": current_runbook,
            "applicability": "used",
            "rationale": "This is the approved recovery and preventive procedure.",
        }
    )

    superseded_runbook = add_evidence(
        "runbook",
        "RB-092",
        "Legacy production index deployment checklist",
        "synthetic_runbook_store",
        incident_started - timedelta(days=400),
        revision="rb-5001-v1-superseded",
    )
    rows["runbooks"].append(
        {
            "evidence_id": superseded_runbook,
            "runbook_id": "RB-092",
            "version": 1,
            "status": "superseded",
            "owner_team": "database-reliability",
            "applies_to_engine": "aurora-postgresql",
            "applies_to_major_versions": "[14,17)",
            "procedure_text": (
                "Legacy guidance allowed ordinary index creation during expected "
                "low-traffic periods after a simple connection-count check."
            ),
            "caveats": (
                "Superseded because connection count does not prove lock compatibility "
                "and the procedure did not protect write-active relations."
            ),
        }
    )
    rows["incident_runbooks"].append(
        {
            "incident_evidence_id": incident,
            "runbook_evidence_id": superseded_runbook,
            "applicability": "rejected",
            "rationale": "The legacy version omitted the required concurrent-build guardrail.",
        }
    )
    rows["change_runbooks"].extend(
        [
            {
                "change_evidence_id": confirmed_change,
                "runbook_evidence_id": current_runbook,
                "relationship": "remediated_by",
                "rationale": "RB-017 supplies the safe replacement for CHG-1842.",
            },
            {
                "change_evidence_id": safe_change,
                "runbook_evidence_id": current_runbook,
                "relationship": "implements",
                "rationale": "CHG-1907 implements the current concurrent-build procedure.",
            },
            {
                "change_evidence_id": confirmed_change,
                "runbook_evidence_id": superseded_runbook,
                "relationship": "superseded_guidance",
                "rationale": "RB-092 describes the obsolete procedure that allowed the risk.",
            },
        ]
    )

    case_visible = add_evidence(
        "support_case",
        "CASE-7419",
        "Acme Retail checkout submissions timed out",
        "synthetic_support_system",
        incident_declared + timedelta(minutes=14),
        revision="case-4000-update-3",
    )
    rows["cases"].append(
        {
            "evidence_id": case_visible,
            "case_id": "CASE-7419",
            "account_name": "Acme Retail (fictional)",
            "support_tier": "Enterprise",
            "severity": "urgent",
            "status": "resolved",
            "opened_at": incident_declared + timedelta(minutes=4),
            "sla_due_at": incident_declared + timedelta(minutes=34),
            "subject": "Checkout writes timed out while order history remained readable",
            "description": (
                "This fictional case reports failed order submissions against "
                "checkout-prod-cluster-01 during INC-2047."
            ),
            "customer_commitment": (
                "Provide a root-cause statement and safe-fix plan under the P1 response."
            ),
        }
    )
    rows["incident_cases"].append(
        {
            "incident_evidence_id": incident,
            "case_evidence_id": case_visible,
            "impact": "affected",
            "rationale": "Cluster, service, and case interval match INC-2047.",
        }
    )

    case_restricted = add_evidence(
        "support_case",
        "CASE-7421",
        "Restricted regulated-account checkout escalation",
        "synthetic_support_system",
        incident_declared + timedelta(minutes=17),
        revision="case-4001-update-2",
        acl=RESTRICTED_ACL,
    )
    rows["cases"].append(
        {
            "evidence_id": case_restricted,
            "case_id": "CASE-7421",
            "account_name": "Northstar Foods (fictional)",
            "support_tier": "Enterprise",
            "severity": "urgent",
            "status": "resolved",
            "opened_at": incident_declared + timedelta(minutes=6),
            "sla_due_at": incident_declared + timedelta(minutes=36),
            "subject": "Restricted checkout write failures",
            "description": (
                "This fictional restricted case shares the incident interval and is "
                "visible only to a role holding the can_see_restricted clearance."
            ),
            "customer_commitment": "Support leadership approval required before disclosure.",
        }
    )
    rows["incident_cases"].append(
        {
            "incident_evidence_id": incident,
            "case_evidence_id": case_restricted,
            "impact": "affected",
            "rationale": "The restricted case references the same cluster and interval.",
        }
    )

    case_unaffected = add_evidence(
        "support_case",
        "CASE-7424",
        "Zenith Corp catalog latency inquiry",
        "synthetic_support_system",
        incident_resolved + timedelta(minutes=30),
        revision="case-4002-update-1",
    )
    rows["cases"].append(
        {
            "evidence_id": case_unaffected,
            "case_id": "CASE-7424",
            "account_name": "Zenith Corp (fictional)",
            "support_tier": "Business",
            "severity": "high",
            "status": "resolved",
            "opened_at": incident_declared + timedelta(minutes=12),
            "sla_due_at": incident_declared + timedelta(hours=4),
            "subject": "Catalog query latency",
            "description": (
                "This fictional inquiry concerns read-only traffic on catalog-prod-01, "
                "not checkout-prod-cluster-01."
            ),
            "customer_commitment": "Provide catalog query findings by the next business day.",
        }
    )
    rows["incident_cases"].append(
        {
            "incident_evidence_id": incident,
            "case_evidence_id": case_unaffected,
            "impact": "not_affected",
            "rationale": "The case targets a different service and cluster.",
        }
    )

    commitment = add_evidence(
        "commitment",
        "COMMIT-4471",
        "P1 root-cause and safe-fix response for Acme Retail",
        "synthetic_support_system",
        incident_resolved + timedelta(hours=1),
        revision="commit-6000-revision-1",
    )
    rows["commitments"].append(
        {
            "evidence_id": commitment,
            "commitment_id": "COMMIT-4471",
            "account_name": "Acme Retail (fictional)",
            "priority": "P1",
            "commitment_text": (
                "Deliver a written root cause, recovery window, and preventive "
                "concurrent-index plan."
            ),
            "due_at": incident_resolved + timedelta(days=2),
            "status": "open",
            "revalidate_live": True,
        }
    )
    rows["case_commitments"].append(
        {
            "case_evidence_id": case_visible,
            "commitment_evidence_id": commitment,
        }
    )

    # ------------------------------------------------------------------
    # Restricted cohort (design section "Restricted-evidence seed").
    #
    # CASE-7421 above remains THE canonical M3 flip noun; these are supporting
    # cast and are never named in a guide checkpoint, a slide, or the canonical
    # question. They exist so row filtering and masking are visibly non-trivial:
    # analyst sees none of the seven, admin sees all seven unmasked, auditor sees
    # all seven with customer identity redacted.
    #
    # Every key here was measured against the CGH-1842 trigram probe before being
    # chosen (max similarity 0.0588, no % match), so D14/G-21 are unaffected.
    # ------------------------------------------------------------------
    restricted_case_regulated = add_evidence(
        "support_case",
        "CASE-8102",
        "Restricted payment-processor escalation",
        "synthetic_support_system",
        incident_declared + timedelta(minutes=21),
        revision="case-8102-update-1",
        acl=RESTRICTED_ACL,
    )
    rows["cases"].append(
        {
            "evidence_id": restricted_case_regulated,
            "case_id": "CASE-8102",
            "account_name": "Cascade Financial (fictional)",
            "support_tier": "Enterprise",
            "severity": "urgent",
            "status": "resolved",
            "opened_at": incident_declared + timedelta(minutes=9),
            "sla_due_at": incident_declared + timedelta(minutes=39),
            "subject": "Restricted settlement write failures",
            "description": (
                "This fictional restricted case reports settlement writes queued "
                "on checkout-prod-cluster-01 during the incident window."
            ),
            "customer_commitment": (
                "Regulator notification is required before any external disclosure."
            ),
        }
    )
    rows["incident_cases"].append(
        {
            "incident_evidence_id": incident,
            "case_evidence_id": restricted_case_regulated,
            "impact": "affected",
            "rationale": "Settlement writes share the cluster and the incident interval.",
        }
    )

    restricted_case_health = add_evidence(
        "support_case",
        "CASE-8137",
        "Restricted clinical-tenant checkout escalation",
        "synthetic_support_system",
        incident_declared + timedelta(minutes=24),
        revision="case-8137-update-1",
        acl=RESTRICTED_ACL,
    )
    rows["cases"].append(
        {
            "evidence_id": restricted_case_health,
            "case_id": "CASE-8137",
            "account_name": "Meridian Health Group (fictional)",
            "support_tier": "Enterprise",
            "severity": "high",
            "status": "pending_customer",
            "opened_at": incident_declared + timedelta(minutes=11),
            "sla_due_at": incident_declared + timedelta(hours=2),
            "subject": "Restricted appointment-booking write failures",
            "description": (
                "This fictional restricted case reports booking writes queued on "
                "checkout-prod-cluster-01 while reads continued."
            ),
            "customer_commitment": (
                "Patient-data handling review must complete before disclosure."
            ),
        }
    )
    rows["incident_cases"].append(
        {
            "incident_evidence_id": incident,
            "case_evidence_id": restricted_case_health,
            "impact": "potentially_affected",
            "rationale": "Booking writes target the same cluster in the same window.",
        }
    )

    restricted_incident_identity = add_evidence(
        "incident",
        "INC-3162",
        "Restricted identity-service credential rotation incident",
        "synthetic_incident_management",
        incident_resolved + timedelta(hours=2),
        revision="inc-3162-final-1",
        acl=RESTRICTED_ACL,
    )
    rows["incidents"].append(
        {
            "evidence_id": restricted_incident_identity,
            "incident_id": "INC-3162",
            "cluster_id": "checkout-prod-cluster-01",
            "severity": "SEV-2",
            "status": "resolved",
            "started_at": incident_started - timedelta(hours=6),
            "mitigated_at": incident_started - timedelta(hours=5),
            "resolved_at": incident_started - timedelta(hours=4),
            "summary": (
                "A restricted credential rotation was executed by on-call operator "
                "Priya Raghavan (fictional) ahead of the checkout incident window."
            ),
            "customer_impact": (
                "No fictional customer-visible impact; the record is restricted "
                "because it names the operator and the rotation procedure."
            ),
            "resolution": (
                "The rotation completed and the superseded credential was revoked."
            ),
        }
    )

    restricted_incident_fraud = add_evidence(
        "incident",
        "INC-4117",
        "Restricted fraud-review queue backlog",
        "synthetic_incident_management",
        incident_resolved + timedelta(hours=3),
        revision="inc-4117-final-1",
        acl=RESTRICTED_ACL,
    )
    rows["incidents"].append(
        {
            "evidence_id": restricted_incident_fraud,
            "incident_id": "INC-4117",
            "cluster_id": "checkout-prod-cluster-01",
            "severity": "SEV-3",
            "status": "resolved",
            "started_at": incident_started - timedelta(hours=3),
            "mitigated_at": incident_started - timedelta(hours=2),
            "resolved_at": incident_started - timedelta(hours=1),
            "summary": (
                "A restricted fraud-review queue backed up while operator "
                "Daniel Okafor (fictional) held the review console open."
            ),
            "customer_impact": (
                "No fictional customer-visible impact; the record is restricted "
                "because it names the reviewer and the detection thresholds."
            ),
            "resolution": "The queue drained after the console session was closed.",
        }
    )

    restricted_change_keys = add_evidence(
        "change",
        "CHG-6213",
        "Restricted key-management configuration change",
        "synthetic_change_management",
        incident_started - timedelta(hours=5),
        revision="chg-6213-closed-1",
        acl=RESTRICTED_ACL,
    )
    rows["changes"].append(
        {
            "evidence_id": restricted_change_keys,
            "change_id": "CHG-6213",
            "cluster_id": "checkout-prod-cluster-01",
            "change_type": "configuration",
            "status": "completed",
            "started_at": incident_started - timedelta(hours=6),
            "completed_at": incident_started - timedelta(hours=5),
            "owner_team": "platform-security",
            "execution_sql": None,
            "description": (
                "Restricted key-management parameter change approved by operator "
                "Priya Raghavan (fictional); the record is restricted because it "
                "names the approver and the parameter."
            ),
            "rollback_plan": "Restore the previous parameter group and restart.",
        }
    )
    rows["incident_changes"].append(
        {
            "incident_evidence_id": restricted_incident_identity,
            "change_evidence_id": restricted_change_keys,
            "relationship": "confirmed",
            "rationale": "The rotation incident was opened for this change.",
            "confirmed_by": "incident commander",
        }
    )

    restricted_change_audit = add_evidence(
        "change",
        "CHG-3309",
        "Restricted audit-logging retention change",
        "synthetic_change_management",
        incident_started - timedelta(hours=2),
        revision="chg-3309-closed-1",
        acl=RESTRICTED_ACL,
    )
    rows["changes"].append(
        {
            "evidence_id": restricted_change_audit,
            "change_id": "CHG-3309",
            "cluster_id": "checkout-prod-cluster-01",
            "change_type": "configuration",
            "status": "completed",
            "started_at": incident_started - timedelta(hours=3),
            "completed_at": incident_started - timedelta(hours=2),
            "owner_team": "platform-security",
            "execution_sql": None,
            "description": (
                "Restricted audit-log retention change executed by operator "
                "Daniel Okafor (fictional) before the checkout incident window."
            ),
            "rollback_plan": "Restore the previous retention window.",
        }
    )
    rows["incident_changes"].append(
        {
            "incident_evidence_id": restricted_incident_fraud,
            "change_evidence_id": restricted_change_audit,
            "relationship": "suspected",
            "rationale": "The retention change preceded the review-queue backlog.",
            "confirmed_by": "platform-security on-call",
        }
    )

    postmortem = add_evidence(
        "postmortem",
        "PM-2047",
        "INC-2047 index-build write stall postmortem",
        "synthetic_incident_management",
        incident_resolved + timedelta(days=3),
        revision="pm-9000-final-1",
    )
    rows["postmortems"].append(
        {
            "evidence_id": postmortem,
            "postmortem_id": "PM-2047",
            "incident_evidence_id": incident,
            "published_at": incident_resolved + timedelta(days=3),
            "root_cause": (
                "CHG-1842 used plain CREATE INDEX. Its granted ShareLock conflicted "
                "with RowExclusiveLock requested by INSERT and UPDATE sessions."
            ),
            "contributing_factors": (
                "Migration review checked estimated duration but did not evaluate the "
                "table-level lock compatibility matrix."
            ),
            "remediation": (
                "The build was cancelled and queued writers recovered. CHG-1907 "
                "schedules CREATE INDEX CONCURRENTLY outside a transaction block."
            ),
            "prevention": (
                "Production index changes now require RB-017, lock_timeout, progress "
                "monitoring, and INVALID-index cleanup instructions."
            ),
        }
    )

    older_started = incident_started - timedelta(days=200)
    older_incident = add_evidence(
        "incident",
        "INC-1980",
        "Older checkout write stall during VACUUM FULL",
        "synthetic_incident_management",
        older_started + timedelta(hours=2),
        revision="inc-2001-final-1",
    )
    rows["incidents"].append(
        {
            "evidence_id": older_incident,
            "incident_id": "INC-1980",
            "cluster_id": "checkout-prod-cluster-01",
            "severity": "SEV-2",
            "status": "resolved",
            "started_at": older_started,
            "mitigated_at": older_started + timedelta(minutes=22),
            "resolved_at": older_started + timedelta(hours=2),
            "summary": (
                "An older relation-lock incident also queued checkout writes, but an "
                "offline VACUUM FULL held AccessExclusiveLock."
            ),
            "customer_impact": "Fictional background cases observed both reads and writes pause.",
            "resolution": "VACUUM FULL was cancelled and moved to a maintenance window.",
        }
    )
    older_change = add_evidence(
        "change",
        "CHG-1731",
        "Compact historical orders with VACUUM FULL",
        "synthetic_change_management",
        older_started + timedelta(minutes=22),
        revision="chg-1010-closed-1",
    )
    rows["changes"].append(
        {
            "evidence_id": older_change,
            "change_id": "CHG-1731",
            "cluster_id": "checkout-prod-cluster-01",
            "change_type": "ddl",
            "status": "cancelled",
            "started_at": older_started,
            "completed_at": older_started + timedelta(minutes=22),
            "owner_team": "checkout-database",
            "execution_sql": "VACUUM FULL orders_history;",
            "description": (
                "Older look-alike incident with a different root cause and stronger "
                "AccessExclusiveLock semantics."
            ),
            "rollback_plan": "Cancel VACUUM FULL and use routine VACUUM.",
        }
    )
    rows["incident_changes"].append(
        {
            "incident_evidence_id": older_incident,
            "change_evidence_id": older_change,
            "relationship": "confirmed",
            "rationale": "The historical incident was caused by VACUUM FULL, not index creation.",
            "confirmed_by": "historical post-incident review",
        }
    )
    rows["inferred_edges"].append(
        {
            "edge_id": _stable_id("edge", "INC-2047-resembles-INC-1980"),
            "from_evidence_id": incident,
            "to_evidence_id": older_incident,
            "relation": "resembles",
            "confidence": 0.62,
            "method": "embedding_knn",
            "source_revision": "fixture-inference-1",
            "metadata": {
                "rationale": "Similar write-stall language, different root cause.",
            },
        }
    )

    staging_started = incident_started - timedelta(days=20)
    staging_incident = add_evidence(
        "incident",
        "INC-2044",
        "Staging writers queued during an index rehearsal",
        "synthetic_incident_management",
        staging_started + timedelta(hours=1),
        revision="inc-2010-final-1",
    )
    rows["incidents"].append(
        {
            "evidence_id": staging_incident,
            "incident_id": "INC-2044",
            "cluster_id": "checkout-staging-01",
            "severity": "SEV-3",
            "status": "resolved",
            "started_at": staging_started,
            "mitigated_at": staging_started + timedelta(minutes=8),
            "resolved_at": staging_started + timedelta(hours=1),
            "summary": (
                "The same relation-lock signature appeared during a staging rehearsal. "
                "Environment filtering must exclude it from the production investigation."
            ),
            "customer_impact": "No customer impact; the cluster is staging.",
            "resolution": "The rehearsal was cancelled and the migration plan changed.",
        }
    )
    staging_change = add_evidence(
        "change",
        "CHG-1840",
        "Staging index rehearsal",
        "synthetic_change_management",
        staging_started + timedelta(minutes=8),
        revision="chg-1011-closed-1",
    )
    rows["changes"].append(
        {
            "evidence_id": staging_change,
            "change_id": "CHG-1840",
            "cluster_id": "checkout-staging-01",
            "change_type": "ddl",
            "status": "cancelled",
            "started_at": staging_started,
            "completed_at": staging_started + timedelta(minutes=8),
            "owner_team": "checkout-database",
            "execution_sql": (
                "CREATE INDEX idx_orders_customer_created "
                "ON orders (customer_id, created_at DESC);"
            ),
            "description": "Same SQL signature as CHG-1842, but on staging.",
            "rollback_plan": "Cancel and update the production migration plan.",
        }
    )
    rows["incident_changes"].append(
        {
            "incident_evidence_id": staging_incident,
            "change_evidence_id": staging_change,
            "relationship": "confirmed",
            "rationale": "Staging-only rehearsal caused the staging event.",
            "confirmed_by": "staging operator",
        }
    )

    capture_id = _stable_id("capture", capture["capture_key"])
    rows["captures"].append(
        {
            "capture_id": capture_id,
            "capture_key": capture["capture_key"],
            "incident_evidence_id": incident,
            "cluster_id": "checkout-prod-cluster-01",
            "capture_mode": capture["capture_mode"],
            "engine_version": str(capture["engine_version"]),
            "instance_class": capture["instance_class"],
            "database_name": capture["database_name"],
            "table_schema": capture["table_schema"],
            "table_name": capture["table_name"],
            "relation_oid": capture["relation_oid"],
            "configured_row_count": capture["configured_row_count"],
            "observed_row_count": capture["observed_row_count"],
            "table_size_bytes": capture["table_size_bytes"],
            "steady_state_connections": capture["steady_state_connections"],
            "capture_started_at": captured_started,
            "capture_ended_at": captured_ended,
            "capture_tool_version": capture["capture_tool_version"],
            "source_bundle_sha256": capture["source_bundle_sha256"],
            "source_bundle_uri": capture.get("source_bundle_uri")
            or f"workshop://capture-bundles/{capture['capture_key']}",
            "release_verified_at": (
                _as_datetime(capture["release_verified_at"])
                if capture.get("release_verified_at")
                else None
            ),
            "manifest": capture["manifest"],
        }
    )

    observation_ids: dict[str, uuid.UUID] = {}
    for observation in capture_bundle["observations"]:
        key = observation["external_key"]
        lock_id = add_evidence(
            "lock_evidence",
            key,
            f"Captured relation-lock evidence for writer {observation['blocked_pid']}",
            "postgresql_fixture_capture",
            _as_datetime(observation["captured_at"]),
            revision=f"{capture['source_bundle_sha256']}:{key}",
            source_uri=(
                f"workshop://{capture['capture_mode']}/"
                f"{capture['capture_key']}/{key}"
            ),
        )
        observation_ids[key] = lock_id
        rows["lock_evidence"].append(
            {
                "evidence_id": lock_id,
                "observation_id": key,
                "incident_evidence_id": incident,
                "change_evidence_id": confirmed_change,
                "capture_id": capture_id,
                "captured_at": _as_datetime(observation["captured_at"]),
                "relation_name": observation["relation_name"],
                "relation_oid": observation["relation_oid"],
                "blocked_pid": observation["blocked_pid"],
                "blocking_pid": observation["blocking_pid"],
                "blocked_state": observation["blocked_state"],
                "blocked_query_start": _as_datetime(
                    observation["blocked_query_start"]
                ),
                "wait_event_type": observation["wait_event_type"],
                "wait_event": observation["wait_event"],
                "blocked_lock_mode": observation["blocked_lock_mode"],
                "blocked_lock_granted": observation["blocked_lock_granted"],
                "blocking_lock_mode": observation["blocking_lock_mode"],
                "blocking_lock_granted": observation["blocking_lock_granted"],
                "blocking_pids": observation["blocking_pids"],
                "blocking_pids_sql": observation["blocking_pids_sql"],
                "blocking_pids_output": observation["blocking_pids_output"],
                "blocked_statement": observation["blocked_statement"],
                "blocking_statement": observation["blocking_statement"],
                "database_insights_slice": None,
                "raw_capture": observation["raw_capture"],
            }
        )

    first_observation = next(iter(observation_ids.values()))
    for sample in capture_bundle.get("pg_stat_activity", []):
        rows["activity_samples"].append(
            {
                "capture_id": capture_id,
                "observation_evidence_id": first_observation,
                "captured_at": _as_datetime(sample["captured_at"]),
                "pid": sample["pid"],
                "backend_type": sample.get("backend_type"),
                "application_name": sample.get("application_name"),
                "state": sample["state"],
                "wait_event_type": sample.get("wait_event_type"),
                "wait_event": sample.get("wait_event"),
                "query_start": (
                    _as_datetime(sample["query_start"])
                    if sample.get("query_start")
                    else None
                ),
                "xact_start": (
                    _as_datetime(sample["xact_start"])
                    if sample.get("xact_start")
                    else None
                ),
                "query": sample["query"],
                "raw_row": sample["raw_row"],
            }
        )
    for sample in capture_bundle.get("pg_locks", []):
        rows["lock_samples"].append(
            {
                "capture_id": capture_id,
                "observation_evidence_id": first_observation,
                "captured_at": _as_datetime(sample["captured_at"]),
                "pid": sample["pid"],
                "locktype": sample["locktype"],
                "database_oid": sample.get("database_oid"),
                "relation_oid": sample["relation_oid"],
                "relation_name": sample["relation_name"],
                "mode": sample["mode"],
                "granted": sample["granted"],
                "fastpath": sample.get("fastpath"),
                "waitstart": (
                    _as_datetime(sample["waitstart"])
                    if sample.get("waitstart")
                    else None
                ),
                "raw_row": sample["raw_row"],
            }
        )
    for sample in capture_bundle.get("pg_blocking_pids", []):
        rows["blocking_samples"].append(
            {
                "capture_id": capture_id,
                "observation_evidence_id": observation_ids[
                    next(
                        observation["external_key"]
                        for observation in capture_bundle["observations"]
                        if observation["blocked_pid"] == sample["blocked_pid"]
                    )
                ],
                "captured_at": _as_datetime(sample["captured_at"]),
                "blocked_pid": sample["blocked_pid"],
                "blocking_pids": sample["blocking_pids"],
                "literal_sql": sample["literal_sql"],
                "literal_output": sample["literal_output"],
                "raw_row": sample["raw_row"],
            }
        )
    for sample in capture_bundle.get("pg_stat_statements", []):
        rows["statement_samples"].append(
            {
                "capture_id": capture_id,
                "phase": sample["phase"],
                "captured_at": _as_datetime(sample["captured_at"]),
                "queryid": sample.get("queryid"),
                "query": sample["query"],
                "calls": sample["calls"],
                "total_exec_time": sample["total_exec_time"],
                "mean_exec_time": sample["mean_exec_time"],
                "rows": sample.get("rows", 0),
                "raw_row": sample["raw_row"],
            }
        )
    for sample in capture_bundle.get("cloudwatch_metrics", []):
        rows["cloudwatch_samples"].append(
            {
                "capture_id": capture_id,
                **sample,
            }
        )
    for sample in capture_bundle.get("database_insights", []):
        rows["database_insights_samples"].append(
            {
                "capture_id": capture_id,
                **sample,
            }
        )
    return rows


def _background_rows(document_target: int) -> dict[str, list[dict[str, Any]]]:
    rows = _empty_rows()
    if document_target <= 0:
        return rows

    services = [
        "billing",
        "catalog",
        "fulfillment",
        "identity",
        "inventory",
        "pricing",
        "shipping",
        "subscriptions",
    ]
    causes = [
        (
            "AccessExclusiveLock during a column rewrite",
            "ALTER TABLE event_log ALTER COLUMN payload TYPE jsonb USING payload::jsonb",
            "Use expand-contract migration for a write-active relation.",
        ),
        (
            "connection-pool saturation",
            None,
            "Reduce client fan-out before raising database limits.",
        ),
        (
            "long transaction retained old row versions",
            "UPDATE event_log SET state = 'processing' WHERE event_id = $1",
            "Bound transaction duration and investigate the owning application.",
        ),
        (
            "VACUUM FULL blocked concurrent access",
            "VACUUM FULL event_log",
            "Use routine VACUUM and schedule rewrites explicitly.",
        ),
    ]
    cluster_count = max(8, min(40, (document_target + 79) // 80))
    for ordinal in range(1, cluster_count + 1):
        service = services[(ordinal - 1) % len(services)]
        cluster_id = f"{service}-prod-{ordinal:02d}"
        rows["clusters"].append(
            {
                "cluster_id": cluster_id,
                "engine": "aurora-postgresql",
                "engine_version": "18.3" if ordinal % 2 else "17.5",
                "aws_region": (
                    "us-east-1" if ordinal % 3 else "us-west-2"
                ),
                "environment": "production",
                "service_name": service,
                "writer_endpoint_alias": f"{cluster_id}.cluster.local",
                "instance_class": "db.r8g.large",
                "database_insights_mode": "advanced",
                "metadata": {
                    "synthetic": True,
                    "tier": "background",
                },
            }
        )

    base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
    group_count = (document_target + 3) // 4
    for ordinal in range(1, group_count + 1):
        service = services[(ordinal - 1) % len(services)]
        cluster = rows["clusters"][(ordinal - 1) % len(rows["clusters"])]
        cause, statement, prevention = causes[(ordinal - 1) % len(causes)]
        started = base_time + timedelta(hours=ordinal * 5)
        incident_key = f"INC-BG-{ordinal:05d}"
        change_key = f"MNT-BG-{ordinal:05d}"
        case_key = f"CASE-BG-{ordinal:05d}"
        runbook_key = f"RB-BG-{ordinal:05d}"
        identifiers = [
            ("incident", incident_key),
            ("change", change_key),
            ("support_case", case_key),
            ("runbook", runbook_key),
        ]
        evidence_rows: list[dict[str, Any]] = []
        for kind, key in identifiers:
            evidence_rows.append(
                {
                    "evidence_id": evidence_id(kind, key),
                    "evidence_kind": kind,
                    "external_key": key,
                    "title": (
                        f"{service.title()} {cause} "
                        f"({key})"
                    ),
                    "source_system": f"synthetic_{kind}_system",
                    "source_uri": f"workshop://synthetic/background/{kind}/{key}",
                    "source_revision": f"{key.lower()}-revision-1",
                    "source_updated_at": started + timedelta(hours=1),
                    "acl": WORKSHOP_ACL,
                }
            )
        remaining = document_target - len(rows["evidence"])
        rows["evidence"].extend(evidence_rows[:remaining])
        if remaining <= 0:
            break

        incident_id = evidence_id("incident", incident_key)
        change_id = evidence_id("change", change_key)
        case_id = evidence_id("support_case", case_key)
        runbook_id = evidence_id("runbook", runbook_key)
        rows["incidents"].append(
            {
                "evidence_id": incident_id,
                "incident_id": incident_key,
                "cluster_id": cluster["cluster_id"],
                "severity": "SEV-3",
                "status": "resolved",
                "started_at": started,
                "mitigated_at": started + timedelta(minutes=20),
                "resolved_at": started + timedelta(hours=1),
                "summary": (
                    f"{incident_key} affected {service} writes on "
                    f"{cluster['cluster_id']}; investigation found {cause}."
                ),
                "customer_impact": (
                    f"Fictional Tenant-{ordinal:04d} observed elevated {service} latency."
                ),
                "resolution": f"The team stopped {change_key}. {prevention}",
            }
        )
        rows["changes"].append(
            {
                "evidence_id": change_id,
                "change_id": change_key,
                "cluster_id": cluster["cluster_id"],
                "change_type": "ddl" if statement else "configuration",
                "status": "cancelled",
                "started_at": started,
                "completed_at": started + timedelta(minutes=20),
                "owner_team": f"{service}-database",
                "execution_sql": statement,
                "description": f"{change_key} was associated with {cause}.",
                "rollback_plan": prevention,
            }
        )
        rows["cases"].append(
            {
                "evidence_id": case_id,
                "case_id": case_key,
                "account_name": f"Tenant-{ordinal:04d} (fictional)",
                "support_tier": "Business",
                "severity": "normal",
                "status": "resolved",
                "opened_at": started + timedelta(minutes=5),
                "sla_due_at": started + timedelta(hours=8),
                "subject": f"{service.title()} latency",
                "description": (
                    f"This fictional case corresponds to {incident_key} on "
                    f"{cluster['cluster_id']}."
                ),
                "customer_commitment": "Provide an incident summary after resolution.",
            }
        )
        rows["runbooks"].append(
            {
                "evidence_id": runbook_id,
                "runbook_id": runbook_key,
                "version": 1,
                "status": "current",
                "owner_team": "database-reliability",
                "applies_to_engine": "aurora-postgresql",
                "applies_to_major_versions": "[14,19)",
                "procedure_text": (
                    f"{runbook_key} procedure for {cause}: {prevention}"
                ),
                "caveats": f"Validate against {cluster['cluster_id']} before execution.",
            }
        )
        rows["incident_changes"].append(
            {
                "incident_evidence_id": incident_id,
                "change_evidence_id": change_id,
                "relationship": "confirmed",
                "rationale": f"{change_key} matches the {incident_key} interval.",
                "confirmed_by": "background fixture generator",
            }
        )
        rows["incident_cases"].append(
            {
                "incident_evidence_id": incident_id,
                "case_evidence_id": case_id,
                "impact": "affected",
                "rationale": f"{case_key} references {incident_key}.",
            }
        )
        rows["incident_runbooks"].append(
            {
                "incident_evidence_id": incident_id,
                "runbook_evidence_id": runbook_id,
                "applicability": "recommended",
                "rationale": f"{runbook_key} covers the observed background pattern.",
            }
        )

    valid_ids = {row["evidence_id"] for row in rows["evidence"]}
    table_id_columns = {
        "incidents": "evidence_id",
        "changes": "evidence_id",
        "cases": "evidence_id",
        "runbooks": "evidence_id",
    }
    for table, column in table_id_columns.items():
        rows[table] = [
            row for row in rows[table] if row[column] in valid_ids
        ]
    rows["incident_changes"] = [
        row
        for row in rows["incident_changes"]
        if row["incident_evidence_id"] in valid_ids
        and row["change_evidence_id"] in valid_ids
    ]
    rows["incident_cases"] = [
        row
        for row in rows["incident_cases"]
        if row["incident_evidence_id"] in valid_ids
        and row["case_evidence_id"] in valid_ids
    ]
    rows["incident_runbooks"] = [
        row
        for row in rows["incident_runbooks"]
        if row["incident_evidence_id"] in valid_ids
        and row["runbook_evidence_id"] in valid_ids
    ]
    return rows


def _merge_rows(
    target: dict[str, list[dict[str, Any]]],
    addition: dict[str, list[dict[str, Any]]],
) -> None:
    for key, values in addition.items():
        target[key].extend(values)


def _insert_many(cursor, statement: str, records: list[dict[str, Any]]) -> None:
    if records:
        cursor.executemany(statement, records)


def load_casework(
    conn,
    *,
    capture_bundle: dict[str, Any],
    background_documents: int = 15_000,
) -> dict[str, int]:
    if background_documents < 0:
        raise ValueError("background_documents must be non-negative")
    rows = _canonical_rows(capture_bundle)
    _merge_rows(rows, _background_rows(background_documents))

    with conn.transaction():
        with conn.cursor() as cursor:
            cursor.execute(
                """
                TRUNCATE TABLE
                  proof.answer_citations,
                  proof.agent_answers,
                  proof.agent_escalations,
                  proof.agent_retrievals,
                  proof.agent_subquestions,
                  proof.agent_runs,
                  proof.run_stages,
                  proof.traversal_results,
                  proof.transport_invocations,
                  proof.retrieval_candidates,
                  proof.observability_refs,
                  proof.retrieval_runs,
                  proof.relevance_judgments,
                  proof.evaluation_queries,
                  retrieval.inferred_edges,
                  retrieval.chunks,
                  retrieval.documents,
                  retrieval.search_index_builds,
                  retrieval.search_index_queue,
                  casework.pg_stat_activity_samples,
                  casework.pg_lock_samples,
                  casework.pg_blocking_pids_samples,
                  casework.pg_stat_statements_samples,
                  casework.cloudwatch_metric_samples,
                  casework.database_insights_samples,
                  casework.lock_evidence,
                  casework.fixture_captures,
                  casework.support_case_commitments,
                  casework.change_runbooks,
                  casework.incident_runbooks,
                  casework.incident_support_cases,
                  casework.incident_changes,
                  casework.postmortems,
                  casework.customer_commitments,
                  casework.runbooks,
                  casework.support_cases,
                  casework.changes,
                  casework.incidents,
                  casework.ingest_receipts,
                  casework.evidence_items,
                  casework.database_clusters
                RESTART IDENTITY
                """
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.database_clusters(
                  cluster_id, engine, engine_version, aws_region, environment,
                  service_name, writer_endpoint_alias, instance_class,
                  database_insights_mode, metadata
                )
                VALUES (
                  %(cluster_id)s, %(engine)s, %(engine_version)s, %(aws_region)s,
                  %(environment)s, %(service_name)s, %(writer_endpoint_alias)s,
                  %(instance_class)s, %(database_insights_mode)s, %(metadata)s::jsonb
                )
                """,
                [
                    {**record, "metadata": _json(record["metadata"])}
                    for record in rows["clusters"]
                ],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.evidence_items(
                  evidence_id, evidence_kind, external_key, title, source_system,
                  source_uri, source_revision, source_updated_at, acl
                )
                VALUES (
                  %(evidence_id)s, %(evidence_kind)s, %(external_key)s, %(title)s,
                  %(source_system)s, %(source_uri)s, %(source_revision)s,
                  %(source_updated_at)s, %(acl)s::jsonb
                )
                """,
                [
                    {**record, "acl": _json(record["acl"])}
                    for record in rows["evidence"]
                ],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.incidents(
                  evidence_id, incident_id, cluster_id, severity, status, started_at,
                  mitigated_at, resolved_at, summary, customer_impact, resolution
                )
                VALUES (
                  %(evidence_id)s, %(incident_id)s, %(cluster_id)s, %(severity)s,
                  %(status)s, %(started_at)s, %(mitigated_at)s, %(resolved_at)s,
                  %(summary)s, %(customer_impact)s, %(resolution)s
                )
                """,
                rows["incidents"],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.changes(
                  evidence_id, change_id, cluster_id, change_type, status, started_at,
                  completed_at, owner_team, execution_sql, description, rollback_plan
                )
                VALUES (
                  %(evidence_id)s, %(change_id)s, %(cluster_id)s, %(change_type)s,
                  %(status)s, %(started_at)s, %(completed_at)s, %(owner_team)s,
                  %(execution_sql)s, %(description)s, %(rollback_plan)s
                )
                """,
                rows["changes"],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.support_cases(
                  evidence_id, case_id, account_name, support_tier, severity, status,
                  opened_at, sla_due_at, subject, description, customer_commitment
                )
                VALUES (
                  %(evidence_id)s, %(case_id)s, %(account_name)s, %(support_tier)s,
                  %(severity)s, %(status)s, %(opened_at)s, %(sla_due_at)s,
                  %(subject)s, %(description)s, %(customer_commitment)s
                )
                """,
                rows["cases"],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.runbooks(
                  evidence_id, runbook_id, version, status, owner_team,
                  applies_to_engine, applies_to_major_versions, procedure_text, caveats
                )
                VALUES (
                  %(evidence_id)s, %(runbook_id)s, %(version)s, %(status)s,
                  %(owner_team)s, %(applies_to_engine)s,
                  %(applies_to_major_versions)s::int4range,
                  %(procedure_text)s, %(caveats)s
                )
                """,
                rows["runbooks"],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.customer_commitments(
                  evidence_id, commitment_id, account_name, priority, commitment_text,
                  due_at, status, revalidate_live
                )
                VALUES (
                  %(evidence_id)s, %(commitment_id)s, %(account_name)s, %(priority)s,
                  %(commitment_text)s, %(due_at)s, %(status)s, %(revalidate_live)s
                )
                """,
                rows["commitments"],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.postmortems(
                  evidence_id, postmortem_id, incident_evidence_id, published_at,
                  root_cause, contributing_factors, remediation, prevention
                )
                VALUES (
                  %(evidence_id)s, %(postmortem_id)s, %(incident_evidence_id)s,
                  %(published_at)s, %(root_cause)s, %(contributing_factors)s,
                  %(remediation)s, %(prevention)s
                )
                """,
                rows["postmortems"],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.fixture_captures(
                  capture_id, capture_key, incident_evidence_id, cluster_id,
                  capture_mode, engine_version, instance_class, database_name,
                  table_schema, table_name, relation_oid, configured_row_count,
                  observed_row_count, table_size_bytes, steady_state_connections,
                  capture_started_at, capture_ended_at, capture_tool_version,
                  source_bundle_sha256, source_bundle_uri, release_verified_at, manifest
                )
                VALUES (
                  %(capture_id)s, %(capture_key)s, %(incident_evidence_id)s,
                  %(cluster_id)s, %(capture_mode)s, %(engine_version)s,
                  %(instance_class)s, %(database_name)s, %(table_schema)s,
                  %(table_name)s, %(relation_oid)s, %(configured_row_count)s,
                  %(observed_row_count)s, %(table_size_bytes)s,
                  %(steady_state_connections)s, %(capture_started_at)s,
                  %(capture_ended_at)s, %(capture_tool_version)s,
                  %(source_bundle_sha256)s, %(source_bundle_uri)s,
                  %(release_verified_at)s, %(manifest)s::jsonb
                )
                """,
                [
                    {**record, "manifest": _json(record["manifest"])}
                    for record in rows["captures"]
                ],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.lock_evidence(
                  evidence_id, observation_id, incident_evidence_id,
                  change_evidence_id, capture_id, captured_at, relation_name,
                  relation_oid, blocked_pid, blocking_pid, blocked_state,
                  blocked_query_start, wait_event_type, wait_event,
                  blocked_lock_mode, blocked_lock_granted, blocking_lock_mode,
                  blocking_lock_granted, blocking_pids, blocking_pids_sql,
                  blocking_pids_output, blocked_statement, blocking_statement,
                  database_insights_slice, raw_capture
                )
                VALUES (
                  %(evidence_id)s, %(observation_id)s, %(incident_evidence_id)s,
                  %(change_evidence_id)s, %(capture_id)s, %(captured_at)s,
                  %(relation_name)s, %(relation_oid)s, %(blocked_pid)s,
                  %(blocking_pid)s, %(blocked_state)s, %(blocked_query_start)s,
                  %(wait_event_type)s, %(wait_event)s, %(blocked_lock_mode)s,
                  %(blocked_lock_granted)s, %(blocking_lock_mode)s,
                  %(blocking_lock_granted)s, %(blocking_pids)s,
                  %(blocking_pids_sql)s, %(blocking_pids_output)s,
                  %(blocked_statement)s, %(blocking_statement)s,
                  %(database_insights_slice)s::jsonb, %(raw_capture)s::jsonb
                )
                """,
                [
                    {
                        **record,
                        "database_insights_slice": (
                            _json(record["database_insights_slice"])
                            if record["database_insights_slice"] is not None
                            else None
                        ),
                        "raw_capture": _json(record["raw_capture"]),
                    }
                    for record in rows["lock_evidence"]
                ],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.pg_stat_activity_samples(
                  capture_id, observation_evidence_id, captured_at, pid,
                  backend_type, application_name, state, wait_event_type,
                  wait_event, query_start, xact_start, query, raw_row
                )
                VALUES (
                  %(capture_id)s, %(observation_evidence_id)s, %(captured_at)s,
                  %(pid)s, %(backend_type)s, %(application_name)s, %(state)s,
                  %(wait_event_type)s, %(wait_event)s, %(query_start)s,
                  %(xact_start)s, %(query)s, %(raw_row)s::jsonb
                )
                """,
                [
                    {**record, "raw_row": _json(record["raw_row"])}
                    for record in rows["activity_samples"]
                ],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.pg_lock_samples(
                  capture_id, observation_evidence_id, captured_at, pid, locktype,
                  database_oid, relation_oid, relation_name, mode, granted,
                  fastpath, waitstart, raw_row
                )
                VALUES (
                  %(capture_id)s, %(observation_evidence_id)s, %(captured_at)s,
                  %(pid)s, %(locktype)s, %(database_oid)s, %(relation_oid)s,
                  %(relation_name)s, %(mode)s, %(granted)s, %(fastpath)s,
                  %(waitstart)s, %(raw_row)s::jsonb
                )
                """,
                [
                    {**record, "raw_row": _json(record["raw_row"])}
                    for record in rows["lock_samples"]
                ],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.pg_blocking_pids_samples(
                  capture_id, observation_evidence_id, captured_at, blocked_pid,
                  blocking_pids, literal_sql, literal_output, raw_row
                )
                VALUES (
                  %(capture_id)s, %(observation_evidence_id)s, %(captured_at)s,
                  %(blocked_pid)s, %(blocking_pids)s, %(literal_sql)s,
                  %(literal_output)s, %(raw_row)s::jsonb
                )
                """,
                [
                    {**record, "raw_row": _json(record["raw_row"])}
                    for record in rows["blocking_samples"]
                ],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.pg_stat_statements_samples(
                  capture_id, phase, captured_at, queryid, query, calls,
                  total_exec_time, mean_exec_time, rows, raw_row
                )
                VALUES (
                  %(capture_id)s, %(phase)s, %(captured_at)s, %(queryid)s,
                  %(query)s, %(calls)s, %(total_exec_time)s, %(mean_exec_time)s,
                  %(rows)s, %(raw_row)s::jsonb
                )
                """,
                [
                    {**record, "raw_row": _json(record["raw_row"])}
                    for record in rows["statement_samples"]
                ],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.cloudwatch_metric_samples(
                  capture_id, metric_name, namespace, dimension_name,
                  dimension_value, statistic, period_seconds, observed_at,
                  value, unit, raw_datapoint
                )
                VALUES (
                  %(capture_id)s, %(metric_name)s, %(namespace)s,
                  %(dimension_name)s, %(dimension_value)s, %(statistic)s,
                  %(period_seconds)s, %(observed_at)s, %(value)s, %(unit)s,
                  %(raw_datapoint)s::jsonb
                )
                """,
                [
                    {**record, "raw_datapoint": _json(record["raw_datapoint"])}
                    for record in rows["cloudwatch_samples"]
                ],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.database_insights_samples(
                  capture_id, evidence_type, captured_at, dimension,
                  dimension_value, db_load, statement, query_id, source_api,
                  raw_payload
                )
                VALUES (
                  %(capture_id)s, %(evidence_type)s, %(captured_at)s,
                  %(dimension)s, %(dimension_value)s, %(db_load)s,
                  %(statement)s, %(query_id)s, %(source_api)s,
                  %(raw_payload)s::jsonb
                )
                """,
                [
                    {**record, "raw_payload": _json(record["raw_payload"])}
                    for record in rows["database_insights_samples"]
                ],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.incident_changes(
                  incident_evidence_id, change_evidence_id, relationship,
                  rationale, confirmed_by
                )
                VALUES (
                  %(incident_evidence_id)s, %(change_evidence_id)s,
                  %(relationship)s, %(rationale)s, %(confirmed_by)s
                )
                """,
                rows["incident_changes"],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.incident_support_cases(
                  incident_evidence_id, case_evidence_id, impact, rationale
                )
                VALUES (
                  %(incident_evidence_id)s, %(case_evidence_id)s,
                  %(impact)s, %(rationale)s
                )
                """,
                rows["incident_cases"],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.incident_runbooks(
                  incident_evidence_id, runbook_evidence_id, applicability, rationale
                )
                VALUES (
                  %(incident_evidence_id)s, %(runbook_evidence_id)s,
                  %(applicability)s, %(rationale)s
                )
                """,
                rows["incident_runbooks"],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.change_runbooks(
                  change_evidence_id, runbook_evidence_id, relationship, rationale
                )
                VALUES (
                  %(change_evidence_id)s, %(runbook_evidence_id)s,
                  %(relationship)s, %(rationale)s
                )
                """,
                rows["change_runbooks"],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO casework.support_case_commitments(
                  case_evidence_id, commitment_evidence_id
                )
                VALUES (%(case_evidence_id)s, %(commitment_evidence_id)s)
                """,
                rows["case_commitments"],
            )
            _insert_many(
                cursor,
                """
                INSERT INTO retrieval.inferred_edges(
                  edge_id, from_evidence_id, to_evidence_id, relation,
                  confidence, method, source_revision, metadata
                )
                VALUES (
                  %(edge_id)s, %(from_evidence_id)s, %(to_evidence_id)s,
                  %(relation)s, %(confidence)s, %(method)s,
                  %(source_revision)s, %(metadata)s::jsonb
                )
                """,
                [
                    {**record, "metadata": _json(record["metadata"])}
                    for record in rows["inferred_edges"]
                ],
            )
            cursor.execute(
                """
                INSERT INTO retrieval.search_index_queue(evidence_id, source_revision)
                SELECT evidence_id, source_revision
                FROM casework.evidence_items
                WHERE NOT is_deleted
                """
            )

            evaluation_queries = [
                {
                    "query_id": "exact-change",
                    "query_text": "What did CHG-1842 change on checkout-prod-cluster-01?",
                    "evaluation_type": "retrieval",
                    "filters": {"cluster_id": "checkout-prod-cluster-01"},
                    "notes": "Exact identifier and production scope require lexical recall.",
                },
                {
                    "query_id": "semantic-symptom",
                    "query_text": "checkout writes froze",
                    "evaluation_type": "retrieval",
                    "filters": {"environment": "production"},
                    "notes": (
                        "The current runbook must be recovered semantically even though "
                        "that phrase does not occur in its text."
                    ),
                },
                {
                    "query_id": "fuzzy-change-id",
                    "query_text": "CGH-1842",
                    "evaluation_type": "retrieval",
                    "filters": {
                        "kinds": ["change"],
                        "environment": "production",
                    },
                    "notes": "The letter transposition must resolve to one change.",
                },
                {
                    "query_id": "customer-impact",
                    "query_text": "Which P1 customer commitment is affected?",
                    "evaluation_type": "traversal",
                    "filters": {
                        "seed_external_keys": ["INC-2047"],
                        "max_depth": 3,
                    },
                    "notes": "Traversal must reach visible case and commitment under ACL.",
                },
            ]
            _insert_many(
                cursor,
                """
                INSERT INTO proof.evaluation_queries(
                  query_id, query_text, evaluation_type, filters, notes
                )
                VALUES (
                  %(query_id)s, %(query_text)s, %(evaluation_type)s,
                  %(filters)s::jsonb, %(notes)s
                )
                """,
                [
                    {**record, "filters": _json(record["filters"])}
                    for record in evaluation_queries
                ],
            )

            canonical = {
                key: evidence_id(kind, key)
                for kind, key in (
                    ("incident", "INC-2047"),
                    ("incident", "INC-1980"),
                    ("incident", "INC-2044"),
                    ("change", "CHG-1842"),
                    ("change", "CHG-1838"),
                    ("change", "CHG-1907"),
                    ("support_case", "CASE-7419"),
                    ("support_case", "CASE-7421"),
                    ("support_case", "CASE-7424"),
                    ("runbook", "RB-017"),
                    ("runbook", "RB-092"),
                    ("lock_evidence", "LOCK-2047-001"),
                    ("lock_evidence", "LOCK-2047-002"),
                    ("commitment", "COMMIT-4471"),
                    ("postmortem", "PM-2047"),
                )
            }
            judgments = [
                ("exact-change", "CHG-1842", 3, "Named confirmed change."),
                ("exact-change", "INC-2047", 2, "Direct incident context."),
                ("exact-change", "LOCK-2047-001", 2, "Direct causal lock evidence."),
                ("exact-change", "CHG-1838", 0, "Explicitly ruled out."),
                ("semantic-symptom", "INC-2047", 3, "Matches symptom split."),
                ("semantic-symptom", "LOCK-2047-001", 3, "Captures queued writer."),
                ("semantic-symptom", "RB-017", 3, "Current recovery guidance."),
                ("semantic-symptom", "INC-1980", 1, "Look-alike, different cause."),
                ("semantic-symptom", "RB-092", 0, "Superseded guidance."),
                ("semantic-symptom", "INC-2044", 0, "Wrong environment."),
                ("fuzzy-change-id", "CHG-1842", 3, "Only valid trigram target."),
                ("fuzzy-change-id", "CHG-1838", 0, "Wrong nearby change."),
                ("customer-impact", "INC-2047", 3, "Traversal seed."),
                ("customer-impact", "CASE-7419", 3, "Visible affected case."),
                ("customer-impact", "COMMIT-4471", 3, "Visible P1 commitment."),
                ("customer-impact", "CASE-7421", 3, "Relevant but ACL-restricted."),
                ("customer-impact", "CASE-7424", 0, "Explicitly unaffected."),
            ]
            _insert_many(
                cursor,
                """
                INSERT INTO proof.relevance_judgments(
                  query_id, evidence_id, relevance, rationale
                )
                VALUES (
                  %(query_id)s, %(evidence_id)s, %(relevance)s, %(rationale)s
                )
                """,
                [
                    {
                        "query_id": query_id,
                        "evidence_id": canonical[key],
                        "relevance": relevance,
                        "rationale": rationale,
                    }
                    for query_id, key, relevance, rationale in judgments
                ],
            )

    return {
        "clusters": len(rows["clusters"]),
        "evidence_items": len(rows["evidence"]),
        "incidents": len(rows["incidents"]),
        "changes": len(rows["changes"]),
        "support_cases": len(rows["cases"]),
        "runbooks": len(rows["runbooks"]),
        "commitments": len(rows["commitments"]),
        "postmortems": len(rows["postmortems"]),
        "lock_evidence": len(rows["lock_evidence"]),
        "capture_mode": capture_bundle["capture"]["capture_mode"],
        "relationships": (
            len(rows["incident_changes"])
            + len(rows["incident_cases"])
            + len(rows["incident_runbooks"])
            + len(rows["change_runbooks"])
            + len(rows["case_commitments"])
        ),
    }
