# DAT410 release-readiness review

**Verdict: engineering repairs are validated; publication-dependent checks remain
blocked or pending. Do not describe this as all pre-publication gates passed.**

The maintainer authorized source commits and pushes, and local Workshop Studio
edits and validation. Studio S3 uploads, staging, commits, pushes and publication
remain **PENDING USER ACTION**. The human fresh-event rehearsal is **EXCLUDED**
from this pass and still required. Automated tests are not that rehearsal.

## Scope and release identity

| Item | Identity |
|---|---|
| Source directory | `sample-agentic-hybrid-retrieval-aurora-postgresql` |
| Source branch and remote | `main`; `https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql.git` |
| Starting source and remote main | `900dc82879c9d07d32b4803b94b5728bf74dbb07` |
| Engineering repair commit | `dbcd6cc99f47418e59b1c7942105d83925cea6b5` |
| First remeasurement commit | `285e0535bff6ad41947ddd4092ceb345b65bceb5` |
| Studio directory | sibling `build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql` |
| Studio branch / unchanged local commit | `mainline` / `4675a1a41fa86e2c290d6e59191d59556ed6a900` |
| Starting local Studio source pin | `900dc82879c9d07d32b4803b94b5728bf74dbb07` |
| Environment used for live checks | Existing authorized Aurora, `us-east-1`, Aurora PostgreSQL 18.3.0, database `mosaic_catalog`, 500,000 products |
| Local application | UI `127.0.0.1:5185`; API `127.0.0.1:8010`; unrelated listener on 8000 preserved |
| Presentation package | External DAT410 workspace, v9 PowerPoint/PDF/notes/video; 12 slides |

The final release is the clean `main` HEAD containing this report and its
measurement-only follow-up commits. Its full SHA is independently read from
`git ls-remote origin refs/heads/main`, included in the delivery handoff, and
written into every local Studio pin by `scripts/repin.py`. Resolve it from the
local Studio `contentspec.yaml` `SourceRevision` value; do not use the earlier
engineering commit as the publication pin. The baseline records the exact
clean code commit measured, and the serving checks compare retrieval/settings
and methodology fingerprints rather than pretending a report changes ranking.

Private evidence is under `.local/release-review/`: starting diffs, AWS identity,
commands, timestamps, logs, search/run receipts and current browser captures.
Account identifiers and connection details are not copied into this public
report. The previous handover's ten modified source files were preserved;
they matched its reviewed branch byte-for-byte. No unrelated checkout was reset.

## Acceptance matrix

PASS is bounded by the evidence stated. BLOCKED is a missing external capability,
not a disguised skip. Only the human rehearsal is EXCLUDED.

| Gate | Status | Evidence and limit |
|---|---|---|
| Scope, ownership and source reconciliation | PASS | Source/Studio branches, starting diffs, worktrees, remotes and process ownership inspected; prior fixes retained |
| Backend/API/data/agent security review | PASS | Typed read-only tools, eligibility, prior-answer scope, synthesis claim checks, request bounds, error sanitization, retry transactions and single-participant threat model reviewed; see `docs/security-boundaries.md` |
| Configuration and meaningful lab gates | PASS | Uppercase/prefixed duplicate settings and missing control cases proved red, then passed after fixes; controls cannot silently become an empty list |
| Offline Python suite | PASS | 1,221 passed, 58 skipped without live environment; live lanes below cover their separate Aurora boundary. One upstream test-client deprecation remains visible |
| Frontend tests, independent type checks and build | PASS | 652 tests; final affected-component rerun 73 tests; both TypeScript projects and Vite build pass |
| Dependency audits | PASS | Full npm audit and Python installed-environment pip-audit: no known vulnerabilities reported at review time |
| Lint, source/data contracts, MCP packaging and CI policy | PASS | `make lint validate validate-db validate-config validate-release-workflow`, MCP tests and isolated wheel smoke; all three live lab validators now run in the approved model job |
| Aurora bootstrap state, functions, missions, filters | PASS | Bootstrap acceptance and function census; 121 mission checks; 720 filter targets plus the canonical set; existing loaded cluster only |
| Aurora SQL and model integration | PASS | 48 database-contract tests and 109 model-backed tests, including retry idempotency and real scope enforcement |
| Model entitlement | PASS | All three pinned models exercised in `us-east-1`; not merely listed as ACTIVE |
| Scorecard and stage comparison | PASS | Clean-source remeasurement; 20 product searches / 74 judgments. nDCG@10 0.850903 and MRR 0.891667; ordered results unchanged from prior baseline. No claim that reranking always improves results |
| Three deliberate failures and repairs | PASS | Lab 1/2 actual SQL defects through the production retrieval service and real providers in rolled-back Aurora transactions; both fail then pass. Isolated API with actual Lab 3 registration defect rejects the answer; repaired production validator passes |
| Lab completion and reset safety | PASS | Three production validators, source-state/idempotent reset tests, named Aurora database guard before any reset edit, saved-run completion checks; no shared data reset left behind |
| Rendered required app routes and controls | PASS | Discover/Alex, Shop/search/filter, product specifications/reviews/source tabs, bag add/remove, Playground completion, Scale controls and Memory save/recall inspected; actual Aurora/AgentCore results, not fixture substitution |
| Reported OH-M349 follow-up | PASS | Browser returned supported specifications for the exact prior product and clearly stated review excerpts were unavailable. Saved evidence in `follow-up.txt` |
| Laptop/mobile/focus checks | PASS | 1728px, 1366px and 390px DOM bounds checked; no page horizontal overflow. Mobile chat/filter dialogs fit; Escape restores focus. Product tabs have valid control targets; browser error log empty during inspected journeys. This is not a WCAG certification |
| Guide commands, teaching order and local content | PASS | Six pages checked; same Observe/Diagnose/Repair/Prove shape, source-line anchors, required payloads, controls, recovery and completion commands validated. Local Markdown preview checked headings/tables/images; it is not the Studio renderer |
| Native Workshop Studio rendering | BLOCKED | No authenticated Studio preview/published revision or native renderer was available. The maintainer must preview tabs, expanders, Mermaid, navigation and downloads in Studio; local Markdown rendering does not establish these |
| CFN, IAM and bootstrap static checks | PASS | Four templates pass cfn-lint; 126 Studio regression tests; shellcheck, source parity, secret redaction, retries, TLS, current SSM AMI family and derived-root revision checks |
| Actual new-host bootstrap/rollback/teardown | BLOCKED | No existing project CloudFormation host/stack was returned in this account; no substantial new infrastructure was created. Existing Aurora and script tests cannot prove this lifecycle. Use an authorized event environment |
| Local cache and asset package | PASS | Immutable manifest/50-shard contract and checksum verifier; local image signatures, references and bootstrap parity. Required re-upload list below |
| Published S3 delivery/checksums | BLOCKED | `ListObjectsV2` AccessDenied and bootstrap `HeadObject` HTTP 403 with current credentials. Obtain the Workshop Studio asset identity and rerun read checks after uploads |
| Hosted artifact identity and final hosted journeys | BLOCKED | No matching deployed stack identified; final code is tested locally against existing Aurora. No claim that a CloudFront deployment runs this release |
| Deck/media/notes | PASS | v9: 12 slides, seven editable code slides, two native tables, notes of 65–72 words in visual order; SQL executed on Aurora and RRF falsifier verified; original app-video pixels preserved |
| Source commit/push and local Studio pin | PASS at delivery | Final source changes and this report are committed/pushed; remote full SHA independently compared; local tooling re-pins to that exact SHA. Studio remains uncommitted by design |
| Combined published-package release gate | BLOCKED | The gate correctly requires clean/published Studio state. Local package validation is separate; do not weaken the dirty-Studio guard to label the combined gate green |
| Human fresh-event Workshop Studio rehearsal | EXCLUDED | Still required after publication; timing, event IAM, fresh bootstrap, participant flow and cleanup checklist below |

## Material repairs

- **P1 configuration:** removed hard-coded served `ef_search` and UI display
  limits. Exposed actual HNSW configuration; broadened the duplicate-setting
  tripwire and caught a second duplicate in scale simulation. Empty sweeps now
  show recovery guidance. PostgreSQL memory values retain their kB/MB/GB units.
- **P1 lab confidence:** declared required control IDs in the mission single
  source, rejected missing controls, and made empty parametrization/unknown
  test markers fail loudly. CI starts the real API and runs all three labs
  behind the existing approval environment.
- **P1 bootstrap/security:** bounded retries for repeatable downloads/install
  steps; full-log redaction before truncation, including encoded passwords;
  DSNs use `verify-full` and the regional RDS CA. Existing password-safe recipes,
  failure signaling and runtime grants are retained. Studio removes password
  output from the credential Lambda, trims excess IAM permissions, retries
  signaling and uses seven-day key deletion. Lambda logs now have seven-day
  retention and stack-owned deletion.
- **P1 environment lifetime:** replaced an AMI that deprecates before the event
  with the official AL2023 arm64/kernel-6.1 SSM family. The exact AMI resolved at
  deployment must be recorded; it is intentionally not an immutable image pin.
- **P2 state/retries:** one request ledger coordinates Aurora session creation
  and the AgentCore idempotency token; changed-payload reuse returns conflict.
  Rerank receipts only name a reranking model when it actually ran. Reset checks
  the named workshop database and Mosaic catalog before writing exercise files.
- **P2 evidence/errors:** added omitted retrieval/methodology files to the
  fingerprint manifests and an import-closure falsifier. Missing registered
  sources now produce actionable Lab 3 guidance rather than a connectivity
  diagnosis. Application error logs use exception types, not raw provider data.
- **P2/P3 interface:** removed an unused fixture-only prototype; improved retry
  actions, stale-comparison clearing, accessible names, dialog references,
  focus handling, smaller-screen layout and participant wording. Shop's story
  caption now agrees with its monitor image. No new visual direction was imposed.
- **Content:** corrected the build-gate output, marked-block solution snippets,
  line citations and unsupported claims about a ranking winner changing. Added
  a plain definition of candidate/shortlist and a concrete cleanup procedure.
  Kept measurements distinct from expectations and supplied code from edits.

AWS references used to verify infrastructure choices: [CloudFormation SSM
parameter types](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/cloudformation-supplied-parameter-types.html)
and [Aurora TLS verification](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/UsingWithRDS.SSL.html).
Live EC2/SSM reads confirmed the prior AMI deprecation and the family resolution.

## Remaining limitations and explicit decisions

1. **Workshop trust model:** this is one participant's disposable synthetic-data
   application. The public Mosaic route, anonymous lab API calls and UUID receipt
   inspection are not tenant authentication. Shared production use requires the
   additional controls in `docs/security-boundaries.md`.
2. **Narrative scope:** Discover/Shop/Playground use headphones, chair and monitor.
   The required Lab 3 still teaches evidence registration with keyboard/chair;
   G-021 separately checks monitor/chair. The introduction states this explicitly.
   `WORKSHOP_LAB_DESIGN_TODO.md` reserves promotion of the monitor request into the
   required timed lab, including new failure/repair proof, for curriculum design.
3. **No fresh-media claim:** the v9 video retains the original Aurora-backed
   before/after capture. Saved records confirm product 2 absent before and present
   at trigram/final rank 1 after. New captions and notes do not make old footage
   a new execution. Speaker playback in PowerPoint Slide Show and room projection
   still need a physical presentation check.
4. **Warnings retained:** optional lazy WebGL chunk is about 593 kB (150 kB gzip);
   it loads only when that illustration opens. Starlette warns about a future
   httpx2 test-client migration. No severity threshold or warning was suppressed.
5. **Lifecycle/cost:** redeploy this package as a fresh workshop environment;
   replacing only the host can rerun import against an already loaded cluster.
   RDS-created log groups and separately provisioned optional AgentCore resources
   require their own cleanup. `RDSOSMetrics` is shared: never delete the group if
   another database uses it. Bootstrap duration and the I/O-Optimized cost choice
   remain measurements for the event environment, not asserted timings here.
6. **Preview boundary:** the local content preview found all referenced images
   and the six-page sequence. Phone-sized tables overflow that generic renderer;
   native Studio behavior, interactive directives and projector readability must
   be inspected in Studio/room. No custom-preview CSS is shipped as a Studio fix.

## Maintainer-only release commands

Run from the Studio directory shown below, using the authorized Workshop Studio
AWS identity. These commands were prepared, not executed. Do not upload from an
incomplete cache checkout, and do not add deletion flags.

```bash
cd /Users/shayons/Desktop/Workshops/build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql
set -e
SRC=../sample-agentic-hybrid-retrieval-aurora-postgresql
ASSET_ROOT=s3://ws-assets-us-east-1/d2acf248-2981-4292-a41c-60a0a0e54ab3

git -C "$SRC" status --short
LOCAL_SHA=$(git -C "$SRC" rev-parse HEAD)
REMOTE_SHA=$(git -C "$SRC" ls-remote origin refs/heads/main | cut -f1)
test "$LOCAL_SHA" = "$REMOTE_SHA"
python3 scripts/repin.py --check --source-repo "$SRC"

"$SRC/.venv/bin/python" "$SRC/scripts/embedding_cache.py" verify \
  assets/embedding-cache/manifest.json --contract "$SRC/db/config/embedding-cache.json"
python3 scripts/validate_workshop.py --source-repo "$SRC"
python3 scripts/validate_participant_queries.py --source-repo "$SRC"
cfn-lint --regions us-east-1 --template static/hybrid-retrieval-main.yml \
  assets/hybrid-retrieval-code-editor.yml assets/hybrid-retrieval-database.yml \
  assets/hybrid-retrieval-vpc.yml
shellcheck --exclude=SC1091,SC2016 assets/mosaic-bootstrap.sh
python3 -m unittest discover -s scripts -p 'test_*.py'

# Upload the four named runtime assets and the verified 51-object cache.
aws s3 cp assets/mosaic-bootstrap.sh "$ASSET_ROOT/mosaic-bootstrap.sh"
aws s3 cp assets/hybrid-retrieval-code-editor.yml "$ASSET_ROOT/hybrid-retrieval-code-editor.yml"
aws s3 cp assets/hybrid-retrieval-database.yml "$ASSET_ROOT/hybrid-retrieval-database.yml"
aws s3 cp assets/hybrid-retrieval-vpc.yml "$ASSET_ROOT/hybrid-retrieval-vpc.yml"
aws s3 sync assets/embedding-cache "$ASSET_ROOT/embedding-cache" --exact-timestamps
python3 scripts/verify_published_bootstrap.py --s3-uri "$ASSET_ROOT/mosaic-bootstrap.sh"

# Review these exact local changes before staging. Large cache files stay out of Git.
git diff --check
git diff --stat
git add -- AGENTS.md FACILITATOR_GUIDE.md README.md WORKSHOP_LAB_DESIGN_TODO.md \
  assets/README.md assets/hybrid-retrieval-code-editor.yml \
  assets/hybrid-retrieval-database.yml assets/mosaic-bootstrap.sh \
  content/index.en.md content/10-introduction/index.en.md \
  content/20-lab-1-retrieve/index.en.md content/30-lab-2-rank/index.en.md \
  content/40-lab-3-reason/index.en.md content/50-conclusion/index.en.md \
  contentspec.yaml scripts/test_validate_workshop.py scripts/validate_workshop.py \
  static/hybrid-retrieval-main.yml static/iam_policy.json
git diff --cached --check
git diff --cached --stat
git commit -m "Prepare validated DAT410 workshop release"
git push origin mainline
make -C "$SRC" check-bootstrap-release
```

Then use the established Workshop Studio content publication/import workflow.
No supported publication CLI or authenticated authoring session was available
here, so no invented publication command is supplied. Preview the exact pushed
Studio revision, verify its source pin and asset prefix, then publish/import it.
Run the facilitator guide's event-owner preflight step 3 against every published
asset (including the manifest and 50 nonempty shards), and rerun the published
bootstrap checksum check. A successful upload alone does not prove deployed bytes.

Files uploaded above are the bootstrap, three nested templates and embedding
cache; root template/contentspec/IAM/content/static guide images travel with the
Studio repository publication. The changed bootstrap and templates remain stale
at their remote keys until these manual actions complete.

## Checks after publication and smallest unblocking actions

- Use the Studio asset AWS identity to remove the current S3 403 blocker; compare
  published bytes, packaging/content types, object count and hashes with the
  reviewed package.
- Supply an authenticated Studio preview/published revision to check native
  navigation, tabs, expanders, Mermaid diagrams, downloads and accessibility.
- Use an authorized project event environment to exercise automated new-host
  bootstrap, health/readiness, model access, three deliberate failures/repairs,
  persisted completion, restart, partial-failure signaling and teardown. Record
  source SHA, resolved AMI, model IDs, elapsed times and retained resources.
- Verify GitHub CI for the final source SHA; local gates do not prove hosted CI.
- Keep the **human** rehearsal separate: time the 12/10/10/20-minute core, leave
  eight minutes for recovery/questions, test laptop and projector readability,
  run the exact three requests, use one hint/recovery path, download the skill,
  verify cleanup, and save the completed rehearsal record. This pass did not do it.
