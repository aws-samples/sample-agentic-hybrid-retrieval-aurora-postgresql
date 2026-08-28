# Working in this repository

Read this before editing. It carries the constraints that are not derivable from
the code.

## Infrastructure: Aurora only

**Do not create a local database. Do not suggest one.**

The Aurora PostgreSQL cluster in `us-east-1` holds the only live tree
(`mosaic_*`), 500,000 products with real Cohere Embed v4 vectors. Every `make`
target reads `DATABASE_URL` and must point at Aurora.

The restore path is `make db-bootstrap-cached` into a **fresh** Aurora cluster,
loading the verified embedding cache, which is what Workshop Studio provisions
and what `ARTIFACTS.md` records. `make db-upgrade-snapshot` is an operator-only
compatibility path for historical snapshot restores, not the primary route.

Any Makefile target, script, or document assuming a local PostgreSQL is a defect
to fix, not a fallback to use. Full policy and rationale: `ARTIFACTS.md`.

The reason is concrete. The pre-rewrite `catalog.*` tree's loaded state existed
only in two local databases; they were dropped in August 2026, and 500,000 rows
of real embeddings cannot be reconstructed without re-embedding. That permanently
removed the ability to diff any ported script against its predecessor.

## Single sources

Do not add a second copy of any of these. Each has a check that fails the build.

| Fact | Single source | Enforced by |
|---|---|---|
| Candidate limits, fusion `k`, weights, trigram threshold | `db/config/retrieval.yaml` | `scripts/config_tripwire.py` |
| Labs, checkpoints, timings, assertions | `data/evals/mosaic_labs_missions.json` | `scripts/mission_contract.py` |
| Assertion vocabulary + falsifiers | `service/assertions.py` | `A1.6`, `A1.8` |

Environment variables override the yaml; that is the documented path. A numeric
literal assigned to a limit- or weight-shaped name anywhere else is a failure,
including a TypeScript `?? 60` fallback.

## House standards

`docs/house-standards.md` is binding for gates, checks, and probes:

1. Errors name the rule, show the offending value, and suggest the nearest fix.
2. Every assertion declares a falsifier; one that cannot fail is deleted.
3. Probes run the production path — `matches_filters` and `configure_hnsw` are
   the exemplars, both learned from measured wrong answers.
4. A green check is not evidence: prove every new gate red at birth, restore
   byte-identical, and keep the violation as a permanent test.
5. An exemption is a monitored seam — exempt from declaring, never from agreeing.
6. Aurora only.

## Validation

```sh
make validate-missions      # contract shape + live target checks (needs DSN)
make validate-evals         # 720 production-filter targets (needs DSN)
python scripts/config_tripwire.py
python scripts/retrieval_profile.py --check
make test                  # Python
cd ui && npm test && npm run build
```

Set `MISSION_GATE_REQUIRE_DB=1` in CI so a missing mission-gate DSN is a loud
failure rather than a silent skip. `make validate-evals` always requires Aurora.

## Coding conventions

Match the surrounding code. Comments explain *why*, never *what* — if a comment
is needed to say what the code does, the code needs changing. Google-style
docstrings on non-trivial public APIs. No commented-out code.

Prose must match arithmetic. If a table says 11/12/11 and a sentence says
"nothing lost time", the sentence is wrong, not the table.
