# Lab regression checks

`data/evals/mosaic_labs_missions.json` owns the requests, filters, targets, assertions and timing. These exercises use `reviews-2023-v2`: original Amazon Reviews 2023 product records and preserved embeddings. Product facts are not modified to manufacture outcomes.

## Participant experiments

| Stage | Visible before | Repair | Visible after |
|---|---|---|---|
| Retrieve / `G-003` | A transposed Logitech listing ID returns other headphones; the intended listing is absent from the combined pool | Reconnect the existing close-spelling search | The intended Logitech listing returns with its close-spelling contribution; two other Zone 900 listings stay out of the results |
| Rank / G-008 | A 27-inch 4K/90W request omits the suitable ViewSonic VG2756-4K; a 1440p Lenovo ThinkVision T27hv-20 title visibly says 1440p | Use actual source positions in RRF | The ViewSonic enters the combined list, then reaches final position 5 after model reranking |
| Reason / G-021 | The starter cannot assemble the agent | Build the supplied Strands agent and deploy it to Runtime | Separate headphone, monitor and chair searches support a complete-room comparison with citations |

## Independent controls

- **G-001 · Preserve the exact listing:** The correctly spelled ASIN retrieves the intended Logitech listing with an Exact terms contribution.
- **G-012 · Keep the brand requirement:** The model-name search retains the Logitech target. Every saved candidate and displayed result stays within the Logitech headphones filter; a related product from another brand is ineligible.
- **G-007 · Compare display specifications:** Retrieve both named Dell monitors. Their records distinguish 3840 x 2160 from 1920 x 1080. Do not infer equivalent USB-C charging, current price or stock.
- **G-009 · Keep brand filters ahead of scoring:** The same monitor need, restricted to Dell, excludes HP and Lenovo before reranking. Inspect both saved candidates and served results.
- **G-019 · Separate listening from microphone evidence:** Resolve specification and sampled-review citations for the Logitech listing. A listed noise-canceling microphone and one reviewer’s experience do not establish call quality for Alex, and other reviews of this listing disagree; present the review as one experience and disclose the gap.

The internal ID `compare-cheaper-alternative` is retained for existing links. G-007 now compares display specifications; no current price claim is made.

## Release rule

Run the same request before and after the marked repair on Aurora. Preserve each response and search/agent run ID. The guide uses `scripts/apply_search_functions.py`, which verifies the selected real-catalog receipt and installs the participant's SQL into the active search schema without automatically solving its gaps. Deploy the edited Lab 3 agent to AgentCore Runtime; a file edit alone does not update it.

Run `scripts/validate_lab.py` for each lab. Lab 2 repeats the same search; Lab 3 also runs G-019 and saves its receipt for completion without extra model calls. The production path must fail on the deliberate defect and pass on the restored code. Source-state labels alone are insufficient. Keep live functions and source byte-identical after an operator proof.

The broader measured alternatives and unchanged/failing controls are in [the worked-example library](real-catalog-exercise-library.md). They are not substituted into required validators.

## Lab 2 movement: what is guaranteed and what is not

Every contribution must equal `1 / (k + source_rank)` and its sum must equal the recorded fused score. The required product must reach the bounded list and finish inside the mission’s declared final top-k after reranking. It need not be first in every search, or first before reranking.

With the verified catalog and profile, the ViewSonic VG2756-4K entered the combined list at position 21 and finished at final position 5 in repeated runs. Preserve the observed source positions, model ID and profile; do not turn position 21 or final position 5 into a universal law. Several chair and headphone control queries keep their winner through both formulas. They prove why visible success alone cannot certify the calculation.

## Dataset and publication boundary

The earlier synthetic 20-query scorecard and 720 generated eligibility cases do not certify the imported catalog. Keep historical results labeled as such. These updated worked examples and live lab checks establish a bounded teaching contract; representative relevance evaluation, release publication and fresh-account rehearsal are separate gates.
