# Terminal readability and the lab SQL fingerprint, 9 November 2026

Findings from the 9 November evening test event of release `f50a95a4a77e2f63` (build
`babc84d2`), walked in Code Editor's own terminal, and what changed
for each. The event's record is in the workshop repository's `release/` folder.

## What the walk showed

- **A verdict was hard to find.** `Lab 3 exercise: PASS` printed in the same white as the
  three lines around it.
- **The agent command went quiet.** Of a 50 s setup request, `synthesize_cited_answer` took
  33 s, and the terminal printed nothing in that time. Each stage also printed its own bar
  line, so the bar read as four bars.
- **A correct Lab 2 fix hid the Playground's measured comparison.** The walk changed the one
  wrong term and kept the exercise's two `TODO` comment lines. Every check passed, and
  `/api/scorecard` returned `attributed: false`: the retrieval fingerprint hashed the lab
  file's bytes (`214adcdc` measured, `490c2104` running). The Playground then showed nothing
  where the comparison belongs.

## What changed

| Commit | Change |
|---|---|
| `b6a7959d` | The two lab SQL files contribute a hash of their SQL tokens to the retrieval fingerprint. Comments and whitespace are ignored; string literals and quoted identifiers are kept whole; any token edit still moves it. Other manifest files are hashed by bytes as before |
| `bffd9dd8` | Where the comparison is withheld, the Playground says the measurements describe the reference lab SQL, that this box's SQL differs, and that the results on the page are live |
| `42d78c63` | `PASS` is green, `FAIL` and `BLOCKED` red, `CANNOT GRADE` yellow, on a terminal only. `NO_COLOR`, `TERM=dumb`, a pipe or a log get the plain line |
| `9b4898ff` | On a terminal `ask_agent.py` redraws one line with the stage, the running tool and the time waited; tool calls stay as lines; the answer prints paragraph by paragraph as the API delivers it |

The answer is not streamed while it is drafted. The API sends the answer's text only after
its claim checks pass, in small pieces, which Ask Mosaic already showed; the terminal now
shows them too. A draft the checks refuse is never printed.

A repair written with different tokens, such as `1.0 / (rrf_k + source_rank)` without the
casts, still differs from the measured SQL, and the Playground's note says so.

## Measured on the event box

The four script changes were applied to the event's checkout and run in Code Editor's
terminal before they were committed.

- `Lab 2 exercise: PASS` printed with a green `PASS`.
- `ask_agent.py` refused the first question with HTTP 503, "Your code in Code Editor changed
  after your deploy", as it should; after a deploy (1:11) the setup request showed three
  `search_products` lines over one redrawn line, `25%  Retrieve evidence: search_products
  0:06`, then nine tool call lines, and ended `OUTCOME: grounded`.
- That run showed a defect: once the stage changed, the line dropped the tool's description
  and read `Compose cited answer` alone. The API names a tool before the stage it opens.
  `9b4898ff` keeps the description across the stage change, and its test sends the events in
  the API's order.

## The re-measure

The fingerprint module is part of the scorecard's methodology, so both artifacts read
unattributed after `b6a7959d`. Both were re-measured on the development cluster (Aurora
PostgreSQL 18.6, pgvector 0.8.2, `db.r8g.2xlarge`) at `9b4898ff`.

- **Scorecard (`ae90c31b`).** Recall@10 1.0, MRR 0.759 and nDCG@10 0.803 are unchanged, and
  `canonical_ranked_results.csv` is byte-identical. The saved query vectors for `G-007` and
  `G-012` are Bedrock's new ones; the commit message says one.
- **Stage comparison.** Every arm and every paired difference is unchanged; only its
  provenance moved.

The clean checkout's fingerprint is now `0228f731`.

## Not done

- The line cannot say that a draft was refused and is being rewritten: the streaming route
  sends an event when a tool call starts and nothing more until the run's answer.
- The guide's screenshots of these commands show the earlier output.
