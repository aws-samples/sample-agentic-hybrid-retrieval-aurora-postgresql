# Lab 3 answer reliability, 8 November 2026

Lab 3 needs two answered requests: Alex's setup request and the 100W follow-up. On a fresh
Workshop Studio event (source `1980e687`, release `707f4e4841344be3`, Aurora PostgreSQL 18.6),
the first setup request ran for 90.7 s and ended with "The answer checks refused every draft
of this answer". Asking again worked. This record measures how often that happens and what
the fix in this commit changes. Per-run results, run IDs and every refused synthesis step are in
[lab3-answer-reliability-2026-11-08.json](lab3-answer-reliability-2026-11-08.json).

## Method

Each arm deployed its code to the event's two runtimes with `deploy_agentcore.py deploy`, then
ran the guide's exact request through `scripts/ask_agent.py` on the event host, four at a
time. A run counts as failed when it ends without an answer. Refused synthesis calls come
from `mosaic.agent_tool_event`. The controller fallback's last attempt in a failed run
records no tool event, so those counts are lower bounds.

## Results

| Arm | Setup request failed | 100W follow-up failed | Median answered time, setup |
|---|---|---|---|
| Release code (`1980e687`) | 5 of 16 | 2 of 12 | 57.8 s |
| Review retry and earlier refusals only | 3 of 16 | not measured | 64.3 s |
| This commit | 0 of 16 | 0 of 16 | 52.5 s |

Fisher's exact test, two-sided: setup 5/16 against 0/16, p = 0.043; both required requests
7/28 against 0/32, p = 0.003. The follow-up alone, 2/12 against 0/16, p = 0.17, is too small
a sample to stand on its own. On the release code, a participant got both answers without
asking again in about (11/16)(10/12) = 57% of attempts.

With this commit, the Go deeper requests behaved as the guide states: the mistyped ID declined
with `unanchored_query_terms: 'B0C2WWFCQB'` (2 of 2), the 100W recommendation declined with
`unsupported_requirements` (2 of 2) and Alex's rating rule answered (3 of 3).

## What refused the drafts

On the release code, 18 refused synthesis calls across the 16 setup requests:

| Cause | Calls | At fault |
|---|---|---|
| The claim-support review broke its own rules: quoting a record its passage does not cite (5), misquoting (2), a malformed decision (1) | 8 | the review |
| A passage marked as no claim yet carrying evidence; the release code's message cannot say whether the passage or the quotes carried it | 1 | unknown |
| The draft said the chair fits, completes or is a strong match for the setup | 4 | the draft |
| A sentence named a product without its citation | 2 | the draft |
| "Amazon Reviews 2023" read as a figure (2); a "Zone 900:" source line (1) | 3 | the draft |

On the follow-up, 15 of 20 refused calls were the review quoting outside its passage's
citations. A review that breaks its own rules says nothing about the draft, but the release
code discarded the draft. Retries started from scratch, without the reasons for earlier
refusals. The drafting prompt also asked for a decision rule "with citations" while requiring
checks to carry none, and the review's refusal messages named no passage.

## The change

- `service/claim_review.py`: a review that breaks its own rules is asked once more, told which
  rule it broke. The corrected review passes the same validation; a second rule break fails
  closed as before. An unsupported verdict still refuses the draft at once. A cited passage
  that the review finds states no product fact refuses the draft, because a citation says the
  record states the sentence. Every message names its passage.
- `service/synthesis.py`: a draft is told why earlier drafts in the same turn were refused. The
  prompt forbids setup fit claims and dataset names, and the decision rule cites the facts it
  states while checks carry no citation.
- `service/agent_tools.py`: each refusal is kept for the turn, so the agent's next call and the
  controller fallback both receive it.

No check was removed or loosened. `tests/test_draft_refusal_recovery.py` and the updated
`tests/test_claim_review.py` fail on the release code (27 of their 46 tests) and pass with
this change.

The measured runtimes ran the same drafting prompt byte for byte. The committed code differs
from the measured code only in line wrapping; the review prompt's text differs in two line
breaks. The committed code itself then ran on the same event: 8 of 8 setup requests and 4 of 4
follow-ups answered, and `grade_setup_run.py` printed `Lab 3 exercise: PASS`.

## Limits

These are 95 requests on one event in us-east-1 with `global.anthropic.claude-sonnet-5-5`,
four at a time. They do not measure a full room's concurrency, other Regions or other models.
Answers vary between runs. None of the fixed code's 44 required requests (32 measured, 12
confirming) failed, which bounds the failure rate below about 7% at 95% confidence.
