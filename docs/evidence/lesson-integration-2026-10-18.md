# Lesson and UI integration, 18 October 2026

Local, unpublished changes build on the [source and teaching audit](source-teaching-audit-2026-10-18.md).
They update the application and the adjacent Workshop Studio guide, starting
from source `79fc9e773f0decf5272b8a5fe6f193174fa9a07f` and guide `72da75f`.
The guide still pins that published source. This record is offline review
evidence, not a release or participant acceptance record.

The opening question is **What if your agent's most convincing answer rests on
the wrong evidence?** The three labs follow the intended product through
candidate retrieval, ranking and a source-supported answer. Their existing
10/10/20-minute allocations remain unchanged; completion stays inside Lab 3.
These allocations have not been verified by a new human rehearsal.

## What was integrated

The colleague's Lab 2 rewrite supplied the strongest teaching changes: carry
Lab 1's saved context into `psql`, compare semantic position with fused
membership, expose equal contributions for unequal positions, repair the
marked function, then repeat the same observation. The existing Lab 2 page
was edited in place. No alternate lab or extra required exercise was added.

Labs 1 and 2 now use the terminal as their required path; Shop is optional.
Context-loading `\i` commands have their own paste blocks. Lab 1's opening
diagram shows the search pipeline, with the fault-revealing animation moved
after diagnosis. Lab 2 distinguishes enforced category filters from size,
resolution and charging requirements expressed as search text.

Lab 2 retains the judged-query comparison and production checks. Its decision
is which setting to test next: candidate admission does not measure final
reranked relevance, latency or actual cost. The live reranking off/on experiment
is optional. Recorded positions remain labelled as examples. The supported
Lab 1 handoff and Lab 2 recovery commands are preserved; the colleague's
unsupported `advance --lab 2` was not adopted. Placeholder captures were not
imported.

Lab 3 stays in Code Editor through deployment, then uses Ask Mosaic for
**Complete my setup**, source inspection and the 100W follow-up in the same
conversation. Completion returns to the terminal with the original setup run
ID. Builder view now exposes that full ID instead of a truncated pill. The
guide no longer uses the two most recent database turns as a substitute for
identifying the participant's own runs.

Shop's Lab 1 notice no longer contains a product photo or red product plate.
It states that the requested listing is missing and labels actual results as
other products. Request IDs and the diagnostic link sit in an expandable
section; the repeated coverage explanation sits with ranking details.
Environment failures retain their visible warning and saved-search link.
Actual result cards retain product imagery.

## Verification and limits

- Source documentation, participant-command and Lab 2 comparison tests:
  **45 passed**.
- Affected UI suites: **137 passed** across five files. An earlier run had a
  timing-sensitive failure reopening an answer; the isolated test and the
  complete affected rerun passed. After preserving the environment-failure
  diagnostic link, all **80 CatalogPage tests** passed again.
- UI TypeScript checks and production build: **passed**.
- Guide tests: **245 passed, 4 skipped**. The initial broad discovery lacked
  `botocore`; rerunning with the source repository's existing environment passed.
- Guide preflight: **passed**, including page structure, static assets,
  source-defined timing and provisioning pins. It used a clean temporary
  checkout of the currently pinned source; changed source behavior was checked
  separately in the application working tree.
- Participant query contract and source configuration tripwire: **passed**.

No live Aurora, Bedrock, AgentCore or fresh-account acceptance was run for
these edits. No connected browser was available for a new visual check. The
new Lab 1 diagram was rendered and inspected; existing Shop and Playground
captures are explicitly labelled as older layouts or alternate views. Their
replacement captures and a timed mixed-experience rehearsal remain delivery
work. The other correctness findings in the original audit remain open.

The source and guide changes must be released together: publish the tested
source, update the guide's release pins, replace the noted captures and follow
the repository's Workshop Studio asset/build workflow when publication is
requested. No commits, pushes, asset uploads or Workshop Studio publication
were performed in this integration.
