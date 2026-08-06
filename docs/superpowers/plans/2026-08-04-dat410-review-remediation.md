# DAT410 Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every concern/gap raised by the 2026-08-03 comprehensive review of the DAT410 "Build agentic hybrid retrieval with Amazon Aurora PostgreSQL" builders session, across both the application repo and the sibling Workshop Studio content repo, so nothing is left for Grant McAlister's co-presented session to trip over.

**Architecture:** No new subsystems. This is a remediation pass: merge a ready branch, fix stale docs, add one payload-size guard, add one regression test, wire a local pre-push gate for the Aurora-only security gates, fix a `.gitignore` gap, and align two repos' release-boundary docs. Every fix targets the exact file/line the review identified; nothing here introduces new architecture.

**Tech Stack:** Python 3.13 (backend, gates, tests), PL/pgSQL (`sql/`), TypeScript/React (frontend, doc-comment only), Bash (git hook), Markdown (docs).

## Global Constraints

- Never fabricate or substitute fixture/canned/offline data into the participant path (`AGENTS.md`, `CLAUDE.md`). Every fix here is process/doc/guard-rail — none touches the live-data pipeline's behavior.
- `main` branch is the source-freeze boundary (`HANDOFF.md:9`); Workshop Studio's `contentspec.yaml`/CFN `SourceRevision` must always resolve on `main` after this plan.
- Commit style: imperative mood, ≤72-char subject, one logical change per commit (per user's global workflow steering). Do not amend or force-push. Do not commit secrets.
- `pg_columnmask` (used by `sql/12_masking.sql`) is an Aurora-only extension — it does not exist in a stock Postgres Docker image. Any new automated check for the security module must run against a real Aurora endpoint, not a CI service container.
- The user has a running Aurora cluster in `us-east-1` available for any step that needs a live database to test against (e.g., the new admission-payload-size guard, the security-checks git hook). Ask the user for its DSN via `.env`/`TEST_DATABASE_URL` when a task needs it rather than assuming a local Postgres will do.
- Two repos are in scope: `sample-agentic-hybrid-retrieval-aurora-postgresql` (this repo, branch `rls-personas-column-masking` → merges to `main`) and the sibling `/Users/shayons/Desktop/Workshops/build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql` (branch `mainline`) for Task 9 only.
- Decisions already made by the user (do not re-litigate): (1) merge `rls-personas-column-masking` into `main` now — the module is functionally complete; (2) the persona-authentication finding gets a **docs-only** fix, not a code auth gate — each participant owns an isolated AWS account and the persona switcher is a deliberate teaching device, not a real trust boundary; (3) the security-gates-before-merge gap gets a **local pre-push git hook**, not a cloud CI workflow — no secrets, no standing cluster dependency in CI.

---

### Task 1: Merge the RLS/masking branch into `main`

**Files:**
- No file changes — this is a git merge operation.

**Interfaces:**
- Produces: `main` at commit `aedceb8` (or a merge commit containing it), matching the `SourceRevision` already pinned in the sibling Workshop Studio repo's `contentspec.yaml:90` and `static/hybrid-retrieval-main.yml:90`.

This closes the blocker finding: Workshop Studio's `SourceRevision` (`aedceb88726e3e0b21d02e60327e9daeea6586d9`) is not an ancestor of `main` (verified: `git merge-base --is-ancestor aedceb8 main` fails). `main` (`0efd460`) is a strict ancestor of `rls-personas-column-masking` (`aedceb8`) — confirmed via `git merge-base --is-ancestor main rls-personas-column-masking` returning true — so this is a pure fast-forward, not a three-way merge. No conflict resolution is possible or needed.

- [ ] **Step 1: Confirm the working tree is clean and re-verify the fast-forward relationship**

```bash
git status
git fetch origin
git merge-base --is-ancestor main rls-personas-column-masking && echo "fast-forward OK"
git merge-base --is-ancestor aedceb8 main && echo "ALREADY MERGED (stop, nothing to do)" || echo "not yet merged (expected)"
```

Expected: working tree clean (except the pre-existing untracked `mockups/`, which Task 8 handles separately), "fast-forward OK", and "not yet merged (expected)".

- [ ] **Step 2: Fast-forward `main` to the branch tip**

```bash
git checkout main
git merge --ff-only rls-personas-column-masking
```

Expected: `Fast-forward` message, `main` now at `aedceb8`. If git refuses with "not possible to fast-forward", stop — `main` has diverged since the review and this needs manual investigation, not a forced merge.

- [ ] **Step 3: Verify `main` now contains the commit Workshop Studio expects**

```bash
git log main -1 --oneline
git merge-base --is-ancestor aedceb8 main && echo "CONFIRMED: aedceb8 is now on main"
```

Expected: `aedceb8 Prepare live workload and workshop release`, then the confirmation line.

- [ ] **Step 4: Push `main`**

```bash
git push origin main
```

Note: this pushes directly to `main` without a PR — acceptable here because `HANDOFF.md:9` explicitly designates this repo's `main` as a branch where "source commit and push may use Shayon's configured GitHub credentials" (i.e., the user, not a generic contributor, owns this boundary). Confirm with the user before running this specific command if there is any doubt, since it is a push to the shared branch.

No test step: this task is a pure ref-move with no code change, so there is nothing to unit-test. Task 2 (doc fix) and the existing `make doctor`/`gates/checks.sh` runs later in this plan are what verify `main` is in a good state post-merge.

---

### Task 2: Fix stale release-boundary and architecture docs in the app repo

**Files:**
- Modify: `docs/architecture.md:96-103`
- Modify: `docs/data-model.md:143-149`

**Interfaces:**
- Consumes: nothing (pure prose edits).
- Produces: nothing consumed by later tasks — these are terminal doc fixes.

This closes the medium finding that `docs/architecture.md` and `docs/data-model.md` still say RLS/masking is "outside this workshop", written before the `4570dda` module existed. `docs/builder-session-flow.md:25,173-175` already describes the optional lab correctly and needs no change.

- [ ] **Step 1: Fix `docs/architecture.md`**

Current text (`docs/architecture.md:96-103`):

```markdown
## Participant Mode

The workshop path is live incident retrieval through cited synthesis,
diagnostics, and replay. `make schema` applies the core schema and the API uses
the participant database directly. The corpus contains no authored restricted
records, so role comparison, masking, and fictional access-control exercises
are outside this workshop.
```

Replace with:

```markdown
## Participant Mode

The workshop path is live incident retrieval through cited synthesis,
diagnostics, and replay. `make schema` applies the core schema and the API uses
the participant database directly. The corpus contains no authored restricted
records: every restricted row a persona can compare against is produced by
that participant's own `make live-workshop` capture, never a fictional one.

An event owner may additionally run `make security-schema` to enable the
optional RLS and column-masking lab (`sql/11_roles_rls.sql`,
`sql/12_masking.sql`) against that same live capture. It adds real
role-based visibility comparison on top of the required path; it does not
replace the fixed workshop visibility predicate the required path always
uses. See `docs/builder-session-flow.md` for when it is offered.
```

- [ ] **Step 2: Fix `docs/data-model.md`**

Current text (`docs/data-model.md:143-149`):

```markdown
hop; it requires no persona role or RLS installation.

Production identity, RLS, and masking remain architecture concerns, not
participant demonstrations. The live workshop corpus contains no authored
restricted customer record, and the API's workshop context is not production
authentication.
```

Replace with:

```markdown
hop; it requires no persona role or RLS installation.

Production identity and authorization revalidation remain architecture
concerns, not participant demonstrations: the API's workshop context is not
production authentication, and its persona selection is a teaching control
under the API caller's own AWS account, not an access-control boundary
between separate identities. The live workshop corpus contains no authored
restricted customer record. An event owner may enable `sql/11_roles_rls.sql`
and `sql/12_masking.sql` as an optional lab so a participant can compare
real RLS/masking visibility against that same live capture from inside the
persona they select.
```

- [ ] **Step 3: Confirm no other doc repeats the stale framing**

```bash
grep -rn "outside this workshop\|not participant demonstrations" docs/*.md README.md AGENTS.md
```

Expected: no matches (both instances were just rewritten). If any remain, apply the same correction pattern.

- [ ] **Step 4: Commit**

```bash
git add docs/architecture.md docs/data-model.md
git commit -m "Describe the optional RLS lab in architecture and data-model docs"
```

---

### Task 3: Disclose the persona switcher as a teaching device, not authentication

**Files:**
- Modify: `README.md:295-300` (Security section)
- Modify: `frontend/src/WorkbenchApp.tsx:3492-3494` (JSX comment only, no behavior change)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing consumed by later tasks.

This is the user-approved docs-only fix for the persona-authentication finding. `backend/app/db.py:35` (`validate_persona`'s docstring, "Validate receipt metadata without treating it as authentication") and `docs/data-model.md` (just updated in Task 2) already disclose this at the code/architecture-doc layer. This task adds the same disclosure where a reader is most likely to actually encounter the control: the top-level `README.md` Security section, and the JSX comment right above the "Viewing as" persona switcher so a future contributor editing that component sees it inline.

- [ ] **Step 1: Extend the README Security section**

Current text (`README.md:295-300`):

```markdown
## Security

The repository commits no credentials, customer data, generated captures, or
model outputs. The frontend calls only the configured API, retrieval applies
the fixed workshop visibility predicate before ranking and traversal, and the
application fails closed when required live evidence is unavailable.
```

Replace with:

```markdown
## Security

The repository commits no credentials, customer data, generated captures, or
model outputs. The frontend calls only the configured API, retrieval applies
the fixed workshop visibility predicate before ranking and traversal, and the
application fails closed when required live evidence is unavailable.

The optional RLS/masking lab's persona selector (`?role=app_engineer|dba|auditor`)
is a teaching control, not an authentication boundary: each participant owns
their own isolated Workshop Studio account and database, so selecting a
persona only changes what that participant's own request can see inside
their own capture. It is not a substitute for a real identity provider in any
deployment where the API is reachable by more than one caller.
```

- [ ] **Step 2: Add an inline comment above the persona switcher in the frontend**

Read the current code at `frontend/src/WorkbenchApp.tsx:3486-3494`:

```tsx
      {personaMode ? (
        <div className="persona-chip">
          <span className="section-label">Viewing as</span>
          <div className="segmented" role="group" aria-label="Viewing as">
            {PERSONA_KEYS.map((key) => (
              <button
```

Add a comment immediately before the `{personaMode ? (` line:

```tsx
      {/* Teaching control, not an auth boundary: each participant's own
          request selects its own persona inside their own isolated account.
          See README.md "Security". */}
      {personaMode ? (
        <div className="persona-chip">
          <span className="section-label">Viewing as</span>
          <div className="segmented" role="group" aria-label="Viewing as">
            {PERSONA_KEYS.map((key) => (
              <button
```

- [ ] **Step 3: Confirm the frontend still builds**

```bash
cd frontend && npm run build
```

Expected: `tsc` and `vite build` both succeed with no new errors (a comment-only change cannot break type-checking, but this confirms no stray syntax slip).

- [ ] **Step 4: Commit**

```bash
git add README.md frontend/src/WorkbenchApp.tsx
git commit -m "Disclose the persona selector as a teaching control, not authentication"
```

---

### Task 4: Fix the `.gitignore` gap for local design mockups

**Files:**
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing consumed by later tasks.

`git check-ignore -v mockups/dat410-a-ledger.html` currently exits `1` (not ignored) because the rule added in `a68df3d` targets the now-nonexistent path `/design/verity-html-mockups/`, while the actual local-only mockup HTML files live in `/mockups/` at repo root. `HANDOFF.md:100` already says "Do not commit ... `mockups/`" as a policy statement, but nothing enforces it. Content was confirmed harmless (placeholder IDs like `INC-LIVE-001`, distinct from the real `INC-<run-suffix>` format — no live-data leakage risk), but a stray `git add -A` would still commit local design work to a public `aws-samples` repo.

- [ ] **Step 1: Confirm current gitignore miss**

```bash
git check-ignore -v mockups/dat410-a-ledger.html; echo "exit:$?"
```

Expected: exit code `1` (not ignored) — reproducing the gap before the fix.

- [ ] **Step 2: Update the design-mockups gitignore rule**

Read `.gitignore` around the existing rule (currently reads, per the diff in `a68df3d`):

```gitignore
# Design packaging archives: build artifacts, not source
/design/verity-html-mockups/
/design/*.zip
```

Replace the first line of that block with a rule matching the actual current path, keeping the existing `/design/*.zip` line untouched:

```gitignore
# Design packaging archives: build artifacts, not source
/mockups/
/design/*.zip
```

- [ ] **Step 3: Confirm the fix**

```bash
git check-ignore -v mockups/dat410-a-ledger.html; echo "exit:$?"
git status --porcelain
```

Expected: exit code `0` (now ignored), and `git status --porcelain` no longer lists `?? mockups/`.

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "Ignore the current local mockups path, not the retired one"
```

---

### Task 5: Add a payload-size guard to `evidence.admit_evidence`

**Files:**
- Modify: `sql/10_admission.sql:29-80` (function header/validation block)
- Test: `backend/tests/test_admission.py` (new test in `AdmitEvidenceTest`)

**Interfaces:**
- Consumes: `evidence.admit_evidence(payload jsonb)` — existing `SECURITY DEFINER` function signature, unchanged.
- Produces: same signature and return shape (`jsonb` receipt), now additionally raising `RAISE EXCEPTION 'admission: payload exceeds N bytes' USING ERRCODE = '22023'` for an oversized payload, in the same style as the function's other validation errors (e.g. `sql/10_admission.sql:82-86`).

This closes the low-medium finding: `admit_evidence` is a `SECURITY DEFINER` entry point reachable by the low-privilege `workshop_participant`/`workshop_app` login, taking an arbitrary-shaped `jsonb` payload with no size cap before it's parsed and looped over in PL/pgSQL — a resource-exhaustion vector even though there's no SQL-injection vector (confirmed: all access uses `#>>`/`#>` jsonb operators, never string-built SQL).

A verified live run (`READINESS.md`, capture `478FD535`) produced 110 documents/chunks and 735 raw telemetry rows; the acceptance bounds in `DAT410-BUILD-BRIEF.md` cap this at 100-250 chunks and 600-1,000 raw rows. Set the cap generously above that (2 MB) so it can never reject a legitimate live capture, while still bounding worst-case memory/CPU spent parsing a malicious payload.

- [ ] **Step 1: Write the failing test**

Add this test method to the `AdmitEvidenceTest` class in `backend/tests/test_admission.py`, near `test_invalid_bundle_rolls_back_every_record` (around line 342):

```python
    def test_oversized_payload_is_rejected_before_parsing(self) -> None:
        oversized = self._payload_copy()
        # Pad well past the 2 MB guard with an inert top-level field; the
        # function must reject this before it touches any real record.
        oversized["_padding"] = "x" * (3 * 1024 * 1024)

        with self.assertRaises(psycopg.errors.InvalidParameterValue):
            self._admit(oversized)
        self.assertEqual(
            self.connection.execute(
                "SELECT count(*) FROM evidence.evidence_items"
            ).fetchone()[0],
            0,
        )
```

- [ ] **Step 2: Run the test to verify it fails**

This suite requires a live-capture payload fixture. Point it at the user's Aurora cluster in `us-east-1`:

```bash
export TEST_DATABASE_URL="<the Aurora us-east-1 DSN, database name must end in _test>"
export ALLOW_TEST_DATABASE_RESET=1
export LIVE_CAPTURE_PAYLOAD="<path to a captured live payload JSON — run `make live-workshop` once against a disposable database first if none exists yet>"
export LIVE_CAPTURE_RUN_ID="<the capture_id from that same run>"
.venv/bin/python -m unittest backend.tests.test_admission.AdmitEvidenceTest.test_oversized_payload_is_rejected_before_parsing -v
```

Expected: **FAIL** — no exception is currently raised for an oversized payload (the assertRaises block does not trigger, or the function successfully admits the padded payload).

- [ ] **Step 3: Add the size guard to `evidence.admit_evidence`**

In `sql/10_admission.sql`, immediately after the function's opening `BEGIN` and before the first existing validation (`IF payload ->> 'schema' IS DISTINCT FROM ...` at line 81), add:

```sql
BEGIN
  IF pg_column_size(payload) > 2 * 1024 * 1024 THEN
    RAISE EXCEPTION 'admission: payload exceeds 2 MB (got % bytes)',
      pg_column_size(payload)
      USING ERRCODE = '22023';
  END IF;
  IF payload ->> 'schema' IS DISTINCT FROM 'admission payload v1' THEN
```

(This inserts one new `IF` block directly above the existing `IF payload ->> 'schema' ...` check; every line after it is unchanged.)

- [ ] **Step 4: Apply the updated schema to the test database**

```bash
DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/python backend/scripts/run_sql.py --files sql/00_extensions.sql sql/01_schema.sql sql/02_indexes.sql sql/03_search_functions.sql sql/09_traverse_evidence.sql sql/10_admission.sql
```

Expected: `Committed 6 SQL file(s) in one transaction`, `Done`.

- [ ] **Step 5: Run the test to verify it passes**

```bash
.venv/bin/python -m unittest backend.tests.test_admission.AdmitEvidenceTest.test_oversized_payload_is_rejected_before_parsing -v
```

Expected: **PASS**.

- [ ] **Step 6: Run the full admission test class to confirm no regression**

```bash
.venv/bin/python -m unittest backend.tests.test_admission -v
```

Expected: all existing tests in `test_admission.py` still PASS — the 2 MB threshold must not reject the real captured payload used by every other test in this file (it won't: a real capture is a few hundred KB at most, per the documented 100-120 document / 600-1,000 raw-row bounds).

- [ ] **Step 7: Commit**

```bash
git add sql/10_admission.sql backend/tests/test_admission.py
git commit -m "Cap evidence.admit_evidence payload size before parsing"
```

---

### Task 6: Prevent silent reversion of persona-aware ACL visibility on re-apply

**Files:**
- Modify: `sql/11_roles_rls.sql:170-198` (add a guard comment + a defensive re-assertion)
- Modify: `Makefile:64-68` (`security-schema` target)

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing consumed by later tasks.

This closes the low finding: `sql/03_search_functions.sql` and `sql/11_roles_rls.sql` both define `retrieval.acl_visible`/`retrieval.acl_scalars_visible` with `CREATE OR REPLACE FUNCTION` over the same signature. Running `make schema` (core files only) after `make security-schema` silently reverts these two functions to their non-persona-aware core definitions, because `make schema`'s `CORE_SQL_FILES` includes `sql/03_search_functions.sql`. The RLS *policies* themselves (`sql/11_roles_rls.sql:511-536`) don't call these functions and stay correct either way, but the two independently-defined "visible" predicates are a drift risk a future edit could desynchronize. The fix is operational, not a schema redesign: make `make security-schema` self-healing (it already re-applies `sql/11`/`sql/12` after the core files, so simply running it again fixes the drift) and make the risk visible where a maintainer would look.

- [ ] **Step 1: Add a guard comment directly above the redefinition in `sql/11_roles_rls.sql`**

Current text at `sql/11_roles_rls.sql:170` (immediately before `CREATE OR REPLACE FUNCTION retrieval.acl_visible`):

Find the line before it — likely a section header comment. Add this comment block immediately before `CREATE OR REPLACE FUNCTION retrieval.acl_visible(`:

```sql
-- DRIFT HAZARD: this CREATE OR REPLACE targets the same signature as the core
-- definition in sql/03_search_functions.sql. Re-running `make schema` alone
-- after `make security-schema` silently reverts this function (and
-- acl_scalars_visible below) to the core, non-persona-aware version -- same
-- signature, so no error, just a quiet loss of the can_see_restricted
-- disjunct. The RLS policies below do not call this function and stay
-- correct regardless, but any other caller of retrieval.acl_visible()/
-- acl_scalars_visible() would silently lose persona-aware visibility. If
-- you suspect this has happened, just re-run `make security-schema` -- it
-- reapplies this file last and is idempotent.
CREATE OR REPLACE FUNCTION retrieval.acl_visible(
```

- [ ] **Step 2: Make the `Makefile` comment on `security-schema` state the same risk explicitly**

Current text (`Makefile:59-63`):

```makefile
# Optional module: enforce evidence access with PostgreSQL RLS and column
# masking. Applies the core files first so the policies land on the current
# schema, then sql/11 and sql/12. Run this against the database that already
# holds a completed `make live-workshop` run: both files read real captured
# evidence to decide what is restricted.
security-schema:
```

Replace with:

```makefile
# Optional module: enforce evidence access with PostgreSQL RLS and column
# masking. Applies the core files first so the policies land on the current
# schema, then sql/11 and sql/12. Run this against the database that already
# holds a completed `make live-workshop` run: both files read real captured
# evidence to decide what is restricted.
#
# sql/11 redefines retrieval.acl_visible/acl_scalars_visible over the same
# signature the core sql/03 defines. If you run `make schema` alone after
# this target, those two functions silently revert to their core definition.
# Re-run `make security-schema` (this target) to restore them; it is
# idempotent.
security-schema:
```

- [ ] **Step 3: Verify gate G-31 (persona equivalence) would catch this class of drift**

```bash
WORKBENCH_SECURITY_ENABLED=1 .venv/bin/python gates/persona_equivalence.py
```

Run this against a database that has `make security-schema` applied (the Aurora `us-east-1` cluster, after Task 5's schema application, satisfies this). Expected: `PASS` (exit 0) — confirming G-31 is a real, currently-passing gate on the merged `main` state, not a stale claim. This is a read-only verification step; no code change results from it.

- [ ] **Step 4: Commit**

```bash
git add sql/11_roles_rls.sql Makefile
git commit -m "Document the acl_visible redefinition drift hazard and its fix"
```

---

### Task 7: Add a pre-push git hook gating the security module on `make security-checks`

**Files:**
- Create: `scripts/git-hooks/pre-push`
- Modify: `README.md:128-138` (Prerequisites section — add one setup step)

**Interfaces:**
- Consumes: `make security-checks` (existing Makefile target, `Makefile:73-74`), which requires `WORKSHOP_APP_DATABASE_URL`/`WORKSHOP_PARTICIPANT_DATABASE_URL` to be set (per `.env.example:7-17`) and a database that already has `make security-schema` applied.
- Produces: a `scripts/git-hooks/pre-push` script a contributor opts into via `git config core.hooksPath scripts/git-hooks`.

This closes the medium finding: security-module tests/gates are opt-in (`WORKBENCH_SECURITY_ENABLED=0` by default) with nothing structurally forcing them to run before a push that touches `sql/11`/`sql/12`. Per the user's decision, this is a **local pre-push hook**, not cloud CI — no secrets in a shared pipeline, no standing cluster dependency for the OSS repo's automation. The hook only activates when the push actually touches the security-module files, so it costs nothing on unrelated pushes, and it reads Aurora connection details from the contributor's own `.env`/shell environment exactly like every other `make` target in this repo already does.

- [ ] **Step 1: Write the hook script**

Create `scripts/git-hooks/pre-push`:

```bash
#!/usr/bin/env bash
# Pre-push gate: if this push touches the optional RLS/masking module, require
# `make security-checks` to pass first. pg_columnmask (sql/12_masking.sql) only
# exists on Aurora PostgreSQL, so this cannot run as a stock CI service
# container -- it runs locally, against whatever Aurora endpoint the
# contributor's .env/shell already points WORKSHOP_APP_DATABASE_URL and
# WORKSHOP_PARTICIPANT_DATABASE_URL at (see .env.example).
#
# Install with: git config core.hooksPath scripts/git-hooks
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

remote="$1"
range_check=""
while read -r local_ref local_sha remote_ref remote_sha; do
  if [[ "$local_sha" == "0000000000000000000000000000000000000000" ]]; then
    continue # deleting a ref; nothing to diff
  fi
  if [[ "$remote_sha" == "0000000000000000000000000000000000000000" ]]; then
    base="$(git merge-base "$local_sha" origin/main 2>/dev/null || echo "$local_sha^")"
  else
    base="$remote_sha"
  fi
  range_check+="$base..$local_sha "
done

if [[ -z "$range_check" ]]; then
  exit 0
fi

touched="$(git diff --name-only $range_check -- sql/11_roles_rls.sql sql/12_masking.sql | head -1)"
if [[ -z "$touched" ]]; then
  exit 0
fi

echo "pre-push: this push touches the RLS/masking module (sql/11 or sql/12)."
echo "pre-push: running 'make security-checks' before allowing the push..."
if ! make security-checks; then
  echo
  echo "pre-push BLOCKED: 'make security-checks' failed. Fix the failing gate" >&2
  echo "(G-27/G-29/G-30/G-31) before pushing, or push with --no-verify if you" >&2
  echo "are certain this failure is unrelated (not recommended)." >&2
  exit 1
fi

echo "pre-push: security checks passed."
exit 0
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x scripts/git-hooks/pre-push
```

- [ ] **Step 3: Document opt-in installation in the README**

Current text (`README.md:128-138`, Prerequisites section, ending before "## Prepare the Live Environment"):

```markdown
## Prerequisites

- Python 3.13+
- Node.js 20.19+
- PostgreSQL 18.3+ with `vector` 0.8.1+, `pg_trgm`, and
  `pg_stat_statements`
- For the workshop path, Aurora PostgreSQL and AWS credentials in `us-east-1`
- Bedrock access to the configured embedding, reranking, and synthesis models

This repository owns application source. The sibling Workshop Studio repository
owns Aurora, VPC, IAM, Code Editor, AgentCore Gateway, and source packaging.
```

Add immediately after that paragraph, still before `## Prepare the Live Environment`:

```markdown
If you will edit `sql/11_roles_rls.sql` or `sql/12_masking.sql`, install the
local pre-push hook so a push touching either file cannot land without
`make security-checks` passing against your Aurora endpoint first:

```bash
git config core.hooksPath scripts/git-hooks
```

`pg_columnmask` is Aurora-only, so this check runs locally against your own
cluster rather than in CI. It only activates on pushes that touch those two
files; every other push is unaffected.
```

- [ ] **Step 4: Verify the hook activates correctly on a touching change and skips on a non-touching one**

```bash
git config core.hooksPath scripts/git-hooks
git log -1 --oneline -- sql/12_masking.sql
touch sql/12_masking.sql && git diff --name-only -- sql/11_roles_rls.sql sql/12_masking.sql
```

This confirms the `git diff --name-only ... -- sql/11_roles_rls.sql sql/12_masking.sql` filter used inside the hook correctly identifies touching changes (manual dry run of the hook's core logic, since actually pushing requires a real push event). Expected: the second command lists `sql/12_masking.sql`, proving the path filter matches. Revert the `touch` before committing:

```bash
git checkout -- sql/12_masking.sql
```

- [ ] **Step 5: Commit**

```bash
git add scripts/git-hooks/pre-push README.md
git commit -m "Add an opt-in pre-push hook gating security-module pushes on make security-checks"
```

---

### Task 8: Delete the orphaned embedding artifact and clean up local hygiene

**Files:**
- Delete: `data/generated/incident-lab/participant-embeddings.jsonl`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

This closes the low-severity dataset-review finding: this file doesn't match any current cache-naming convention (`embeddings-<run_suffix>.jsonl`, per `labs/incident/run_live_workshop.py:1491`), isn't referenced by any code path, is already gitignored (`.gitignore:30`, `/data/generated/`), and would already be rejected by `scripts/build_live_source_archive.sh:71-87` if it ever ended up in a packaged archive. It's a stale local artifact from an earlier script version; delete it as ordinary local cleanup.

- [ ] **Step 1: Confirm the file is genuinely unreferenced and gitignored before deleting**

```bash
git check-ignore -v data/generated/incident-lab/participant-embeddings.jsonl
grep -rn "participant-embeddings" --include="*.py" --include="*.sh" --include="*.md" . 2>/dev/null | grep -v node_modules
```

Expected: the first command confirms it's gitignored (exit 0, showing the `/data/generated/` rule); the second returns no matches, confirming nothing references this filename.

- [ ] **Step 2: Delete it**

```bash
trash data/generated/incident-lab/participant-embeddings.jsonl
```

(Per the user's global workflow steering: use `trash`, not `rm -rf`, for destructive deletes.)

- [ ] **Step 3: Confirm cleanup**

```bash
ls data/generated/incident-lab/ 2>&1
```

Expected: either the directory is now empty/gone, or contains only current-run artifacts matching the `embeddings-<suffix>.jsonl` naming convention.

No commit needed — this file was never tracked by git (confirmed gitignored in Step 1), so there is nothing to stage or commit for this task.

---

### Task 9: Fix Workshop Studio repo timing/facilitator-scale gaps

**Files (in the sibling repo** `/Users/shayons/Desktop/Workshops/build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql`, branch `mainline`):
- Modify: `FACILITATOR_GUIDE.md`

**Interfaces:**
- Consumes: nothing from the app repo except the already-merged `main` state from Task 1 (this task's content describes behavior, it doesn't call any app-repo function).
- Produces: nothing consumed by later tasks.

This closes two review findings against the sibling repo: (1) no facilitator guidance on expected Lab 1 wall-clock time or Performance-Insights-publication latency risk, and (2) no cost/quota/model-access preflight guidance for a 30-100 participant fleet. Both are additions to `FACILITATOR_GUIDE.md`'s existing structure — no restructuring, matching that file's current terse style.

- [ ] **Step 1: Add a Lab 1 timing-risk note to the "60-minute path" section**

In `/Users/shayons/Desktop/Workshops/build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql/FACILITATOR_GUIDE.md`, immediately after the existing "60-minute path" table (which ends with the `00:58-01:00 | Summary and cleanup` row) and before the `## Event-owner preflight` heading, add:

```markdown
Lab 1's `make live-workshop` run includes up to a 5-minute wait for AWS
Performance Insights to publish the captured `Lock:relation` wait event and
its SQL text — on top of the deliberate ~60-second write stall, CloudWatch
collection, and a full Cohere Embed 4 batch through Bedrock for the run's
100-250 chunks. PI publication latency varies per account and is outside the
participant's control. During your dry run, record your own room's actual
median and worst-case Lab 1 wall-clock time here, and use the worst-case mark
(not the 15-minute budget alone) as your signal for when to start pairing
stragglers rather than waiting for them to fall further behind.
```

- [ ] **Step 2: Add a cost/quota/model-access preflight subsection**

Immediately after the existing `## Event-owner preflight` section's numbered list (which currently ends with item 7, "Confirm every returned key uses the receipt's suffix and every source URI belongs to its capture UUID.") and before `## Optional lab gate`, add:

```markdown
### Fleet-scale preflight (30-100 participants)

Before the event, in a throwaway participant account:

1. Confirm Bedrock model access for Cohere Embed 4, Cohere Rerank 3.5, and
   the configured Claude synthesis model is enabled in `us-east-1` for a
   *freshly vended* Workshop Studio account, not just your own long-lived
   AWS account. Model access can require a one-time per-account console
   grant; if it does, that grant must happen automatically at bootstrap or
   every participant's Lab 1 will fail at the embedding step.
2. Estimate per-account hourly cost (Aurora writer instance class, Code
   Editor instance, and the Bedrock calls one Lab-1 run makes) and multiply
   by your expected room size and event duration for the event owner's
   budget approval.
3. Check whether concurrent Bedrock embedding batches from every participant
   hitting `us-east-1` in the same 10-25 minute window risk any per-account
   or per-model throughput limit. If uncertain, request a quota increase or
   confirm the default is sufficient before the event, not during it.
```

- [ ] **Step 3: Verify the edits render correctly**

```bash
cd /Users/shayons/Desktop/Workshops/build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql
git diff FACILITATOR_GUIDE.md
```

Expected: a clean diff showing only the two additions above, no accidental disruption to the existing "Optional lab gate", "Recovery", or "Publishing gate" sections that follow.

- [ ] **Step 4: Commit** (in the sibling repo; per `HANDOFF.md:10`, Workshop Studio commit/push remains user-managed — confirm with the user before pushing, only commit locally here)

```bash
git add FACILITATOR_GUIDE.md
git commit -m "Add Lab 1 timing risk and fleet-scale preflight guidance"
```

---

### Task 10: Final verification pass

**Files:** none — this task only runs existing validation commands.

**Interfaces:** none.

This is the release-validation checklist from `HANDOFF.md:82-91`, run once at the end to confirm all prior tasks compose cleanly and nothing regressed.

- [ ] **Step 1: Run the app repo's full validation suite**

```bash
cd /Users/shayons/Desktop/Workshops/sample-agentic-hybrid-retrieval-aurora-postgresql
make doctor
make test
gates/checks.sh
cd frontend && npm run build && cd ..
git diff --check
```

Expected: `doctor` reports no failures against your Aurora endpoint; `test` passes (core suite; the destructive admission suite from Task 5 already ran directly against the Aurora `_test` database); `gates/checks.sh` (core gates only, `WORKBENCH_SECURITY_ENABLED=0` by default) reports `RESULT: GREEN`; frontend build succeeds; `git diff --check` reports no whitespace errors.

- [ ] **Step 2: Run the security gates explicitly (they are not in the default `gates/checks.sh` run)**

```bash
make security-checks
```

Expected: `RESULT: GREEN` — `FAIL_ON_BLOCKED=1` per the Makefile target, so this only passes if G-27/29/30/31 all genuinely ran and passed against your Aurora endpoint (with `make security-schema` already applied, from Task 5/6).

- [ ] **Step 3: Confirm the merge landed correctly end-to-end**

```bash
git log main -1 --oneline
git log origin/main -1 --oneline
```

Expected: both show `aedceb8` or a later commit that contains it (from Tasks 2-8's commits, which land on top of `main` after Task 1's fast-forward) — confirming the blocker finding from the review is resolved and pushed.

No commit for this task — it is verification only.
