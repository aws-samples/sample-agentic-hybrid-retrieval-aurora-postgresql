# DAT410 deck, Playground and lab alignment

Audited and revised on 1 October 2026 against
`DAT410-Agentic-Hybrid-Retrieval-v2.10.pptx`. The revised presentation is v2.11;
the original is preserved in the presentation working directory.

## The connected journey

Alex completes a home office with headphones, a monitor and a chair. The four
pipeline phases are **Retrieve → Rank → Re-rank → Reason**, taught through
three required labs in the existing 40-minute hands-on budget.

| Surface | Aligned behavior |
|---|---|
| Deck walkthrough and Playground default | **Focus at home** runs the deck's exact headphone request and filters. Retrieve, Rank and Re-rank inspect one saved search. |
| Headphone evidence follow-up | **Check the focus picks** explicitly asks about Logitech Zone 900 and 3M Quiet Space, adding the call-evidence requirement. It runs a new agent request with its own searches. |
| Lab 1 | Recover Alex's saved Bose listing through the close-spelling channel. |
| Lab 2a: Rank | Diagnose and repair the RRF contribution so the monitor can reach the reranker. |
| Lab 2b: Re-rank | Inspect combined versus final order, prove the repair and judge the proposed tuning change. Both parts remain within one ten-minute lab. |
| Lab 3 and Complete my room | Independently search the Bose headphones, ViewSonic monitor and Steelcase chair; compare all three, cite their records and explain one search's ranking. |
| Optional work | Memory and HNSW remain optional after required completion. |

The mission manifest owns canonical requests and targets. Shop, Playground and
Ask Mosaic resolve their examples from it. Exact retrieval pills run an exact
search; Reason preserves that reference search while identifying the agent's
new searches separately. The agent does not inherit evidence authorization from
the inspection display.

## Corrections made

- Split Rank and Re-rank into distinct inspection phases. Derive their status
  from saved diagnostics; agent evidence activity no longer masquerades as SQL
  ranking. Disabled or unavailable reranking is not displayed as successful.
- Show the complete saved candidate pool, including products outside the served
  result window. Sorting the displayed products alone hid the deck's 2→22
  demotion. Contribution counts now say they describe survivors in the pool.
- Continue the selected request in Reason instead of silently switching from
  headphones to a monitor/chair scenario.
- Permit three focused agent searches. Keep the existing two-product search
  window and two-record evidence limit independent of that search-call budget.
  Require every room target in both the comparison and final shortlist.
- Update Shop's room copy, Code Editor folder labels, guides, front doors and
  the Workshop Studio Lab 2/3 instructions. Remove the ambiguous “Optional Lab 4”
  label. Preserve the existing exercise seams, models, filters and SQL settings.
- Correct deck source paths and Lab 3 wording. Use one recorded headphone event
  for the numbers: dyplay combines at #11, and the kids' headset moves #20→#5.
  Speaker notes distinguish the authored source
  comparison from a captured agent answer and identify the call follow-up.

## Verification

The original deck's cited event is
`61675dc2-295b-4253-8127-090d633efcd5`. Its saved response agrees with the Logitech
and 3M arithmetic and all 50 contribution sums. Original deck SHA-256:
`09714adfa35759b527ce133eff0d8a1388fa3d8a6bd6869360ab9a6d314a6a4f`.

Fresh development search `6088342d-41f9-4dfd-a6cf-3fc7b47b681f` reproduced Logitech
Zone 900 at combined #4 → final #1 and 3M at #1 → #2. The candidate-pool display
exposed Logitech Zone Wireless at #2 → #22, outside the displayed results.
Fresh searches retain their own positions; the deck is a recorded example.

Development agent run `1f246f77-c924-4697-ba5d-ddd403c595ce` returned all three room
targets. All ten agent-response checks passed, including independent searches,
comparison, source resolution and a replayable ranking explanation. Its nine
successful tool calls used three searches, comparison, ranking explanation,
three evidence reads and synthesis. It retained uncertainty about actual call
clarity and personal chair comfort. The production Lab 1 and Lab 2 response
validators also passed, including their supporting controls.

Repository validation passed: 2,285 offline Python tests (64 Aurora skips),
2,323 Python tests with Aurora (one skip, 25 deselected), 793 UI tests, production
UI build, lint, configuration and contract gates, release-workflow checks and
MCP package checks. New regression cases failed before the repairs: the third
search was refused and a room comparison could omit the headphones.

## Remaining release evidence

These development measurements are not managed Runtime or fresh-account
acceptance. No participant lab was reset or silently completed. The configured
development database contains the correct 553,911 selected real products but
also retains historical synthetic rows, so `db-verify-bootstrap` correctly
fails its real-only fresh-workshop contract. Do not delete those retained rows
or weaken the check to publish a passing result.

The maintainer requested a new Workshop Studio build first and will create a
test event for end-to-end validation. Managed deployment/rehearsal and
clean-account acceptance remain pending for the new source pin. Human completion timing, projector checks and controlled cold starts
remain separate from automated test passes. The presentation's access-code
placeholder must be filled with the actual event code before delivery.
