<div align="center">

# Build agentic hybrid retrieval with Amazon Aurora PostgreSQL

**Full-text, fuzzy and semantic search fused in SQL, reranked with Amazon Bedrock, and a
Retrieval agent on Amazon Bedrock AgentCore that answers with sources.**

[![CI](https://img.shields.io/github/actions/workflow/status/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql/ci.yml?branch=main&style=for-the-badge&label=CI&logo=githubactions&logoColor=white)](https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql/actions/workflows/ci.yml)
[![CodeQL](https://img.shields.io/github/actions/workflow/status/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql/github-code-scanning%2Fcodeql?branch=main&style=for-the-badge&label=CodeQL&logo=github&logoColor=white)](https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql/actions/workflows/github-code-scanning/codeql)
[![License: MIT-0](https://img.shields.io/badge/license-MIT--0-0A7BBB?style=for-the-badge)](LICENSE)

[![Amazon Aurora PostgreSQL](https://img.shields.io/badge/Amazon%20Aurora-PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white&labelColor=232F3E)](https://aws.amazon.com/rds/aurora/)
[![Claude in Amazon Bedrock](https://img.shields.io/badge/Amazon%20Bedrock-Claude-D97757?style=for-the-badge&logo=claude&logoColor=white&labelColor=232F3E)](https://aws.amazon.com/bedrock/anthropic/)
[![Cohere Embed and Rerank in Amazon Bedrock](https://img.shields.io/badge/Amazon%20Bedrock-Cohere%20Embed%20%C2%B7%20Rerank-39594D?style=for-the-badge&labelColor=232F3E)](https://aws.amazon.com/bedrock/cohere/)
[![Amazon Bedrock AgentCore](https://img.shields.io/badge/Amazon%20Bedrock-AgentCore-FF9900?style=for-the-badge&labelColor=232F3E)](https://aws.amazon.com/bedrock/agentcore/)
[![Strands Agents](https://img.shields.io/badge/Agent%20framework-Strands%20Agents-3F8624?style=for-the-badge&labelColor=232F3E)](https://strandsagents.com/)

[![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-20232A?style=for-the-badge&logo=react&logoColor=61DAFB)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![MCP tools through AgentCore Gateway](https://img.shields.io/badge/MCP-AgentCore%20Gateway-000000?style=for-the-badge&logo=modelcontextprotocol&logoColor=white)](https://modelcontextprotocol.io/)

[The scenario](#the-scenario) · [Labs](#what-you-build) · [Architecture](#architecture) ·
[How it works](#how-hybrid-retrieval-works) · [Run the workshop](#run-the-workshop) ·
[Use it in your project](#use-it-in-your-own-project)

</div>

This repository contains **Mosaic**, the sample product discovery application for the
workshop *Build agentic hybrid retrieval with Amazon Aurora PostgreSQL*. In three
hands-on labs you repair hybrid search in Amazon Aurora PostgreSQL, tune how its results
are ranked, and then build and deploy a Retrieval agent with Strands Agents on Amazon
Bedrock AgentCore that answers with sources.

The catalog holds **553,911 real products from the Amazon Reviews 2023 dataset**, with
saved Cohere Embed v4 embeddings. Alex, the shopper in the story, is fictional; every
search and answer runs against the real catalog and its source records.

> **Attending the workshop?** Your account, Aurora cluster, application and terminal are
> already prepared, so there is nothing to install. Follow your Workshop Studio guide and
> open [START_HERE.md](START_HERE.md) in Code Editor.

## The scenario

Alex is a software engineer setting up a home office. He has a desk and a laptop, and
needs headphones, a monitor and a chair, with sources behind each recommendation. Each
lab takes one part of that request and starts from a failure you can observe: a results
page that looks plausible but does not include the product Alex wanted, with no error
to explain why.

## What you build

Each lab follows the same cycle: **Broken → Diagnose → Fix → Prove**. You trace the
failing request, repair the marked code, apply or deploy it, and prove the fix against
the same request. Your repairs carry forward from one lab to the next.

| Lab | Question to answer | Where you work |
|---|---|---|
| **Lab 1: Retrieve - Debug hybrid search** | Can search find Alex's Logitech Zone 900 headphones from a mistyped listing ID? | [`labs/lab1_retrieve/`](labs/lab1_retrieve/) |
| **Lab 2: Rank and re-rank - Tune rank fusion and reranking** | Which candidates survive rank fusion, and how does reranking change their order? | [`labs/lab2_rank/`](labs/lab2_rank/) |
| **Lab 3: Reason - Build and deploy the Retrieval agent** | Can your Retrieval agent complete Alex's setup, support each choice with sources, and respond when his requirements change? | [`labs/lab3_reason/`](labs/lab3_reason/) |

Labs 1 and 2 are SQL exercises: you diagnose in `psql`, repair the marked SQL file and
apply it to Aurora. In Lab 3 you build the Retrieval agent in Python, deploy it to
AgentCore Runtime and check its answers from the terminal. Optional exercises cover
AgentCore Memory, a smaller and faster HNSW index for filtered semantic search, weighted
rank fusion and building your own retrieval tool.

## Architecture

![Hybrid retrieval architecture with an Ask Mosaic path and a Shop path. Alex uses the Mosaic API on CloudFront and EC2. On the Ask Mosaic path, the Retrieval agent runs on AgentCore Runtime with Strands and Claude Sonnet 5.5 and calls MCP tools through AgentCore Gateway; the SQL tools, on a second AgentCore Runtime, embed and rerank with Cohere models in Amazon Bedrock and query hybrid SQL and evidence in Aurora PostgreSQL. AgentCore Memory is optional. On the Shop path, the Mosaic API runs the same search without the agent: Cohere Embed v4 and Cohere Rerank 3.5 in Amazon Bedrock, then Aurora. Only the agent uses Claude.](docs/images/architecture.png)

| Component | Role |
|---|---|
| **Amazon Aurora PostgreSQL** | Stores products, vectors, source records and saved searches. Runs full-text search, fuzzy matching and semantic search, and combines their rankings, all in SQL. |
| **Amazon Bedrock** | Provides Cohere Embed v4 for query embeddings, Cohere Rerank 3.5 for reranking, and Claude Sonnet 5.5 for the Retrieval agent. |
| **Amazon Bedrock AgentCore** | **Runtime** hosts the Retrieval agent and its SQL tools, **Gateway** exposes the tools over MCP, and **Memory** holds optional conversation context. Product facts always come from Aurora. |
| **[Strands Agents](https://strandsagents.com/)** | The Python framework the Retrieval agent is built with. |
| **Mosaic** | A FastAPI service and React interface. **Shop** runs the same search as the agent's SQL tools without asking the Retrieval agent, **Ask Mosaic** sends questions to the Retrieval agent, and **Playground** shows saved searches, rankings, tool calls and sources. |

## How hybrid retrieval works

![The four stages, left to right: Retrieve runs full-text search, fuzzy matching and semantic search in Aurora PostgreSQL; Rank combines the three lists with reciprocal rank fusion; Re-rank uses Cohere on Amazon Bedrock to check fit; Reason uses a Strands agent on AgentCore Runtime to help Alex decide.](docs/images/retrieval-pipeline.png)

1. **Retrieve.** Under the same SQL filters, three searches each return a ranked list:
   PostgreSQL full-text search (`tsvector`) for terms and IDs, `pg_trgm` fuzzy matching
   for misspellings, and `pgvector` semantic search (HNSW) for meaning.
2. **Rank.** Reciprocal rank fusion (RRF) combines the lists by position, because each
   search scores on its own scale, and keeps a shortlist.
3. **Re-rank.** Cohere Rerank 3.5 compares each shortlisted product with the request and
   reorders the shortlist. It cannot recover a product that never reached it.
4. **Reason.** The Retrieval agent chooses its searches, reads specifications and
   reviews, and answers with sources. A citation identifies a source but does not prove
   the claim, so the application checks every drafted answer: each citation must name a
   record the agent was given, and every figure a sentence states must appear in the
   cited record, in the same unit.

Everything search reads or runs lives in one schema, `mosaic_search`: the
`product_listing` table with one index per search, the `product_listing_view` that every
search reads, and the functions the labs repair. Run
`\sf mosaic_search.search_hybrid_rrf` in `psql` to print the SQL Aurora runs. Candidate
limits, the RRF constant and other settings are in
[`db/config/retrieval.yaml`](db/config/retrieval.yaml), and the
[architecture guide](docs/architecture.md) covers the design in depth.

## Run the workshop

The workshop runs in AWS Workshop Studio, which provisions the Aurora cluster, the
Mosaic application, Code Editor and model access for each participant.

1. Open **Getting started** in your Workshop Studio guide.
2. Open Code Editor beside the guide and follow [START_HERE.md](START_HERE.md).
3. Run the catalog readiness check, save Lab 1's failing search, and begin Lab 1 in
   `psql`.

Claude Code in the prepared terminal acts as a coding coach. [AGENTS.md](AGENTS.md),
loaded through [CLAUDE.md](CLAUDE.md), gives it the lab map, validation commands and
exercise boundaries, so it offers hints before answers and asks before it edits a file
or runs a command.

The commands you use most:

| Purpose | Command |
|---|---|
| See where each lab stands | `uv run python scripts/lab_state.py status` |
| Finish Lab 1 or Lab 2 and prepare the next lab | `uv run python scripts/lab_state.py advance --lab 1` |
| Deploy your Retrieval agent (Lab 3) | `uv run python scripts/deploy_agentcore.py deploy` |
| Ask the deployed Retrieval agent | `uv run python scripts/ask_agent.py "QUESTION"` |
| Check your Lab 3 setup run | `uv run python scripts/complete_agent.py` |
| Catch up by installing a lab's reference answer | `uv run python scripts/lab_state.py finish --lab N` |

A successful deploy or a plausible answer is not completion: each lab ends with the
guide's checks against the same request, run on the state you applied or deployed.

To run the workshop outside an AWS event, in an account you own, follow
[Run Mosaic in your own account](docs/run-in-your-own-account.md).

## Use it in your own project

Connect your agent to the retrieval tools, then add the skill to guide its workflow. In
Mosaic, **Playground → Use it in your own agent** links to the MCP setup and HTTP
contracts, the agent skill, and the search SQL with its adaptation guide.

- [Adapt the implementation](docs/use-in-your-app.md) maps the schema, retrieval SQL,
  ranking, evaluations and citation checks to the files you change.
- The [Hybrid Agentic Search skill](skills/mosaic-hybrid-retrieval/SKILL.md) gives your
  agent instructions for finding products, comparing them and checking sources. Keep
  its reference files together and follow the
  [adaptation checklist](skills/mosaic-hybrid-retrieval/references/adapting.md).
- [MCP integration](docs/mcp-interoperability.md) connects another agent host to the
  catalog tools.
- [Build a retrieval tool](docs/build-retrieval-tool.md) is an optional extension for
  applying your own filtering rule.

The skill requires a running Mosaic service or compatible backend, configured with its
URL and authentication; a workshop endpoint expires with its event. The catalog tools
are read-only, although each search appends an audit record. MCP tool annotations and
skill instructions do not grant or restrict database access: the service validates
requests and the database role enforces privileges. See
[the access boundary](docs/mcp-interoperability.md#permissions-and-workflow-guidance).

## Repository layout

| Path | Contents |
|---|---|
| [`labs/`](labs/) | One folder per lab: the file you edit, a short README and the reference answer in `solution/` |
| [`db/`](db/) | Schema, search SQL in install order, indexes, retrieval settings and catalog contracts |
| [`service/`](service/) | The FastAPI service: retrieval, agent tools, evidence and citation checks |
| [`ui/`](ui/) | The React interface: Shop, Playground and Ask Mosaic |
| [`deploy/`](deploy/) | AgentCore Runtime entry points, the container image and the host bootstrap |
| [`mcp-server/`](mcp-server/) | The MCP adapter for the catalog tools |
| [`skills/mosaic-hybrid-retrieval/`](skills/mosaic-hybrid-retrieval/) | A portable agent skill for hybrid product retrieval |
| [`scripts/`](scripts/) | Participant commands at the top level; maintainer tooling in `catalog/`, `evals/`, `bench/` and `checks/` |
| [`data/`](data/) | Lab missions, evaluation cases and saved benchmark measurements |
| [`docs/`](docs/) | Architecture, operations and adaptation guides ([documentation map](docs/index.md)) |
| [`tests/`](tests/) | Offline tests and tests that run against Aurora |

## Develop and contribute

To run or change Mosaic outside a workshop event, follow
[docs/development.md](docs/development.md). There is no local database path: development
and tests use an Amazon Aurora PostgreSQL cluster with the Mosaic catalog loaded, and the
prepared catalog bundle is not stored in this repository. Read [AGENTS.md](AGENTS.md)
and the [house standards](docs/house-standards.md) before you change code, and see
[CONTRIBUTING.md](CONTRIBUTING.md) to propose a change.

Further reading:

- [Managed agent on AgentCore Runtime](docs/agentcore-runtime.md)
- [Session memory](docs/session-memory.md)
- [Documentation map](docs/index.md)

## Data and attribution

The catalog comes from **Amazon Reviews 2023** (McAuley Lab, UC San Diego). Cite it as
the publisher asks: Yupeng Hou, Jiacheng Li, Zhankui He, An Yan, Xiusi Chen, and Julian
McAuley. 2024. *Bridging Language and Items for Retrieval and Recommendation.*
[arXiv:2403.03952](https://arxiv.org/abs/2403.03952). [NOTICE.md](NOTICE.md) has the
BibTeX entry and the ESCI and WANDS citations and terms used by the evaluations. Product
names, brands and trademarks belong to their owners.

## Security

See [CONTRIBUTING.md](CONTRIBUTING.md#security-issue-notifications) for more
information. Please report a potential security issue through the
[AWS vulnerability reporting page](https://aws.amazon.com/security/vulnerability-reporting/),
not a public GitHub issue.

## License

This sample is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.
