-- sql/11_roles_rls.sql - workshop identities and RLS enforcement (D24, A1/A2/A7/A8).
--
-- Runs after every table it references exists. Idempotent: safe to re-run on a
-- cluster where some or all of these roles already exist, PROVIDED the role running
-- it holds ADMIN OPTION on them -- which the role that created them does, and which
-- section 1 asserts up front rather than discovering at the first GRANT. Roles are
-- CLUSTER-GLOBAL, so CREATE ROLE is guarded and never dropped here.
--
-- The identity model has exactly one axis: the persona. Data classification is a
-- stamp on the row (acl_visibility in {'workshop','restricted'}), never an identity.
--
--   can_see_restricted     NOLOGIN clearance group. A key, not a limitation:
--                          granted to DBA and Auditor, never to App Engineer.
--                          Additive grants fail closed; a subtractive marker
--                          would fail open.
--   persona_app_engineer  NOLOGIN persona. Workshop rows only.
--   persona_dba           NOLOGIN persona. All rows, unmasked.
--   persona_auditor       NOLOGIN persona. All rows, sensitive columns masked
--                          (sql/12_masking.sql).
--   workshop_app           LOGIN. The API pool identity. Owns nothing, holds NO
--                          direct table grants, is granted the personas WITH INHERIT
--                          FALSE. With no role set a SELECT raises permission denied:
--                          a forgotten SET ROLE fails CLOSED. This is why the pool
--                          must not be retrieval_admin: the owner holds
--                          can_see_restricted (granted below, so the seed and index
--                          build can index the whole corpus), and a pool holding
--                          the clearance key would serve restricted rows to everyone.
--   workshop_participant   LOGIN. The Lab terminal identity. Same INHERIT FALSE
--                          persona grants, EXECUTE on admission, pg_monitor for the
--                          watch snippets, and NO evidence SELECT: the permission
--                          denied on a bare evidence SELECT is the first lesson.

-- ---------------------------------------------------------------------------
-- 1. Roles.
-- ---------------------------------------------------------------------------

-- Preserve grants, memberships, and policy OIDs when upgrading an existing
-- deployment. ALTER ROLE ... RENAME changes the role name in place; creating a
-- second role would leave the old one attached to policies and default grants.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'persona_analyst') THEN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'persona_app_engineer') THEN
      RAISE EXCEPTION
        'both persona_analyst and persona_app_engineer exist; cannot choose which '
        'role owns the existing grants. Remove the unintended duplicate and re-run.';
    END IF;
    EXECUTE 'ALTER ROLE persona_analyst RENAME TO persona_app_engineer';
  END IF;

  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'persona_admin') THEN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'persona_dba') THEN
      RAISE EXCEPTION
        'both persona_admin and persona_dba exist; cannot choose which role owns '
        'the existing grants. Remove the unintended duplicate and re-run.';
    END IF;
    EXECUTE 'ALTER ROLE persona_admin RENAME TO persona_dba';
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'can_see_restricted') THEN
    CREATE ROLE can_see_restricted NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'persona_app_engineer') THEN
    CREATE ROLE persona_app_engineer NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'persona_dba') THEN
    CREATE ROLE persona_dba NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'persona_auditor') THEN
    CREATE ROLE persona_auditor NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'workbench_lab_owner') THEN
    CREATE ROLE workbench_lab_owner NOLOGIN;
  END IF;
END
$$;

-- The personas must never acquire LOGIN, even if an earlier build created them
-- differently. This is an ASSERTION, not an ALTER, for the same privilege reason as
-- the login-role assertion in section 3 below -- and here the reason is sharper.
-- ALTER ROLE requires CREATEROLE *plus* ADMIN OPTION on the target role, and PG16+
-- auto-grants ADMIN OPTION only to the role that CREATED it. So on the exact case
-- this block exists to defend -- the roles already exist, created by someone else --
-- `ALTER ROLE persona_app_engineer NOLOGIN` raises 42501 and aborts the file. Measured on
-- PG17 with a non-superuser owner and pre-existing personas:
--   ERROR: permission denied to alter role
--   DETAIL: Only roles with the CREATEROLE attribute and the ADMIN option on role
--           "persona_app_engineer" may alter this role.
-- The guarded CREATE above had correctly skipped them, so the "assert the invariant"
-- statement was the only thing that failed, and it failed on a CORRECT cluster.
-- The assertion needs no privilege, covers can_see_restricted the same way, and
-- names the offending role instead of the file that could not alter it.
DO $$
DECLARE
  v_bad text;
BEGIN
  SELECT string_agg(rolname, ', ' ORDER BY rolname)
    INTO v_bad
    FROM pg_roles
   WHERE rolname IN ('persona_app_engineer', 'persona_dba', 'persona_auditor',
                     'can_see_restricted')
     AND rolcanlogin;

  IF v_bad IS NOT NULL THEN
    RAISE EXCEPTION
      'these personas hold LOGIN: %. A persona is an assumable role, not an '
      'account: a LOGIN persona can be connected to directly, which skips the '
      'SET LOCAL ROLE envelope the whole enforcement story is told through. '
      'Run ALTER ROLE <name> NOLOGIN as a role holding ADMIN OPTION on it, then '
      're-run this file.', v_bad;
  END IF;
END
$$;

-- ADMIN OPTION precondition, checked ONCE here rather than guarded at each of the
-- 13 role-membership GRANTs below.
--
-- Granting a role requires ADMIN OPTION on that role, and PG16+ auto-grants it only
-- to the role that CREATED it. The guarded CREATE block above is therefore a trap on
-- a re-run by a DIFFERENT owner: it correctly skips the existing roles, and then
-- every GRANT below raises 42501. Measured on PG17, owner holding CREATEROLE but not
-- ADMIN OPTION, personas pre-created by another role:
--   ERROR: permission denied to grant role "can_see_restricted"
-- A REDUNDANT grant raises identically -- PG checks the privilege before noticing the
-- membership already exists -- so this is not merely a first-run concern. It breaks
-- the "safe to re-run" property this file's header claims.
--
-- Not a concern on the deploy target, and this states why rather than assuming it:
-- retrieval_admin creates these roles itself on the first `make schema`, and ADMIN
-- OPTION IS inherited through role membership (unlike the role ATTRIBUTES noted in
-- section 3). Measured read-only on the live cluster: retrieval_admin holds
-- ADMIN OPTION on pg_monitor and rds_superuser via its rds_superuser membership, so
-- `GRANT pg_monitor TO workshop_participant` below succeeds. The failing case is a
-- local or shared cluster where the roles outlived the owner that made them.
DO $$
DECLARE
  v_bad text;
BEGIN
  SELECT string_agg(r, ', ' ORDER BY r)
    INTO v_bad
    FROM unnest(ARRAY['can_see_restricted', 'persona_app_engineer', 'persona_dba',
                      'persona_auditor', 'workbench_lab_owner', 'pg_monitor']) AS r
   WHERE NOT pg_has_role(current_user, r, 'MEMBER WITH ADMIN OPTION');

  IF v_bad IS NOT NULL THEN
    RAISE EXCEPTION
      '% lacks ADMIN OPTION on: %. Every GRANT below would raise 42501, including '
      'a redundant one, so this file cannot complete as this role. These roles are '
      'CLUSTER-GLOBAL and outlive any one database: they were created by a different '
      'role. Either re-run as that role, or have a role holding ADMIN OPTION run '
      'GRANT <role> TO % WITH ADMIN OPTION, INHERIT FALSE for each. INHERIT FALSE '
      'matters: a plain grant would also hand this role the personas PASSIVELY, '
      'and section 2 grants them INHERIT FALSE precisely so the owner reads by '
      'clearance rather than by silently inheriting a persona.',
      current_user, v_bad, quote_ident(current_user);
  END IF;
END
$$;

-- The clearance key. Direction is the whole point: withhold the key from App
-- Engineer rather than marking that persona as limited.
GRANT can_see_restricted TO persona_dba;
GRANT can_see_restricted TO persona_auditor;

-- Upgrade the core workshop-only predicates to persona-aware visibility. These
-- signatures intentionally match sql/03 so applying `make security-schema`
-- changes policy behavior without changing any retrieval function contract.
CREATE OR REPLACE FUNCTION retrieval.acl_visible(
  p_acl jsonb,
  p_role name DEFAULT current_user
)
RETURNS boolean
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
  SELECT coalesce(p_acl ->> 'visibility', 'restricted') = 'workshop'
    OR pg_has_role(p_role, 'can_see_restricted', 'USAGE')
$$;

COMMENT ON FUNCTION retrieval.acl_visible(jsonb, name) IS
  'Optional persona-aware evidence visibility. USAGE honors the effective '
  'clearance role; MEMBER would ignore INHERIT.';

CREATE OR REPLACE FUNCTION retrieval.acl_scalars_visible(
  p_visibility text,
  p_role name DEFAULT current_user
)
RETURNS boolean
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
  SELECT coalesce(p_visibility, 'restricted') = 'workshop'
    OR pg_has_role(p_role, 'can_see_restricted', 'USAGE')
$$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
      FROM pg_auth_members m
      JOIN pg_roles grp ON grp.oid = m.roleid
      JOIN pg_roles mem ON mem.oid = m.member
     WHERE grp.rolname = 'can_see_restricted'
       AND mem.rolname = 'persona_app_engineer'
  ) THEN
    RAISE EXCEPTION
      'persona_app_engineer holds can_see_restricted; App Engineer would see '
      'restricted rows and the row-filtering demo is broken';
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 2. Read grants for the personas.
--
-- The personas need table-level SELECT for RLS to have anything to filter: RLS
-- narrows rows a role can already reach, it does not grant reach. Writes stay with
-- the owner (schema build, seed, index build) and with the API's proof-writing
-- path, which runs under the persona and therefore needs INSERT on proof.*.
-- ---------------------------------------------------------------------------

DO $$
DECLARE
  v_persona text;
BEGIN
  FOREACH v_persona IN ARRAY ARRAY['persona_app_engineer', 'persona_dba', 'persona_auditor']
  LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA casework, retrieval, proof TO %I', v_persona);
    EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA casework TO %I', v_persona);
    EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA retrieval TO %I', v_persona);
    EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA proof TO %I', v_persona);
    -- Remove grants from earlier revisions before installing the minimum write
    -- surface below. In particular, personas must not mutate evaluation fixtures,
    -- views, or another future proof table merely because it lives in the schema.
    EXECUTE format(
      'REVOKE INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA proof FROM %I',
      v_persona
    );
    EXECUTE format(
      'GRANT INSERT, UPDATE ON proof.retrieval_runs, proof.observability_refs, '
      'proof.agent_runs, proof.agent_subquestions, proof.agent_retrievals, '
      'proof.agent_answers, proof.traversal_results TO %I',
      v_persona
    );
    EXECUTE format(
      'GRANT INSERT ON proof.retrieval_candidates, proof.run_stages, '
      'proof.agent_escalations, proof.transport_invocations, '
      'proof.action_proposals, proof.action_proposal_citations, '
      'proof.action_executions TO %I',
      v_persona
    );
    EXECUTE format(
      'GRANT INSERT, DELETE ON proof.answer_citations TO %I',
      v_persona
    );
    EXECUTE format('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA retrieval TO %I', v_persona);
    EXECUTE format('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA proof TO %I', v_persona);
    EXECUTE format(
      'REVOKE EXECUTE ON FUNCTION proof.attach_wave_b_receipt(uuid, uuid, uuid) '
      'FROM %I',
      v_persona
    );
  END LOOP;
END
$$;

-- Future tables created by the owner inherit the same grants, so a later schema
-- addition cannot silently become unreadable to every persona.
ALTER DEFAULT PRIVILEGES IN SCHEMA casework
  GRANT SELECT ON TABLES TO persona_app_engineer, persona_dba, persona_auditor;
ALTER DEFAULT PRIVILEGES IN SCHEMA retrieval
  GRANT SELECT ON TABLES TO persona_app_engineer, persona_dba, persona_auditor;
ALTER DEFAULT PRIVILEGES IN SCHEMA proof
  REVOKE INSERT, UPDATE, DELETE ON TABLES
  FROM persona_app_engineer, persona_dba, persona_auditor;
ALTER DEFAULT PRIVILEGES IN SCHEMA proof
  GRANT SELECT ON TABLES
  TO persona_app_engineer, persona_dba, persona_auditor;

-- ---------------------------------------------------------------------------
-- 3. The two LOGIN roles.
--
-- Passwords are NOT set here: this file is committed to a public repository.
-- The sibling Workshop Studio repo provisions credentials (Secrets Manager) and
-- runs ALTER ROLE ... PASSWORD out of band.
-- ---------------------------------------------------------------------------

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'workshop_app') THEN
    CREATE ROLE workshop_app LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'workshop_participant') THEN
    CREATE ROLE workshop_participant LOGIN;
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- The disposable lab-workload owner.
--
-- Lab 4's central step is the participant running CREATE INDEX on
-- workbench_lab.orders themselves. PostgreSQL has no grantable CREATE INDEX
-- privilege: the participant must own the table directly or through an inherited
-- role membership. The tables are recreated for every workload bootstrap, so
-- object grants would both be insufficient and disappear on the next rebuild.
--
-- workbench_lab_owner owns only the disposable workbench_lab schema. It is
-- NOLOGIN and gives no role attributes. workshop_participant inherits it so a
-- plain Code Editor session can create the approved index. workshop_app is
-- deliberately excluded: the API pool receives narrow DML grants during each
-- rebuild, never ownership or passive DDL.
-- ---------------------------------------------------------------------------

GRANT workbench_lab_owner TO workshop_participant WITH INHERIT TRUE;

-- The bootstrap connection must SET ROLE to the ownership handle after it
-- recreates workbench_lab. current_user is retrieval_admin locally and
-- workshop_admin in a provisioned environment, so do not hard-code either.
DO $$
BEGIN
  EXECUTE format(
    'GRANT workbench_lab_owner TO %I WITH INHERIT TRUE',
    current_user
  );
END
$$;

-- Neither login may ever bypass RLS. This is an ASSERTION, not an ALTER, and the
-- distinction is a privilege one: changing the SUPERUSER or BYPASSRLS attribute
-- requires a real superuser, and this file runs as retrieval_admin, which is an
-- rds_superuser MEMBER and not a superuser. `ALTER ROLE ... NOBYPASSRLS
-- NOSUPERUSER` would therefore raise on Aurora while succeeding on a local cluster
-- whose owner is a true superuser -- a failure that only appears at deployment.
-- The assertion gives the same guarantee, needs no privilege, and reads better:
-- CREATE ROLE above already defaults every one of these attributes to false, so
-- the only way to trip this is for someone to have granted them deliberately.
DO $$
DECLARE
  v_bad text;
BEGIN
  SELECT string_agg(
           format('%s(super=%s bypassrls=%s createdb=%s createrole=%s)',
                  rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole),
           ', ' ORDER BY rolname)
    INTO v_bad
    FROM pg_roles
   WHERE rolname IN ('workshop_app', 'workshop_participant')
     AND (rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole);

  IF v_bad IS NOT NULL THEN
    RAISE EXCEPTION
      'the workshop login roles hold privileges that defeat RLS: %. A login with '
      'SUPERUSER or BYPASSRLS reads restricted rows regardless of policy, so G-27 '
      'would pass while the enforcement claim is false. Revoke the attributes as a '
      'superuser and re-run.', v_bad;
  END IF;
END
$$;

-- WITH INHERIT FALSE is load-bearing: the login may SET ROLE to a persona but
-- gains no passive access from the grant. Without it, workshop_app would inherit
-- the personas' SELECT and a forgotten SET ROLE would fail OPEN.
GRANT persona_app_engineer TO workshop_app WITH INHERIT FALSE;
GRANT persona_dba   TO workshop_app WITH INHERIT FALSE;
GRANT persona_auditor TO workshop_app WITH INHERIT FALSE;

GRANT persona_app_engineer TO workshop_participant WITH INHERIT FALSE;
GRANT persona_dba   TO workshop_participant WITH INHERIT FALSE;
GRANT persona_auditor TO workshop_participant WITH INHERIT FALSE;

-- The bootstrap owner gets the same three grants, for one specific reason:
-- admission/admit.sh's exact-arm checkpoint runs inside the A3 envelope
-- (BEGIN; SET LOCAL ROLE persona_app_engineer; SELECT; ROLLBACK), and that script is run
-- BOTH by a participant (as workshop_participant) and by a developer or the Step 5
-- scratch verification (as the bootstrap owner). Without this, the developer path
-- raises "permission denied to set role" while the participant path works -- a
-- divergence that only shows up for whoever is not in the room.
--
-- current_user, not a literal: the owner is retrieval_admin locally and
-- workshop_admin on a provisioned Aurora cluster (the sibling repo's MasterUsername).
-- Naming either one hardcodes the wrong cluster.
--
-- Strictly, PostgreSQL 16+ auto-grants a CREATEROLE role membership WITH ADMIN
-- OPTION on roles it creates, so the owner that ran the CREATE ROLE block above can
-- already SET ROLE to them. That implicit path is not good enough: on an idempotent
-- re-run nothing is created, so a DIFFERENT owner applying this file inherits
-- nothing. Explicit and idempotent beats implicit and conditional.
--
-- INHERIT FALSE keeps this from being a privilege change: the grant adds no passive
-- access, it only makes SET ROLE available. And because SET ROLE changes current_user
-- to a persona that does NOT hold can_see_restricted, the checkpoint gets real RLS
-- on both paths -- the owner's own clearance does not follow it into the persona.
DO $$
BEGIN
  EXECUTE format('GRANT persona_app_engineer TO %I WITH INHERIT FALSE', current_user);
  EXECUTE format('GRANT persona_dba   TO %I WITH INHERIT FALSE', current_user);
  EXECUTE format('GRANT persona_auditor TO %I WITH INHERIT FALSE', current_user);
END
$$;

-- The participant's own privileges: the exercise surface only.
-- pg_monitor is required, not optional: without it pg_stat_activity shows only the
-- participant's own backend and every Lab-1 watch snippet reads as empty.
GRANT pg_monitor TO workshop_participant;

-- ./admit.sh calls casework.admit_evidence. That is the ONLY casework reach the
-- participant gets: USAGE on the schema plus EXECUTE on the one function. No table
-- SELECT, so a bare SELECT on evidence raises permission denied - the first lesson.
--
-- EXECUTE ALONE IS NOT ENOUGH, and this is the trap that would have broken Lab 1.
-- casework.admit_evidence is LANGUAGE plpgsql with NO SECURITY DEFINER clause
-- (sql/10_admission.sql:36-39), so its body runs with the CALLER's privileges. Its
-- first statement reads casework.ingest_receipts (:78) and it then writes
-- evidence_items, lock_evidence, inferred_edges, search_index_queue and
-- ingest_receipts. A participant holding only EXECUTE would get
-- "permission denied for table ingest_receipts" on the Lab-1 finale, while G-30 --
-- which deliberately probes has_function_privilege and never invokes -- still
-- reported PASS. Two grants that would each defeat the lesson, and the fix:
--
--   * Granting the participant direct DML on those five tables would ALSO grant the
--     SELECT that the "permission denied on a bare SELECT" lesson depends on. Fails.
--   * Making the function SECURITY DEFINER keeps the participant's reach at exactly
--     one function while giving the body the owner's privileges. Correct.
--
-- sql/10 defines the function with SECURITY DEFINER, a pinned search_path, and no
-- PUBLIC EXECUTE so reapplying its owning migration cannot weaken this boundary.
-- The ALTER statements below are idempotent defense in depth; this file owns the
-- role-specific grants.
GRANT USAGE ON SCHEMA casework TO workshop_app, workshop_participant;
GRANT EXECUTE ON FUNCTION casework.admit_evidence(jsonb) TO workshop_participant;

-- Definer rights + a pinned search_path. The pin is mandatory, not hygiene: a
-- SECURITY DEFINER function that resolves unqualified names through the caller's
-- search_path is the classic privilege-escalation vector, and the participant
-- controls their own search_path. Every reference in the body is already
-- schema-qualified; the pin makes that structural.
ALTER FUNCTION casework.admit_evidence(jsonb) SECURITY DEFINER;
ALTER FUNCTION casework.admit_evidence(jsonb) SET search_path = pg_catalog, casework, retrieval;

-- PUBLIC gets EXECUTE on every new function by default, which for a SECURITY
-- DEFINER writer means any role in the cluster could admit evidence. Revoke it and
-- re-grant only the two identities that need it.
REVOKE ALL ON FUNCTION casework.admit_evidence(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION casework.admit_evidence(jsonb) TO workshop_participant;
GRANT EXECUTE ON FUNCTION casework.admit_evidence(jsonb) TO workshop_app;

-- The definer is the function's owner, the schema owner (retrieval_admin), which
-- holds can_see_restricted and therefore reads and writes every row. That is correct
-- here and must be stated so nobody "fixes" it later: admission is a WRITE path whose
-- ACL is carried in the payload, not a read path. No participant reads a row through
-- it --
-- the function returns only the ingest receipt (sql/10_admission.sql:163), which
-- holds hashes, counts and IDs, never evidence body text.

-- ---------------------------------------------------------------------------
-- 4. RLS on the three read-path tables, plus the evidence detail tables.
--
-- All three, not just casework: retrieval.vector_search reads retrieval.chunks
-- standalone (sql/03_search_functions.sql:488-514) and retrieval.fuzzy_search reads
-- retrieval.documents standalone (:614-634). A policy on casework.evidence_items
-- alone would leak restricted body text through the vector and fuzzy arms while the
-- headers stayed filtered. This is the single most important correctness
-- requirement in this file.
--
-- FORCE is required because the tables are owned by retrieval_admin and owners
-- bypass RLS by default. FORCE still does NOT subject a role holding SUPERUSER or
-- BYPASSRLS, which is why the app pool is workshop_app, not retrieval_admin.
--
-- Note the attribute, not the membership: role attributes are NOT inherited through
-- role membership. Measured read-only on the live cluster: retrieval_admin has
-- rolsuper=false and rolbypassrls=false, and rds_superuser itself has
-- rolbypassrls=false -- so there is no bypass to inherit and the owner IS subject to
-- FORCE on Aurora exactly as it is locally. Any comment claiming otherwise is wrong.
-- ---------------------------------------------------------------------------

ALTER TABLE casework.evidence_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE casework.evidence_items FORCE ROW LEVEL SECURITY;
ALTER TABLE retrieval.documents     ENABLE ROW LEVEL SECURITY;
ALTER TABLE retrieval.documents     FORCE ROW LEVEL SECURITY;
ALTER TABLE retrieval.chunks        ENABLE ROW LEVEL SECURITY;
ALTER TABLE retrieval.chunks        FORCE ROW LEVEL SECURITY;

-- The bootstrap owner needs the clearance key, and this is NOT belt-and-braces.
-- Measured on PostgreSQL 17 against this exact policy shape (four cases):
--
--   owner in policy TO list? | owner holds clearance? | rows the owner sees
--   -------------------------|------------------------|--------------------
--   no                       | no                     | 0  (all rows vanish)
--   no                       | YES                    | 0  (still vanish)
--   YES                      | no                     | workshop rows ONLY
--   YES                      | YES                    | all rows
--
-- Row three is the dangerous one, because nothing fails: the owner reads a
-- SILENTLY TRUNCATED table. The seed, the search-index build and every derived
-- evidence write run as the owner, and a measured
-- `INSERT INTO derived_table SELECT ... FROM source` under row three copied 1 of 2
-- rows and reported success. Restricted evidence would simply never reach
-- retrieval.documents/chunks -- and then G-27(b) would "pass" (analyst sees 0
-- restricted rows) for the wrong reason: there would be no restricted rows to see.
-- Both halves are required. This grant is the second half; the FIRST half is naming
-- CURRENT_USER in each policy's TO list below, and it is not optional on ANY cluster.
--
-- This grant alone lands the build in row TWO, not row four. Measured on PG17 with a
-- non-superuser owner, FORCE enabled, this grant applied and the policies listing
-- only the three personas: the owner saw 0 of 2 rows, `INSERT` raised
-- "new row violates row-level security policy", and `INSERT INTO derived_table SELECT`
-- copied 0 rows and exited 0. A PERMISSIVE policy set that names no applicable role
-- denies every row, and the clearance key cannot rescue a role no policy applies to.
--
-- The persona grants to the owner are WITH INHERIT FALSE, which is why the owner does
-- not reach the policies through them: measured, pg_has_role(owner, 'persona_app_engineer',
-- 'USAGE') is false, and the TO list is matched by that same USAGE semantics.
--
-- Not an Aurora no-op either. Role attributes are not inherited through membership;
-- measured read-only on the live cluster, retrieval_admin is rolsuper=false
-- rolbypassrls=false and rds_superuser has rolbypassrls=false. Without both halves,
-- `make schema` followed by `make seed` breaks on the deploy target, not just on the
-- disposable test databases.
--
-- Deliberately NOT the personas' clearance path: the owner is the writer, and the
-- teaching claim is about readers.
DO $$
BEGIN
  EXECUTE format('GRANT can_see_restricted TO %I', current_user);
END
$$;

DROP POLICY IF EXISTS rls_evidence_items_visibility ON casework.evidence_items;
DROP POLICY IF EXISTS rls_documents_visibility      ON retrieval.documents;
DROP POLICY IF EXISTS rls_chunks_visibility         ON retrieval.chunks;

-- casework.evidence_items keeps its classification inside the acl jsonb
-- (sql/01_schema.sql:40); the two retrieval tables carry the denormalized scalar
-- (:901, :968). Same value for the same row, same fail-closed default.
--
-- CURRENT_USER in the TO list is the first half of the owner fix above, and it is
-- safe: PostgreSQL resolves it to an OID at CREATE POLICY time and stores that OID in
-- pg_policy.polroles -- it is NOT re-evaluated per query. Measured on PG17: the
-- stored roles read {persona_dba, persona_app_engineer, persona_auditor,
-- retrieval_admin}, and `SET LOCAL ROLE persona_app_engineer` still saw 1 of 3 rows. If it
-- were dynamic it would match every persona and hand the analyst the clearance
-- disjunct, which is exactly the failure G-27(b) exists to catch. It does not.
CREATE POLICY rls_evidence_items_visibility ON casework.evidence_items
  FOR ALL
  TO persona_app_engineer, persona_dba, persona_auditor, CURRENT_USER
  USING (
    coalesce(acl ->> 'visibility', 'restricted') = 'workshop'
    OR pg_has_role(current_user, 'can_see_restricted', 'USAGE')
  );

-- THE teaching expression. Byte-identical to the Lab-3 H2 predicate and to the
-- guide snippet. "The predicate teaches, RLS enforces" is the same expression at
-- two layers - if you change one, change all three.
CREATE POLICY rls_documents_visibility ON retrieval.documents
  FOR ALL
  TO persona_app_engineer, persona_dba, persona_auditor, CURRENT_USER
  USING (
    acl_visibility = 'workshop'
    OR pg_has_role(current_user, 'can_see_restricted', 'USAGE')
  );

CREATE POLICY rls_chunks_visibility ON retrieval.chunks
  FOR ALL
  TO persona_app_engineer, persona_dba, persona_auditor, CURRENT_USER
  USING (
    acl_visibility = 'workshop'
    OR pg_has_role(current_user, 'can_see_restricted', 'USAGE')
  );

-- ---------------------------------------------------------------------------
-- 5. RLS on the evidence detail tables.
--
-- The three policies above are necessary and NOT sufficient. The sensitive text
-- is not in casework.evidence_items -- that table holds the header (external_key,
-- title, acl). The body lives in per-kind detail tables keyed 1:1 on evidence_id,
-- and section 2 grants every persona SELECT ON ALL TABLES IN SCHEMA casework
-- because RLS narrows reach, it does not grant it. Without the policies below, a
-- participant does this and the whole teaching claim collapses:
--
--   BEGIN; SET LOCAL ROLE persona_app_engineer;
--   SELECT count(*) FROM casework.evidence_items;   -- restricted rows hidden, correct
--   SELECT body, structured
--     FROM casework.telemetry_evidence;              -- the captured SQL in full.
--   ROLLBACK;
--
-- psql is the workshop's primary surface, not a back door: Lab 1's first lesson is
-- that a bare SELECT is denied. A participant who is denied at evidence_items and
-- then reads the captured query text one query later has been taught the opposite
-- of the intended lesson.
--
-- The predicate is a bare EXISTS back to the parent, NOT a copy of the clearance
-- expression. Three reasons: the detail tables have no acl column to read; one
-- definition of clearance beats seven; and the parent is already RLS-filtered, so
-- the child inherits the parent's visibility for free. Measured on PG17 with the
-- parent policy active: analyst saw 1 of 2 parent rows and 1 of 2 child rows with
-- the restricted account_name denied, while admin saw 2 and 2 unmasked. Graded,
-- not deny-all.
--
-- The dependency on the parent's RLS is load-bearing and was verified by negative
-- control: with ALTER TABLE casework.evidence_items DISABLE ROW LEVEL SECURITY,
-- the analyst saw every child row again. The EXISTS is not self-sufficient -- it
-- is filtered by the parent's policy. If a future change disables RLS on
-- casework.evidence_items, every table below silently opens. G-27 asserts
-- enabled+forced on the parent, which is what keeps that from happening quietly.
--
-- FOR ALL with USING only, matching the policies above. WITH CHECK defaults to
-- USING when omitted, and the foreign key guarantees the parent row exists, so
-- seed INSERTs still pass -- measured: the owner inserted a new restricted parent
-- and child under FORCE, and INSERT INTO derived_table SELECT copied 3 of 3 rows with
-- no silent truncation. FOR SELECT would be wrong: FORCE subjects the owner to
-- INSERT policies too, and with no INSERT-applicable policy every seed write is
-- denied.
--
-- CURRENT_USER in each TO list for the same reason as the policies above, which is
-- not optional on any cluster: it is stored as an OID in pg_policy.polroles at
-- CREATE POLICY time, and without it the owner reads zero rows and every derived
-- evidence write truncates while reporting success.
--
-- EVERY evidence-keyed detail table, discovered from the catalog rather than
-- listed. The bypass class is "the grant is schema-wide, so any evidence_id-keyed
-- table is a door" -- a hand-maintained allowlist re-opens the hole the moment a
-- later capture adds a kind, and the earlier authored-corpus list had already gone
-- stale against the live telemetry schema. The catalog query cannot drift: it
-- selects ordinary tables in casework holding an evidence_id column, excluding the
-- parent itself.
-- ---------------------------------------------------------------------------

-- ONE policy per table, ANDing every evidence reference the table carries. Two
-- policies on the same table would be a security regression, not defense in depth:
-- PERMISSIVE policies combine with OR, so a second policy would let a row through
-- when EITHER predicate passed. The junction reasoning in section 6 is therefore
-- enforced by this same loop, over the same tables, in one predicate.
DO $$
DECLARE
  v_table text;
  v_columns text[];
  v_predicate text;
  v_column text;
BEGIN
  FOR v_table, v_columns IN
    SELECT c.relname, array_agg(a.attname ORDER BY a.attnum)
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_attribute a ON a.attrelid = c.oid
    WHERE n.nspname = 'casework'
      AND c.relkind = 'r'
      AND c.relname <> 'evidence_items'
      AND a.attnum > 0
      AND NOT a.attisdropped
      AND (a.attname = 'evidence_id' OR a.attname LIKE '%\_evidence\_id')
    GROUP BY c.relname
    ORDER BY c.relname
  LOOP
    v_predicate := NULL;
    FOREACH v_column IN ARRAY v_columns
    LOOP
      v_predicate := concat_ws(
        ' AND ',
        v_predicate,
        format(
          '(casework.%I.%I IS NULL OR EXISTS (SELECT 1 FROM casework.evidence_items '
          'reachable WHERE reachable.evidence_id = casework.%I.%I))',
          v_table, v_column, v_table, v_column
        )
      );
    END LOOP;

    EXECUTE format('ALTER TABLE casework.%I ENABLE ROW LEVEL SECURITY', v_table);
    EXECUTE format('ALTER TABLE casework.%I FORCE  ROW LEVEL SECURITY', v_table);
    EXECUTE format('DROP POLICY IF EXISTS rls_%s_visibility ON casework.%I',
                   v_table, v_table);
    EXECUTE format($fmt$
      CREATE POLICY rls_%s_visibility ON casework.%I
        FOR ALL
        TO persona_app_engineer, persona_dba, persona_auditor, CURRENT_USER
        USING (%s)
    $fmt$, v_table, v_table, v_predicate);
  END LOOP;
END
$$;

-- ---------------------------------------------------------------------------
-- 6. RLS on the capture-keyed raw sample tables.
--
-- Sections 4 and 5 reach every table that carries an evidence reference. The raw
-- capture tables are the ones that do not. The two captured statement-text
-- columns are also the source of C1's deterministic visibility classifier:
--
--   casework.pg_stat_activity_samples.query       -- one observed backend
--   casework.pg_stat_statements_samples.queries    -- normalized phase snapshot
--
-- `pg_stat_activity_samples` carries `observation_evidence_id`, so section 5
-- scopes its rows through the lock observation. Those lock observations remain
-- workshop-visible: the blocked-PID topology is the Lab 1 evidence every
-- participant needs. Its query column is therefore redacted by sql/12 rather than
-- hidden by RLS.
--
-- `pg_stat_statements_samples` is keyed only by `capture_id`; it has no
-- `evidence_id` or `*_evidence_id`, so section 5's catalog walk cannot reach it.
-- The bare required EXISTS below makes it visible only while its capture's
-- incident is visible. Do not make this predicate "generous" with a
-- `NOT EXISTS ... OR EXISTS ...` branch: an RLS-filtered subquery cannot
-- distinguish a missing parent from a parent the caller is forbidden to see, and
-- absence must never become permission. sql/12 redacts the `queries` array for
-- personas without clearance while retaining the phase counters needed by the
-- optional lab.
-- ---------------------------------------------------------------------------

ALTER TABLE casework.pg_stat_statements_samples ENABLE ROW LEVEL SECURITY;
ALTER TABLE casework.pg_stat_statements_samples FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_pg_stat_statements_samples_visibility
  ON casework.pg_stat_statements_samples;

CREATE POLICY rls_pg_stat_statements_samples_visibility
  ON casework.pg_stat_statements_samples
  FOR ALL
  TO persona_app_engineer, persona_dba, persona_auditor, CURRENT_USER
  USING (
    EXISTS (
      SELECT 1
      FROM casework.incident_capture_runs run
      JOIN casework.evidence_items reachable
        ON reachable.evidence_id = run.incident_evidence_id
      WHERE run.capture_id = casework.pg_stat_statements_samples.capture_id
    )
  );

-- cloudwatch_metric_samples holds no statement text -- measured: metric name,
-- value, unit, dimension. It is gated on the capture run anyway, so the rule is
-- "every capture-keyed table is scoped by its capture's visibility" rather than a
-- judgement call about which payloads are interesting.
--
-- casework.database_clusters is deliberately NOT gated: it is keyed by cluster_id
-- with no capture_id and no evidence reference, and it holds engine version,
-- region, and instance class -- the cluster's own configuration, not an
-- observation of it. There is nothing here for a persona predicate to join to.
DO $$
DECLARE
  v_table text;
BEGIN
  FOREACH v_table IN ARRAY ARRAY['cloudwatch_metric_samples'] LOOP
    EXECUTE format('ALTER TABLE casework.%I ENABLE ROW LEVEL SECURITY', v_table);
    EXECUTE format('ALTER TABLE casework.%I FORCE  ROW LEVEL SECURITY', v_table);
    EXECUTE format('DROP POLICY IF EXISTS rls_%s_visibility ON casework.%I',
                   v_table, v_table);
    EXECUTE format($fmt$
      CREATE POLICY rls_%s_visibility ON casework.%I
        FOR ALL
        TO persona_app_engineer, persona_dba, persona_auditor, CURRENT_USER
        USING (EXISTS (SELECT 1
                         FROM casework.incident_capture_runs run
                         JOIN casework.evidence_items reachable
                           ON reachable.evidence_id = run.incident_evidence_id
                        WHERE run.capture_id = casework.%I.capture_id))
    $fmt$, v_table, v_table, v_table);
  END LOOP;
END
$$;

-- 7. RLS on inferred relationships and the index outbox.
--
-- Canonical relationship tables are protected above. Inferred edges need the
-- same both-endpoints rule or retrieval.evidence_edges can reveal that a visible
-- record is related to a restricted one. Personas only read this table; the
-- admission function writes it as the schema owner.
--
-- retrieval.search_index_queue is here for the same reason, and it is the one
-- evidence-keyed table outside casework: section 5's loop walks casework only, so
-- the outbox is a separate evidence-bearing read path. It carries no body text,
-- but it does expose evidence identity and source revision; an App Engineer must
-- not enumerate rows the ACL hides elsewhere. G-27 asserts the rule structurally
-- (every table holding an evidence, capture, run, or ACL reference is
-- ENABLE+FORCE), so leaving this table out would require a hand-typed exemption --
-- exactly the drift the catalog-driven loop exists to prevent.
-- ---------------------------------------------------------------------------

ALTER TABLE retrieval.inferred_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE retrieval.inferred_edges FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS rls_inferred_edges_visibility ON retrieval.inferred_edges;
DROP POLICY IF EXISTS rls_inferred_edges_owner ON retrieval.inferred_edges;

CREATE POLICY rls_inferred_edges_visibility ON retrieval.inferred_edges
  FOR SELECT
  TO persona_app_engineer, persona_dba, persona_auditor
  USING (
    EXISTS (
      SELECT 1
      FROM casework.evidence_items near
      WHERE near.evidence_id = retrieval.inferred_edges.from_evidence_id
    )
    AND EXISTS (
      SELECT 1
      FROM casework.evidence_items far
      WHERE far.evidence_id = retrieval.inferred_edges.to_evidence_id
    )
  );

CREATE POLICY rls_inferred_edges_owner ON retrieval.inferred_edges
  FOR ALL
  TO CURRENT_USER
  USING (true)
  WITH CHECK (true);

ALTER TABLE retrieval.search_index_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE retrieval.search_index_queue FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS rls_search_index_queue_visibility ON retrieval.search_index_queue;
DROP POLICY IF EXISTS rls_search_index_queue_owner ON retrieval.search_index_queue;

-- FOR SELECT, not FOR ALL: nothing a persona does writes this table. The two
-- writers are the index builder (labs/incident/run_live_workshop.py, connected as
-- the owner) and casework.admit_evidence, which is SECURITY DEFINER owned by the
-- schema owner (sql/10_admission.sql) -- so both write under the owner policy
-- below, not this one.
CREATE POLICY rls_search_index_queue_visibility ON retrieval.search_index_queue
  FOR SELECT
  TO persona_app_engineer, persona_dba, persona_auditor
  USING (
    EXISTS (
      SELECT 1
      FROM casework.evidence_items reachable
      WHERE reachable.evidence_id = retrieval.search_index_queue.evidence_id
    )
  );

CREATE POLICY rls_search_index_queue_owner ON retrieval.search_index_queue
  FOR ALL
  TO CURRENT_USER
  USING (true)
  WITH CHECK (true);

-- ---------------------------------------------------------------------------
-- 8. RLS on replayable proof.
--
-- A run_id is a reference, not a bearer capability. Root rows carry the persona
-- that created them; every child row inherits visibility through its root.
-- Exact-persona isolation is intentional: replay reproduces the visibility and
-- masking context of the original run, so a different persona starts a new run
-- instead of reopening this one.
--
-- Clearing through the run is necessary and NOT sufficient for the four child
-- tables that also name evidence. Those rows must clear through the EVIDENCE too,
-- and the measured leak is why: proof.retrieval_candidates.evidence_snapshot is a
-- copy of the document header and chunk snippet as retrieved. A run owned by an
-- App Engineer can therefore outlive the visibility context that originally
-- filtered its candidates. The run-role predicate alone would pass because the
-- run is theirs, while a snapshot could still repeat captured PostgreSQL statement
-- text that RLS withheld at casework.evidence_items, retrieval.documents, and
-- retrieval.chunks.
--
-- The snapshot is written by the API as the schema owner, which holds clearance, so
-- the write is not the defect: the retrieval arms themselves were persona-filtered
-- at query time and these rows predate the policies. Either way the receipt must be
-- re-filtered on read, because a receipt outlives the visibility context that
-- produced it and the ACL can also change underneath it.
--
-- Both predicates AND together in ONE policy per table. Two policies would be a
-- regression, not defense in depth: PERMISSIVE policies combine with OR, so a
-- second policy would admit a row when EITHER predicate passed.
-- ---------------------------------------------------------------------------

DO $$
DECLARE
  v_table text;
BEGIN
  FOREACH v_table IN ARRAY ARRAY[
    'retrieval_runs',
    'agent_runs',
    'transport_invocations'
  ]
  LOOP
    EXECUTE format('ALTER TABLE proof.%I ENABLE ROW LEVEL SECURITY', v_table);
    EXECUTE format('ALTER TABLE proof.%I FORCE ROW LEVEL SECURITY', v_table);
    EXECUTE format('DROP POLICY IF EXISTS proof_%s_persona ON proof.%I',
                   v_table, v_table);
    EXECUTE format('DROP POLICY IF EXISTS proof_%s_owner ON proof.%I',
                   v_table, v_table);
    EXECUTE format($fmt$
      CREATE POLICY proof_%s_persona ON proof.%I
        FOR ALL
        TO persona_app_engineer, persona_dba, persona_auditor
        USING (
          role = CASE current_user::text
            WHEN 'persona_app_engineer' THEN 'app_engineer'
            WHEN 'persona_auditor' THEN 'auditor'
            WHEN 'persona_dba' THEN 'dba'
            ELSE NULL
          END
        )
        WITH CHECK (
          role = CASE current_user::text
            WHEN 'persona_app_engineer' THEN 'app_engineer'
            WHEN 'persona_auditor' THEN 'auditor'
            WHEN 'persona_dba' THEN 'dba'
            ELSE NULL
          END
        )
    $fmt$, v_table, v_table);
    EXECUTE format($fmt$
      CREATE POLICY proof_%s_owner ON proof.%I
        FOR ALL TO CURRENT_USER
        USING (true)
        WITH CHECK (true)
    $fmt$, v_table, v_table);
  END LOOP;
END
$$;

-- The evidence clause is appended from the CATALOG, not from a second list of
-- table names. observability_refs and run_stages carry no evidence_id and get the
-- run predicate alone; retrieval_candidates, traversal_results and answer_citations
-- carry one and get both. A later receipt table that names evidence inherits the
-- clause the moment it is created, which is the drift G-27's structural rule
-- asserts and this loop must not be able to fall behind.
--
-- The clause lands in WITH CHECK as well as USING, and that is deliberate rather
-- than incidental: in security mode the API writes these rows under the requesting
-- persona (backend/app/db.get_conn issues SET LOCAL ROLE per transaction), so the
-- persona is the inserting identity. An App Engineer can only retrieve evidence it
-- can see, so every candidate row it writes names visible evidence and the check
-- passes; a receipt naming evidence the writer cannot see is a bug, and this makes
-- it a denied INSERT instead of a stored leak.
DO $$
DECLARE
  v_table text;
  v_evidence_clause text;
BEGIN
  FOREACH v_table IN ARRAY ARRAY[
    'observability_refs',
    'retrieval_candidates',
    'run_stages',
    'traversal_results',
    'answer_citations'
  ]
  LOOP
    SELECT CASE WHEN EXISTS (
             SELECT 1
             FROM pg_attribute a
             JOIN pg_class c ON c.oid = a.attrelid
             JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'proof'
               AND c.relname = v_table
               AND a.attname = 'evidence_id'
               AND a.attnum > 0
               AND NOT a.attisdropped
           )
           THEN format(
             ' AND EXISTS (SELECT 1 FROM casework.evidence_items reachable '
             'WHERE reachable.evidence_id = proof.%I.evidence_id)', v_table)
           ELSE ''
      END
      INTO v_evidence_clause;

    EXECUTE format('ALTER TABLE proof.%I ENABLE ROW LEVEL SECURITY', v_table);
    EXECUTE format('ALTER TABLE proof.%I FORCE ROW LEVEL SECURITY', v_table);
    EXECUTE format('DROP POLICY IF EXISTS proof_%s_persona ON proof.%I',
                   v_table, v_table);
    EXECUTE format('DROP POLICY IF EXISTS proof_%s_owner ON proof.%I',
                   v_table, v_table);
    EXECUTE format($fmt$
      CREATE POLICY proof_%s_persona ON proof.%I
        FOR ALL
        TO persona_app_engineer, persona_dba, persona_auditor
        USING (
          EXISTS (
            SELECT 1
            FROM proof.retrieval_runs parent
            WHERE parent.run_id = proof.%I.run_id
          )%s
        )
        WITH CHECK (
          EXISTS (
            SELECT 1
            FROM proof.retrieval_runs parent
            WHERE parent.run_id = proof.%I.run_id
          )%s
        )
    $fmt$, v_table, v_table, v_table, v_evidence_clause,
           v_table, v_evidence_clause);
    EXECUTE format($fmt$
      CREATE POLICY proof_%s_owner ON proof.%I
        FOR ALL TO CURRENT_USER
        USING (true)
        WITH CHECK (true)
    $fmt$, v_table, v_table);
  END LOOP;
END
$$;

DO $$
DECLARE
  v_table text;
BEGIN
  FOREACH v_table IN ARRAY ARRAY[
    'agent_subquestions',
    'agent_escalations'
  ]
  LOOP
    EXECUTE format('ALTER TABLE proof.%I ENABLE ROW LEVEL SECURITY', v_table);
    EXECUTE format('ALTER TABLE proof.%I FORCE ROW LEVEL SECURITY', v_table);
    EXECUTE format('DROP POLICY IF EXISTS proof_%s_persona ON proof.%I',
                   v_table, v_table);
    EXECUTE format('DROP POLICY IF EXISTS proof_%s_owner ON proof.%I',
                   v_table, v_table);
    EXECUTE format($fmt$
      CREATE POLICY proof_%s_persona ON proof.%I
        FOR ALL
        TO persona_app_engineer, persona_dba, persona_auditor
        USING (
          EXISTS (
            SELECT 1
            FROM proof.agent_runs parent
            WHERE parent.agent_run_id = proof.%I.agent_run_id
          )
        )
        WITH CHECK (
          EXISTS (
            SELECT 1
            FROM proof.agent_runs parent
            WHERE parent.agent_run_id = proof.%I.agent_run_id
          )
        )
    $fmt$, v_table, v_table, v_table, v_table);
    EXECUTE format($fmt$
      CREATE POLICY proof_%s_owner ON proof.%I
        FOR ALL TO CURRENT_USER
        USING (true)
        WITH CHECK (true)
    $fmt$, v_table, v_table);
  END LOOP;
END
$$;

-- Supervised-execution receipts. Proposals follow their agent run; citation
-- links and executions follow the retrieval run whose answer they prove.
DO $$
DECLARE
  v_table text;
BEGIN
  FOREACH v_table IN ARRAY ARRAY['action_proposals']
  LOOP
    EXECUTE format('ALTER TABLE proof.%I ENABLE ROW LEVEL SECURITY', v_table);
    EXECUTE format('ALTER TABLE proof.%I FORCE ROW LEVEL SECURITY', v_table);
    EXECUTE format('DROP POLICY IF EXISTS proof_%s_persona ON proof.%I',
                   v_table, v_table);
    EXECUTE format('DROP POLICY IF EXISTS proof_%s_owner ON proof.%I',
                   v_table, v_table);
    EXECUTE format($fmt$
      CREATE POLICY proof_%s_persona ON proof.%I
        FOR ALL
        TO persona_app_engineer, persona_dba, persona_auditor
        USING (
          EXISTS (
            SELECT 1
            FROM proof.agent_runs parent
            WHERE parent.agent_run_id = proof.%I.agent_run_id
          )
        )
        WITH CHECK (
          EXISTS (
            SELECT 1
            FROM proof.agent_runs parent
            WHERE parent.agent_run_id = proof.%I.agent_run_id
          )
        )
    $fmt$, v_table, v_table, v_table, v_table);
    EXECUTE format($fmt$
      CREATE POLICY proof_%s_owner ON proof.%I
        FOR ALL TO CURRENT_USER
        USING (true)
        WITH CHECK (true)
    $fmt$, v_table, v_table);
  END LOOP;

  FOREACH v_table IN ARRAY ARRAY[
    'action_proposal_citations',
    'action_executions'
  ]
  LOOP
    EXECUTE format('ALTER TABLE proof.%I ENABLE ROW LEVEL SECURITY', v_table);
    EXECUTE format('ALTER TABLE proof.%I FORCE ROW LEVEL SECURITY', v_table);
    EXECUTE format('DROP POLICY IF EXISTS proof_%s_persona ON proof.%I',
                   v_table, v_table);
    EXECUTE format('DROP POLICY IF EXISTS proof_%s_owner ON proof.%I',
                   v_table, v_table);
    EXECUTE format($fmt$
      CREATE POLICY proof_%s_persona ON proof.%I
        FOR ALL
        TO persona_app_engineer, persona_dba, persona_auditor
        USING (
          EXISTS (
            SELECT 1
            FROM proof.retrieval_runs parent
            WHERE parent.run_id = proof.%I.run_id
          )
        )
        WITH CHECK (
          EXISTS (
            SELECT 1
            FROM proof.retrieval_runs parent
            WHERE parent.run_id = proof.%I.run_id
          )
        )
    $fmt$, v_table, v_table, v_table, v_table);
    EXECUTE format($fmt$
      CREATE POLICY proof_%s_owner ON proof.%I
        FOR ALL TO CURRENT_USER
        USING (true)
        WITH CHECK (true)
    $fmt$, v_table, v_table);
  END LOOP;
END
$$;

ALTER TABLE proof.agent_retrievals ENABLE ROW LEVEL SECURITY;
ALTER TABLE proof.agent_retrievals FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS proof_agent_retrievals_persona ON proof.agent_retrievals;
DROP POLICY IF EXISTS proof_agent_retrievals_owner ON proof.agent_retrievals;
CREATE POLICY proof_agent_retrievals_persona ON proof.agent_retrievals
  FOR ALL
  TO persona_app_engineer, persona_dba, persona_auditor
  USING (
    EXISTS (
      SELECT 1 FROM proof.agent_runs agent
      WHERE agent.agent_run_id = proof.agent_retrievals.agent_run_id
    )
    AND EXISTS (
      SELECT 1 FROM proof.retrieval_runs run
      WHERE run.run_id = proof.agent_retrievals.run_id
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM proof.agent_runs agent
      WHERE agent.agent_run_id = proof.agent_retrievals.agent_run_id
    )
    AND EXISTS (
      SELECT 1 FROM proof.retrieval_runs run
      WHERE run.run_id = proof.agent_retrievals.run_id
    )
  );
CREATE POLICY proof_agent_retrievals_owner ON proof.agent_retrievals
  FOR ALL TO CURRENT_USER USING (true) WITH CHECK (true);

ALTER TABLE proof.agent_answers ENABLE ROW LEVEL SECURITY;
ALTER TABLE proof.agent_answers FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS proof_agent_answers_persona ON proof.agent_answers;
DROP POLICY IF EXISTS proof_agent_answers_owner ON proof.agent_answers;
CREATE POLICY proof_agent_answers_persona ON proof.agent_answers
  FOR ALL
  TO persona_app_engineer, persona_dba, persona_auditor
  USING (
    EXISTS (
      SELECT 1 FROM proof.retrieval_runs run
      WHERE run.run_id = proof.agent_answers.run_id
    )
    AND (
      agent_run_id IS NULL
      OR EXISTS (
        SELECT 1 FROM proof.agent_runs agent
        WHERE agent.agent_run_id = proof.agent_answers.agent_run_id
      )
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM proof.retrieval_runs run
      WHERE run.run_id = proof.agent_answers.run_id
    )
    AND (
      agent_run_id IS NULL
      OR EXISTS (
        SELECT 1 FROM proof.agent_runs agent
        WHERE agent.agent_run_id = proof.agent_answers.agent_run_id
      )
    )
  );
CREATE POLICY proof_agent_answers_owner ON proof.agent_answers
  FOR ALL TO CURRENT_USER USING (true) WITH CHECK (true);

ALTER TABLE proof.relevance_judgments ENABLE ROW LEVEL SECURITY;
ALTER TABLE proof.relevance_judgments FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS proof_relevance_judgments_persona ON proof.relevance_judgments;
DROP POLICY IF EXISTS proof_relevance_judgments_owner ON proof.relevance_judgments;
CREATE POLICY proof_relevance_judgments_persona ON proof.relevance_judgments
  FOR SELECT
  TO persona_app_engineer, persona_dba, persona_auditor
  USING (
    EXISTS (
      SELECT 1
      FROM casework.evidence_items evidence
      WHERE evidence.evidence_id = proof.relevance_judgments.evidence_id
    )
  );
CREATE POLICY proof_relevance_judgments_owner ON proof.relevance_judgments
  FOR ALL TO CURRENT_USER USING (true) WITH CHECK (true);
