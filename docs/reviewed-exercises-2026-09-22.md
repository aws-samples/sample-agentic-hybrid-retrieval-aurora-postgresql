# Reviewed exercises: headphones, chairs and monitors

The required story remains one home office: recover the headphones Alex saved,
find a monitor whose record meets the stated need, then check that monitor and
an adjustable chair against their sources. All three actual participant repairs
were run before and after with identical requests. Source files and live SQL
functions were restored byte-identically afterward.

| Required lab | Broken production result | Repaired production result |
|---|---|---|
| Retrieve: copied Bose listing ID | Intended listing absent from the saved combined list; an adapter appeared first | Intended Bose listing admitted at combined position 2 and final position 1 |
| Rank: 27-inch 4K USB-C monitor, up to 90W | Documented Dell listing absent from the saved combined list | Dell admitted at combined position 24 and final position 1 |
| Reason: monitor and adjustable chair | HTTP 503 naming missing evidence registration; no recommendation | Answer with registered, resolvable product evidence for both products |

Fresh production validation then passed **10 Lab 1, 15 Lab 2 and 19 Lab 3
checks**, including the independent controls. See the requests, search IDs,
repair diffs, answers and remaining limits in
[`evidence/reviewed-exercises-2026-09-22.json`](evidence/reviewed-exercises-2026-09-22.json).
Counts and positions describe these recorded runs, not guaranteed future ranks.

## Reviewed source comparisons

Playground now links to **Compare product details** at `/labs/examples`. Three
equal category controls keep headphones, chairs and monitors visible. Seven
case views contain 12 current Amazon catalog products and four separate WANDS
records. Source text, original Amazon photos and original listing links are
preserved. WANDS supplies neither photos nor original listing URLs; the UI does
not manufacture them.

Alex's hero retains its wheeled chair, consistent with the casters stated in
the reviewed Steelcase listing. The optional ESCI chair-base comparison is
explicitly another customer's request, not a no-wheels requirement for Alex.
The hero illustrates the room; it does not claim to show that exact Steelcase.

Rendered inspection covered all three category views, the original Amazon
photos and listing links, and both WANDS comparisons. The saved Lab 1 and
Lab 2 before/after events were replayed in Playground: the repaired cards
visibly identify the intended Bose listing and Dell's stated up-to-90W charging.
Shop issues a fresh search; use Playground's event replay to inspect a saved run.

| Category | Compare | Source evidence |
|---|---|---|
| Headphones | Earbuds versus an audio adapter | ESCI query 107238, Exact versus Complement; linked to the current catalog records by ASIN and US locale |
| Chairs | Fixed versus rolling base | ESCI query 75180, Exact versus Irrelevant; current photo/text must still support the distinction |
| Chairs | Adjustable versus fixed arms | WANDS query 422, products 33601 and 29752; seat-height adjustment is not arm adjustment |
| Monitors | Ultrawide screen versus documented USB-C connection | ESCI query 106506, Exact versus Substitute; missing text is not an absent feature |
| Monitor stands | One screen versus two | WANDS query 163, products 37389 and 37390; Amazon VIVO stands are separately reviewed and inherit no WANDS labels |

The [reference bundle](../data/evals/references/README.md) contains ten original
records, original judgments, source-file hashes, licenses and reproducible
extraction instructions. Six ESCI records link to six of the twelve reviewed
Amazon products. WANDS remains a separate comparison set. None of these labels
or teaching notes changes retrieval scores or embedding input.

Requirements, released relevance labels and source facts remain separate. The
UI suppresses saved claims if the current Amazon product revision changes.
The live verifier checked all twelve current records, twenty-one exact quotes
and their unchanged embedding inputs. Permanent negative tests cover identity,
source changes, vector-input mismatches, invented quotes, conflicting labels,
wrong locale, cross-dataset joins and missing category coverage.

## What the additional searches actually did

The three ESCI queries were also sent unchanged to the production search API,
without category filters and with the normal reranker. These are healthy-path
observations, not another before/after repair:

- **Headphones:** selected earbuds appeared first; the selected adapter was
  outside the saved list.
- **Chairs:** neither selected source pair appeared in the saved list.
- **Monitors:** neither selected source pair appeared in the saved list.

Keep these misses visible. The other returned products are ungraded, not
automatically wrong: this reviewed selection is incomplete and the search
corpus differs from the released datasets. Do not compute an accuracy score or
claim a new ranking improvement from these observations. Full requests and
returned titles are retained in
[`evidence/reference-searches-2026-09-22.json`](evidence/reference-searches-2026-09-22.json).

## Catalog and remaining limits

An Aurora read checked **500,000 stored vectors and 500,000 matching embedding
input hashes**. A subsequent category-only reconciliation moved **1,662**
monitor arms/stands from `other` to `monitor_stand`. It checked all other
columns for those rows: **zero changed**, **zero vectors regenerated**. This
is additional to the earlier category repair, not another count of those rows.

The Lab 1 list still contains adapter product 1238789 after the recovered Bose
listing. Its source files it under headphones. That known source-category error
is retained in the receipt; the spelling repair does not clean the entire
catalog. Lab 2 does not prove every other monitor unsuitable. The required
Lab 3 run retrieved product specifications, not customer review excerpts; its
answer explicitly says usage experience and all-day comfort are unestablished.

The workshop guides link the comparisons in collapsed optional explanations.
The required timings and three code gaps are unchanged. The 131 local Workshop
Studio tests pass. The full package validator remains blocked by the existing
bootstrap-script hash mismatch between contentspec and the checked-in asset.
Publication, source pin parity and fresh-account rehearsal
are separate gates; this pass does not claim them. No complete WANDS/ESCI table
load, new embeddings, whole-catalog benchmark or Workshop Studio publication
was performed.
