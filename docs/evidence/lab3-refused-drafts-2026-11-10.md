# Refused drafts in Lab 3's answers, 10 November 2026

Lab 3's two requests are answered through `synthesize_cited_answer`, which drafts an answer
and checks every claim against its source before delivering it. On a fresh Workshop Studio
event (source `c88e6b7f`, release `59cc5923229175e4`, Aurora PostgreSQL 18.6) both requests
of the participant walk ended `OUTCOME: grounded`, each after one draft the checks refused.
The terminal printed `draft refused by the answer check`, with no reason. This record
measures how often a participant sees a refused draft, what refuses it, and what this
commit changes. Per-run results, run IDs and every refused step are in
[lab3-refused-drafts-2026-11-10.json](lab3-refused-drafts-2026-11-10.json).

The [8 November record](lab3-answer-reliability-2026-11-08.md) measured requests that ended
without an answer and removed them. This one measures answered requests.

## Method

Each arm deployed its code to the event's two runtimes with `deploy_agentcore.py deploy`,
then ran the guide's exact requests through `scripts/ask_agent.py` on the event host, four
at a time, in batches of ten setup requests and ten 100W follow-ups. A run has a refused
draft when one of its `synthesize_cited_answer` steps in `mosaic.agent_tool_event` ended in
error. One call already rewrites a refused draft before it reports a refusal, so a refused
step means every draft of that call failed. A run was repaired inside the call when its
accepted call needed more than one claim review (`claim_review_usage.reviewCalls`).

## Results

All 140 runs ended grounded.

| Arm | Setup: refused draft | Setup: median time | Follow-up: refused draft | Follow-up: median time |
|---|---|---|---|---|
| Release code (`c88e6b7f`), one repair | 4 of 10 | 61.9 s | 2 of 10 | 36.4 s |
| Five drafting rules, one repair | 3 of 20 | 57.8 s | 5 of 20 | 44.8 s |
| Two drafting rules, one repair | 3 of 20 | 48.7 s | 7 of 20 | 42.0 s |
| This commit: two drafting rules, two repairs | 0 of 20 | 53.0 s | 5 of 20 | 47.0 s |

Fisher's exact test, two-sided. Setup request, release code against this commit, 4/10
against 0/20: p = 0.008. Follow-up, 2/10 against 5/20: p = 1.0. Both requests, 6/20 against
5/40: p = 0.16. So the setup request, the one Lab 3's completion check grades, shows a
reduction; the follow-up shows none, and the two requests together are not distinguishable
from the release code at this sample size.

With one repair, the drafting rules alone did not change the rate measurably: 18 of 80 runs
against 6 of 20 (p = 0.56).

On this commit the first draft was accepted outright in 7 of 20 setup runs and 6 of 20
follow-ups. The repairs inside the call absorb the rest of the setup request's refusals and
not the follow-up's, where later drafts fail for the same kinds of reason as the first.

## What refused the drafts

34 refused calls across the 140 runs:

| Cause | Calls | Setup | Follow-up | At fault |
|---|---|---|---|---|
| A sentence stating a fact, or what the records do not state, with no citation | 13 | 3 | 10 | the draft |
| The claim review broke its own rules on its corrected attempt too | 5 | 3 | 2 | the review |
| A caveat cited to a record when it is Mosaic's scope note on that record | 5 | 0 | 5 | the draft |
| Another claim the review found unsupported | 3 | 2 | 1 | the draft, or a strict reading |
| A figure that is not in the cited record, such as a derived "10W below" | 3 | 0 | 3 | the draft |
| A compatibility phrase | 2 | 0 | 2 | the draft |
| The pick called the right chair for, or a fit with, the setup | 1 | 1 | 0 | the draft |
| A "Sources:" line of citations | 1 | 1 | 0 | the draft |
| A product named without its citation | 1 | 0 | 1 | the draft |

The participant walk's two refusals, outside these batches, were a fit phrase ("the chair for
your setup") and a cited scope note. The fit phrase and the "Sources:" line each appeared on
the release code and not after the drafting rules that name them.

## The change

- `scripts/ask_agent.py`: a refused draft prints the check's reason, wrapped to the
  terminal, then a line saying what happens next: the agent is told why and drafts again.
  The claim review's refusals had no wording and printed `draft refused by the answer
  check`; they now print the review's own reason, a cited scope note, a cited line with no
  product fact, or a review that could not confirm the draft.
- `service/synthesis.py`: one call rewrites a refused draft twice before it reports a
  refusal (`DRAFT_REPAIRS`). For a request covering different product categories the
  drafting prompt gives the opening sentence's form and forbids calling a product right,
  best or ideal for the shopper's setup; it also forbids a Sources line.
- `service/claim_review.py`: the review prompt says that naming a pick adds no product
  fact while calling a product a fit for the setup is a claim, and that a scope note does
  not make a claim the record's own words support unsupported.

No check was removed or loosened. Run on the event against the ViewSonic's listing record,
three times each: under the new review prompt six unsupported sentences (right for the
setup, fits the desk and matches the headset, comfortable for every buyer, charges any
laptop at full speed, this variant at today's price, speakers reviewers call excellent)
were refused 18 of 18 times and two supported sentences accepted 6 of 6. Under the release
prompt the same six were refused 18 of 18 and the supported opener "is the one to choose:"
was refused once in three.

Three more drafting rules were measured and left out, because the refusals they targeted
did not fall: write a figure only beside the record that states it, cite every sentence
about what the records do not state, and never cite a record's scope note. With the last
one, drafts stated the scope note without a citation and were refused for that instead.

## Limits

These are 140 requests on one event in us-east-1 with `global.anthropic.claude-sonnet-5-5`,
four at a time. They do not measure a full room's concurrency, other Regions or other
models, and answers vary between runs. Zero refused drafts in 20 setup requests bounds the
rate below about 14% at 95% confidence, not at zero. The committed code differs from the
last arm's measured code only in a comment and in line wrapping. It has not been through
the Aurora-backed evaluation gates, which need the development cluster.
