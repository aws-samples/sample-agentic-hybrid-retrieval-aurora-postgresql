# Remediation status

Tracks the six-task remediation plan and the pre-release handoff. States:
pending, in progress, code verified, runtime verified, blocked. Runtime
verification means a recorded run against Aurora or a deployed environment;
offline tests never promote a task past code verified.

## Baseline

- Source revision at start: `2a37629` on `main`, with an uncommitted dataset
  v2 change set in the maintainer's worktree (catalog scripts, evidence loaders,
  release archive, lab runner gate) and pre-existing maintainer edits to
  `AGENTS.md`, `CLAUDE.md`, `README.md`, `docs/index.md`, `workshop.md`.
- `docs/hardening-review.md` is not present in this checkout; findings it
  cites (H3, M4, A-M6, A-P1, A-P3, A-H4, A-H5, A-U7) were revalidated against
  current code instead of taken from the review.
- Toolchain: Python 3.13 via `uv` (`.venv`), ruff, pytest; Node via `ui/`
  lockfile; PostgreSQL work only against Aurora.
- Offline baseline before remediation: `make lint` pass, `make validate` pass,
  full offline pytest 1,681 passed / 62 skipped (skips are the `aurora`-marked
  files, which need `DATABASE_URL`).
- Environments: the maintainer's Aurora dev cluster (databases `mosaic_catalog`
  and `mosaic_v2`). No fresh rehearsal environment and no companion Workshop
  Studio credentials in this session.

## Merged state checks

After merging Tasks 3 and 5 onto `main` (`24dc0d3`): full offline pytest
1,737 passed / 62 skipped; UI `tsc --noEmit` clean and vitest 741 passed;
`make lint`, `make validate`, `git diff --check` clean.

## Live verification against the v2 database (dev cluster, 2026-09-26)

Run with the maintainer's Aurora DSN pointed at `mosaic_v2` (dataset
`reviews-2023-v2`, synthetic base loaded). The measured Lab 1, Lab 2 and
Lab 3 runs through the v2 API passed their broken-then-repaired contracts;
the fixture files that encoded the v1 targets were rewritten to the ViewSonic
and Steelcase Gesture (Licorice) anchors. The access-control task's 90-second
agent-turn deadline was too tight for a Lab 3 turn that retries synthesis (one
turn exceeded it); the healthy repaired turn measured 35.7 s of tool time
including a 16.8 s synthesis, and each Lab 3 phase took 62 s of wall clock
including the runner's checks, so the default is now 180 s.

The 553,911-row catalog exposed a second defect: `matches_filter_values` and
`matches_filters` were declared IMMUTABLE while their enum casts are only
STABLE, so PostgreSQL never inlined them and every whole-view scan called the
function per row after building the full document row, embedding included.
Shop browse and batched counts took about 30 s per filter set and returned
503 under the new 30 s statement timeout. Both functions are now STABLE and
the Shop paths pass the scalar columns, so the rule inlines into plain
predicates (0.2 to 0.5 s per count, category filters through the index).

Final live gates on `mosaic_v2` (2026-09-26 03:20): `make validate-missions`
with `MISSION_GATE_REQUIRE_DB=1` (111 checks), `make validate-evals`
(720, 15 and 38 judged targets), `make validate-lab-1`, `-2` and `-3`
(production-path validation passed), the independent relevance contract
(24 queries) and the held-out ESCI contract (407 queries) all pass. Offline:
1,834 passed / 62 skipped; UI 751 passed; `make lint`, `make validate`,
`tsc --noEmit` and `git diff --check` clean. The billed canonical scorecard
was not re-measured: `data/evals/canonical_queries.jsonl` mixes twelve
`synthetic-legacy` queries with nine real-catalog queries, and
`require_single_served_catalog` (added on 2026-09-22) refuses paid scoring
of a mixed set while a real catalog is served. The committed scorecard
therefore still stamps revision `47bf847`, and its attribution stays hidden
until the maintainer splits the query set by catalog and scores the real
one against `reviews-2023-v2`.

## Pre-release handoff

| Item | State | Notes |
| --- | --- | --- |
| 1. Remove `httpx2` | merged to `main` (`68cf412`) | Removed from `pyproject.toml`, re-locked; `uv.lock` no longer lists `httpx2`, `httpcore2` or `httpx2-jsfetch`; `make lint` and `make validate` pass. The MCP server keeps its own lock. |
| 2. Validate `ASSETS_PREFIX` | already done at `2a37629` | `deploy/mosaic-bootstrap.sh` checks it through `required_defined_environment` with the documented empty-allowed rule. |
| 3. Split the shared secret | merged with Task 1; sibling template and validator updated | Folded into Task 1 below (`CODE_EDITOR_OS_PASSWORD` generated in-script, `CODE_EDITOR_CONNECTION_TOKEN` and `ORIGIN_VERIFY_SECRET` supplied by the stack). |
| 4. Rate-limit the Bedrock-backed API | merged with Task 1 | Folded into Task 1 below: nginx 5 r/s per client with burst 20, 30 r/s shared with burst 60, 20 connections per client; application admission of 12 concurrent model runs and 120 per minute per process. |
| 5. Hardening review Medium findings | blocked | `docs/hardening-review.md` is not in this checkout. |

Report-only items (numbers left unchanged as instructed): the 40/45-minute
hands-on budget appears with different arithmetic in `CLAUDE.md`, the mission
contract `session` block and `docs/instructor-guide.md`; the model pin
`global.anthropic.claude-sonnet-4-6` must match IAM and intake; several docs
(`docs/hnsw-focused-product-prompts.md`, `docs/media-regeneration-batches.md`)
are maintainer material rather than participant-path material and belong under
a maintainer index.

## Remediation tasks

| Task | State | Branch | Notes |
| --- | --- | --- | --- |
| 1. Bound access and resource consumption | code verified, merged to `main` (`ff42272`, `c42de79`); runtime blocked | merged | `service/access_control.py`: origin-header verification on every route but `/api/health`, fail-closed startup, loopback-only dev bypass; admission semaphore and rate window with 429 and Retry-After; transaction-local statement and lock timeouts on every checkout; agent-turn deadline; three bootstrap secrets instead of one; nginx per-client, room and connection limits; docs and direct callers updated. Review round 1: rebase onto main needed (readiness gate), the deadline overclaimed what it bounds (an in-flight Bedrock call can run up to BEDROCK_MAX_ATTEMPTS x 65 s after the deadline; now documented), validate_lab.py lacked dotenv, local dev bypass undocumented, stream handler length; all fixed in `c42de79`, 1,839 offline tests pass on the branch. Sibling CloudFormation must supply `ORIGIN_VERIFY_SECRET` (also as the CloudFront origin custom header) and `CODE_EDITOR_CONNECTION_TOKEN`. |
| 2. Cancel abandoned work, prevent stale UI results | code verified, merged to `main` (`52ddf29`, `b292ff4`) | `worktree-agent-abd54f8c5dbefe7be` (`797957f`) | Stop generating with a cancelled terminal state, version-guarded abort in the conversation hook and the Shop search effect, debounced price commits, server disconnect check that stops scheduling further tools, generator closed in `finally`; jump-to-latest control. 729 UI and 1,661 offline tests pass on the branch. Review round 1: a disconnect during the fallback tail could skip persistence of a completed synthesis (blocking, fix requested with a permanent test), page-component import cycle, undersized stop and jump controls, missing StrictMode test; rebase onto Task 1 with the admission slot integrated. Fixed in `b292ff4` (rebased chain `52ddf29`, `bf4412a`): the admission slot is stored on the run state and released once from the agent, a disconnect during the fallback tail still persists the completed synthesis (permanent test), motion constant moved out of the page, 44px controls, StrictMode stop test; 1,842 offline and 749 UI tests pass on the branch. |
| 3. Make the required workshop path obvious | code verified, merged to `main` (`8e896da`, `b936460`) | merged | New `WorkshopProgress` panel on the Playground landing reads `GET /api/labs/state` and the mission contract; CTA into the next unrepaired lab; timing-literal test; docs updated. UI tests 734 pass, lint and audit clean. Review round 1: CTA read "Continue Lab 1" for a fresh participant (no API fact separates never-attempted from still-broken), repaired-rule predicate and lab-state fetch duplicated, failed reads indistinguishable from a fresh start; fixed in `9fc84ac`: CTA reads Open / Continue / Review from settled state, shared `isLabRepaired` predicate and `useLabStates` hook, distinct failed-read line, token-based sizes; 741 UI tests pass. README and workshop.md updates are the coordinator's cutover pass. Keyboard and 390/1440 walkthrough still owed by a maintainer. |
| 4. Reduce UI maintenance cost | code verified, merged to `main` (`bf4412a`, `b292ff4`) | same branch (`7521143`) | Ask Mosaic split into types, stage progress, evidence panels and result cards (1,600 to 808 lines); Shop filter sheet extracted (2,026 to 1,797 lines); both global stylesheets split by surface with byte-identical concatenation; ratchet tests scan every sheet; design-system doc updated. Remaining large file: `CatalogPage.tsx`. |
| 5. Independent relevance evidence | code verified, merged to `main` (`570460a`, `24dc0d3`); corpus re-pointed at `reviews-2023-v2` and its live contract passes; measured run still owed | merged | 24-query coverage probe (4 catalog cohorts x 6 request shapes) with 65 judgments derived from the lab-products file, runner `scripts/independent_relevance_eval.py` over the production retrieval service, 28 tests, `docs/evaluation-plan.md` section. Review round 1: seven of the twelve judged products are already in the canonical scorecard and four are live mission anchors, so item-level independence fails; agent-authored judgments were labelled reviewed. Fixed in `0a0f42d`: per-judgment anchor_overlap (4 mission, 3 canonical, 5 none) cross-checked by a test, vocabulary agent_grounded / agent_inferred / reviewed (human, with reviewer and date) / esci_human, certified tier empty until a human reviews, ranks from final_rank, ESCI held-out file contract with a disjointness check; 1,715 offline tests pass on the branch. Follow-up done on 2026-09-26: `scripts/prepare_esci_held_out.py` built `data/evals/esci_held_out_queries.jsonl` against `reviews-2023-v2` (407 human-judged queries, 2,096 judgments, disjoint from the 141 tuning queries and the canonical set; refurbished and other filter-ineligible judgments dropped with counts); the runner's live contract check passes on it. The measured relevance run is still owed. Measured run blocked on Aurora and Bedrock. |
| 6. Fresh rehearsal and bounded load evidence | code verified, merged to `main` (`a0417c5`, `4390305`); runtime blocked | merged | `scripts/rehearsal.py` records the eleven acceptance steps into a validated manifest; `scripts/load_exercise.py` runs the opt-in bounded concurrency exercise; `docs/rehearsal-runbook.md`; three Makefile targets; 59 tests including redaction and missing-stage falsifiers. Review round 1: the manifest could never report a completed rehearsal (deployment timing never recorded), the first-query timing named in READINESS.md had no field, and redaction missed security-token and tkn= shapes; fixed in `8934ec9` (deployment timestamps, first-query field, security-token and tkn= redaction, admission context before and after load, recovery probe on any saturation, Makefile wiring; 1,738 offline tests pass on the branch). No rehearsal recorded: needs a fresh authorized environment, S3 credentials, Aurora DSN, Bedrock access. |
