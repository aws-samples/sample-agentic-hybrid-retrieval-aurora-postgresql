# Workshop security boundaries

Mosaic is a disposable, single-participant workshop application with a synthetic
catalog. It is not a shared-tenant storefront or an authentication example.
The Code Editor requires its generated credential. The Mosaic storefront is
intentionally reachable without a login; its CloudFront origin header and WAF
protect the origin and limit traffic, not the identity of a shopper. Do not
load customer data or expose one workshop instance to multiple trust domains.

Browser memory sessions use server-checked shopper/session ownership. Reusing a
request ID with different content is rejected; retries reuse the same Aurora
session and AgentCore event token. Anonymous CLI agent calls are supported for
labs and do not establish a tenant identity. Search receipts can be inspected
by UUID; possession of that UUID is not authorization for a production system.

The agent receives typed, bounded tools. Product and evidence reads must remain
inside the current retrieval or a verified previous answer. Catalog text,
reviews and remembered preferences are data, never instructions or permissions.
Memory can frame a request but cannot prove a product claim. Model output must
map to returned product/evidence identities before becoming the answer of
record. Read-only product tools still write diagnostic receipts and incur
model charges; model calls and retry budgets are deliberately bounded.

SQL values use bound parameters. Dynamic identifiers come from application
allowlists or validated workshop configuration, not model-authored SQL. Aurora
connections use certificate and hostname verification. The runtime role has
catalog SELECT access plus the specific diagnostic/session write grants; schema
installation and exercise repair use the workshop administration identity.

Logs at application and bootstrap boundaries report exception types or bounded,
redacted messages. Credentials must not appear in commands, generated reports,
CloudFormation responses or participant-visible error details. Do not enable
content capture for real personal data. Review service-provider retention and
the workshop cleanup checklist before reusing this sample beyond an event.

A production adaptation needs authenticated identities, owner-scoped receipt
and memory access, application-level quotas, an explicit data-retention policy,
and authorization tests for its actual tenant model. Those capabilities are not
claimed by this workshop release.
