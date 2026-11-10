# Mosaic: guidance for coding agents

This is the participant application source for **Build agentic hybrid retrieval
with Amazon Aurora PostgreSQL**. Follow the participant's current Workshop
Studio lab guide first, alongside [START_HERE.md](START_HERE.md). Help them
understand and complete that lab; do not turn a workshop question into repository
maintenance. Claude Code imports this file through the root `CLAUDE.md`.
During an event, follow the sections before **Maintaining this repository**;
that section and the ones under it are for maintainers working outside an event.

## Participant journey and working rules

Alex is setting up a home office. Participants retrieve eligible products, rank
them, then build an agent that supports recommendations with source evidence.
Each lab follows **Broken → Diagnose → Fix → Prove**. The prepared account has
deliberate exercise faults; a wrong answer alone does not mean provisioning failed.
Each started lab's fault is an uncommitted change in its marked file, so `git diff`
shows it before the participant has typed anything: it is the exercise, not their
edit. Answer in plain words; many participants are new to search. When someone asks
where to start or what they will build, give each lab's goal in one sentence and point
to the current lab's first step in the guide (Lab 1 starts in `psql`, with Alex's
request already saved by the guide's Getting started page). Do not say what is
broken, why, or which code to change: finding that is the lab. Name services as the
guide does: Amazon Aurora PostgreSQL, Amazon Bedrock AgentCore.

Before editing, run `uv run python scripts/lab_state.py status`, inspect
`git diff`, and read the current
lab's saved search or agent run. Start from the participant's hypothesis and
observed result. Explain the mechanism and offer a hint before supplying an
answer. Preserve unrelated edits.
Do not silently solve later labs or write their explanation for them.

Each lab's folder under `labs/` holds the file to edit, its README and a
`solution/` copy of the reference answer. Do not read from or copy `solution/`
unless the participant asks for the reference answer.

Change only the current marked `LAB1`, `LAB2`, or `LAB3` seam. Never drop,
rebuild, disable or replace catalog indexes. Do not change retrieval limits,
weights, thresholds, models or tool schemas to make a lab pass. In Lab 3 keep the
supplied instructions as the `system_prompt` along with the tools and execution hooks; a rule
of the participant's own may follow the instructions, but it steers the agent's searches,
not the answer's wording, which the cited-answer step writes under its own fixed prompt.
Use a reset only when the
participant asks to restart a lab. Use `uv run python scripts/lab_state.py
apply-solution --lab N` only when they explicitly request the full recovery path; it
overwrites the exercise seam. `uv run python scripts/lab_state.py finish --lab N`
runs that whole path, from start through the lab's checks, and first finishes
any earlier lab that has not handed off; `skip-to --lab N` finishes the earlier
labs the same way and stops at lab N's start. Use them only when the participant
asks to finish a lab or to start at a later lab. `uv run python scripts/diff.py` names the lines of
the lab files that differ, inside the marked block (without printing the answer)
and outside it (against the original file), and changes nothing; offer it as a
hint. `uv run python scripts/diff.py --answer` also prints the reference answer's
lines, so run it only when the participant asks to compare with the answer.

The terminal already loads this event's settings. Aurora, dependencies, API and
UI are prepared: do not install a replacement stack or start duplicate servers.
Use the existing `DATABASE_URL` without printing it. Never display `.env`, shell
environments, passwords, tokens or connection strings in responses or logs.
The workshop preserves Git for inspecting diffs, but disables participant
commits with a hook. Do not remove that hook or push participant changes.

## Lab map: mechanism, failure, recovery and proof

The mission manifest, `data/evals/mosaic_labs_missions.json`, owns the precise
requests, target IDs, assertions, supporting cases and timings. Read it when a
question needs exact values; do not invent or maintain a second copy here.

| Lab and customer need | Mechanism and wrong answer | Recovery and proof | Files |
|---|---|---|---|
| 1: recover Alex's intended headphones from a transposed listing ID | Full-text search, fuzzy matching and semantic search candidates feed fusion. A disconnected fuzzy matching search returns plausible headphones but omits the requested identity. Reranking cannot recover a missing candidate. | Reconnect the marked retrieval seam. Repeat the identical request and filters; inspect candidate membership, fuzzy matching rank/contribution and the ineligible controls. | `labs/lab1_retrieve/`; `scripts/lab_state.py`; the `retrieve` mission |
| 2: find a monitor for coding, a 4K screen and USB-C charging | RRF combines positions from the three searches before bounded reranking. Collapsed contributions make a tie-breaker select the shortlist; a plausible winner does not prove fusion works. | Repair the marked rank calculation. Inspect unequal source positions and contributions, combined versus final order, and the target's membership. Use the guide's judged-query exercise before claiming a tuning improvement. | `labs/lab2_rank/`; `service/lab_checks.py`; the `rank` mission |
| 3: complete Alex’s home office setup with headphones, monitor and chair and defensible sources | A Strands agent on Runtime calls SQL tools through Gateway. The starting code cannot assemble the agent. Even a running agent can make unsupported compatibility or comfort claims. | Assemble the supplied agent components, deploy, then inspect separate searches, comparison, citations and ranking explanation in the participant's own run. Changed requirements must be checked against the actual records. | `labs/lab3_reason/`; `service/gateway_tools.py`; `scripts/deploy_agentcore.py`; the `reason` mission |

## Participant CLI

Run commands from the prepared repository terminal and follow the guide's order.
Participants use the `uv run` scripts below, exactly as the guides show them;
`service/participant_commands.py` holds the same strings for every message.
The Makefile wraps them for maintainers only.

| Purpose | Command |
|---|---|
| Inspect the current source/applied lab state; Lab 3 reads SOLVED only after your deployed agent passed completion (otherwise "BROKEN", "REPAIRED, NOT DEPLOYED" or "DEPLOYED, NOT YET PROVED") | `uv run python scripts/lab_state.py status` |
| Enter a lab: save its failing request; Labs 2 and 3 also install their fault once | `uv run python scripts/lab_state.py start --lab N` |
| Hand off Lab 1: validate its repair, save passing evidence and prepare Lab 2 without discarding edits; a repaired saved file that Aurora does not run yet is applied first | `uv run python scripts/lab_state.py advance --lab 1` |
| Hand off Lab 2: validate its repair, save passing evidence and install the Retrieval agent's starting code for Lab 3 without discarding edits; a repaired saved file that Aurora does not run yet is applied first | `uv run python scripts/lab_state.py advance --lab 2` |
| Discard one lab's edits and restore its starting code, only when asked to restart; it also puts back a deleted lab file or lab folder from Git's copy, and a `solution/` file whose LAB markers were edited away. `status` reports a deleted file as FILE MISSING; `start --lab 2` and `--lab 3` restore it themselves, while `start --lab 1`, `advance`, `validate`, `diff.py` and `apply_search_functions.py` stop with that message and name `reset` | `uv run python scripts/lab_state.py reset --lab N` |
| Finish a lab with the reference answer, only when asked: start, the answer, apply or deploy, and the lab's checks and hand-off, after any earlier lab not handed off (Lab 3 stops at deploy) | `uv run python scripts/lab_state.py finish --lab N` |
| Start at a later lab, only when asked: the earlier labs are finished as `finish` does, then lab N starts with its own exercise | `uv run python scripts/lab_state.py skip-to --lab N` |
| Name the lines of the lab files that differ from the reference answer, inside and outside the markers, without the answer (changes nothing) | `uv run python scripts/diff.py` |
| The same, with the reference answer's lines, only when the participant asks to compare with the answer | `uv run python scripts/diff.py --answer` |
| Apply the participant's SQL repair in Labs 1 or 2 | `uv run python scripts/apply_search_functions.py` |
| Check the saved source and the SQL Aurora last applied (Labs 1 and 2); `DATABASE_URL` comes from the prepared terminal, and the command reads it itself when the flag is left off; its `Next:` is the lab's proof, for Lab 1 the repeat-request command, then `advance --lab 1` | `uv run python scripts/lab_state.py validate --lab N --database-url "$DATABASE_URL"` |
| Repeat the saved request against the repaired state; prints Before and After | `uv run python scripts/lab_request.py send --lab N --phase after` |
| Prove the Lab 1 or Lab 2 repair after repeating the request (Lab 3 is rejected: it is graded on the saved run) | `uv run python scripts/prove_lab.py --lab N` |
| Grade the participant's own exercise or saved run and record the attempt, without generating a new answer | `uv run python scripts/lab_exercise.py grade --lab N` |
| Run Lab 2's request with reranking off, then on, and print both pages (changes no served setting) | `uv run python labs/lab2_rank/rerank_off_on.py` |
| Judge three retrieval settings in Lab 2 | `uv run python scripts/lab_exercise.py compare --lab 2` |
| Grade the optional HNSW index exercise and save its receipt | `uv run python scripts/hnsw_exercise.py grade` |
| List managed SQL tools | `uv run python scripts/deploy_agentcore.py tools` |
| Deploy edited Lab 3 code and check managed connectivity; shows each of its five steps against its usual time (about 1:11 in all), says how long is left and names the failing step on error | `uv run python scripts/deploy_agentcore.py deploy` |
| Recheck deployed code, Gateway tools and Aurora evidence | `uv run python scripts/deploy_agentcore.py verify` |
| See the agent and tools runtimes, Gateway and Memory a deploy updates (read-only Get calls) | `uv run python scripts/deploy_agentcore.py resources` |
| Ask the deployed agent from the terminal: answer, tool trace, citations, outcome, decline reason and Run ID. Lab 3's setup request and 100W follow-up use it; Ask Mosaic is the optional browser view | `uv run python scripts/ask_agent.py "QUESTION"` |
| Run one sentence through the agent's answer checks, citing a product's listing as [1] (generates and saves nothing) | `uv run python scripts/check_claim.py PRODUCT_ID "SENTENCE [1]"` |
| Grade the participant's newest setup run since Lab 3 started (or one named with `--run-id <run-id>`) | `uv run python scripts/grade_setup_run.py` |
| Inspect the diff for whitespace errors | `git diff --check` |

Each command above ends with a blank line and a `Next:` line that names the step after it
(on a failure, the recovery step), so point a participant to that line before the guide.
Output is coloured only on a terminal; a pipe or `NO_COLOR` gets the same words plain.

A SQL file edit alone does not update Aurora; an agent edit alone does not
update Runtime. Proof must use the newly applied/deployed state. From Lab 3's start,
questions and completion also need a deploy made since that start, even when the code
matches the reference Retrieval agent the account was provisioned with; each deploy is
recorded in `.local/agentcore/deploys.json`. The deploy
`verify` action checks the two separately: the deployed application against Code
Editor's code, and the SQL Aurora last applied against the search SQL in
Code Editor, including the two lab SQL files. Labs 2 and 3 ship repaired and cannot pass
before their start command; a rerun of a start keeps the participant's edits. Preserve
before/after records in `.local/lab-N/`. Never invent a run ID or a passing result.
The deploy `verify` action proves deployment connectivity, not participant completion.
The guide's final Lab 3 command evaluates the saved run without generating a
replacement answer. Optional exercises follow required completion, in the guide's order: Scale & HNSW, Session & Memory, Retrieval tool, Review examples.

## Evidence and policy boundary

Aurora stores products, vectors, source evidence and audit records. Bedrock
supplies query embeddings, reranking and the agent model. AgentCore Runtime
hosts the Strands agent and an MCP tools runtime; Gateway exposes the SQL tools.
Memory supplies optional conversation context, never current product facts.

Never weaken structured filters, tool authorization, citation checks or
fail-closed behavior. Catalog tools cannot mutate product data, but searches
still write audit records. Registering evidence authorizes a citation; it does
not prove that the text supports a particular claim. Specifications and reviews
have different evidentiary roles. Unknown compatibility stays unknown.

`service/lab_checks.py` is the shared production checker; each `LabCheck` has a
name, pass/fail result, falsifier and detail. `service/lab_proof.py` runs the live
proof, records search-event IDs and checks saved agent evidence.
`GET /api/labs/state` reports source/applied state; labs are proved in the
terminal with the guide's commands, never in the browser. The exact payloads live in
`service/models.py`; inspect them rather than fabricate fields. A release
scorecard is not proof of the participant's repairs. Mission and evaluation
case counts come from the manifests and validators, not a parallel prose list.

## Source map and troubleshooting

- `ui/`: Shop (with Alex's brief) and Playground, including saved results and lab proof.
- `service/`: API, retrieval, tools, evidence and citation checks.
- `labs/`: one folder per lab with the exercise file, README and `solution/`.
- `db/`: the remaining SQL (numbered in install order), indexes, retrieval
  settings and hash-pinned catalog contracts. `db/sql/install.sql` includes the
  two lab SQL files; `service/search_sql.py` lists the search files in that order.
- `scripts/`: participant commands and their helpers at the top level;
  maintainer tooling in `catalog/`, `evals/`, `bench/` and `checks/`
  (see `scripts/README.md`).
- `deploy/agentcore/`: managed entry points; `deploy/mosaic-bootstrap.sh`: host setup.
- `skills/mosaic-hybrid-retrieval/`: portable retrieval skill and adaptation notes.

Capture the failing command, redacted error, lab state and relevant saved
request/run ID. Check whether the source was applied or deployed before
diagnosing model behavior. If Aurora, Bedrock, Gateway, the API or UI is
unhealthy, identify an **environment failure** and give the facilitator the
evidence. Do not substitute data, relax checks or add IAM grants to bypass it.
Facilitators can inspect CloudFormation's first failed resource,
`/var/log/mosaic-bootstrap.log`, `journalctl -u mosaic-bootstrap` (the host's
provisioning runs as that unit and resumes at the next boot; `/var/lib/mosaic-bootstrap/`
holds one `.done` marker per finished phase), `/var/log/cloud-init-output.log`, the
`mosaic-api` / `mosaic-ui` systemd logs, and `mosaic-hnsw-prepare` for the optional
Scale & HNSW page's data, which builds after the stack reports ready. Read only relevant excerpts and redact
secrets; a failed dependency may prevent a later runtime from existing.

Useful explanations: [architecture](docs/architecture.md),
[managed agent](docs/agentcore-runtime.md),
[MCP integration](docs/mcp-interoperability.md), and
[adaptation](docs/use-in-your-app.md). Maintainers should also read
[development](docs/development.md) and [readiness](READINESS.md).

## Maintaining this repository

Everything from here on is for people changing this repository outside an event.
None of it authorizes participant commits, provisioning, catalog reloads or release
changes during a lab.

This file ships in every participant's checkout and `CLAUDE.md` imports it, so keep it
to rules that hold for every reader. Notes that belong to one maintainer or one
account, such as publication authority, cluster details or release history, go in a
Git-ignored `CLAUDE.local.md`, which Claude Code loads beside `CLAUDE.md`. Release
status belongs in [READINESS.md](READINESS.md) and `docs/evidence/`, never in a dated
table here. `tests/test_documentation_contract.py` checks that `CLAUDE.md` only
imports this file, that Git ignores `CLAUDE.local.md` and that every repository path
named here exists.

### Testing and delivery pitfalls

- Run offline Python tests with `PYTHONPATH=. uv run pytest -q`; a bare pytest
  invocation may not resolve `service`. A green offline run skips Aurora-marked
  tests and does not certify database or managed-service behavior.
- `make test` requires the intended Aurora DSN. Load the development `.env` as
  described in [development](docs/development.md); its `MOSAIC_CATALOG_DATASET` must
  match the prepared receipt in the database selected by `DATABASE_URL`. An older
  database on the same cluster is not a substitute. Live probes must select their
  witnesses from the active catalog, because catalog identities and classifications
  can change.
- Source SQL ships repaired; bootstrap installs exercise faults, so distinguish a
  clean source checkout from a participant's current lab state.
- An event's participant checkout is this repository at the source revision the
  Workshop Studio repository pins, `AGENTS.md` and `CLAUDE.md` included. A change
  here reaches events only after that pin moves and a new build is published. The
  separate managed-runtime container image has an explicit application-file
  allowlist; it is not the Code Editor source bundle.
- Catalog assets are Git-ignored and hash-pinned. A fresh clone alone is not a
  complete asset working copy.
- Required gates live in [READINESS.md](READINESS.md). Never describe an offline
  pass, source push or Workshop Studio build as fresh-account acceptance.
- Workshop Studio builds are published from the separate Workshop Studio content
  repository with its authoring credentials, under its own runbooks; nothing in
  this repository publishes an event.

### Aurora only

Do not create a local database or suggest one. Every `make` target reads
`DATABASE_URL`, which must point at an Amazon Aurora PostgreSQL cluster loaded with
the `reviews-2023-v2` catalog: 553,911 real source products, their saved Cohere
Embed v4 vectors and real source evidence. To build one, run
`make db-bootstrap-schema` into a fresh cluster, restore the hash-pinned bundle with
`scripts/catalog/real_catalog_cache.py restore` and select it with
`MOSAIC_CATALOG_DATASET`; `make db-verify-bootstrap` then rejects legacy synthetic
rows. Never load historical synthetic products, reviews, premium cohorts or
vocabulary; their retired loaders exist only in Git history. A Makefile target,
script or document that assumes a local PostgreSQL is a defect to fix, not a
fallback. Policy and rationale: [ARTIFACTS.md](ARTIFACTS.md).

### Single sources

Do not add a second copy of any of these. Each has a check that fails the build.

| Fact | Single source | Enforced by |
|---|---|---|
| Candidate limits, fusion `k`, weights, fuzzy threshold | `db/config/retrieval.yaml` | `scripts/checks/config_tripwire.py` |
| Labs, checkpoints, timings, assertions | `data/evals/mosaic_labs_missions.json` | `scripts/checks/mission_contract.py` |
| Assertion vocabulary + falsifiers | `service/assertions.py` | `A1.6`, `A1.8` |
| Rules for coding agents | `AGENTS.md` (`CLAUDE.md` imports it) | `tests/test_documentation_contract.py` |

Environment variables override the yaml; that is the documented path. A numeric
literal assigned to a limit- or weight-shaped name anywhere else is a failure,
including a TypeScript `?? 60` fallback.

### House standards

[House standards](docs/house-standards.md) are binding for gates, checks, and probes:

1. Errors name the rule, show the offending value, and suggest the nearest fix.
2. Every assertion declares a falsifier; one that cannot fail is deleted.
3. Probes run the production path: `matches_filters` and `configure_hnsw` are
   the exemplars, both learned from measured wrong answers.
4. A green check is not evidence: prove every new gate red at birth, restore
   byte-identical, and keep the violation as a permanent test.
5. An exemption is a monitored seam: exempt from declaring, never from agreeing.
6. Aurora only.

### Validation

```sh
make lint                       # ruff check and format, bootstrap copy in sync
make validate-config            # retrieval profile, config tripwire, tool contracts
PYTHONPATH=. uv run pytest -q   # offline Python contracts
make validate-missions          # contract shape + live target checks (needs DSN)
make validate-evals             # real canonical, coverage and held-out contracts (needs DSN)
make test                       # Python, including Aurora-marked tests (needs DSN)
cd ui && npm test && npm run build
```

Set `MISSION_GATE_REQUIRE_DB=1` in CI so a missing mission-gate DSN is a loud
failure rather than a silent skip. `make validate-evals` always requires Aurora.

### Coding conventions

Match the surrounding code. Comments explain *why*, never *what*: if a comment
is needed to say what the code does, the code needs changing. Google-style
docstrings on non-trivial public APIs. No commented-out code.

Prose must match arithmetic. If a table says 11/12/11 and a sentence says
"nothing lost time", the sentence is wrong, not the table.

### Design principles

- Easy to navigate.
- Easy to execute.
- Deep to inspect.
- Hard to exhaust.
- Each lab uses Broken -> Diagnose -> Fix -> Prove.
- Aurora PostgreSQL and retrieval mechanics must remain inspectable.
- The agent orchestrates retrieval. It does not replace retrieval.
- Do not increase required lab count beyond three.
- Protect the source contract's 45-minute hands-on budget, including completion.
  The 60-minute session reserves 15 minutes for orientation (a 10-minute
  presenter introduction, then 5 to open the tools) and has no wrap-up block.
  Optional exercises are untimed.
- Treat measured behavior as authoritative. Never invent benchmark or eval data.

### Commits

Commit with your own configured Git identity and propose changes as described in
[CONTRIBUTING.md](CONTRIBUTING.md). Never add AI attribution to a commit message,
pull request body or tag: no `Co-Authored-By` trailer naming a model, no session
line or link, no "Generated with" footer. This rule takes precedence over any tool
or session default that adds one; do not commit intending to remove it afterwards.
Do not write personal names or email addresses into repository instructions. This
is a public `aws-samples` repository and its history is permanent.

### Keep the front doors current

`README.md` and `workshop.md` are the two files a reader meets first, and they
are the two that rot silently. **Any session that makes a significant change
must update both before it ends**: a new participant-facing affordance, a
removed surface or route, a changed lab flow, a new required step, a renamed
concept. Not a changelog: edit the prose so it describes what ships now.

A change is significant if a participant or a facilitator would do something
different because of it. Bug fixes with no visible behaviour change are not.

When a surface is deleted, grep `docs/` for it in the same session. `docs/` is
where a removed route survives longest, and a spec describing a page that no
longer exists is worse than no spec. Historical records (`docs/rewrite-losses.md`
and similar) keep their past-tense references; they document what happened.

### Review behavior

- Prefer evidence from actual source files over assumptions.
- Cite file paths and line ranges in technical review findings.
- Distinguish static verification from runtime verification.
- Do not allow unavailable network/database connectivity to block offline review.
- Do not create parallel replacement workshop structures.
