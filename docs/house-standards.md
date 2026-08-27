# House standards

Rules adopted because something shipped broken without them. Each one names the
failure that produced it, so it can be argued with on evidence rather than
deferred to as style.

These apply to gates, checks, probes, and assertions — the code whose job is to
tell you the truth about other code.

---

## 1. Error style: name the rule, show the value, suggest the nearest fix

Every failure message carries the offending value and the specific edit that
resolves it.

```
FAIL A2.10 hnsw-performance/420001 attribute 'usb_c' exists:
  found filters.attributes names 'usb_c', which the target does not carry;
  fix: did you mean one of ['usb_c_power_w']?
```

**Why.** That message turned a hunt through 500,000 products into a one-line
correction. The mission had shipped with an attribute key the target did not
carry; the predicate was *answerable* — 4,215 other products matched it — so the
run returned a full pool of 50 candidates and simply never contained its own
target. A failure that says only "assertion failed" leaves the reader to
reconstruct the author's intent.

**How.** `explain(found, fix)` in `scripts/mission_contract.py` and
`scripts/retrieval_profile.py`. Tests assert every message contains both halves,
so the style cannot decay silently.

## 2. Every assertion declares a falsifier

An assertion is admitted to the vocabulary only with a stated condition under
which it fails. `service/assertions.py` makes `falsifier` a required dataclass
field and refuses to construct one without it; `A1.8` checks the whole
vocabulary.

**Why.** Phase 1 shipped a lexical arm that returned zero rows on four of six
missions with every gate green, because no assertion named the arm. Phase 2 found
the same shape in `hnsw`. The rule's first real save was preventing a *new*
instance: `typo-recovery` declared `hnsw`, and on an all-misspelled query the
vector arm returns a full 150-row pool while never recalling the target. Adding
`semantic_signal_present` there would have passed forever on pool size while the
arm contributed nothing. Writing the falsifier down is what forced the question.

**How.** If you cannot state what makes it fail, the assertion is decoration —
delete it, or un-declare the thing it claims to prove.

## 3. Probes run the production path

A check that measures the system must call the same functions the request path
calls, with the same setup. Never a reimplementation, and never a shortcut.

**Two exemplars, both learned the hard way.**

`mosaic_search.matches_filters` — `scripts/catalog_contract.py` reimplemented
filter logic by hand and did not know about `max_price_cents`, `in_stock_only`,
or the refurbished and sponsored exclusions the real SQL applies. Two missions
shipped that could not pass, and the gate that existed to catch them was
structurally incapable of it. The mission gate now calls the production function
on the cluster.

`mosaic_search.configure_hnsw` — a probe measuring per-arm recall skipped the
`configure_hnsw` call the service makes before every query. Semantic pools came
back as 0–38 against a 150 cap. Those numbers were an artefact of default
iterative-scan limits, and acting on them would have produced the opposite
decision on three missions. Re-run with the production setup, the same pools are
150.

**Corollary.** Unit tests do not substitute for this. Unit C's yaml migration
passed 166 unit tests while every live search returned `UndefinedFunction`: an
integral float (`1.0` where the old hardcoded default was `1`) changed the SQL
type psycopg inferred, so no `configure_hnsw` overload matched. Only the
end-to-end probe against Aurora saw it.

**Corollary: compare full unions, never served windows.** When a check compares
two orderings of the same set, it must read the **untruncated** result. Any
`LIMIT` applied *after* the thing being compared makes two different orderings
disagree about the tail by construction, so the check fails on a healthy system.

Measured: Unit D's substrate assertion first compared the served 50-row windows of
unweighted and weighted fusion and reported the sets as different — **36 of 50 in
common**. Both functions `LIMIT` after fusion. At full depth both return **250**,
identical, each exactly equal to the arm union. The check was wrong, not the
substrate. `FULL_POOL_LIMIT` must exceed the summed arm caps (120 + 80 + 150) for
this reason, and a test asserts that relation rather than the literal.

## 4. A green check is not evidence on its own

Every new gate is proven red at birth: introduce the violation it exists to
catch, show it fail, restore byte-identical, show it pass. The violation fixture
then **stays as a permanent test**, not a one-time demonstration.

**Why.** A gate that cannot fail is worse than no gate, because it reads as
evidence. Two measured cases in this repository were green-on-broken.

**How.** `tests/test_mission_contract_gate.py` and
`tests/test_config_tripwire.py` hold the fixtures. Restores are verified with
`cmp`, not by eye.

## 5. An exemption is a monitored seam, never a blind spot

Where a rule must be relaxed, the exempted thing is pinned to the value it must
agree with, and the agreement is checked.

**Why.** A PostgreSQL function signature cannot read a config file, so SQL
parameter defaults are exempt from the tripwire's "declare it only in the yaml"
rule. Left there, that exemption is precisely where a second copy would grow
unobserved. So each exempted default is asserted **equal** to its yaml
counterpart: exempt from *declaring*, never from *agreeing*. Same for
`CREATE INDEX` build parameters. An exemption with no yaml counterpart must carry
a written reason.

### 5a. Every seam needs an exhaustiveness rule

A seam monitored by an **enumerated list** decays, because nothing forces the list
to stay complete. Pair every such list with a rule that the enumeration is
exhaustive over its own domain.

Exemplar, the tripwire's rule `C1c`: *all retrieval-named SQL parameter defaults
must be enumerated in `SQL_DEFAULTS`.* Not "the ones we listed agree" — that is
rule 2, and rule 2 alone is satisfiable by an empty list.

**Worked example, measured.** The gap was an assertion-shape mismatch nobody would
guess: rule 1 matched `name = value` and `name: value`, but a SQL default is
`name type DEFAULT value` — **no `=` and no `:`** — so rule 1 could not see a
single one of them, and rule 2 only checked those already listed. Unit D added
**13 defaults, three of them fusion weights**, and the tripwire stayed **green**
with none pinned. Two rules that each looked sound left a hole between them.

The generalization: when a check's pattern and its exemption list are written
separately, ask what the pattern *cannot see*, and make that question a rule.

## 6. Infrastructure: Aurora only

No local databases exist or will exist. The Aurora PostgreSQL cluster in
`us-east-1` holds the only live tree (`mosaic_*`); the cluster snapshot is the
only restore path; every `make` bootstrap target points at Aurora.

**Why.** Two local databases (`catalog_workshop`, `catalog_codex_20260807`) held
the only loaded state of the pre-rewrite `catalog.*` tree. They were dropped in
August 2026. The DDL survives in git; the loaded state does not — 500,000 rows
with real Cohere embeddings are unreconstructible without re-embedding. That
lost the ability to diff any ported script against its predecessor, which is why
Unit E's definition of done is a **correctness** statement against live
`mosaic_*` rather than an equivalence diff.

**Corollary.** Any Makefile target, script, or document assuming a local
Postgres gets updated or deleted. Phase 2 Unit E retired every target that
installed the dead `catalog.*` tree. New work must target the live
`mosaic_*` schema family only.

## 7. Sensitivity is insufficient: every gate needs three proofs

A gate is admitted only with all three, demonstrated and recorded:

1. **Red-at-birth.** The intended violation makes it fail. Introduce the
   violation, show the failure, restore byte-identical.
2. **Independence.** An irrelevant change does *not* make it fail.
3. **Witness.** The code path under test actually executed.

Rule 4 already requires the first. It is not enough on its own, and rule 2's
falsifier is a *claim* about failure rather than a demonstration of it.

**Why.** Eight gates in one change set were logically correct and proved nothing,
because the branch they described never ran. Measured, in escalating subtlety:

- a `pytest.raises` inside a loop over a **provably empty** list, so the raise was
  never awaited;
- a fixture that gave two different rank spaces the **same value**, so swapping
  `final_rank` and `pre_rerank_rank` was undetectable;
- an absence-only assertion (`X not in source`) that passes equally on a
  **deleted** file;
- a check on a workflow guard's *position* that ignored whether the guard had
  **teeth**, so removing its `exit 2` still passed;
- a test asserting a `--strict-markers` mechanism this repo **does not configure**;
- a gate that went red on the right edit but through an **unrelated module's**
  error path, so a refactor there would silently stop it discriminating;
- an envelope-independence probe run against a **single-contract** capability,
  where the comparison loop never executes, so "green" proved nothing;
- a rule whose test **re-derived the production set logic** instead of calling it,
  so deleting the production branch broke no test.

The last two are the reason the witness is a separate proof. The others fail the
first two proofs; those fail *neither* while still proving nothing.

**How.** Assert the witness explicitly. Depending on the gate: assert a collection
is non-empty before iterating it, assert a comparison counter is `> 0`, assert the
fixture holds the multiple records a comparison needs, or have the function under
test report what it examined. Then never satisfy a gate by re-implementing the
logic it is meant to police: **call the production path**, per rule 3.

**Corollary, and the reason this belongs in a workshop repo.** The session's own
thesis is that a correct answer does not prove a correct pipeline. One level down,
a green test does not prove a correct gate. Same failure, same fix: inspect the
mechanism, not the outcome.
