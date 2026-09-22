# Monitor workshop validation — 20 September 2026

The current generated-catalog workshop now ends with a monitor and chair
decision. The public catalog remains staged; none of the following live lab
results establish retrieval quality on that replacement catalog.

## Exercise and guide changes

- The canonical G-021 mission requires a 32-inch 4K monitor, USB-C video and
  90 W laptop charging, plus a mesh ergonomic chair for 12-hour workdays with
  seat-depth adjustment and dynamic lumbar support. Each item is under $800.
  The target products are 420001 and 370001. The complete request and assertions
  remain in `data/evals/mosaic_labs_missions.json`.
- G-007 now compares a monitor with a cheaper monitor. Products 420001 and
  422221 remain inspectable, including the cheaper option's lack of USB-C
  charging. A cheaper alternative is not automatically an eligible substitute.
- Participant guides, instructor notes and current speaker notes use monitors.
  Generic catalog tests and immutable historical measurements can still contain
  keyboards; they are not workshop exercises.
- Each lab follows observe, diagnose, repair and prove. Optional deeper
  inspection stays collapsed, and one flex exercise follows completion at
  minute 50. Memory remains optional Lab 4 after the hour.
- The ending is **Use what you built in your own agent**. The participant
  completion section is **Complete the workshop**. Old aggregate measurements
  retain their original queries and hashes and are labeled historical; see
  `data/evals/HISTORICAL-MEASUREMENTS.md`. Regression checks remain required.

## Live evidence against Aurora

The local API used `global.anthropic.claude-sonnet-5` for orchestration and
synthesis, `us.cohere.embed-v4:0` for embeddings and `cohere.rerank-v3-5:0` for
reranking. This is the existing generated catalog, with all 500,000 products.

| Experiment | Recorded result |
|---|---|
| Lab 3 evidence-registration seam deliberately broken in an isolated source copy | HTTP 503, turn `6f6b3829-a503-4825-9a6a-277d2cabc2b3` |
| Initial repaired monitor mission | Grounded answer, turn `8c3e9d5c-837d-41dc-bee4-b2d96ca1fd8b`; all ten mission checks passed |
| Lab 2 with monitor control G-007 and control G-009 | All 17 checks passed |
| Final fresh G-021 production validation | All ten checks passed, turn `0173fd64-a50a-483f-8d19-845f3fabad02` |
| Final fresh G-019 evidence control | All nine checks passed, turn `e2c0a545-d194-4b59-9cb8-473766a6ce03` |
| Completion using the saved receipt | Both runs regraded successfully against current code, settings and database records; no new model calls |

The final receipt is `.local/monitor-workshop-2026-09-20/lab-3-validation.json`.
Its source-content hash is
`c0b1acc0e1f1a8470f62cdfe00428e51ead4d5970c6ae48c1d6624dabb1ab69d`.
This records a dirty development worktree, not a published release.

There was an intermediate failure worth preserving: turn
`9fbfcf2c-8d1b-4418-8df3-8d16b0d9c31e` declined after cited synthesis failed.
A diagnostic run found a sentence combining two chairs' numeric capacities,
which the product-scope guard correctly rejected. The synthesis instructions
now put each product's measurements and citation in a separate sentence and
omit unrelated measurements. The guard itself was not weakened. The final
successful validation still logged one synthesis formatting rejection before
the bounded recovery succeeded; this is not a claim that every model draft
passes first time.

The first saved-receipt replay encountered a stale pooled connection and a
readiness HTTP 503. The pool discarded it; the next replay passed. This was an
environment/readiness failure, not a passing or failing lab answer.

## Claude Code coding coach

The source-owned bootstrap and its byte-identical Workshop Studio delivery
copy install Claude Code **2.1.233** and configure
`ANTHROPIC_MODEL=global.anthropic.claude-sonnet-5` with
`CLAUDE_CODE_USE_BEDROCK=1`. The shell, bootstrap preflight, model output and
regional/global inference permissions agree. The application runtime's
Workshop Studio model remains its separate Sonnet 4.6 pin.

The exact pinned CLI made a real Bedrock call using local AWS credentials and
returned `MOSAIC_CLAUDE_READY` with exit code 0. The account's global Sonnet 5
inference profile reported ACTIVE. The local result is saved in
`.local/monitor-workshop-2026-09-20/claude-code-preflight.json`.

The Introduction now says to open `CodeEditorURL`, run `claude`, inspect
`/status`, and use the current lab's third hint as the coaching prompt.
Participant-global guidance requires diagnosis, a small edit within the marked
seam, and production validation. It does not contain the solutions.

Five permanent coach-contract tests exercise the production validator. They
prove failures for a partial model update, each missing IAM resource and a
misleading model output; an unrelated comment still passes. A wrapper verifies
the delivery validator actually calls this check, and each mutation is in
memory, leaving the source bytes unchanged.

No deployed Mosaic Code Editor stack was visible in the current account's
`us-east-1` stack listing. The local CLI call does not prove participant-role
or fresh event-account access. That remains a release rehearsal requirement.

## Validation and deck

- 120 live mission checks and 74 canonical judged targets passed through
  Aurora's production filter function.
- 192 focused Python checks passed for the mission, evidence and answerability
  changes. A further bootstrap/editor run passed 32 checks. Its two database
  integration cases were then run against Aurora and both passed, including the
  missing-grant falsifier and successful runtime-role conversation attachment.
- 674 UI tests passed across 64 files; the production build passed. The
  existing HNSW bundle-size warning remains.
- 131 Workshop Studio tests passed. Participant requests match all three
  required source missions and the five required controls.
- Retrieval configuration checks passed: 335 scanned files/exemptions, 35
  pinned defaults, 19 validated profile settings.
- CloudFormation lint passed; shellcheck passed with the repository's documented
  exclusions. The source and delivered bootstrap files are byte-identical.
- The v16 PowerPoint updates the monitor story, defect descriptions, rounded
  agenda and closing takeaway. All 12 slides passed package validation and
  rendered review. Slide 3 media, relationships and autoplay timing are
  unchanged. Native PowerPoint playback has not been retested.

The review deck is `DAT410-Agentic-Hybrid-Retrieval-v16.pptx` in the existing
`Downloads/Presentations/2026/DAT410/output` directory, beside its speaker and
playback notes. v15 remains intact.

## Public catalog assessment and remaining release work

The `/catalog-preview` page's **Selected catalog only** filter displays ten
reviewed products from the selected public corpus, across headphones, chairs
and monitors. All ten photos loaded in the browser review. Recognizable
products and source-derived facts provide stronger comparisons than invented
product specifications. Cases, chair mats, lower-resolution monitors and
missing charging specifications provide useful negative and unknown examples.

This is sample evidence, not a quality score for all 500,000 records. The
broader catalog needs a curated home-office selection; historical or missing
prices cannot stand in for current price and stock. Review evidence is wired
for seven of these ten samples, not for the entire corpus. See the existing
`catalog-wiring-2026-09-20.md` and source audit for coverage details.

Before release, finish and verify the new embedding cache, wire its products
and evidence into the production retrieval path, reselect and validate mission
targets, rerun current measurements, and replace old-catalog demonstration
footage. The present preview uses a 27-inch monitor example; it is not evidence
that the current 32-inch G-021 mission is ready on the public corpus.

The full publishing gate remains blocked: bootstrap hash and infrastructure
release pins need regeneration together with a reviewed, published source
revision. `scripts/repin.py` deliberately refuses a dirty source worktree.
Do not update those pins piecemeal or claim a fresh Workshop Studio deployment
has passed. After publishing the reviewed source, repin all delivery surfaces
and rehearse the participant role, Claude Code and all labs in a fresh account.
