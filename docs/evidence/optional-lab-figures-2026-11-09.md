# Optional lab and Lab 1 in depth figures, 9 November 2026

The workshop guide quotes figures from single recorded runs: the Scale & HNSW exercise
(Optional labs) and the plan table in Lab 1 in depth (Go deeper). The first recording was a
fresh event on 22 October 2026, on Aurora PostgreSQL 18.3. These are the same measurements on
Aurora PostgreSQL 18.6 with pgvector 0.8.2, the engine events now run, on a Workshop Studio
test event account (us-east-1, `db.r8g.2xlarge`), with Lab 1's saved request.

## Scale & HNSW exercise

Step 1 ran the guide's own block (four read-only plans of Lab 1's request). Step 2 created
`.local/lab-1/recall.sql` with the guide's block, the exact query was written, and
`scripts/lab_exercise.py grade --lab 1` graded it.

| Measurement | 22 October, 18.3 (guide) | 9 November, 18.6 |
|---|---|---|
| A. `relaxed_order` (the app) | 150 rows | 150 rows, 11.8 ms, 343 removed by the filter |
| B. `strict_order` | 150 rows | 150 rows, 14.4 ms, 386 removed |
| C. iterative scan off, `ef_search` 100 | 36 rows | 15 rows, 4.1 ms, 85 removed |
| D. iterative scan off, `ef_search` 400 | 143 rows | 123 rows, 9.3 ms, 277 removed |
| Recall, planner's plan and forced HNSW | 0.760 (114 of 150) | 0.753 (113 of 150), `Lab 1 exercise: PASS` |

Every plan used `Index Scan using product_search_vector_idx`. Each event builds its own HNSW
graph, so C, D and recall move between events, as the guide says. The lesson holds on both
engines: without iterative scanning far fewer than 150 eligible rows return, and more initial
effort returns more but not all of them.

## Lab 1 in depth: listings that pass and the plans

| Measurement | Guide | 9 November, 18.6 |
|---|---|---|
| Listings that pass the headphones filter | 42,538 | 42,538 |
| Listings that pass the monitors filter | 6,830 | 6,830 |
| *headphones that help me focus when working from home*, headphones filter: of the exact 150 nearest, returned | 118, HNSW index then the filter | 118, `Index Scan using product_search_vector_idx` |
| The same request, no category filter | 118, HNSW index | 118, `Index Scan using product_search_vector_idx` |

The exact 150 were ordered by `(embedding <=> vector) + 0, product_id`, which cannot use the
index, under the same filters (`mosaic_search.matches_filters`). The approximate 150 came from
`mosaic_search.search_semantic` after `configure_hnsw` set the request's own profile. The
request's vector was the one the API embedded for that search. The monitors row's plan and
recall were not re-measured here.
