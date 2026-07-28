# SPEC — DAT410 three-surface builders session
## "Terminal → Database Insights → Hybrid Retrieval Workbench" · live incident + evidence lab

Version: draft-13 · Jul 26 2026 — crew-of-five floor model (D10), review brief added to bundle
Audience of this document: a coding agent (Claude Code / Codex) building the session assets, plus facilitators.
Companion documents: the Hybrid Retrieval Workbench implementation spec (authoritative for schemas, tools, API, workbench base), `verity-ui-design-system.md` (visual language), the seven concept screens (talk assets only — see D9).

---

## 0. Storyline and laws

One browser, four tabs, four labs, one direction:

```
TAB 1  Guide             (Workshop Studio)      — the script of the session
TAB 2  Editor/terminal   (code-server)          — Lab 1 home; parity flips in Labs 2–4
TAB 3  Database Insights (CloudWatch console)   — Lab 1 only
TAB 4  Hybrid Retrieval Workbench  (live, cluster-backed) — Labs 2–4 home

LAB 1  INCIDENT & OBSERVABILITY   trigger CHG-1842, watch it live in DBI, fix with CIC
LAB 2  HYBRID RETRIEVAL           the engine — exact / fuzzy / semantic archetypes,
                                  weighted RRF, rerank, the verify-in-psql beat
LAB 3  AGENTIC RETRIEVAL          the agent — one question, six tools, the ACL flip, the
                                  evidence graph (customer-impact lives here: it is a
                                  relationship question, not a ranking one)
LAB 4  PROOF & REPLAY             run proof, replay with zero model calls, DBI hand-off
                                  links, live-capture stretch (flag)
```

**Ordering is engine-first (D11): Hybrid retrieval precedes Agentic retrieval.** The agent is the payoff,
not the premise — its trace is only auditable by a room that already knows what
`T#1 · V#3 · F#1` means, and the session's differentiator against managed agentic
retrieval is the engine, not the loop.

The participant **is** the engineer who runs CHG-1842. They trigger the incident on their own
cluster (same table, same column, same statement as the corpus fixture), watch it in Database
Insights while it is still blocking, fix it with `CREATE INDEX CONCURRENTLY`, and then
investigate the *synthetic, three-weeks-later* version of the same incident through Hybrid Retrieval Workbench's
agentic retrieval — receipts, ACL, graph, replay.

**The canonical question** (verbatim everywhere, Law 1): *"Why did CHG-1842 block checkout
writes during INC-2047, which visible customer was affected, and what was the safe fix?"*

**Law 1 — Same nouns everywhere.** The live schema, the corpus fixtures, the guide, and the UI
use identical identifiers: `shop.orders`, `customer_id`, `idx_orders_customer`,
`Lock:relation`, `CHG-1842`, `INC-2047`. Any new name is a defect.

**Law 2 — psql parity.** Nothing renders in the Hybrid Retrieval Workbench that cannot be reproduced
from psql with a `run_id`. Every panel carries a "Verify in psql" affordance (Section 6.2). The
empty-database test (Section 10 G-14) enforces that no number is hardcoded.

**Law 3 — One-way flow.** Lab boundaries are the only surface changes. Lab 1 owns all
terminal↔DBI movement (2→3, 3→2 for the fix); the Lab 1→2 handoff (2→4) is the last
free transition. The one exception: **scripted parity flips** (tab 4 → tab 2 → tab 4)
during the verify beats of Labs 2 and 4 — brief, guide-scripted, and the point of Law 2.
Every transition is a deep link in the guide, never free navigation.

**Law 4 — Observability vs evidence, said out loud.** The Lab 1 → Lab 2 transition line:
*"Database Insights showed you the incident while it was happening. Hybrid Retrieval Workbench is what remains
when it's over — durable, queryable, citable."* This sentence is in the guide and the
speaker notes.

---

## 1. Decisions (binding)

| # | Decision | Rationale |
|---|---|---|
| **D1** | **The incident trigger is executed by participants (Lab 1), never by bootstrap on their behalf.** | The pedagogy is "you ran the change." Also: DBI lock analysis needs a *currently blocking* session for the live lock-tree moment — a bootstrap-time incident would be long gone. |
| **D2** | **Bootstrap runs everything else**: infra, params, corpus, embeddings, shop seed, baseline load generator, calibration, one **prime run** of the incident (flag `PRIME_INCIDENT=1`, default on), workbench build + smoke, readiness report. | Prime run gives DBI historical Top-SQL/plan/wait data as facilitator fallback, and proves the incident path works in this account before doors open. Everything slow, flaky, or credentialed is pre-baked; the participant path contains zero provisioning. |
| **D3** | **The incident script has a deadman**: auto-cancel of the blocking build at `INCIDENT_TTL` (default 480 s). Participants are *expected* to cancel it themselves first. | Nobody wedges a cluster and raises a hand mid-session. |
| **D4** | **Baseline load generator starts at bootstrap and runs continuously** (systemd). | DBI needs minutes-to-hours of aggregation for a credible "before" picture, including the slow seq-scan query that *motivates* CHG-1842. |
| **D5** | The in-room UI is the **live workbench** (Hybrid Retrieval Workbench spec Section 13 + deltas in Section 6). The seven synthetic concept screens appear only in the 15-minute talk and the deck. | A single hardcoded number in the lab discounts the whole surface (Law 2). |
| **D6** | No RDS Proxy, Lambda, or Gateway in the participant path. Workbench backend connects with a native driver directly to the cluster (needs `SET LOCAL` ANN controls + `EXPLAIN`). Proxy/Gateway remain talk content. | Fewer live failure modes; the transaction-local ANN story requires a plain session anyway. |
| **D7** | Live-incident capture into Hybrid Retrieval Workbench is a **feature-flagged stretch** (`VERITY_LIVE_CAPTURE=1`, default off in the room until rehearsed green). See Section 4.6. | Best 90 seconds of the session if it works; cannot hurt if it doesn't. |
| **D8** | Ordinary-build cancel leaves **no** INVALID index (that is a failed-CIC artifact). The INVALID demo is an optional exploration in the guide appendix, not the core path. | Technical accuracy; RB-017's cleanup clause stays truthful. |
| **D9** | Lab 1 ≤ 19 min of the 45-min lab; Labs 2–4 get ≥ 24 min. Cut-ladder: Lab 4 merges into Lab 3 if late; within Lab 1, DBI check 3 compresses first; **Lab 2 is never cut**. Overrun theory (locks, CIC) moves into the DBI lead's talk segment, not lab time. | The incident is the on-ramp; the engine is the session. |
| **D10** | Presenter mapping: Shayon owns Labs 2–3 and the trigger; **the DBI lead owns the DBI segment of Lab 1** plus the lock/CIC theory beat, and plays **auditor** in the Lab 2 and Lab 4 parity beats ("pick any number on any screen"). **Crew of five**: two voices on stage per lab — never three — and three on the floor with named jobs: **F1** resets (`reset.sh` authority, wedged participants), **F2** DBI/IAM triage + deep-link fallback, **F3** flags + the demo-of-last-resort cluster. Roles are assigned by name in the rehearsal timing sheet. | Voice change signals surface change; the audit role converts the skeptic. At room scale the floor is where sessions are saved — an unowned failure is a failure that eats stage time. |
| **D11** | **Engine-first ordering**: Lab 2 (arms + fusion) precedes Lab 3 (agent). | The agent's trace is only legible after the arms are understood; agent-first re-treads what managed agentic retrieval now does in one API call; the session's claim — Aurora as retrieval engine of record — is engine-shaped. |
| **D12** | Lab names are canonical and Law 1 applies to them: **Incident & observability / Hybrid retrieval / Agentic retrieval / Proof & replay** — verbatim in guide pages, slides, script banners, and speaker notes. | Labs 2–3 decompose the session title ("agentic hybrid retrieval") into its two halves in teaching order; Labs 1 and 4 name the on-ramp and the differentiator. |
| **D13** | **Single-LLM policy**: one generation model for both synthesis and free mode — `claude-sonnet-5` (Converse, Global CRIS). No Opus-class model; no second LLM as throttle fallback (the extractive fallback + replay are the degradation path). Per answer: **one LLM, three model invocations** (embed · rerank · synthesize). | The engine does the reasoning-shaped work; the model writes it down — "Sonnet is enough" *is* the thesis. One model string = one quota request, one lifecycle check, easier room-scale throughput. Opus would stretch the dominant latency stage for no measurable gain in a ≤8-evidence-block synthesis. |
| **D14** | **Identifier arithmetic**: ticket numbers stay irregular (no CHG-1000-style rounds); the typo fixture is a **letter transposition, `CGH-1842`** — corrupt the letters, keep the digit block intact. Normalization for the trigram arm is lowercase with **separators preserved**. Digit transposition (`CHG-1482`) is banned. | Measured on a live engine: `chg-1482` is a six-way tie at 0.3846 across every `chg-1*` record (digit transposition destroys all interior digit trigrams); `cgh-1842` is unique at 0.5000 with runner-up 0.2000. Round numbers put the nearest distractor at 0.2857 — one background ID from the 0.30 threshold (the documented CHG-0100 ≡ 0.5000 bug class). Stripping the hyphen drops the letter-transposition margin to 0.3333. Only one ID is ever hand-typed in the session (the typo itself); memorability lives in the incident, not the digits. **Upstream: the base Hybrid Retrieval Workbench spec's `fuzzy-change-id` acceptance line needs the same correction.** |
| **D15** | **AgentCore posture — compose vs replace.** Exactly one component enters the participant path: **Gateway**, as optional module **M5** (post-Lab-4 / fast finishers / take-home), pre-provisioned by bootstrap behind `VERITY_GATEWAY=1` (default 0), never built live (the M5 forwarder Lambda sits outside the timed lab path, so D6 stands). M5 terminates in a **receipt diff**: the canonical question over Gateway MCP vs stdio → identical candidates and citations, diffed in psql. Runtime, Identity, Policy, Memory, and Evaluations stay slides; the Policy slide carries one line — *"Policy decides which tools may be called; Aurora decides which rows exist."* | Gateway *composes* with the engine thesis (a managed tool plane over your engine); managed retrieval *replaces* it — compose gets a module, replace gets a positioning slide. A second live enforcement plane would blur the ACL moment (CASE-7421 is denied by the database, at every arm and hop). Audit-safe because M5's claim is database-verifiable: zero differing rows — and it carries two engine beats: `SET LOCAL` ANN GUCs surviving any transport, and Gateway→Lambda fan-out as where the RDS Proxy discussion attaches. |
| **D16** | **Overview-first IA — nav mirrors the labs.** The workbench opens on an **Overview** anchored on the canonical question and the current run; primary nav is the lab ladder — **Overview / Retrieval / Agent / Proof** — with Corpus, Evaluation, and Health demoted to utility nav. One lab = one primary surface; every guide checkpoint state is **URL-addressable** (Section 6.0); the run_id chip is the persistent breadcrumb; drill depth ≤ 2 (surface → inline drawer). Supersedes the base spec's Investigate / Run proof / Corpus / Evaluation shell — shell only; panel contracts unchanged. | Tension with the labs is translation cost: if the guide says "Hybrid retrieval" and the nav says "Investigate," every participant pays it at every transition. Nav labels that repeat the lab nouns (Law 1 extended to navigation) make the workbench the labs' surface rather than a fifth thing to learn — and addressable routes let the guide land people on a checkpoint instead of narrating clicks. |
| **D17** | **Takeaway packaging.** Participants leave with two artifacts: the repo (baseline) and an **Agent Skill** — `skills/aurora-hybrid-retrieval/` — packaging the method for reuse on the customer's own schema: canonical fusion SQL templates (numeric-cast and COALESCE correctness baked in, `%`-operator trigram, ACL-inside-every-arm), the gotcha registry (E1, E2, E6, E7; D14 normalization; 1024-d pinning), the receipts DDL, the eval-harness scripts, and a gates checklist the skill **instructs the consuming agent to run**. Authored last, distilled from the final guide and gates. The MCP server and workbench remain demo artifacts, not the takeaway. | A tool executes against fixed assumptions; a skill transfers judgment and adapts to their tables. Skills are an open, portable format, so the takeaway works in Claude Code on Bedrock — the room's own environment. It passes the auditor test because it is guidance that verifies itself: the skill's first instruction is to run the shipped assertions, not to trust the prose. |
| **D18** | **Takeaway ladder + protected moments.** Each lab closes with one canonical takeaway sentence the participant just proved (experience → principle → artifact); the skill's four section headers are those sentences **verbatim** (Law 1): Lab 1 — *"Observability shows the incident while it happens; evidence answers for it later"* → "Why receipts". Lab 2 — *"Fuse ranks, never raw scores — and verify the arithmetic on a live engine"* → "The canonical fusion SQL". Lab 3 — *"The agent consumes the engine; entitlements live in the database, at every arm and hop"* → "ACL & traversal patterns". Lab 4 — *"A claim you can't replay is a vibe — every number gets a run_id"* → "Gates: run the shipped assertions". The guide renders a skill-assembly strip (one section unlocked per lab); the **final checkpoint** of Lab 4 is installing the skill in Claude Code on the participant host and running its first assertion to a green check. **Protected moments, exempt from the D9 cut-ladder**: M1 first blocked writer in their terminal · M2 room-as-auditor (the audience picks any number on any screen; it is reproduced in psql live) · M3 the ACL flip · M4 replay with zero model calls. | The skill stops being a download and becomes the receipt of their own session; the last action in the room is the first action at work. M2 is the peak: fully de-risked by Law 2 + G-13, it converts the room from spectators into co-auditors. |

---

## 2. Environment & bootstrap

### 2.1 Account shape (per participant, Workshop Studio)

- 1 × Aurora PostgreSQL cluster (target engine per release gate #1; pgvector ≥ 0.8 with
  `iterative_scan` — hard requirement), 1 writer instance. Readers optional; not in lab path.
- 1 × EC2 instance running code-server (browser VS Code + terminal), the Hybrid Retrieval Workbench backend
  (FastAPI, port 8000) and frontend (static build served by the backend), bootstrap artifacts.
- **Tab-4 exposure**: the workbench is reached through the same authenticated front door as
  code-server (its `/proxy/8000/` path or the event ALB/CloudFront route) — never a raw
  public port. `[VERIFY mechanism in the Workshop Studio template]` (open item 9).
- Bedrock model access: Cohere Embed 4, Rerank 3.5, Claude (per Hybrid Retrieval Workbench spec Section 3), pre-enabled
  by Workshop Studio account config.
- CloudWatch **Database Insights Advanced** enabled on the cluster (Section 5.1).
- Participant IAM role: DBI/CloudWatch read (Section 5.3), no RDS mutate beyond connect.

Connection contract: `/etc/verity/env` written by bootstrap, sourced by every script:

```bash
export PGHOST=<writer endpoint>  PGPORT=5432  PGDATABASE=verity
export PGUSER=workshop           PGPASSWORD=<from Secrets Manager at boot>
export VERITY_REGION=<region>    VERITY_DB_RESOURCE_ID=<DbiResourceId>
export VERITY_CLUSTER_ID=checkout-prod-cluster-01     # display identity, Law 1
export INCIDENT_TTL=480          ORDER_ROWS=25000000
export PRIME_INCIDENT=1          VERITY_LIVE_CAPTURE=0
```

### 2.2 Bootstrap stages (single `bootstrap.sh`, idempotent, resumable, logged to `/var/log/verity-bootstrap.log`, stage markers in `/var/lib/verity/stage`)

```
S1  infra-verify     CFN outputs present; psql connects; extensions vector/pg_trgm present;
                     SELECT version(), extversion — abort with named error if wrong.
S2  params           Apply + verify DBI-related parameters (Section 5.2). Reboot if any is static.
                     Assert with SHOW after apply. THIS RUNS BEFORE ANY DATA so a reboot is free.
S3  verity-schemas   casework/retrieval/proof DDL + synthetic corpus + embeddings + projection
                     (existing Hybrid Retrieval Workbench bootstrap, unchanged). Ends with assert_projection_ready().
S4  shop-seed        Section 3.1 DDL + server-side seed (generate_series). Target: orders=ORDER_ROWS.
                     Records actual row count + table size in the readiness report.
S5  loadgen          Install + start systemd units verity-loadgen-reads / -writes (Section 3.3).
S6  calibrate        Run a THROWAWAY ordinary CREATE INDEX on shop.orders under the incident
                     session settings (Section 4.2), time it, DROP INDEX, write build_seconds to
                     readiness report. If build_seconds < 240 → WARN and print the ORDER_ROWS
                     bump suggestion (gate G-6). If > 420 → suggest reduction.
S7  prime-run        If PRIME_INCIDENT=1: execute incident.sh --unattended --ttl 180, then
                     resolve. Leaves a historical Lock:relation spike + captured plans in DBI.
S8  workbench        Build frontend, start backend service, smoke: POST /v1/agent/answer with
                     the canonical question under principal=workshop; assert 5 citations
                     validate; record smoke run_id in the readiness report.
                     Install Claude Code (Bedrock mode) on the host; verify
                     `claude --version` + one Bedrock invocation under the participant
                     role (feeds the D18 final checkpoint; open item 13).
                     If VERITY_GATEWAY=1 (D15): deploy the M5 forwarder Lambda (in-VPC,
                     security-group access to the backend :8000, timeout 30 s), create the
                     Gateway with a **Lambda target** whose tool schemas are generated from
                     agent/registry.py (T4), assert every exposed tool name matches the
                     `targetName___toolName` prefix shape, smoke one tool call, record the
                     gateway run_id. On any failure: log, force the flag to 0, continue.
S9  readiness        Write /home/participant/READINESS.md: stage results, build_seconds,
                     corpus counts, smoke run_id, DBI deep links (Section 5.4), param values.
```

**What bootstrap must never do:** run the participant-facing incident outside the prime run;
enable `VERITY_LIVE_CAPTURE`; leave `idx_orders_customer` existing (S6/S7 must clean up —
gate G-7).

---

## 3. Surface B files — the shop (Lab 1 substrate)

Repo layout for this spec's assets:

```
verity-session/
  bootstrap/bootstrap.sh, stages/*.sh
  shop/ddl.sql, seed.sql
  incident/incident.sh, resolve.sh, fix.sh, reset.sh, watch.sql
  incident/loadgen/{reads.sql, writes.sql, loadgen.sh, verity-loadgen-*.service}
  capture/capture_incident.sh                # D7, flagged
  agent/{registry.py, tools/*.py, runner.py}    # Section 7 T1–T4
  mcp/verity_mcp.py                             # generated stdio server, Section 7 T5
  mcp/gateway_forwarder.py                      # M5 thin Lambda forwarder (Section 7 T6)
  gates/{checks.sh, empty_db_ui_test.py, verify_sql_golden.py}
  guide/ (Workshop Studio contentspec, Section 8)
```

### 3.0 Sizing at a glance

| Table | Rows | ~Size | Sized by |
|---|---|---|---|
| `shop.customers` | 200,000 | ~25 MB | key space for Zipf skew; point lookups cache-resident |
| `shop.products` | 5,000 | ~1 MB | — |
| `shop.orders` | **25,000,000** (`ORDER_ROWS`) | ~2.2 GB heap + ~0.7 GB PK | G-6: single-worker ordinary build lands 240–420 s on the target class; the seq scan is visibly expensive in Top SQL |
| casework documents | 12,011 (incl. ~200 background IDs) | small | release corpus (base spec) |
| `retrieval.chunks` | 48,226 × `vector(1024)` | ~200 MB + ~200 MB HNSW | deliberately buffer-pool-resident — the lab's predictable regime (see the Scale screen for what breaks past it) |
| evaluation queries | 4 retrieval + 2 traversal (expand to ~25 pre-deck) | — | ablation reads as evidence, not anecdote |
| `proof.*` | 24 candidates per run | grows with runs | smoke run = 1 |

Seed mechanics: load `shop.orders` **without FK constraints**, then `ALTER TABLE … ADD
CONSTRAINT` afterward (one validation scan) — per-row FK checks make a 25 M-row seed crawl.
`ANALYZE` after constraints.

### 3.1 `shop/ddl.sql`

```sql
CREATE SCHEMA IF NOT EXISTS shop;

CREATE TABLE shop.customers (
  customer_id bigint PRIMARY KEY,
  name        text NOT NULL,
  region      text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE shop.products (
  product_id  bigint PRIMARY KEY,
  sku         text NOT NULL UNIQUE,
  name        text NOT NULL,
  price_cents integer NOT NULL CHECK (price_cents >= 0)
);

CREATE TABLE shop.orders (
  order_id    bigserial PRIMARY KEY,
  customer_id bigint  NOT NULL REFERENCES shop.customers,
  product_id  bigint  NOT NULL REFERENCES shop.products,
  qty         integer NOT NULL DEFAULT 1,
  status      text    NOT NULL DEFAULT 'placed',
  total_cents integer NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);
-- DELIBERATELY no index on orders(customer_id).
-- The seq scan on "orders by customer" is the motivation for CHG-1842.
```

### 3.2 `shop/seed.sql` (server-side, fast)

- customers: 200,000 rows (`generate_series`, region ∈ {na,emea,apac,latam}).
- products: 5,000 rows.
- orders: `ORDER_ROWS` (default 25 M) via `INSERT … SELECT` over `generate_series`,
  customer_id skewed (Zipf-ish via `(random()^2 * 200000)::bigint + 1`) so hot customers exist,
  created_at spread over 180 days. `ANALYZE` after load. Log rowcount + `pg_table_size`.

### 3.3 Load generator (`incident/loadgen/`)

Three pgbench processes, rate-limited, running as systemd units from bootstrap onward (D4).
Rates are coupled to Section 3.0: a 2.2 GB seq scan cannot run 20×/s — the slow query runs at
**one per 5 s**, which still tops Top SQL by per-call cost without saturating the instance
(and Labs 2–4 need that headroom). After `fix.sh`, the same query's load visibly collapses —
a free before/after beat.

`reads-point.sql` (`-R 18`) — the healthy shop:
```sql
\set oid random(1, 25000000)
SELECT order_id, status, total_cents FROM shop.orders WHERE order_id = :oid;
```

`reads-slow.sql` (`-R 0.2` — one per 5 s) — the query that motivates CHG-1842:
```sql
\set cid random(1, 200000)
SELECT c.name, count(*) AS orders, sum(o.total_cents) AS spend
FROM shop.customers c JOIN shop.orders o USING (customer_id)
WHERE c.customer_id = :cid
GROUP BY c.name;                       -- seq scan on orders → the DBI "before" story
```

`writes.sql` (run at `-R 10`):
```sql
\set cid random(1, 200000)
\set pid random(1, 5000)
INSERT INTO shop.orders (customer_id, product_id, qty, status, total_cents)
VALUES (:cid, :pid, 1, 'placed', (random()*10000)::int);
```

`loadgen.sh start|stop|status` wraps the three pgbench invocations
(`--progress=10`, `--log`, PID files in `/run/verity/`). Units `Restart=always`.
Acceptance: after start, `status` reports all three TPS values; DBI Top SQL shows the slow
read query within 15 minutes of bootstrap.

---

## 4. Surface B files — the incident (Lab 1 · Incident & observability)

### 4.1 `incident/incident.sh` — the trigger (participant-run; D1)

Usage: `./incident.sh` (interactive) · `--unattended --ttl N` (bootstrap prime run only).

Behavior contract, in order:

1. **Preflight** (abort with one-line remedies on failure): env sourced; loadgen running
   (offer to start); `idx_orders_customer` absent (offer `reset.sh`); no other backend
   already running a CREATE INDEX on shop.orders; `INCIDENT_TTL` sane (120–900).
2. **Print the change ticket** — verbatim, Law 1:
   ```
   ┌──────────────────────────────────────────────────────────────┐
   │ CHANGE  CHG-1842                                             │
   │ Cluster checkout-prod-cluster-01 · table shop.orders         │
   │ "Reads filtering orders by customer are slow. Add an index." │
   │   CREATE INDEX idx_orders_customer                           │
   │     ON shop.orders (customer_id);                            │
   │ Window: now. Approver: you.                                  │
   └──────────────────────────────────────────────────────────────┘
   ```
3. **Start the build** in a background psql session that first pins duration
   (Section 4.2 settings), records the backend PID to `/run/verity/incident_build.pid`, timestamps
   `t0` to `/run/verity/incident_t0`.
4. **Monitor loop** (foreground, every 5 s until build gone):
   ```
   t+0:35  blocked writers: 14   reads: OK (20.1 tps)   writes: STALLED (0.0 tps)
           blocking pid 3944 · wait_event Lock:relation
   ```
   Sourced from `pg_stat_activity` (count of backends with `wait_event_type='Lock' AND
   wait_event='relation'` on shop.orders) and the pgbench progress logs.
5. **At first blocked writer**, print the Lab 1 DBI handoff block: the DBI deep link
   (from READINESS.md) + "keep this running; open Database Insights in tab 3."
6. **Deadman** (D3): at `t0 + INCIDENT_TTL`, `SELECT pg_cancel_backend(<build_pid>)`,
   print `DEADMAN: build cancelled after ${INCIDENT_TTL}s — writers recovering`, exit 0.
7. Exit codes: 0 resolved (by participant or deadman), 2 preflight failure, 3 internal.

### 4.2 Build-duration pinning (honest and teachable)

The blocking session runs:

```sql
SET maintenance_work_mem = '64MB';
SET max_parallel_maintenance_workers = 0;
CREATE INDEX idx_orders_customer ON shop.orders (customer_id);
```

Duration is controlled by `ORDER_ROWS` + these session settings, calibrated in S6 to
**240–420 s** on the target instance class (gate G-6). No artificial locks, no sleeps —
the guide states the settings openly ("we build single-worker so the window is long enough
to inspect; parallel maintenance is the first real-world mitigation, and it is not enough").

### 4.3 `incident/watch.sql` — terminal equivalents of every DBI view (also the DBI-outage fallback, Section 9)

```sql
-- who is blocked, by whom
SELECT a.pid, a.wait_event_type, a.wait_event,
       pg_blocking_pids(a.pid) AS blocked_by,
       left(a.query, 60) AS query
FROM pg_stat_activity a
WHERE a.wait_event_type = 'Lock';

-- the lock conflict itself
SELECT l.locktype, l.mode, l.granted, l.pid, left(a.query, 50) AS query
FROM pg_locks l JOIN pg_stat_activity a USING (pid)
WHERE l.relation = 'shop.orders'::regclass
ORDER BY l.granted DESC;

-- reads are fine (run it; it returns)
SELECT count(*) FROM shop.orders WHERE customer_id = 42;
```

### 4.4 `incident/resolve.sh` — the participant's cancel

Reads the PID file → `pg_cancel_backend` → waits until no Lock waiters remain → prints
recovery ("writes: 10.0 tps"), confirms **no index exists** (ordinary cancel = clean
rollback, D8), points to `fix.sh`.

### 4.5 `incident/fix.sh` — RB-017 enacted

1. Prints the RB-017 excerpt (CONCURRENTLY, no transaction block, INVALID-on-failure cleanup).
2. Runs `CREATE INDEX CONCURRENTLY idx_orders_customer ON shop.orders (customer_id);`
   in the background; foreground polls `pg_stat_progress_create_index` every 5 s
   (phase, blocks done/total) — this is a DBI-lead beat.
3. On completion: assert `indisvalid`; re-run the reads.sql query with
   `EXPLAIN (ANALYZE, BUFFERS)` and print the before/after: Seq Scan → Index Scan, ms drop.
4. On failure/interrupt: detect INVALID index, print the RB-017 cleanup
   (`DROP INDEX CONCURRENTLY …`), offer retry. (Appendix exploration: `fix.sh --demo-invalid`
   kills CIC mid-build to manufacture the INVALID artifact deliberately.)

### 4.6 `capture/capture_incident.sh` — flagged stretch (D7)

Only when `VERITY_LIVE_CAPTURE=1`:

1. During the incident (or from `/run/verity` artifacts after), snapshot two blocked-writer
   rows + the blocking row (pids, wait event, statements, timestamps).
2. Insert casework rows: kind `lock`, keys `LOCK-LIVE-001`, `LOCK-LIVE-002`, source URI
   `workshop://live/<session>/lock/N`, ACL public; canonical edge is **not** claimed —
   link to CHG-1842 as `evidence_supports`, **inferred**, method `live_session_capture`.
3. Queue projection → wait for `assert_projection_ready()` (timeout 90 s → non-zero exit,
   flag stays visually "pending" in the workbench, nothing breaks).
4. Payoff in Lab 4: re-ask the canonical question; the answer may now cite the participant's
   own lock snapshot. The guide script for this beat: *"That citation is from nine minutes
   ago. You made that evidence."*

### 4.7 `incident/reset.sh` — facilitator recovery

Cancels any shop.orders index build; drops `idx_orders_customer` (valid or INVALID);
clears `/run/verity/incident_*`; restarts loadgen; prints a clean-slate check. Safe to run
at any time, twice.

---

## 5. Surface C — Database Insights (Lab 1 · DBI segment)

Nothing to build here; everything to **pre-enable, pre-verify, and pre-link**.

### 5.1 Enablement (bootstrap S2, with reboot budget)

- Database Insights **Advanced** mode on the cluster. `[VERIFY on target: exact CLI —
  expected `aws rds modify-db-cluster --database-insights-mode advanced` + Performance
  Insights enablement/retention prerequisites; confirm flags and Workshop Studio cost
  approval for Advanced pricing.]`
- Cluster parameter `aurora_compute_plan_id = on` (required for plan analysis).
- Instance parameter `aurora_stat_plans.with_analyze = on` — **without this, the console
  shows estimated plans only**; the session narrates *actual* plans. Accept the capture
  overhead for a workshop cluster.
- `[VERIFY: apply type static vs dynamic for both params → reboot in S2 if needed.]`
- Assert post-apply: `SHOW aurora_compute_plan_id;` etc., recorded in READINESS.md.

### 5.2 The three participant checks (guide, Lab 1 — total ≤ 7 min)

1. **DB load, sliced by waits** — the `Lock:relation` wall rises while total load is modest:
   *"the database isn't busy, it's stuck."* Reads keep flowing (compare with terminal check 4.3-3).
2. **Lock analysis / lock tree** — blocking session = the CREATE INDEX backend; blocked =
   their pgbench writers. Cross-check the pids against `pg_blocking_pids` output from tab 2.
   `[VERIFY: whether lock analysis shows history after resolution or current-only — determines
   whether stragglers need the prime-run spike or a re-trigger.]`
3. **Top SQL → the reads.sql digest → Plans tab** — the seq-scan plan captured under load
   (thanks to D4 there is history), and after `fix.sh`, the new index-scan plan appears →
   **plan comparison** on one digest. This is the DBI money shot and the DBI lead's segment.

### 5.3 Participant IAM (bootstrap-verified, gate G-10)

Read-only console access sufficient for Section 5.2: CloudWatch Database Insights views +
Performance Insights data APIs (`pi:GetResourceMetrics`, `pi:DescribeDimensionKeys`,
`pi:GetDimensionKeyDetails`, `pi:ListAvailableResource*`), `cloudwatch:GetMetricData`,
`rds:DescribeDBClusters/Instances`. `[VERIFY exact minimal set against the DBI docs; test
with the participant role, not admin.]`

### 5.4 Deep links

During the dry run, capture the real console URLs for (a) the cluster's Database Insights
instance view, (b) the lock analysis view, and template them with `{region}`,
`{db_resource_id}` as Workshop Studio variables. READINESS.md and the guide embed them.
Free navigation is never required (Law 3).

---

## 6. Surface D — Hybrid Retrieval Workbench deltas (Labs 2–4)

Base = Hybrid Retrieval Workbench spec Section 13 (Investigate / Run proof / Corpus / Evaluation; no remote fonts;
dense, operational). This section specifies only the deltas.

### 6.0 Information architecture — overview-first (D16)

Hub-and-spoke: an Overview anchored on the canonical question; each deeper surface is a
lens on the current run.

```
Header (all surfaces): wordmark · run chip rr_… (breadcrumb) · principal · health dot

PRIMARY NAV — the lab ladder
  Overview    the question · run state · entry cards      Lab 1→2 landing; carries the Law-4 line
  Retrieval   arms · fusion controls · candidates ·       Lab 2
              per-candidate receipt drawer · plan drawer (6.5)
  Agent       plan chips · six-tool thread · cited        Lab 3
              answer · principal flip · evidence graph
  Proof       run receipt · replay · timeline ·           Lab 4
              observability refs (6.3) · capture (6.4)

UTILITY NAV (right / overflow — never primary)
  Corpus · Evaluation · Health
```

Rules:
- **One lab = one primary surface.** Guide deep links land with state prefilled — routes
  are contract: `/overview` · `/retrieval?preset={exact|fuzzy|semantic}` ·
  `/agent?principal={workshop|support-lead}` · `/proof/{run_id}`.
- **run_id is the breadcrumb.** Every surface renders the same run chip; switching
  surfaces never loses the run.
- **Drill depth ≤ 2**: surface → inline drawer/expansion (candidate receipt, tool
  receipt, edge provenance). No stacked modals.
- **Nav labels are Law-1 nouns** — "Retrieval," "Agent," "Proof," never "Investigate."
- Mapping from the base spec's Section 13 tabs: Investigate → Retrieval + Agent;
  Run proof → Proof; Corpus and Evaluation → utility. The base spec's panel and data
  contracts are unchanged; only the shell moves.

### 6.1 Live banner

Header strip on every page, from `GET /ready` (the readiness probe already queries
Aurora for the projection status and document counts the banner shows; `/health` stays
a dependency-free liveness probe):
`cluster {VERITY_CLUSTER_ID} · projection READY · 12,011 docs · engine {version()} ·
pgvector {extversion}` — `version()` and `extversion` are read from Aurora per call and
`cluster_id` is env-sourced display identity; none hardcoded in the frontend (Law 2).

### 6.2 "Verify in psql" (the authentication moment)

- Every panel that renders retrieval or proof data gets a `⌘ verify` affordance opening a
  modal: the exact SQL, bound to the visible `run_id`, with a copy button and the expected
  row shape.
- The SQL is **generated server-side** and returned by the API alongside the data
  (`_verify_sql` field), sourced from the same canonical query registry the endpoint
  executes — not a hand-maintained twin (drift = defect, gate G-13). The registry lives in
  `backend/app/verify_sql.py`; the endpoint imports each statement to *both* query Aurora and
  publish the descriptor, so there is no twin string to drift.
- **Verify at the grain of reproducibility**, not always the panel:
  - **Panel grain** — the receipt family (run / candidates / stages / answer) is one
    `run_id`-bound SELECT per panel; the panel publishes one descriptor.
  - **Element grain** — composite panels (graph edges, timeline events) are not one SELECT,
    so each element carries its own single-key descriptor (`edge_key` for an edge,
    `evidence_id` for an event) drawn from the same projection block the batch query uses.
    The element key is unique, so the drawer's SQL reproduces exactly the displayed row.
    G-13 replays each element and diffs it, so the zero-mismatch contract holds unchanged.
  - **Honest labels** — panels with no run-bound reproduction (the live EXPLAIN plan, the
    evaluation leaderboard) carry an explicit `{"reproducible": false, "reason": …}` marker
    in place of the verify affordance. Visible honesty, never a decorative SQL string; the
    eval affordance may show the harness command (`make evaluate`) instead of a query.
- Scripted beat (Lab 2 opening): open the smoke run's receipt → copy the
  candidates verify-SQL → run it in tab 2 → same arm positions, same RRF, same rerank
  scores. The auditor's invitation: *"pick any number on any screen."*
- `[VERIFY]` backlog — the query embedding is persisted (`proof.retrieval_runs.query_embedding`),
  and replay guarantees zero model calls, so the semantic-arm EXPLAIN could become run-bound:
  a plan-drawer variant that runs `EXPLAIN` with the *stored* embedding (not a freshly computed
  one) would make the query-plan panel verifiable too. Not built; would extend G-13 to the plan
  drawer without any live Bedrock call.

### 6.3 Database Insights hand-off (adopted from the architecture review)

- New table `proof.observability_refs (run_id, db_resource_id, window_start, window_end,
  wait_event, sql_digest nullable)` — written by the retrieval path with the query's
  execution window; by `capture_incident.sh` with the incident window when flagged.
- Run-proof page renders two buttons when a ref exists: **Open in Database Insights** and
  **Open lock analysis** (deep-link templates from Section 5.4, time-window query params if the
  console supports them `[VERIFY]`). Jumping surfaces = following a citation (Law 4).

**Shipped (application source).** The table exists (`sql/01_schema.sql`, FK to
`proof.retrieval_runs`, `ON DELETE CASCADE`). The retrieval success path writes one row per
run from the run's own persisted `started_at`/`completed_at` window (`backend/app/search.py`),
so `window_start`/`window_end` are the honest execution window — no separate capture logic.
`db_resource_id` is `VERITY_DB_RESOURCE_ID` from config (NULL when unset). `wait_event` and
`sql_digest` stay NULL on this path; they are the incident-capture path's fields (6.4).
`GET /v1/runs/{run_id}` attaches `observability_ref` with the stored window, a `_verify_sql`
descriptor for the window row (Law 2), and any composed deep links. The Proof replay lens
always shows the observed window; the two buttons appear **only** when a console URL template
(`VERITY_DBI_URL_TEMPLATE` / `VERITY_LOCK_URL_TEMPLATE`, Section 5.4) is configured and every
placeholder it names resolves — with no template, no button points at an unverified URL.
Templates and `VERITY_DB_RESOURCE_ID` are empty by default and are captured on the target
account during the dry run.

**Deferred (infra-coupled).** The `capture_incident.sh` incident-window write (with
`wait_event`/`sql_digest` from a currently blocking session) lands with that script in the
Workshop Studio repo (Section 4.6, D7). The exact console time-window query-param format stays
`[VERIFY]` until captured against the target console, so no time-window params are invented in
the templates here.

### 6.4 Live-capture surfacing (D7)

When `VERITY_LIVE_CAPTURE=1` and projection is ready, Investigate shows `LOCK-LIVE-*`
results with a `LIVE` badge (styling: existing badge component, green); the citation list in
Run proof renders the `workshop://live/...` URI. No new pages.

**Deferred.** This surfacing lands with `capture_incident.sh` (Section 4.6) in the Workshop
Studio repo. Not built in the application source; no phantom `LIVE` path exists here.

### 6.5 EXPLAIN affordance

The Investigate diagnostics drawer (existing per base spec) adds a "captured on this
cluster" label with timestamp, and — if Optimized Reads is active on the instance class —
surfaces `aurora_orcache_hit` from the BUFFERS output verbatim. Never rendered on
non-NVMe instance classes (the field won't exist; hiding it is the honest state).

---

## 7. Agent & tooling — technical choices

Everything the agent path uses, chosen once. "Lab path" = runs in the room; "appendix" =
documented and demoed only when flagged. Versions are pinned at content freeze (Section 12).

| # | Layer | Choice | Boundaries / why |
|---|---|---|---|
| **T1** | Agent framework | **Strands Agents SDK** (Python), version pinned `[VERIFY current API at freeze]` | Continuity from the 2025 session; AWS-native; typed tool interface, first-class MCP client, OTel tracing. Not used as a free ReAct loop in the lab path — see T2. |
| **T2** | Orchestration mode | **Planned**: the deterministic plan emitted by `decompose_question` drives tool order; the Strands agent *executes* steps, it never chooses them. `VERITY_AGENT_MODE=planned` default | The inspectable-plan guarantee survives only if no model picks tools. This is what makes the trace repeatable (Law 2 applied to the agent). |
| **T3** | Model calls per answer | Exactly **one** agent-loop model call: `synthesize_cited_answer` via Converse (`global.anthropic.claude-sonnet-5`, Global CRIS). Rerank (`cohere.rerank-v3-5:0` via bedrock-agent-runtime `Rerank`) and query embedding (`us.cohere.embed-v4:0`, 1024-d pinned, `search_query`) happen *inside* `search_evidence`, not as agent steps | Latency and cost are countable per answer; skip-rerank and extractive-fallback modes give a graceful zero-model degradation path (Section 9). |
| **T4** | Tool registry | **Single source of truth**: the six tools defined once in `agent/registry.py` (typed signatures + docstrings). Strands tool specs, the stdio MCP server, and the Gateway OpenAPI are all *generated* from it | Cross-transport drift was the pass-2 failure class. Gate G-17. |
| **T5** | MCP | stdio server `mcp/verity_mcp.py` (official Python MCP SDK), generated from T4; identical JSON contracts as HTTP | Lab 3 stretch: attach any MCP client (Claude Code, Cursor, …) to the same six tools against the same cluster. Parity captures run `rerank:false` so they replay offline. Gate G-18. |
| **T6** | AgentCore Gateway | **Optional module M5 (D15)**, flag-gated `VERITY_GATEWAY`, pre-provisioned in bootstrap S8. **Target type is Lambda, deliberately**: Lambda invocation travels the AWS control plane (execution role), not a network path — the only target type that reaches the private backend without a public endpoint (Section 2.1). OpenAPI and MCP-server targets require an endpoint reachable by the managed service (credential-provider or public) — declined. The Lambda is a **thin forwarder** to `/v1` (~50 lines), never a second tool implementation, so G-22 diffs the transport, not adapter logic; its tool schemas are generated from the registry (T4). Recorded gotcha: Gateway exposes tools as `${targetName}___${toolName}` (three underscores) — names and descriptions must survive that prefixing `[VERIFY on current AgentCore]` | The stdio→Gateway escalation turns "same receipts over three transports" from a stated claim into a demonstrated one — while keeping Gateway out of the timed 45 minutes and its failure out of the room's budget. |
| **T7** | Descriptions as guardrails | `explain_ranking` described as a diagnostics/debugging tool; `synthesize_cited_answer` as terminal-only | So free-mode models and third-party MCP clients don't select them mid-plan (pass-2 lesson). Gate G-19. |
| **T8** | DB access | psycopg 3 + psycopg_pool, native driver, direct to the instance (D6 — no proxy) | Each retrieval is one transaction: `SET LOCAL hnsw.ef_search / hnsw.iterative_scan`, then the one canonical statement per search function. |
| **T9** | Backend | FastAPI + uvicorn under systemd (`verity-workbench`): `/v1` API, the `_verify_sql` registry (Section 6.2), static frontend | One process to restart, one health endpoint for the guide. |
| **T10** | Frontend | React + Vite, system font stacks (no remote fonts), base workbench + Section 6 deltas | |
| **T11** | Budgets & trace | `max_tool_calls 12`, per-tool timeouts; every tool call appended to the run receipt with timing and spend. Strands OTel export to CloudWatch is optional and never load-bearing | `proof.*` is the trace of record; OTel is a mirror, not a source. |
| **T12** | Free mode (stretch) | `VERITY_AGENT_MODE=free`: model-driven tool selection within T11 budgets, citations still validated | Demonstrates budgets + T7 guardrails live; never the room default. |

**Deliberately not used:** LangChain / LlamaIndex (dependency surface without benefit here);
AgentCore Runtime, Memory, and Policy in the lab path (D6 — receipts already persist state;
the Policy-vs-`acl_visible` division of labor stays a talk slide); AgenticRetrieveStream
(the positioning contrast, Section 12); OpenSearch / S3 Vectors (the single-engine claim).

## 8. Surface A — the guide (tab 1)

Workshop Studio contentspec; pages map 1:1 to acts.

```
00-setup             tabs (order = lab order, Law 3), READINESS.md check
10-lab1-incident     change ticket → ./incident.sh → monitor → watch.sql moments
                     [checkpoint: "blocked writers ≥ 5 and reads still return"]
                     → DBI deep link → three checks (Section 5.2)
                     [checkpoint: blocking pid in the lock tree matches pg_blocking_pids]
                     → back to tab 2: ./resolve.sh → ./fix.sh → before/after plan
                     [checkpoint: Index Scan, indisvalid = true]
20-lab2-hybrid       Law 4 sentence → deep link to /overview → verify-in-psql beat →
                     archetypes: exact-change → fuzzy-change-id → semantic-symptom →
                     fusion controls (k, weights, rerank toggle)
                     [checkpoint: RRF for CHG-1842 recomputed in psql matches the panel]
30-lab3-agentic      one question → six tools in order (planned mode, Section 7 T2) →
                     cited answer → customer-impact + principal flip (ACL) →
                     evidence graph
                     [checkpoint: support-lead adds CASE-7421; workshop shows nothing]
40-lab4-proof        run proof → replay by run_id (zero model calls) →
                     DBI hand-off links (Section 6.3) → live-capture stretch (flag, Section 4.6)
                     [checkpoint: replayed run_id resolves identical candidates]
                     → FINAL CHECKPOINT (D18): install skills/aurora-hybrid-retrieval in
                     Claude Code on this host; run its first assertion → green
50-stretch           agent free mode (Section 7 T12) · attach an MCP client to verity-mcp (Section 7 T5) ·
                     M5: flip to AgentCore Gateway and diff the receipts (D15, flag) ·
                     CIC INVALID demo (fix.sh --demo-invalid) · eval harness
90-appendix          full watch.sql, reset.sh, DBI-outage fallback path, cut-ladder
```

Every psql snippet in the guide is generated from the repo files at build time (single
source; gate G-12). Checkpoints are copy-pastable one-liners that print `OK` or a remedy.

### Run-of-show (45-min lab; talk precedes with concept screens per D5)

```
 0:00  setup — tabs, readiness check                          (Shayon)
 3:00  LAB 1  INCIDENT & OBSERVABILITY
              trigger + monitor + watch.sql                   (Shayon)
 9:00         DBI: waits → lock tree → plans                  (DBI lead)
15:00         resolve + CIC + before/after                    (DBI lead → Shayon)
19:00  LAB 2  HYBRID RETRIEVAL
              Law-4 line; verify-in-psql beat;
              exact / fuzzy / semantic; fusion                (Shayon + audit)
28:00  LAB 3  AGENTIC RETRIEVAL
              one question, six tools, citations;
              ACL flip; evidence graph                        (Shayon)
36:00  LAB 4  PROOF & REPLAY
              run proof; replay; DBI hand-off;
              live-capture stretch (flag)                     (Shayon + audit)
43:00  close — takeaway: repo + the aurora-hybrid-retrieval skill (D17);
       cut-ladder content dropped silently if late (D9)
```

### Talk skeleton (15 min, precedes the lab; assets = concept screens + slides)

```
 0:00  thesis — Aurora as the retrieval engine of record (concept screens)   (Shayon)
 3:00  the incident pattern + lock theory teaser                             (DBI lead)
 6:00  hybrid arms + weighted RRF; the ablation slide (Eval screen)          (Shayon)
 9:00  positioning — compose vs replace: AgenticRetrieveStream
       replaces the engine (slide); AgentCore Gateway composes
       with it (module M5) · Policy-vs-acl_visible one-liner                 (Shayon)
11:00  E4 — ReplicaLag is page-cache lag (new public material)               (DBI lead)
13:00  what the lab will do; four tabs; Optimized Reads appendix pointer
```

Pre-answered FAQ carried in speaker notes: why exact folds into the lexical arm rather
than a fourth RRF arm; the rerank-worth-it ablation; Embed v4's 1536-d default → 1024
pinning; the Aurora pgvector version posture (0.8.1 vs the 0.8.3 vacuum fix — tracked
risk, not a stage claim).

---

## 9. Failure modes & fallbacks

| Failure | Detection | Fallback |
|---|---|---|
| Bedrock throttled at room scale | synth/rerank errors | Replay by `run_id` (smoke run from S8) — zero model calls; guide's replay page is the same page |
| DBI console inaccessible (IAM/region) | participant report | `watch.sql` covers all three checks in tab 2; facilitator screen-shares one working console |
| Build finishes < 240 s (calibration drift) | incident.sh timer | `reset.sh && ORDER_ROWS=+50% re-seed` is too slow live → facilitator uses prime-run DBI history for the Lab 1 DBI segment; participant re-triggers with `INCIDENT_TTL` floor honored |
| Participant wedged / lost state | any | `reset.sh` (idempotent), rejoin at current guide page |
| Live capture fails (D7) | capture exit ≠ 0 | Flag off; Labs 3–4 unchanged (default posture anyway) |
| Gateway module fails to provision (M5) | S8 assertion | Flag forced to 0 by bootstrap; stdio MCP stretch unaffected; M5 becomes a take-home |
| Workbench backend down | health check in guide | `systemctl restart verity-workbench`; all Lab 2–4 content also reachable via psql (Law 2) — degraded but truthful |

### Pre-doors checklist (facilitator)

`gates/checks.sh` green · READINESS.md green with build_seconds inside the G-6 range ·
deep links resolve under the **participant** role · smoke run_id replays with zero model
calls · DBI shows prime-run history and the reads digest · loadgen TPS visible ·
`reset.sh` exercised once · flags at defaults (`VERITY_LIVE_CAPTURE=0`,
`VERITY_AGENT_MODE=planned`) · floor roles assigned by name (D10: F1 resets · F2 DBI/IAM ·
F3 flags + last-resort cluster) · one facilitator cluster held mid-incident as the
demo-of-last-resort.

---

## 10. Gates (numbered, testable; extend the Hybrid Retrieval Workbench release-gate list)

- **G-1** Target Aurora engine + pgvector version pinned; `iterative_scan` accepted and
  effective (not the <0.8 silent-WARNING trap) — asserted in S1.
- **G-2** DBI Advanced + both parameters verified via `SHOW` post-bootstrap; actual (not
  estimated) plans confirmed visible in console during dry run.
- **G-3** Deep links resolve for a **participant-role** session in the target region.
- **G-4** Prime run leaves visible artifacts: Lock:relation spike in DB load history; reads
  digest present in Top SQL.
- **G-5** incident.sh full cycle unattended: trigger → ≥ 5 blocked writers → deadman cancel →
  writers recover → exit 0 → no index left.
- **G-6** Calibration: 240 s ≤ build_seconds ≤ 420 s on the target instance class.
- **G-7** After S6/S7/reset.sh: `idx_orders_customer` does not exist; no INVALID indexes.
- **G-8** resolve.sh + fix.sh cycle: CIC completes, `indisvalid`, before/after plans show
  Seq Scan → Index Scan on the reads digest.
- **G-9** Reads never stall during incident (pgbench reads TPS > 0 throughout G-5).
- **G-10** Participant IAM: Section 5.2's three checks performed with the participant role only.
- **G-11** Law 1 lint: grep across guide/scripts/fixtures for a canonical-noun list; any
  synonym ("checkout_orders", "cust_id", …) fails CI.
- **G-12** Guide snippets byte-identical to repo sources (build-time extraction).
- **G-13** Verify-SQL golden test: for the smoke run_id, execute every `_verify_sql` and
  diff against the API JSON — zero mismatches.
- **G-14** Empty-database UI test: workbench against a schema-only DB renders only empty
  states; the built frontend bundle contains no fixture numerals (denylist: `0.0650`,
  `94.8`, `12,011`, `48,226`, rerank scores, …).
- **G-15** Live capture (flagged): end-to-end on a rehearsal cluster — snapshot → projection
  ready ≤ 90 s → citable in a fresh answer.
- **G-16** Full dry run on a 13″ laptop at projector resolution, four tabs, timed against Section 8.
- **G-17** Registry drift: Strands specs, MCP schemas, and the Gateway OpenAPI regenerate
  from `agent/registry.py` in CI; any diff fails.
- **G-18** Transport parity: the golden question over in-process, HTTP, and stdio MCP with
  `rerank:false` yields identical normalized candidates and citations.
- **G-19** Guardrail test: free mode (T12) against a prompt urging early synthesis stays
  within `max_tool_calls`, never invokes `synthesize_cited_answer` twice or
  `explain_ranking` mid-plan.
- **G-20** Exclusives verified on the target engine during dry run: E1 (integer-division
  zero), E2 (filter-starved counterfactual), E3 (wait-event seam captured during a live
  incident), E6 (trigram plan pair) — outputs captured into the guide verbatim.
- **G-21** Fixture arithmetic (D14): `cgh-1842` returns **exactly one** candidate ≥ 0.30
  against the full corpus including the ~200-ID background, measured on the target engine;
  the assertion lives in the fixture generator, not in prose.
- **G-22** Gateway parity (M5, when flagged): the canonical question over Gateway MCP
  yields candidates and citations identical to the stdio/HTTP captures (`rerank:false`),
  and every exposed tool name matches the asserted `${targetName}___${toolName}` shape
  (closes open item 7).
- **G-23** Route contract (D16): every deep link in the guide resolves to its intended
  surface with state prefilled (preset, principal, run_id) — verified headlessly in CI
  and again on the dry-run laptop (feeds G-16).
- **G-24** Takeaway ladder (D18): the skill's four section headers match the four lab
  takeaway sentences byte-for-byte; the final-checkpoint assertion runs green on the
  dry-run host under the participant role; M1–M4 appear in the rehearsal timing sheet
  and survive the 35-minute cut rehearsal.

---

## 11. Only-here register (the exclusives)

Material participants will not find in any blog, doc narrative, or other session — because it
requires this session's design to exist. Three sources of exclusivity: (a) failures that only
occur when fusion runs *in the database*, (b) Aurora internals read through an incident the
participant caused, (c) evidence the participant created. Each row names its slot; anything
without a slot is cut, not "mentioned if there's time."

| # | Exclusive | Slot | Demo mechanic | Status |
|---|---|---|---|---|
| **E1** | **The naive-RRF zero**: `2/(60+r)` is integer division — the weighted term silently evaluates to 0 for every candidate | Lab 2 verify beat | Guide snippet: naive formula → all 0.00000 → cast one operand → real scores. Line: "this failure exists only because we fuse in-database — and so does the receipt that catches it." | verified on live engine |
| **E2** | **ef_search cannot beat a WHERE clause**: no ANN widening returns a row the filter excluded before the index was consulted (RB-017 has no cluster_id) | Lab 2→3 hinge | Workbench: runbook query under cluster filter; ef 40→200 → still 0; drop filter → rank 1. Counterfactual run persisted (RUN-7105 pattern). | design verified pass-2; demo via fixture |
| **E3** | **The engine seam of their own incident**: `Lock:relation` is community PostgreSQL; the commit path (`IO:XactSync`, `IO:AuroraStorageLogAllocate`) is Aurora | Lab 1, DBI-lead beat | wait_event capture during the incident → two-column readout "the Postgres half / the Aurora half" | events doc-verified; live capture = G-20 |
| **E4** | **ReplicaLag is page-cache lag**: the coldest reader reports the best lag while serving the worst HNSW latency — anti-signal for vector read scaling | Talk slide; optional reader demo | Slide from doc mechanics; measured demo only if a reader joins the environment `[VERIFY measured]` | doc-derived; no public write-up exists |
| **E5** | **Three memory tiers per plan node**: `aurora_orcache_hit` / `aurora_storage_read` in EXPLAIN — no other PostgreSQL has them; absence ≠ evidence (`with_buffers` off by default) | Lab 2 diagnostics drawer (Section 6.5) | Live EXPLAIN on NVMe class | doc-verified; rides open item 5 |
| **E6** | **The trigram index trap**: `WHERE similarity(k,q) > 0.30` cannot use the GIN index; `%` + `pg_trgm.similarity_threshold` can | Lab 2 fuzzy archetype | Two EXPLAINs: Seq Scan vs Bitmap Index Scan | verified (repair pass) |
| **E7** | **The silent ANN downgrade**: pgvector <0.8 accepts `hnsw.iterative_scan` as a WARNING, drops it, reverts to post-filtering; recall falls, nothing errors | Talk + G-1 shown firing | Demonstrate the bootstrap assertion as the moral: "the only defense is asserting the version" | verified pass-2 inventory |
| **E8** | **halfvec is mandatory, not an optimization**: 3072-d embeddings cannot be HNSW-indexed as `vector` (≤2000) | Talk/appendix | Dim-cap table + 4d+8 / 2d+8 storage math | doc-verified |
| **E9** | **A starved HNSW workload on Aurora looks idle**: memory-starved instance never exceeds ~15% CPU while the NVMe one runs ~95% | Appendix, labeled | Quoted BIGANN figures — explicitly *quoted, not reproduced* | quoted; reproduce only via gate-6 |
| **E10** | **Evidence you made**: the session's own lock snapshot becomes a citable source minutes later | Lab 4 stretch (Section 4.6) | capture → projection → citation with `workshop://live/...` URI | spec'd; G-15 |

## 12. Out of scope (this session)

Managed Knowledge Base federation; AgentCore Identity/Policy/Evaluations; AppFlow/Step
Functions live ingestion (frame-only slide); Automated Reasoning; Bedrock Data Automation;
RDS Proxy in the lab path (D6); Optimized Reads *claims* without gate-#6 measurements on
NVMe-class instances (r6gd/r8gd/r6id; tiered cache = I/O-Optimized clusters only).

## 13. Open items (resolve before content freeze)

1. Section 5.1 CLI flags + Advanced-mode pricing approval in Workshop Studio.
2. Section 5.2 lock-analysis history-vs-current behavior → straggler strategy.
3. Section 5.4 / Section 6.3 console URL formats + time-window params.
4. Section 5.3 minimal IAM action set.
5. **Instance class — RESOLVED by the Workshop Studio template: `db.r8g.xlarge`**
   (Graviton4, 4 vCPU / 32 GiB; allowed range `r8g.large`→`r8g.4xlarge`), storage
   `aurora-iopt1` (I/O-Optimized). This is a non-NVMe class, so Section 6.5's
   `aurora_orcache_hit` beat **stays appendix** — the hardware to demonstrate it is
   not provisioned (Optimized Reads needs an r*gd/r*id NVMe class; I/O-Optimized
   storage is a separate, orthogonal mode and does not surface `orcache_hit`).
   **G-6 calibration directive (S6, on the pinned class):** seed `shop.orders` at
   `ORDER_ROWS=25_000_000` as the starting point, keep the pinned build settings
   (`maintenance_work_mem=64MB`, `max_parallel_maintenance_workers=0` — never widen
   these to hit the window; `ORDER_ROWS` is the only knob), time the throwaway
   ordinary `CREATE INDEX`, and adjust `ORDER_ROWS` until `build_seconds` lands in
   240–420 s. On 4 vCPU + 64 MB sort memory the single-column bigint build may come
   in under 240 s at 25 M; expect to bump toward **40–50 M**. Record the final
   `ORDER_ROWS`, measured `build_seconds`, and `pg_table_size` in READINESS.md.
   These numbers are provisional until a dry run in a Workshop Studio account
   confirms them; the window is the acceptance criterion, not the row count. Expect
   an auditor to challenge the build time on stage, so the measured value must be
   reproducible from READINESS.md, not asserted.
6. Pin `strands-agents` and MCP SDK versions; re-verify tool-decorator and MCP client APIs
   at freeze (T1, T5).
7. Confirm current AgentCore Gateway tool-naming behavior (T6) before the appendix ships.
8. Request/verify Bedrock room-scale quotas for exactly three model IDs (D13): embed-v4,
   rerank-3-5, claude-sonnet-5 — and re-check the Sonnet lifecycle/ID at freeze.
9. Tab-4 exposure mechanism (Section 2.1): confirm the authenticated route to port 8000 in the
   Workshop Studio template.
10. Reader instance: the template provisions a single writer (no reader), so **E4
    stays a slide** unless a reader is added to the Workshop Studio template. Decide
    at freeze; graduating E4 to a measured demo requires the template change, not
    just a runtime flag.
11. Companion-asset fix: `verity-scale.html` instance options → NVMe classes
    (r6gd/r8gd/r6id) with the I/O-Optimized tiered-cache note, for E5/Section 6.5
    consistency. Note the distinction the asset must make clear: the deployed class
    (`r8g.xlarge`) is I/O-Optimized *storage* but not an Optimized *Reads* (NVMe)
    class — the scale story is the contrast, not the running cluster.
12. Takeaway skill (D17): author `skills/aurora-hybrid-retrieval/` at content freeze from
    the final guide + gates; confirm repo license/naming via the AWS sample-code process;
    verify the skill loads and triggers correctly in Claude Code on Bedrock.
13. D18 final checkpoint: confirm Claude Code (Bedrock mode) installs and invokes under
    the participant role inside Workshop Studio accounts; budget its Bedrock usage into
    the D13 quota request.
