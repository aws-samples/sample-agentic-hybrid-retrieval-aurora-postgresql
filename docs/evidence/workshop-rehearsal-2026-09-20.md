# Workshop rehearsal — 20 September 2026

These observations use the existing live Aurora catalog and the connected
AgentCore Memory resource. They do not certify the staged public catalog or a
fresh Workshop Studio deployment. The local API runs the development worktree
based on `c6300668ab27b4abb956d64cf2d58f6f84c14654`; that base revision alone does
not identify the uncommitted UI and exercise changes.

## Required repair labs

Each fault ran through the production path. The temporary SQL definitions and
Lab 3 source file were restored byte-identically after the experiment.

| Lab | Broken observation | Repaired observation |
|---|---|---|
| Retrieve | Run `4753a995-7552-49ee-a117-20172a1c8ff0`: target 2 absent from the first ten results; no trigram contribution; hard filters held. | Run `a9e25647-6556-4a31-9a07-4803d04bf0b9`: target 2 first, with trigram rank 1 and no FTS or semantic rank. Required checks and independent controls passed. |
| Rank | Run `6a0d6335-a113-400e-bbcd-779fb750c30d`: reciprocal-rank arithmetic failed for nine products. | Run `c382a771-9a3a-445b-a3a1-3da85111e27d`: arithmetic, repeatability and independent controls passed. Product 370002 was already first before repair, so a winner change is not promised. |
| Reason | Turn `de93e8ad-310f-4194-a765-542dcef90bf9`: tools retrieved products and evidence, but synthesis could not attach supporting sources; HTTP 503 and no assistant answer. | Final G-021 run `bbf8d9b6-3e52-4212-a611-d097e112e371` and G-019 run `e07a651b-c9b7-47ad-8c89-cb53e33b3025` passed the production validator. |

All three validators passed again with the current worktree API. The final
Reason receipt identifies `global.anthropic.claude-sonnet-5` for agent and
synthesis, `us.cohere.embed-v4:0` for embeddings, and
`cohere.rerank-v3-5:0` for reranking. Receipt hashes:

- Source: `486d50f6ab0bedee860a9c7bf6b20e381e7d75e8a003e820b0e212f5a19e19c4`
- Settings: `3635fb13943e9504b42c530ffcd75317f5f326d1abf569e108078aa55498116e`
- Database: `6cedf819787fa6a3f0ac8e89221aaeb2b1802f68627799a3da4f0cf33d10bc0e`

## Optional Memory exercise

The participant question, example, changed request and checkpoints are owned by
`optional_labs.memory` in `data/evals/mosaic_labs_missions.json`. Session & Memory
reads that definition directly. This exercise remains outside the required hour;
event storage does not guarantee immediate extraction.

A dedicated test actor saved event `0000001789949229048#16ee5312`. Two extracted
preference records were inspected:

- `mem-7fe699e0-84ad-4f39-b3f6-4d709a9701ef`: 27-inch monitor with USB-C laptop charging.
- `mem-2fdd7f6e-2026-4b03-98af-78c6e5eac36c`: code and documentation side by side with fewer cables.

The following final runs used the current API and Sonnet 5:

| Check | Observed evidence |
|---|---|
| Same actor, new conversation | Run `b172e4a4-3043-4f01-ae3d-c609ccae35cf` read five memory records and zero prior conversation events. It issued fresh Aurora searches for a 27-inch coding monitor and USB-C charging, then returned four product citations. |
| Current request takes priority | Run `a923d15a-6dbf-4433-8e70-97bb9d2fdab3` read five records and zero prior events, searched for a 32-inch monitor, and cited two 32-inch choices. |
| Memory disabled | Run `4be3cbe5-ba39-4281-b7e6-05774e42e596` read zero records and zero prior events. This particular run declined to answer; opt-out guarantees the read boundary, not a particular answer or refusal. |
| Separate actor | A second browser identity retrieved zero relevant records and received HTTP 404 when requesting the first actor’s session events. |

Recall influenced the new searches. It did not prove that every recommended
product met every preference: the final answer explicitly supported USB-C power
delivery for one of its four choices. Product claims still require their own
catalog evidence. An earlier, more restrictive request declined when the available
evidence did not support all requested specifications; that guard was retained.

Test actors are isolated. Starting fresh changes the browser identity and does
not delete saved events or long-term records. Provider error handling and session
ownership also passed the focused production-path Python tests.

## Interface and release boundary

Hybrid Retrieval, Scale & HNSW and Session & Memory were checked at desktop and
mobile widths with no horizontal overflow or page errors. Memory actions use
rounded controls. The connected indicator pulses only while connected and is
static when reduced motion is requested. Actual extracted records were inspected
in the finished UI.

Validation completed: 668 tests in the full UI suite, followed by all 15 Memory
tests after the final request-example addition; TypeScript and production build;
57 focused Python tests; 124 live mission checks; retrieval configuration and
profile checks; and all three live lab validators.

The v15 slide 3 video demonstrates the existing catalog. Replacing it with a
public-catalog recording depends on that catalog’s retrieval and source-evidence
acceptance. Embeddings continue independently; no staged products were promoted
to the live storefront by this rehearsal.
