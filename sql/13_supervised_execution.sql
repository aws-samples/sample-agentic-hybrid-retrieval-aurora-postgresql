-- Supervised execution (design spec, "Supervised Execution Model").
--
-- The agent never executes anything. It writes a structured, cited PROPOSAL;
-- the participant approves and executes it themselves in Code Editor; the
-- execution is recorded here with the index definition read back FROM THE
-- CATALOG, not from the participant's typed text. That read-back is what makes
-- the proposed-vs-executed comparison evidence rather than assertion.
--
-- These tables are an audit trail written ABOUT the agent's output. They are
-- not an agent capability: nothing here is reachable from agent/registry.py,
-- and no task in this plan may make it so.

CREATE TABLE IF NOT EXISTS proof.action_proposals (
  proposal_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_run_id uuid NOT NULL
    REFERENCES proof.agent_runs(agent_run_id) ON DELETE RESTRICT,
  run_id uuid NOT NULL
    REFERENCES proof.retrieval_runs(run_id) ON DELETE RESTRICT,
  -- Allowlist, enforced by the database rather than by the prompt. Widening
  -- this CHECK is a schema change and a review conversation, which is exactly
  -- the friction it is here to create.
  action_type text NOT NULL CHECK (action_type IN ('create_index')),
  target_schema text NOT NULL,
  target_table text NOT NULL,
  index_method text NOT NULL DEFAULT 'btree',
  is_unique boolean NOT NULL DEFAULT false,
  -- Ordered. (priority_tier, created_at DESC) is not the same action as
  -- (created_at DESC, priority_tier), so this is an array and never a set.
  key_columns text[] NOT NULL
    CHECK (coalesce(array_length(key_columns, 1), 0) >= 1),
  included_columns text[] NOT NULL DEFAULT '{}',
  -- MEASURED DEFECT, fixed by this CHECK: a partial-index predicate cannot be
  -- fingerprinted consistently, so a non-NULL predicate is rejected outright.
  --
  -- The proposal side stores the predicate as the agent wrote it; the catalog
  -- side reads it back through pg_get_expr(), which REWRITES it. Measured on
  -- PostgreSQL 17.10: proposed `status = 'open'` against the identical executed
  -- index yields catalog text `(status = 'open'::text)`, two different
  -- fingerprints, and `fingerprint_matches = false` for a participant who did
  -- exactly what was asked. That is the worst failure this design can have --
  -- the workshop calling a correct participant wrong -- and it is not fixable by
  -- normalizing strings on the proposal side, because matching pg_get_expr's
  -- output means reimplementing the PostgreSQL expression printer.
  --
  -- The honest fix is to make the unfingerprintable case unrepresentable. Lab 4
  -- proposes a plain composite b-tree index and needs no predicate. Verified on
  -- PostgreSQL 17.10 with predicate NULL: the plain Lab 4 index, an INCLUDE
  -- index, and a UNIQUE index each produced identical proposal-side and
  -- catalog-side fingerprints.
  --
  -- If partial indexes are ever wanted, the correct route is to canonicalize the
  -- proposal side THROUGH the server -- have the proposal store the predicate as
  -- rendered by pg_get_expr() for a trial expression -- and only then relax this
  -- CHECK. Do not relax it and hope.
  predicate text CHECK (predicate IS NULL),
  -- The authoritative equality test. Computed by
  -- proof.index_action_fingerprint() from the structured fields above.
  proposed_fingerprint text NOT NULL,
  -- Audit only. NEVER compared to decide whether the participant executed the
  -- proposed action: whitespace, quoting, and equivalent PostgreSQL syntax make
  -- raw-hash equality brittle, and a participant who typed the recommended
  -- index with different spacing would be wrongly told they executed something
  -- else.
  proposed_sql text NOT NULL,
  proposed_sql_sha256 text NOT NULL,
  preconditions jsonb NOT NULL DEFAULT '[]'::jsonb
    -- Measured on a real server: without this CHECK, storing an OBJECT here
    -- (`'{"satisfied": true}'::jsonb` — a plausible writer bug) makes
    -- proof.autonomy_readiness() raise `cannot get array length of a non-array`
    -- at its jsonb_array_length call instead of returning a verdict. The
    -- proposal is then unjudgeable rather than ineligible, which is the one
    -- outcome this module must never produce. The empty ARRAY stays storable:
    -- with the CHECK in place, `'[]'` inserts and the verdict reports
    -- `no preconditions were recorded`.
    CHECK (jsonb_typeof(preconditions) = 'array'),
  expected_effect text NOT NULL,
  rollback_sql text,
  rollback_guidance text,
  statement_timeout text,
  lock_timeout text,
  created_at timestamptz NOT NULL DEFAULT now(),
  -- One proposal per agent run. A run that produced two conflicting
  -- recommendations is a defect to surface, not a history to accumulate.
  UNIQUE (agent_run_id),
  -- Referenced by proof.action_executions' composite foreign key below.
  -- Redundant with the primary key by design: PostgreSQL requires a UNIQUE
  -- constraint on exactly the referenced column pair, and the primary key alone
  -- does not satisfy a two-column reference.
  UNIQUE (proposal_id, run_id)
  -- Deliberately NO constraint requiring rollback guidance, bounded timeouts,
  -- or satisfied preconditions. An incomplete proposal must be STORABLE so
  -- proof.autonomy_readiness() can report WHY it is ineligible. Rejecting it
  -- at insert time would make the ineligible case unobservable, and the
  -- ineligible case is the teaching point of this whole module.
);

CREATE TABLE IF NOT EXISTS proof.action_proposal_citations (
  -- COMPOSITE, not a bare proposal_id reference, and this is a measured fix.
  -- An earlier draft referenced proof.action_proposals(proposal_id) alone and
  -- left run_id tied only to proof.answer_citations below. Nothing then required
  -- the link's run_id to equal the PROPOSAL's run_id, and measured on
  -- PostgreSQL 17.10, 2026-08-04: a link naming proposal C (of run A) with
  -- run_id = B inserted cleanly (`same_run = f`). Requirement 6 then evaluates
  -- the link against proof.validate_answer_citations(PROPOSAL.run_id) while the
  -- link's own FK was satisfied against run B, so the two sides validate
  -- different rows. Measured verdict for a proposal whose supporting link points
  -- at another run's INVALID citation: `PASSES requirement 6`. With this
  -- composite reference the same INSERT is refused with
  -- `foreign_key_violation`. This is what proof.action_proposals'
  -- UNIQUE (proposal_id, run_id) is for -- it is referenced twice, from here and
  -- from proof.action_executions.
  proposal_id uuid NOT NULL,
  run_id uuid NOT NULL,
  citation_number integer NOT NULL,
  claim text NOT NULL,
  PRIMARY KEY (proposal_id, citation_number),
  FOREIGN KEY (proposal_id, run_id)
    REFERENCES proof.action_proposals(proposal_id, run_id) ON DELETE CASCADE,
  -- The proposal's supporting citations are the SAME rows the answer cited, so
  -- proof.validate_answer_citations() already governs them. A separate quote
  -- column here could drift from the chunk text it claims to quote.
  --
  -- ON DELETE CASCADE, and this is a correction of a measured defect, not a
  -- preference. `backend/app/agent.py:737` runs
  -- `DELETE FROM proof.answer_citations WHERE run_id = %s` on EVERY call to
  -- _persist_answer(), including the second call for a run that already has an
  -- answer (the function's own INSERT is `ON CONFLICT (run_id) DO UPDATE`, so
  -- re-answering the same run is a supported path, not an error path). With
  -- RESTRICT here, the first proposal written against a run permanently
  -- wedges that run's answer: measured on a real server, the re-persist
  -- failed with `update or delete on table "answer_citations" violates
  -- foreign key constraint
  -- "action_proposal_citations_run_id_citation_number_fkey" on table
  -- "action_proposal_citations"`. With CASCADE, the same DELETE succeeded, the
  -- stale link count went 1 -> 0, and the proposal row itself survived
  -- (`proposal row still present: 1`) for Task D2a to relink inside the same
  -- transaction. Note what CASCADE does NOT weaken: it deletes the LINK when
  -- the cited answer citation is replaced, never the proposal. A proposal whose
  -- links are gone reports `the proposal cites no evidence` and is ineligible,
  -- which is the correct verdict for a proposal whose supporting answer was
  -- rewritten.
  FOREIGN KEY (run_id, citation_number)
    REFERENCES proof.answer_citations(run_id, citation_number) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS proof.action_executions (
  execution_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  proposal_id uuid NOT NULL
    REFERENCES proof.action_proposals(proposal_id) ON DELETE RESTRICT,
  -- Denormalized from the proposal so the RLS policy in step 12 can chain this
  -- row's owning persona through proof.retrieval_runs directly. NOT NULL is
  -- load-bearing twice over: the policy predicate needs a non-null key, and
  -- gates/rls_enforcement.py's _run_root() (line 515) RAISES RuntimeError on a
  -- run-gated table whose run key is nullable, because an inner join through a
  -- nullable key silently drops rows and understates the owner's oracle. The
  -- composite foreign key at the bottom of this table makes the denormalization
  -- safe: a run_id that disagrees with the proposal's is refused by the engine.
  run_id uuid NOT NULL,
  -- The tiebreak for "which attempt is the current one". MEASURED on PostgreSQL
  -- 17.10, 2026-08-04: now() is transaction START time, so two rows inserted in
  -- one transaction carry a single identical approved_at (`distinct_timestamps=1`
  -- across 2 rows), and `ORDER BY approved_at DESC LIMIT 1` then returns whichever
  -- row the heap happens to yield first. Reclustering the same two rows returned
  -- 'failed', then 'succeeded', then 'failed' -- three different verdicts from
  -- unchanged data with no write in between. With this tiebreak all three
  -- returned 'succeeded'. An identity column is monotonic in insertion order,
  -- which is exactly the question being asked; execution_id cannot serve because
  -- gen_random_uuid() is unordered.
  recorded_seq bigint GENERATED ALWAYS AS IDENTITY,
  approved_by text NOT NULL,
  approved_at timestamptz NOT NULL DEFAULT now(),
  executed_sql text,
  executed_sql_sha256 text,
  -- Read back from pg_indexes / pg_get_indexdef AFTER the DDL ran, never
  -- parsed from executed_sql. This is the load-bearing column.
  observed_index_definition text,
  observed_fingerprint text,
  fingerprint_matches boolean,
  -- TWO values, not three. An earlier draft allowed 'abandoned' as well, and
  -- review found it unreachable: a proposal that was approved but never executed
  -- is the ABSENCE of a row in this table, which the verdict already reports as
  -- `no execution has been recorded yet`. A third value that can only ever mean
  -- what zero rows already mean is dead schema, and dead schema in a CHECK reads
  -- as a state the system can enter. It cannot.
  --
  -- 'failed' IS reachable, and only became so once step 8's ordering was
  -- corrected to record before admission: a CREATE INDEX that errored or hit its
  -- statement_timeout leaves no index, and Task D3 records that fact rather than
  -- writing nothing.
  outcome text NOT NULL
    CHECK (outcome IN ('succeeded', 'failed')),
  outcome_detail text,
  started_at timestamptz,
  completed_at timestamptz,
  plan_before_checkpoint text,
  plan_after_checkpoint text,
  wave_b_capture_id uuid
    REFERENCES evidence.incident_capture_runs(capture_id) ON DELETE SET NULL,
  wave_b_ingest_id uuid
    REFERENCES evidence.ingest_receipts(ingest_id) ON DELETE SET NULL,
  CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at),
  -- A succeeded execution must carry the catalog read-back and its verdict.
  -- Without this, a NULL observed_fingerprint would silently read as
  -- "unmatched" and the comparison would be unfalsifiable.
  CHECK (
    outcome <> 'succeeded'
    OR (observed_index_definition IS NOT NULL
        AND observed_fingerprint IS NOT NULL
        AND fingerprint_matches IS NOT NULL)
  ),
  -- Proven on a real server: an execution whose run_id matches its proposal is
  -- accepted, and one pointing at a different run is refused with
  -- `violates foreign key constraint
  -- "action_executions_proposal_id_run_id_fkey"`. Without this, the denormalized
  -- run_id could name a run belonging to another persona and the RLS policy would
  -- hand the row to the wrong one.
  FOREIGN KEY (proposal_id, run_id)
    REFERENCES proof.action_proposals(proposal_id, run_id) ON DELETE RESTRICT
);

-- ONE case-folding rule for every name-shaped field on both sides.
--
-- MEASURED DEFECT this replaces (PostgreSQL 17.10, 2026-08-04). The earlier draft
-- inlined the rule as `CASE WHEN expr LIKE '%"%' THEN expr ELSE lower(expr) END`
-- in canonical_index_key only, and applied a bare `lower(btrim(...))` to the
-- schema, table, and INCLUDE columns. That produced four separate defects, three
-- of them measured as reproducing:
--
--   1. FALSE MATCH, the worst kind: `lower(btrim(relname))` on the observed side
--      folds a QUOTED mixed-case relation onto the lower-case one. An index built
--      on workbench_lab."ORDERS" -- a genuinely different table -- fingerprinted
--      IDENTICALLY to the proposal for workbench_lab.orders. The workshop would
--      report a match for an action performed on the wrong table.
--   2. FALSE MISMATCH: INCLUDE columns were sorted but never folded, so a
--      proposal saying `Created_At` never matched the catalog's `created_at`.
--   3. FALSE MATCH: `LIKE '%"%'` tests for a double quote ANYWHERE, so it does not
--      fire on single-quoted string literals inside an expression.
--      regexp_replace(note,'A','B') and regexp_replace(note,'a','b') -- different
--      indexes -- folded to one fingerprint.
--   4. FALSE MISMATCH: the same test fires on `name COLLATE "C"` because of the
--      quoted collation name, so the whole expression including the column name
--      stayed byte-exact and `NAME COLLATE "C"` never matched.
--
-- The rule below fixes all four by asking the right question. Not "does this
-- contain a quote" but "is this WHOLE string a bare identifier". Only a bare
-- identifier is case-insensitive in PostgreSQL, so only a bare identifier may be
-- folded. Everything else -- a quoted identifier, an expression, a COLLATE clause
-- -- is preserved byte-exact. The catalog side reaches this with quote_ident()
-- already applied (see step 6), so both derivations present names the same way.
--
-- Consequence, accepted deliberately: `NAME COLLATE "C"` still does not match
-- `name COLLATE "C"`. That is a false mismatch this rule does not fix, and
-- fixing it means parsing SQL expressions. It is unreachable for this workshop --
-- Task D2a's parser only accepts bare identifiers as key columns, so no COLLATE
-- clause can ever reach a proposal -- and a false mismatch on an unreachable
-- input is an honest limitation, not a live defect. Do not "improve" this by
-- widening the fold; widening it is what produced defects 1 and 3.
CREATE OR REPLACE FUNCTION proof.canonical_sql_name(p_text text)
RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE
           WHEN t.trimmed ~ '^[A-Za-z_][A-Za-z0-9_]*$' THEN lower(t.trimmed)
           ELSE t.original
         END
  FROM (
    SELECT coalesce(p_text, '') AS original,
           regexp_replace(coalesce(p_text, ''), '^\s+|\s+$', '', 'g') AS trimmed
  ) t
$$;

COMMENT ON FUNCTION proof.canonical_sql_name(text) IS
  'The one case-folding rule for name-shaped fields. Folds only a string that is '
  'entirely a bare identifier; a quoted identifier or an expression is preserved '
  'byte-exact, including whitespace inside string literals. Folding or collapsing '
  'more than this produced measured false matches.';

-- One canonicalizer, called by BOTH sides. The proposal side passes the agent's
-- structured fields; the observation side passes what it read out of the
-- catalog. If each side had its own normalizer, the comparison would be testing
-- two normalizers against each other rather than testing the action.
CREATE OR REPLACE FUNCTION proof.canonical_index_key(
  p_expression text,
  p_direction text,
  p_nulls text,
  p_opclass text
) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT concat_ws(
    ' ',
    proof.canonical_sql_name(p_expression),
    v.direction,
    -- PostgreSQL's own default: NULLS LAST for ASC, NULLS FIRST for DESC. Both
    -- sides must materialize the default identically or an explicit
    -- "DESC NULLS FIRST" would not match a bare "DESC".
    coalesce(
      nullif(lower(btrim(coalesce(p_nulls, ''))), ''),
      CASE WHEN v.direction = 'desc' THEN 'nulls_first' ELSE 'nulls_last' END
    ),
    -- An opclass name in the catalog is always a bare identifier, so folding it
    -- unconditionally is safe here in a way it is NOT for schema/table names.
    coalesce(nullif(lower(btrim(coalesce(p_opclass, ''))), ''), 'default')
  )
  FROM (
    SELECT CASE WHEN lower(btrim(coalesce(p_direction, 'asc'))) = 'desc'
                THEN 'desc' ELSE 'asc' END AS direction
  ) v
$$;

COMMENT ON FUNCTION proof.canonical_index_key(text, text, text, text) IS
  'Canonical form of one index key. Called by both the proposal side and the '
  'catalog-observation side so the comparison tests the action, not two '
  'independent normalizers.';

CREATE OR REPLACE FUNCTION proof.index_action_fingerprint(
  p_action_type text,
  p_schema_name text,
  p_table_name text,
  p_index_method text,
  p_is_unique boolean,
  p_key_columns text[],
  p_included_columns text[],
  p_predicate text
) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  v_canonical jsonb;
BEGIN
  IF p_action_type IS NULL OR p_schema_name IS NULL OR p_table_name IS NULL THEN
    RAISE EXCEPTION
      'index_action_fingerprint requires action type, schema, and table '
      '(got %, %, %)', p_action_type, p_schema_name, p_table_name;
  END IF;
  IF coalesce(array_length(p_key_columns, 1), 0) = 0 THEN
    RAISE EXCEPTION 'index_action_fingerprint requires at least one key column';
  END IF;
  -- jsonb, NOT a delimiter-joined string. A key expression may legitimately
  -- contain a comma -- lower(substr(note, 1, 5)) -- and joining on one would let
  -- ['a,b','c'] and ['a','b,c'] serialize identically. Measured during this
  -- task's prototype; do not "simplify" back to array_to_string.
  v_canonical := jsonb_build_object(
    'version', 1,
    'action_type', lower(btrim(p_action_type)),
    -- canonical_sql_name, NOT lower(btrim(...)). A bare lower() here folded a
    -- quoted mixed-case relation onto the lower-case one, and workbench_lab."ORDERS"
    -- fingerprinted identically to workbench_lab.orders -- a measured FALSE MATCH
    -- reporting success for an action taken on a different table. The observation
    -- side supplies these already quote_ident()-ed (step 6) so the two derivations
    -- agree on how a name is spelled.
    'schema', proof.canonical_sql_name(p_schema_name),
    'table', proof.canonical_sql_name(p_table_name),
    -- An access method name is always a bare identifier, so folding is safe.
    'method', lower(btrim(coalesce(p_index_method, 'btree'))),
    -- A UNIQUE index and a plain index on the same column are different
    -- actions with different semantics. Omitting this collapsed them during
    -- the prototype.
    'unique', coalesce(p_is_unique, false),
    -- Ordered: key order is semantically load-bearing.
    'keys', to_jsonb(p_key_columns),
    -- Unordered: INCLUDE columns are a payload set, so sort for stability. They
    -- are canonicalized BEFORE sorting, and sorted on the canonical form -- the
    -- earlier draft sorted the raw values and folded nothing, so a proposal
    -- naming `Created_At` never matched the catalog's `created_at`. Sorting on
    -- the raw value would also order 'Zebra' before 'apple' by byte value while
    -- the catalog side orders the folded names, reintroducing the mismatch for
    -- multi-column INCLUDE lists.
    'include', to_jsonb(coalesce(
      (SELECT array_agg(proof.canonical_sql_name(c)
                        ORDER BY proof.canonical_sql_name(c))
         FROM unnest(coalesce(p_included_columns, '{}')) AS c),
      '{}'::text[]
    )),
    'predicate', coalesce(btrim(p_predicate), '')
  );
  RETURN encode(sha256(convert_to(v_canonical::text, 'UTF8')), 'hex');
END
$$;

COMMENT ON FUNCTION proof.index_action_fingerprint(
  text, text, text, text, boolean, text[], text[], text
) IS
  'Authoritative equality test for a proposed vs executed index action. Raw SQL '
  'hashes are stored for audit but never compared: whitespace, quoting, and '
  'equivalent PostgreSQL syntax make raw-hash equality brittle.';

-- Reads an index's real shape out of the catalog and fingerprints it with the
-- SAME function the proposal side used. Nothing here parses the participant's
-- typed SQL: reading the definition back from the catalog rather than trusting
-- the input is what makes the comparison evidence rather than assertion.
CREATE OR REPLACE FUNCTION proof.observed_index_fingerprint(p_index_oid oid)
RETURNS TABLE (
  fingerprint text,
  schema_name text,
  table_name text,
  index_name text,
  index_method text,
  is_unique boolean,
  key_columns text[],
  included_columns text[],
  predicate text,
  index_definition text
)
LANGUAGE sql STABLE AS $$
  WITH idx AS (
    SELECT i.indexrelid,
           i.indrelid,
           i.indnkeyatts,
           i.indnatts,
           i.indoption,
           i.indclass,
           i.indpred,
           i.indisunique,
           -- quote_ident, NOT the bare relname. pg_class stores names DECODED:
           -- relname is `ORDERS` for both "ORDERS" and (impossibly) an unquoted
           -- one, and lower()ing it collapsed workbench_lab."ORDERS" onto
           -- workbench_lab.orders -- a measured FALSE MATCH on a different table.
           -- quote_ident renders `orders` as orders and `ORDERS` as "ORDERS", which
           -- is exactly the distinction proof.canonical_sql_name preserves, and it
           -- is how pg_get_indexdef already renders the key and INCLUDE columns.
           -- Both derivations must present names in the same notation.
           quote_ident(ns.nspname) AS schema_name,
           quote_ident(tbl.relname) AS table_name,
           irel.relname AS index_name,
           am.amname AS index_method
    FROM pg_index i
    JOIN pg_class irel ON irel.oid = i.indexrelid
    JOIN pg_class tbl ON tbl.oid = i.indrelid
    JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
    JOIN pg_am am ON am.oid = irel.relam
    WHERE i.indexrelid = p_index_oid
  ),
  keys AS (
    -- The 3-argument pg_get_indexdef returns ONE column's expression, which is
    -- what makes per-key canonicalization possible; the 1-argument form returns
    -- the whole CREATE INDEX statement and would have to be re-parsed.
    -- indoption bit 0 = DESC, bit 1 = NULLS FIRST.
    SELECT k.ord,
           proof.canonical_index_key(
             pg_get_indexdef(idx.indexrelid, k.ord::int, false),
             CASE WHEN (idx.indoption[k.ord - 1] & 1) = 1 THEN 'desc' ELSE 'asc' END,
             CASE WHEN (idx.indoption[k.ord - 1] & 2) = 2
                  THEN 'nulls_first' ELSE 'nulls_last' END,
             -- A default opclass is elided so the observation side does not
             -- require the proposal side to know catalog opclass names.
             CASE WHEN opc.opcdefault THEN NULL ELSE opc.opcname END
           ) AS key_repr
    FROM idx
    CROSS JOIN generate_series(1, idx.indnkeyatts) AS k(ord)
    JOIN pg_opclass opc ON opc.oid = idx.indclass[k.ord - 1]
  ),
  included AS (
    -- Attributes past indnkeyatts are INCLUDE columns. This range is empty for
    -- an index without INCLUDE, which is the expected Lab 4 case.
    SELECT pg_get_indexdef(idx.indexrelid, k.ord::int, false) AS col
    FROM idx
    CROSS JOIN generate_series(idx.indnkeyatts + 1, idx.indnatts) AS k(ord)
  ),
  shaped AS (
    SELECT idx.schema_name,
           idx.table_name,
           idx.index_name,
           idx.index_method,
           idx.indisunique AS is_unique,
           (SELECT array_agg(key_repr ORDER BY ord) FROM keys) AS key_columns,
           coalesce((SELECT array_agg(col ORDER BY col) FROM included), '{}')
             AS included_columns,
           -- pg_get_expr normalizes the predicate in the catalog, so
           -- "where amount > 100", "where (amount>100)", and
           -- "where ((orders.amount) > 100::numeric)" all arrive identical.
           -- Measured in this task's prototype.
           pg_get_expr(idx.indpred, idx.indrelid) AS predicate,
           pg_get_indexdef(idx.indexrelid) AS index_definition
    FROM idx
  )
  SELECT proof.index_action_fingerprint(
           'create_index', schema_name, table_name, index_method,
           is_unique, key_columns, included_columns, predicate
         ),
         schema_name, table_name, index_name, index_method, is_unique,
         key_columns, included_columns, predicate, index_definition
  FROM shaped
$$;

COMMENT ON FUNCTION proof.observed_index_fingerprint(oid) IS
  'Catalog read-back: the real shape of an existing index, fingerprinted with '
  'proof.index_action_fingerprint. Never parses participant-supplied SQL.';

-- Computed, never narrated. The participant does not get told "this looks safe";
-- they get two booleans and, when false, the specific reasons.
--
-- THE INVARIANT: post-execution evidence NEVER feeds pre_execution_eligible.
-- The pre-execution branch below reads no column of proof.action_executions.
-- Successful post-execution evidence must not be used retroactively to claim
-- the action was safe beforehand -- this is an autonomy-READINESS assessment,
-- not autonomous execution. G-34 exists to prove that path is absent rather
-- than merely unused.
CREATE OR REPLACE FUNCTION proof.autonomy_readiness(p_proposal_id uuid)
RETURNS TABLE (
  pre_execution_eligible boolean,
  pre_execution_reasons text[],
  post_execution_validated boolean,
  post_execution_reasons text[]
)
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_proposal proof.action_proposals%ROWTYPE;
  v_exec proof.action_executions%ROWTYPE;
  v_pre text[] := '{}';
  v_post text[] := '{}';
  v_cited integer;
  v_validated integer;
BEGIN
  SELECT * INTO v_proposal
    FROM proof.action_proposals WHERE proposal_id = p_proposal_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'no action proposal %', p_proposal_id;
  END IF;

  -- Requirement 1: an allowlisted action.
  IF v_proposal.action_type <> 'create_index' THEN
    v_pre := v_pre || format('action type %L is not allowlisted',
                             v_proposal.action_type);
  END IF;

  -- Requirement 2: an approved target. Hardcoded literals, not a lookup against
  -- the schema being judged -- see the gate-self-reference-fail-open hazard.
  IF (v_proposal.target_schema, v_proposal.target_table)
     <> ('workbench_lab', 'orders') THEN
    v_pre := v_pre || format('target %I.%I is not an approved target',
                             v_proposal.target_schema, v_proposal.target_table);
  END IF;

  -- Requirement 3: preconditions recorded AND all satisfied. An empty list is
  -- its own failure: "nothing was checked" is not "everything passed".
  IF jsonb_array_length(v_proposal.preconditions) = 0 THEN
    v_pre := v_pre || 'no preconditions were recorded'::text;
  ELSIF EXISTS (
    SELECT 1
    FROM jsonb_array_elements(v_proposal.preconditions) AS p
    WHERE coalesce((p.value ->> 'satisfied')::boolean, false) IS NOT TRUE
  ) THEN
    v_pre := v_pre || 'at least one precondition is unsatisfied'::text;
  END IF;

  -- Requirement 4: bounded timeouts. Both, not either.
  IF v_proposal.statement_timeout IS NULL OR v_proposal.lock_timeout IS NULL THEN
    v_pre := v_pre
             || 'statement_timeout and lock_timeout must both be bounded'::text;
  END IF;

  -- Requirement 5: rollback guidance, in either form.
  IF btrim(coalesce(v_proposal.rollback_sql, '')) = ''
     AND btrim(coalesce(v_proposal.rollback_guidance, '')) = '' THEN
    v_pre := v_pre || 'no rollback guidance was recorded'::text;
  END IF;

  -- Requirement 6: validated citations. proof.validate_answer_citations() is the
  -- same function that governs the agent's answer, so a proposal cannot be
  -- supported by a citation the answer layer would have rejected.
  --
  -- COUNT THE VALIDATED ONES AND REQUIRE ALL OF THEM. Counting the INVALID ones
  -- and requiring zero is the same test only when every link actually reaches a
  -- validation row, and a link can fail to reach one WITHOUT being invalid. The
  -- inner join then drops it, `v_invalid` stays 0, and the proposal is called
  -- eligible on evidence that was never checked -- fail-open, in the one function
  -- whose entire purpose is to refuse.
  --
  -- MEASURED on PostgreSQL 17.10, 2026-08-04, against a probe carrying this
  -- schema's real policies. proof.validate_answer_citations (sql/06_receipts.sql:67)
  -- INNER JOINs retrieval.documents and retrieval.chunks, both ENABLE + FORCE
  -- ROW LEVEL SECURITY (sql/11_roles_rls.sql:446-449) with policies keyed on
  -- acl_visibility (lines 522-536); the API runs this function under the
  -- requesting persona, because backend/app/db.py:169 issues SET LOCAL ROLE per
  -- transaction. A restricted document therefore removes the citation's
  -- validation row for that persona while the LINK stays visible -- the link
  -- table has no evidence_id, so step 12's policy is the bare parent-run check,
  -- strictly weaker than proof.answer_citations' policy, which DOES carry the
  -- evidence-reachability clause (lines 963-979). Measured on one proposal whose
  -- citation quote does not appear in its chunk: owner
  -- `INELIGIBLE: 1 cited claims failed`, persona `PASSES requirement 6`, with
  -- `visible_links = 1` and `visible_citations = 0`. Same rows, no tampering,
  -- opposite verdicts. With the count inverted, both roles return
  -- `1 of 1 could not be validated`.
  --
  -- The reason string says "could not be validated", not "failed validation",
  -- because unreachable and invalid are different facts and this branch cannot
  -- tell them apart. Do not narrow it back to "failed".
  SELECT count(*) INTO v_cited
    FROM proof.action_proposal_citations
   WHERE proposal_id = p_proposal_id;
  SELECT count(*) INTO v_validated
    FROM proof.action_proposal_citations pc
    JOIN proof.validate_answer_citations(v_proposal.run_id) v
      ON v.citation_number = pc.citation_number
   WHERE pc.proposal_id = p_proposal_id
     AND v.is_valid;
  IF v_cited = 0 THEN
    v_pre := v_pre || 'the proposal cites no evidence'::text;
  ELSIF v_validated < v_cited THEN
    v_pre := v_pre || format('%s of %s cited claims could not be validated',
                             v_cited - v_validated, v_cited);
  END IF;

  -- Post-execution branch. Reads ONLY the execution record; contributes nothing
  -- to v_pre above.
  -- recorded_seq is the tiebreak, not decoration. Two rows recorded inside one
  -- transaction share an approved_at (now() is transaction start time), and
  -- ordering on approved_at alone would let the verdict differ between two calls
  -- with no intervening write. See the column comment in step 3.
  SELECT * INTO v_exec
    FROM proof.action_executions
   WHERE proposal_id = p_proposal_id
   ORDER BY approved_at DESC, recorded_seq DESC
   LIMIT 1;
  IF NOT FOUND THEN
    v_post := v_post || 'no execution has been recorded yet'::text;
  ELSE
    IF v_exec.outcome <> 'succeeded' THEN
      v_post := v_post || format('execution outcome was %L', v_exec.outcome);
    END IF;
    IF v_exec.fingerprint_matches IS NOT TRUE
       OR v_exec.observed_fingerprint
            IS DISTINCT FROM v_proposal.proposed_fingerprint THEN
      v_post := v_post
                || 'the executed action does not match the proposed action'::text;
    END IF;
    IF v_exec.wave_b_capture_id IS NULL OR v_exec.wave_b_ingest_id IS NULL THEN
      v_post := v_post
                || 'the result was not validated by an admitted Validation Evidence capture'::text;
    END IF;
  END IF;

  -- Each literal append above carries an explicit ::text cast. Without it,
  -- PL/pgSQL resolves a bare string appended to text[] as an ARRAY LITERAL and
  -- raises "malformed array literal". Measured during this task's prototype.
  RETURN QUERY SELECT
    (array_length(v_pre, 1) IS NULL), v_pre,
    (array_length(v_post, 1) IS NULL), v_post;
END
$$;

COMMENT ON FUNCTION proof.autonomy_readiness(uuid) IS
  'Two independent verdicts. pre_execution_eligible is computed WITHOUT reading '
  'any execution record, so a successful execution can never retroactively make '
  'an ineligible proposal eligible.';

-- The receipt attachment. SECURITY INVOKER (the default) -- deliberately NOT
-- SECURITY DEFINER, and deliberately granted to nobody. Its only caller is the
-- Validation Evidence recorder, which already runs as the owner. See the plan text above:
-- the DEFINER variant was measured to add no capability and to hand every
-- participant an arbitrary-row write.
--
-- The REVOKE below is necessary but NOT sufficient. This file is in
-- CORE_SQL_FILES and applies BEFORE sql/11_roles_rls.sql, whose persona loop runs
-- `GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA proof` -- evaluated over the
-- functions that exist, which by then includes this one. Measured: persona
-- EXECUTE goes f -> t across those two files. Task A5 step 11a adds the matching
-- targeted REVOKE inside that loop, and step 11b asserts no persona holds
-- EXECUTE. If you make this function SECURITY DEFINER, that stale grant becomes
-- an arbitrary-row write on every execution row -- which is why it is INVOKER.
CREATE OR REPLACE FUNCTION proof.attach_wave_b_receipt(
  p_execution_id uuid,
  p_capture_id uuid,
  p_ingest_id uuid
) RETURNS void
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, proof, evidence AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM evidence.incident_capture_runs capture
    JOIN evidence.ingest_receipts receipt
      ON receipt.source_uri = capture.source_bundle_uri
    WHERE capture.capture_id = p_capture_id
      AND capture.wave = 'B'
      AND receipt.ingest_id = p_ingest_id
  ) THEN
    RAISE EXCEPTION
      'capture % and ingest receipt % are not one admitted Validation Evidence bundle',
      p_capture_id, p_ingest_id;
  END IF;

  UPDATE proof.action_executions
     SET wave_b_capture_id = p_capture_id,
         wave_b_ingest_id = p_ingest_id
   WHERE execution_id = p_execution_id
     AND wave_b_capture_id IS NULL
     AND wave_b_ingest_id IS NULL;
  IF NOT FOUND THEN
    RAISE EXCEPTION
      'execution % does not exist or already carries a Validation Evidence receipt',
      p_execution_id;
  END IF;
END
$$;

REVOKE ALL ON FUNCTION proof.attach_wave_b_receipt(uuid, uuid, uuid) FROM PUBLIC;

COMMENT ON FUNCTION proof.attach_wave_b_receipt(uuid, uuid, uuid) IS
  'Attaches a Validation Evidence receipt to an already-recorded execution, once. Exists so '
  'the execution can be recorded BEFORE admission -- a successful CREATE INDEX '
  'followed by a failed admission must not vanish. Owner-only by design: the '
  'recorder that calls it already runs as the owner, so no GRANT is needed. Two '
  'REVOKEs keep it that way -- the one below, and the targeted one in '
  'sql/11_roles_rls.sql''s persona loop that undoes that file''s blanket GRANT '
  'EXECUTE ON ALL FUNCTIONS IN SCHEMA proof.';

-- The append-only rule, enforced where privilege cannot reach: the OWNER can
-- UPDATE this table, and the whole comparison collapses if a mismatch can be
-- edited into a match. Only the two Validation Evidence receipt columns may ever change, and
-- only from NULL.
--
-- MEASURED on PostgreSQL 17.10, 2026-08-04, and TWO drafts of this trigger were
-- measured wrong before this one:
--
-- 1. The first draft silently reverted protected columns
--    (`NEW.outcome := OLD.outcome`) instead of raising. An `UPDATE` that set
--    `fingerprint_matches = true` and a receipt in ONE statement then succeeded,
--    wrote the receipt, kept the honest verdict -- and reported no error at all.
--    The caller believed it had rewritten the verdict; the log showed a
--    successful UPDATE. Silent correction is the wrong failure mode for an
--    integrity rule: it leaves the operator with a false belief and leaves
--    nothing behind. This version raises.
--
-- 2. The second draft refused ANY update to a row that already carried a
--    receipt. That also refuses the `ON DELETE SET NULL` on both receipt foreign
--    keys, because a referential action IS an UPDATE and fires BEFORE UPDATE
--    triggers. Measured: `DELETE FROM evidence.incident_capture_runs` on a
--    referenced capture failed with `execution ... already carries a Validation Evidence
--    receipt`, the delete rolled back, and the capture became undeletable for as
--    long as the execution row existed. So the rule is stated on the TRANSITION,
--    not on the row: NULL -> value is an attach, value -> NULL is the engine
--    clearing a dangling reference, value -> different value is the overwrite
--    that must never happen.
CREATE OR REPLACE FUNCTION proof.action_executions_append_only()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, proof AS $$
BEGIN
  IF ROW(
       NEW.execution_id,
       NEW.proposal_id,
       NEW.run_id,
       NEW.recorded_seq,
       NEW.approved_by,
       NEW.approved_at,
       NEW.executed_sql,
       NEW.executed_sql_sha256,
       NEW.observed_index_definition,
       NEW.observed_fingerprint,
       NEW.fingerprint_matches,
       NEW.outcome,
       NEW.outcome_detail,
       NEW.started_at,
       NEW.completed_at,
       NEW.plan_before_checkpoint,
       NEW.plan_after_checkpoint
     ) IS DISTINCT FROM ROW(
       OLD.execution_id,
       OLD.proposal_id,
       OLD.run_id,
       OLD.recorded_seq,
       OLD.approved_by,
       OLD.approved_at,
       OLD.executed_sql,
       OLD.executed_sql_sha256,
       OLD.observed_index_definition,
       OLD.observed_fingerprint,
       OLD.fingerprint_matches,
       OLD.outcome,
       OLD.outcome_detail,
       OLD.started_at,
       OLD.completed_at,
       OLD.plan_before_checkpoint,
       OLD.plan_after_checkpoint
     ) THEN
    RAISE EXCEPTION
      'proof.action_executions is append-only except for its Validation Evidence receipt; '
      'execution % attempted to change a verdict or provenance column',
      OLD.execution_id;
  END IF;
  IF (OLD.wave_b_capture_id IS NOT NULL
      AND NEW.wave_b_capture_id IS NOT NULL
      AND NEW.wave_b_capture_id <> OLD.wave_b_capture_id)
     OR (OLD.wave_b_ingest_id IS NOT NULL
         AND NEW.wave_b_ingest_id IS NOT NULL
         AND NEW.wave_b_ingest_id <> OLD.wave_b_ingest_id) THEN
    RAISE EXCEPTION
      'execution % already carries a different Validation Evidence receipt',
      OLD.execution_id;
  END IF;
  RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS action_executions_append_only
  ON proof.action_executions;
CREATE TRIGGER action_executions_append_only
  BEFORE UPDATE ON proof.action_executions
  FOR EACH ROW EXECUTE FUNCTION proof.action_executions_append_only();
