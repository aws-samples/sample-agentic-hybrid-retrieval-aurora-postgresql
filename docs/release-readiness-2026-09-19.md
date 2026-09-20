# DAT410 pre-publication review

Status: **engineering repairs validated; final measurement and release finalization in progress. No Workshop Studio publication performed.**

This review follows the maintainer's explicit boundary: source changes may be
committed and pushed; Workshop Studio may be edited and validated locally.
Workshop Studio uploads, staging, commits, pushes and publication are reserved
for the maintainer. The human fresh-event rehearsal is excluded from this pass
and remains required. Automated journeys and live integration checks are in scope.

## Scope and starting identities

| Item | Starting state |
| --- | --- |
| Source | `sample-agentic-hybrid-retrieval-aurora-postgresql`, branch `main` |
| Source HEAD and independently checked remote main | `900dc82879c9d07d32b4803b94b5728bf74dbb07` |
| Source remote | `https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql.git` |
| Workshop Studio | sibling `build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql`, branch `mainline` |
| Studio local HEAD | `4675a1a41fa86e2c290d6e59191d59556ed6a900` |
| Studio local source pin | `900dc82879c9d07d32b4803b94b5728bf74dbb07` |
| Required track | 60-minute Mosaic Builders session: Retrieve, Rank, Reason; optional extensions follow completion |
| Database | Existing authorized Aurora PostgreSQL in `us-east-1`; no local database |
| Presentations | External DAT410 presentation workspace; 12-slide deck, PDF, notes and video |

The prior handover referenced an older source/Studio state. Its source fixes
on `release-readiness-fable` are byte-equivalent to the ten existing modified
source files at this review's start. They have not been discarded. The earlier
report and both starting diffs are preserved in private local review evidence.
Account identifiers, hostnames and process details belong in that private
evidence rather than this public source repository.

## Acceptance matrix

PASS requires current evidence. FAIL includes a required gate not yet verified;
the explanation distinguishes an observed defect from unfinished validation.
BLOCKED is reserved for an external dependency. NOT APPLICABLE requires a
reason. EXCLUDED applies only to the human rehearsal. Final statuses will replace
these initial entries after repairs and checks.

| Gate | Status | Evidence or remaining work |
| --- | --- | --- |
| Repository scope and source remote identity | PASS | Current branch, dirty state, worktrees and `git ls-remote` inspected |
| Existing work preserved and reconciled | PASS | Starting diffs retained; prior source fixes match current pending edits |
| Backend, API, data and agent correctness/security | FAIL | Complete review and final tests pending; prior findings being reconciled |
| Configuration and single-source contracts | FAIL | Reported uppercase `ef_search` duplication requires verification and repair |
| Lab validators detect meaningful failures | FAIL | Empty-control and broken/repaired cases require proof |
| CI, release automation and dependency checks | FAIL | Live lab CI coverage and environment boundaries require repair/review |
| Offline formatting, lint, tests, type-check and builds | FAIL | Final revision checks pending |
| Aurora bootstrap state, function census, missions and eval targets | FAIL | Final revision checks pending |
| Aurora SQL and billed integration test lanes | FAIL | Final revision checks pending |
| Model access and attributed retrieval evaluation | FAIL | Final revision checks pending; no earlier scorecard is treated as final proof |
| Automated lab failure, repair, completion and reset journeys | FAIL | Final source and established Aurora environment checks pending |
| Rendered UI routes, controls and state transitions | FAIL | Current browser inspection and backend effects pending |
| Keyboard, focus, contrast, motion and responsive layouts | FAIL | Current desktop/laptop/mobile inspection pending |
| Participant guide commands, expected results and recovery | FAIL | Full source/guide consistency pass pending |
| Local Studio rendering, navigation and assets | FAIL | Local preview and asset checks pending |
| CloudFormation, IAM, bootstrap retries and lifecycle | FAIL | AMI lifetime, retry gaps and existing security fixes require validation |
| Contentspec, source pins, derived revision and bootstrap parity | FAIL | Final source publication and local re-pin pending |
| Published assets and hosted artifact identity | FAIL | Read-only delivery checks pending; local success is not hosted proof |
| Deck, PDF, notes, screenshots and media consistency | FAIL | Code examples verified in Aurora; final ordering and presentation pass pending |
| Final task-related source commit, push and remote SHA | FAIL | Final reviewed changes not yet committed/pushed |
| Final clean-source and local Studio release validation | FAIL | Pending final source commit and local re-pin |
| Human fresh-environment Workshop Studio rehearsal | EXCLUDED | Still required after publication; never substituted by these automated checks |

## Publication operations reserved for the maintainer

| Operation | Status |
| --- | --- |
| Workshop Studio asset uploads | PENDING USER ACTION |
| Workshop Studio git staging, commit and push | PENDING USER ACTION |
| Workshop Studio publication/import | PENDING USER ACTION |
| Verification dependent on those operations | PENDING USER ACTION |

Exact reviewed files, commands, checksums and execution order will be recorded
here after the final source SHA and local package are known. No destructive
asset sync or broad staging command will be prescribed.

## Findings and repair evidence

The prior handover's open findings are inputs to this review, not accepted
completion claims. Severity, applicability, fixes and regression evidence will
be recorded here as they are verified. Each final result must identify whether
it used the local final build, an existing deployment, or a published artifact.

## Human rehearsal checklist

After publication, deploy a fresh Workshop Studio event environment; time
bootstrap and the participant path; verify the intended initial broken lab;
complete Retrieve, Rank and Reason by minute 52; exercise recovery, replacement
environment and restart instructions; inspect laptop and projector layouts;
then perform cleanup and check retained resources and costs. Keep the deployment,
source SHA, model access, timing, screenshots, validator outputs and cleanup
evidence together. This checklist is not execution evidence.


## Engineering checkpoint

Aurora production validators pass for all three labs; live database-contract
and model-backed lanes passed 48 and 109 tests respectively. The SQL failure
and repair proof exercised the real retrieval service and providers with the
actual Lab 1/2 defects in rolled-back Aurora transactions. An isolated API with
the actual Lab 3 defect failed closed; the source-error response now identifies
the repair instead of incorrectly suggesting a connectivity outage.

The current frontend suite passes 652 tests. Independent TypeScript and build
checks pass. Full frontend and Python dependency audits found no known
vulnerabilities. The optional, lazy-loaded WebGL illustration still produces a
593 kB chunk warning; it is not loaded for required labs. The Python test client
reports its upstream httpx migration deprecation; no warning was suppressed.

The local Studio package passes 126 validator regression tests, participant
query checks, CloudFormation lint and bootstrap shell checks. Bucket list and
object-head reads were both denied with the configured AWS identity; published
asset delivery remains BLOCKED until an authorized Studio identity checks it.
No existing Mosaic/retrieval CloudFormation stack was returned in the current
account. Existing Aurora checks are not evidence of the new host bootstrap.

The 12-slide v9 deck, PDF, notes and embedded 3840 x 1680 app video are finalized
in the external presentation workspace. Teaching SQL ran against Aurora 18.3;
RRF's defective constant produced the intended tie. Full Bedrock request shape,
result-index bounds, duplicates and invalid response handling passed offline
checks. All notes contain 65–72 words, in the same order as visible content.
The video's original app pixels and saved before/after search IDs were verified;
this review did not relabel them as new footage.
