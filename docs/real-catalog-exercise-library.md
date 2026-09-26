# Worked examples from the real catalog

These are measured requests against `reviews-2023-500k-v1`, the catalog in place when they were run, with the normal filtered search, fusion cutoff and Bedrock reranker. They are alternative teaching examples and controls, not a representative quality benchmark. The required three labs and their five controls remain defined in `data/evals/mosaic_labs_missions.json`. The workshop now serves `reviews-2023-v2`; the required Lab 2 row below is updated to its measured v2 values, but the other secondary examples in this file have not been reverified against the larger catalog and should be treated as historical until they are.

No product descriptions, images, reviews or embeddings were changed to create a result. The deliberate fault is in the code participants repair. Both SQL experiments restored the original live functions byte-for-byte afterwards.

## Recover an exact listing

The later [reviewed comparison pass](reviewed-exercises-2026-09-22.md) adds
separate ESCI and WANDS source records, a three-category comparison view, and a
new proof using the actual on-disk participant reset/repair operations. It keeps
the observations below, including unsuccessful requests, as historical evidence.

A related product is wrong when the request identifies one specific listing. For these queries, keep the shown category and domain filters. The incorrect identifier transposes two adjacent characters. Correct and mistyped identifiers are deliberately shown side by side so participants need not memorize them.

| Product | Category | Correct listing ID | Mistyped request | Before: target position | After: target position |
|---|---|---|---|---|---|
| Bose QuietComfort 35 II (1277987) | headphones | `B07G95TJ3P` | `B07G95T3JP` | Absent | 1 |
| Steelcase Gesture (1221817) | chair | `B01NAKXH73` | `B01NAKX7H3` | 1 | 1 |
| Dell U2720Q (1408222) | monitor | `B0939N79Y8` | `B0939N7Y98` | Absent | 1 |
| Amazon Basics mesh chair (1379290) | chair | `B08KTS3M9M` | `B08KTS39MM` | Absent | 1 |
| Newtral chair with seat-depth adjustment (1490476) | chair | `B0BYZ4KH7G` | `B0BYZ4K7HG` | Absent | 1 |
| Staples Hyken (1248512) | chair | `B076NXZZPD` | `B076NXZPZD` | Absent | 1 |
| Nouhaus Ergo3D (1389794) | chair | `B08QDNY2GK` | `B08QDNYG2K` | Absent | 1 |

Six targets were absent from the combined pool before repair and became final position 1 afterwards. The Steelcase request already worked through meaning search. Keep that unchanged result as a control: not every typo needs the spelling path.

## Compare requirements with product text

The same collapsed-RRF fault is applied for every request below. A visible winner change is useful teaching evidence; unchanged winners still need correct contribution arithmetic.

| Request | Product being checked | Before: target position | After: target position | Teaching use |
|---|---|---|---|---|
| 27 inch 4K monitor USB-C 90W laptop charging | 1551237 | Absent | 5 | Required Lab 2: missing product reaches the shortlist |
| 27 inch monitor to connect and charge my laptop with one USB-C cable 90W 4K | 1408222 | Absent | Absent | Failure retained: wording needs further investigation |
| 27 inch 4K IPS monitor with USB Type C and a height adjustable pivot stand | 1481815 | 1 | 1 | Control: winner is unchanged; inspect the contributions |
| office chair with adjustable lumbar support seat depth adjustment and footrest | 1490476 | 1 | 1 | Control: winner is unchanged; inspect the contributions |
| mesh office chair with 3D adjustable armrests and 3D lumbar support | 1389794 | 1 | 1 | Control: winner is unchanged; inspect the contributions |
| mesh high back chair with flip up arms and headrest | 1379290 | 1 | 1 | Control: winner is unchanged; inspect the contributions |
| wireless noise cancelling headphones with Alexa voice control | 1277987 | 1 | 1 | Control: winner is unchanged; inspect the contributions |

For the required monitor request, inspect the ViewSonic VG2756-4K source for 3840 x 2160 and 90W USB-C charging over one cable. Compare the Lenovo ThinkVision T27hv-20, whose title says 1440p. Do not label every other returned monitor wrong: check its actual record, and distinguish an undocumented feature from an explicitly absent feature.

The alternative chair requests let builders distinguish seat-depth adjustment, lumbar support, movable arms, flip-up arms and a headrest. Those are separate claims. The document must explicitly support the claimed adjustment; the word “ergonomic” alone does not.

## Other useful exercises

- **Exact words and meaning:** use the correctly spelled ID as an exact lookup, then use the full need from the table. Compare which search lists contain the result. Do not infer a universal semantic advantage from a single query.
- **Filtering before ranking:** repeat the monitor request with `brand: "Dell"`; inspect every saved candidate with the production eligibility check. A high model score cannot override a brand or category requirement.
- **Compare near-matches:** G-007 retrieves Dell U2720Q and SE2717H. Both are 27-inch monitors; their source records distinguish 4K from 1080p. An item’s absence from the request’s first page is different from proof that it lacks a feature.
- **Separate specification and experience:** G-019 compares Bose listing text with a sampled customer review. A review discussing listening does not establish call-microphone performance.
- **Scope an answer to its sources:** Lab 3 checks a monitor and a chair using separate searches, a typed comparison, and resolvable citations for each. The deliberate missing evidence registration must fail before repair.

## Reproduce and inspect

`data/evals/real_catalog_exercise_verification.json` stores each request, category/domain filters, search-event IDs and both outcomes, including the unsuccessful wording variant. Send a case’s `query` and `filters` to `/api/search` with `limit: 10`, `include_diagnostics: true` and `rerank: true`. Use `/api/retrieval/events/{search_event_id}` to inspect the full saved pool. Changing the query requires a new measurement; do not reuse a prior result as its proof.

Keep the source catalog fixed for the experiment. More rows and more embeddings do not, by themselves, make an exercise more explanatory.
