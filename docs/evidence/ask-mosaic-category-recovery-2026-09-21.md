# Ask Mosaic: saved categories and empty searches

Status: fixed and verified on the local application against Aurora and Bedrock.
This is a focused regression check, not a release or clean-account rehearsal.

## Failure established from the saved run

Run `4a23646d-90ba-4349-88a1-678700af09a5` asked:

> I take video calls from home and need headphones that keep my voice clear despite background noise.

The browser supplied the previous catalog's `over-ear-headphones` category.
The model requested the new `headphones` key, but request-level constraints
correctly took precedence. All ten tool searches therefore retained the retired
key and returned no eligible products. Empty results did not consume the
two-search budget or populate the completed-search list. The controller had no
answer of record and the stream displayed a generic runtime error.

Aurora was available. Readiness confirmed 500,000 products and 500,000 embedded
products in `reviews-2023-500k-v1`; AWS credential validation passed. Refreshing
credentials was not the remedy for this failure.

## Repair

- Resolve known saved category keys when validating filters for the selected
  real catalog. Search, agent requests, and browse filters share that boundary.
  Explicit domain, brand, price, rating, and attribute constraints stay intact.
  Unknown category keys and the legacy catalog are not rewritten.
- Keep the search plan and retrieval receipt even when a completed search is
  empty. Reserve search slots before network calls, including parallel tools.
- Return `declined / no_matching_products` after completed empty searches,
  with no recommendations or citations. A dependency failure remains a failure;
  it cannot become a no-match response.
- Give the participant an explanation about the search and filters. The generic
  error no longer speculates that the API session needs refreshing.

No product fields, photos, embeddings, index settings, or ranking parameters
were changed for this repair.

## Verification

The new category and empty-search regression fixtures failed before the fix.
A separate concurrent-call fixture also failed before slot reservation was
added. Both remain permanent tests.

- 157 focused Python tests passed; two Aurora-marked legacy fixtures were
  skipped. Live verification below used the selected real catalog instead.
- 80 related UI tests passed, including the no-match presentation.
- UI type checks and production build passed. The existing optional HNSW
  visualization bundle-size warning remains.
- Ruff, configuration tripwire, retrieval-profile check, and diff whitespace
  checks passed.

| Live run | Observed outcome |
|---|---|
| `76813592-d8bb-4442-b129-8dac431be09b` | Original request completed in the browser with four recommendations and source links from the new catalog. The model hit its output limit; the existing controller completed the required evidence and synthesis steps. This was recovery, not an uninterrupted model loop. |
| `86ccce03-05f9-4a70-bf05-860a11966848` | The browser's “What do reviews say?” follow-up completed using the prior product identity and fresh source evidence. It stated that no review excerpts were available for that answer. |
| `61811e5a-88a2-45e5-840d-1d4efa769311` | A direct streamed request deliberately retained the old category key. Both searches used `headphones` and returned products. The answerability check declined `unsupported_requirements`. The probe's expectation of a recommendation failed; it did not reproduce the runtime error. This outcome is retained rather than counted as a recommendation success. |
| `622ee063-647e-47a9-a8d1-57a24ba242e5` | A deliberately absent brand filter completed with `no_matching_products`, two searches, two saved receipts, and no recommendations. The stream reached `complete` without an `error` event. |

Local machine receipts are under `.local/real-products/ask-mosaic-*-proof.json`
and `ask-mosaic-recovery-runs.json`. The final API restart and smoke check also
exercise the old category together with the empty-brand filter.

The broad natural-language question does not promise a recommendation on every
model run. Source support is checked separately from whether retrieval and the
stream completed. Further workshop example selection and full release gates
remain separate work. These changes are local and have not been pushed or
published to Workshop Studio.
