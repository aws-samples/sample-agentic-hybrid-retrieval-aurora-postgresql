# Build agentic hybrid retrieval with Amazon Aurora PostgreSQL

In this workshop, you help Alex choose headphones, a monitor, and a chair for his
home office. You will build and inspect the search, ranking, and Retrieval agent steps
behind **Mosaic**, a product discovery application.

The catalog contains **553,911 real source products from Amazon Reviews 2023**.
The product records and saved Cohere embeddings are provided. Maintainer restore
and validation commands use this real catalog; synthetic fixtures and loaders
have been retired. Alex is a fictional
shopper; your searches and answers use the source products and their evidence.

## Start the workshop

1. Open **Introduction → Getting started** in your Workshop Studio guide.
2. Open **Code Editor → [Start Here](START_HERE.md)** beside the guide. Your
   application, Aurora database, and terminal connection are already prepared.
3. Open Mosaic and run the guide's environment checks. Then begin **Lab 1**:
   choose **Browse all products** beside **Shop the workspace**, follow the
   guide's category selections, and inspect the first search before editing code.

Claude Code in the prepared terminal can help you investigate a lab. The
project's [AGENTS.md](AGENTS.md), loaded by [CLAUDE.md](CLAUDE.md), gives it the
lab map, validation commands and exercise boundaries. Share your current lab
and observed result; ask for a hint before a full recovery.

You do not need to install dependencies or start a database or server during
the workshop. Follow the guide's commands as you move through the labs.

<details>
<summary>📷 Mosaic and Alex's home office</summary>

![Mosaic introduces Alex and his home-office needs](docs/images/mosaic-discover.png)

</details>

## What you will build

The workshop follows **Retrieve → Rank → Re-rank → Reason**. Labs 1 and 2 improve
your SQL search. Lab 3 connects that search to the Retrieval agent, a Strands agent on AgentCore Runtime
and exposes the SQL tools through AgentCore Gateway.
`uv run python scripts/deploy_agentcore.py deploy` builds an ARM64 container from your current source, pushes it to the workshop's ECR
repository and updates both runtimes. Docker and registry access are prepared
for you; the command checks deployed source identity and Gateway connectivity,
and that a search through Gateway ran your Lab 1 and Lab 2 SQL in Aurora.
`uv run python scripts/ask_agent.py "QUESTION"` shows each tool call's route and,
under each search, whether Aurora ran your lab files. When the workshop stack
turns on AgentCore Observability (its default), each Retrieval agent run is also traced in
the CloudWatch console's **GenAI Observability** pages; Lab 3 works the same
without it.

| Lab | Question to answer | Where you work |
|---|---|---|
| **Lab 1: Retrieve - Debug hybrid search** | Can search find Alex's Logitech Zone 900 headphones from a mistyped listing ID? | [`labs/lab1_retrieve/`](labs/lab1_retrieve/) |
| **Lab 2: Rank and re-rank - Tune rank fusion and reranking** | **2a Rank:** which candidates survive fusion? **2b Re-rank:** how does their order change? | [`labs/lab2_rank/`](labs/lab2_rank/) |
| **Lab 3: Reason - Build and deploy the Retrieval agent** | Can your Retrieval agent help Alex complete his home office, bring the three choices together, and respond when his requirements change? | [`labs/lab3_reason/`](labs/lab3_reason/) |

The participant workspace, [Mosaic.code-workspace](Mosaic.code-workspace),
groups the existing files as **01 - Retrieve**, **02 - Rank and re-rank**, and **03 - Reason**.
Code Editor starts with the **Dark Modern** theme, independent of the device's
light or dark appearance. Participants can change the theme in Code Editor.
**04 - Explore Mosaic source** opens the application source; prepared
terminals run commands from its root. Maintainer-only files (tests, CI, release
records, lockfiles) are hidden from the Explorer but stay in the checkout. Each lab README follows **Broken →
Diagnose → Fix → Prove**, with a collapsed recovery section linking the
reference answer in `solution/`. Solution folders are hidden from the default
Explorer view. When a lab starts, its
marked blocks hold a `TODO(Lab n)` note that repeats the guide's contract.

Use **Shop** for product search and **Playground** for saved candidates,
ranking, tool calls and cited sources. **Ask Mosaic** opens from the pill in the
header on every page. **Complete my setup** runs Lab 3's
three-product request, and its Ask Mosaic starter stays available before and after
you build the Retrieval agent; it runs on its own filters and says when it clears Shop's.
Keep its original run ID for completion. Ask Mosaic's **Builder view** switch (off by default) adds the run's recorded steps, saved search ids and how each search ranked its products to every answer. The Playground's Prove page keeps the
maintainers' saved scorecard collapsed under **Maintainer measurements**; those
results do not grade your repairs.

The prepared workshop serves a built UI so a live-reload connection cannot
interrupt your answer. Keep the answer open while inspecting its sources, and
save the run ID before refreshing or leaving the page.

The guide opens with the business challenge and workshop structure, then Getting
started. Each lab asks you to predict, investigate, repair and prove the result,
with reference material and optional exercises collapsed. The closing recap
connects what you fixed to Alex's next need. Each lab README is a short reminder beside the
file you edit. Shop’s lab cards show the observed problem before the diagnosis;
repair feedback requires the exercise state and a search made after preparation.
The ranking table sorts the same displayed products and preserves both positions.

After Lab 1's repair check, continue with the guide's description search.
At the end of the lab, run `uv run python scripts/lab_state.py advance --lab 1`
to validate its repair, save passing evidence and prepare Lab 2. Retries resume
preparation without discarding edits. For direct entry, start a lab with
`uv run python scripts/lab_state.py start --lab N`: it saves the failing request,
installs that lab's fault once and preserves earlier repairs. An interrupted
start resumes without overwriting edits. Finish and apply earlier repairs first.
`lab_state.py validate`, `validate_lab.py`, `advance` and `start` judge a saved
Lab 1 or Lab 2 block the same way, against the block Aurora runs, so one cannot
pass while another refuses. A refusal names what differs, the fix and the
command to run again; `uv run python scripts/diff.py` names, in plain words,
the lines of the lab files that differ from the reference answer without
printing it, and `--answer` adds the answer's lines. Live-check failures name the product and the search method
as Shop shows them, and an apply error names the line of your file Aurora rejected.

After editing, apply SQL or deploy the Retrieval agent, repeat the same request, and run
the guide's checks. A plausible result or successful deployment alone is not
completion. Source records must support product claims; a USB-C port alone
does not establish laptop charging compatibility. Finding is fuzzy, recommending
is exact: search tolerates a mistyped ID, but the Retrieval agent recommends a product only
for an ID the catalog carries. Its decline names the listing fuzzy matching
found, if exactly one is that close, and asks you to use that ID.

Use the guide's hints for recovery. Reset discards the selected lab's edits;
the solution action replaces them with the reference answer. Both still need
the lab's proof. Optional Memory and HNSW exercises follow completion.

## How the search works

Mosaic combines three ways to find products: PostgreSQL full-text search,
`pg_trgm` fuzzy matching for misspellings, and pgvector semantic search (HNSW).
Reciprocal-rank fusion (RRF) combines their ranked lists, then Cohere Rerank
reorders the shortlist for the request. The default RRF gives each channel the
same rank-based contribution. The Rank guide offers an optional weighted-RRF
comparison after required completion, using the same candidate lists; it does
not change the default search.

Everything search reads or runs lives in one Aurora PostgreSQL schema,
`mosaic_search`: the `product_listing` table with one index per search
(`product_search_fts_idx`, `product_search_trigram_idx`,
`product_search_vector_idx`), the `product_listing_view` every search reads, and
the functions the labs repair, applied exactly as the lab files define them, so
`\sf mosaic_search.search_hybrid_rrf` prints the SQL Aurora runs.

Bootstrap prepares Lab 2's judged-query cache on the workshop's own Aurora
indexes, using the production HNSW configuration. The cache is tied to the
reference search SQL and search settings. Release tests
check the reference cache's identity; grading checks the prepared cache against
Aurora and repeats live searches.

```mermaid
flowchart LR
    FTS[Full-text search] --> RRF[Combine ranked lists]
    TRGM[Fuzzy matching] --> RRF
    VECTOR[Vector search] --> RRF
    RRF --> RERANK[Rerank the shortlist]
    RERANK --> AGENT[Retrieval agent reads product sources]
    AGENT --> ANSWER[Answer with source checks]
```

Aurora PostgreSQL holds the products, vectors, source records, and saved searches.
Filters determine which products are eligible before candidate limits apply.
Amazon Bedrock supplies query embeddings, reranking, and the Retrieval agent's model. The
application checks the evidence used in the answer. AgentCore Runtime hosts the
Retrieval agent, Gateway exposes its SQL tools over MCP, and AgentCore Memory
provides conversation context for the optional memory exercise.

You can inspect the [search settings](db/config/retrieval.yaml) and follow the
[architecture guide](docs/architecture.md) when you want more detail.

## Take it into your own project

Connect your agent to the retrieval tools, then add the skill to guide the
workflow. **Connect retrieval tools** in Mosaic links to the MCP setup and HTTP
contracts. **Download the skill** adds search, comparison and source-checking
instructions; **Adapt the implementation** supplies reference code.

The tools are catalog-read-only; searches still append audit records. MCP tool
annotations and skill instructions do not grant or restrict database access.
The service checks requests and the database role enforces its privileges.
See [the access boundary and official references](docs/mcp-interoperability.md#permissions-and-workflow-guidance).

- [Adapt the implementation](docs/use-in-your-app.md) maps the schema, retrieval
  SQL, ranking, evaluations, and citation checks to the files you change.
- The [Hybrid Agentic Search skill](skills/mosaic-hybrid-retrieval/SKILL.md) gives
  your agent instructions for finding products, comparing them, and checking
  sources. Keep its reference files together and follow the
  [adaptation checklist](skills/mosaic-hybrid-retrieval/references/adapting.md).
- [Build a retrieval tool](docs/build-retrieval-tool.md) is an optional extension
  for applying your own filtering rule.

The skill requires a running Mosaic service or compatible backend, configured
with its URL and authentication. The workshop endpoint expires with the event;
the download does not include a hosted service.

## Further reading

- [Developer setup and checks](docs/development.md) — run or contribute to the
  application outside the workshop. Database work always uses Aurora.
- [MCP integration](docs/mcp-interoperability.md) — connect another agent host.
- [Session memory](docs/session-memory.md) — explore saved preferences and conversations.
- [Documentation map](docs/index.md) — additional technical and operator guides.

## Data and license

The catalog comes from **Amazon Reviews 2023** (McAuley Lab, UC San Diego). Cite
it as the publisher asks: Yupeng Hou, Jiacheng Li, Zhankui He, An Yan, Xiusi
Chen, and Julian McAuley. 2024. *Bridging Language and Items for Retrieval and
Recommendation.* [arXiv:2403.03952](https://arxiv.org/abs/2403.03952). The BibTeX
entry, and the ESCI and WANDS citations and terms, are in [NOTICE.md](NOTICE.md).
The prepared catalog bundle is excluded from Git; its public redistribution
remains unresolved. Code uses the [MIT-0 license](LICENSE).
For contributions and security reporting, see [CONTRIBUTING.md](CONTRIBUTING.md).
