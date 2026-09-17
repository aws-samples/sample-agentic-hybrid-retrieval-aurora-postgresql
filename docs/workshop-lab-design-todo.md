# Workshop lab design TODO

Status: deferred for the workshop guide authors to review. These are design
decisions and acceptance criteria, not new participant instructions. Keep the
current three labs, their scenarios, timings, repairs and validators unchanged
until that review is complete. The mission manifest remains the single source
for the executable lab contract.

Use role labels here. Keep the personal staffing roster outside the repository.

## TODO: connect Lab 3 execution to the same visible answer

The participant guide creates before/after agent runs in the terminal, then
asks the reader to inspect the answer in Shop. The supplied `ask=1` link opens
the chat panel; it does not load the terminal response. The existing `run`
handoff to the guided Playground supplies a run ID for grading, not an answer
replay in Shop.

- [ ] Choose one execution surface for each before/after experiment. Either
  make the browser the execution path, or provide a read-only view of the
  terminal run's persisted answer, searches, trace and source snapshots.
- [ ] Define the source API/UI support required by that choice, including
  failed and declined runs. Preserve existing access and product/source scope.
- [ ] Demonstrate that the displayed run ID equals the executed run ID, and
  opening it makes no additional model call. Do not substitute a new answer or
  today's source text for the evidence the saved answer read.
- [ ] Measure the complete participant path, including any UI submissions and
  validator runs, before documenting the number of model-backed runs.
- [ ] Retain the completion gate's regrading of saved runs against current
  records. Displaying a past answer does not certify that it still passes.

## TODO: align the guide opening with the presenter opening

- [ ] Explain that the catalog, embeddings and application scaffolding are
  supplied; participants implement and prove three critical connections.
- [ ] Show the missing-product symptom and collect a prediction before naming
  the disconnected path. Keep the diagnosis and exact repair in the lab.
- [ ] Use the same before/after request and explicit prediction, observation
  and explanation throughout. Preserve all independent controls.

## TODO: weave the expert questions into the existing proof windows

- [ ] Retrieve: distinguish correct eligibility filters from sufficient vector
  candidate coverage. Use an existing plan and count; do not add an index build.
- [ ] Rank: check source-rank contributions even if the final winner is correct;
  discuss the measured reranker benefit, regressions, time and usage together.
- [ ] Reason: identify the actual model-requested and application-started calls;
  trace a particular claim to supporting text and state what is unknown.
- [ ] Introduce G-012 as a deliberate transfer to another product category,
  then return to Alex. Keep its payload and independent target intact.
- [ ] Keep completion inside the current core budget, with Memory and the other
  extensions optional. These discussions must replace explanation time rather
  than add another required exercise.

## TODO: evaluate a monitor alternative for Alex

Proposal, not an approved scenario change: replace the quiet-keyboard need with
a monitor when redesigning the lab story. A developer starting with a laptop
and desk has a clear reason to want more screen space for code, documentation
and calls. The current keyboard need remains consistent across the shipped app
and required labs until a complete replacement is validated.

Candidate brief: sharp text, enough space to work comfortably, and fewer cables.
Keep the wording inclusive; Alex's workflow supplies the requirements.

- [ ] Compare this brief with the existing quiet mechanical keyboard tradeoff.
  Select the scenario that produces the clearest evidence-based decision, not
  simply the most familiar product category.
- [ ] Inspect actual monitor specifications and reviews before fixing a target.
  Useful distinctions may include resolution and size, stand adjustment, USB-C
  display support and power delivery. A USB-C connector alone does not establish
  display capability, charging adequacy or compatibility with a particular laptop.
- [ ] Define one supported option, one plausible alternative and one requirement
  the available evidence cannot establish. Do not force a more expensive winner.
- [ ] Preserve two independent product searches and the comparison in the
  compound request, with the chair requirement and per-product budget explicit.
- [ ] Update the mission manifest first, then adapt the dataset/evidence and
  production checks as needed. Align Discover, Shop, Playground, profile copy,
  presenter material, guides and screenshots together. Do not leave a partial
  keyboard-to-monitor rename across surfaces.
- [ ] Validate the failure, repair, controls, source support and elapsed time
  against Aurora before changing the participant contract.

## Review boundary

The source presenter brief and general Playground explanations can improve
while these decisions remain open. No task here changes the submitted abstract,
adds a fourth lab, makes Memory required or counts a facilitator demonstration
as a participant pass. Publication and the separately required fresh-account
rehearsal remain distinct from this design review.
