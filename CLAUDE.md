# Claude Code Entry Point

Read `AGENTS.md` before changing this repository.

For search index, retrieval SQL, ranking, citations, diagnostics, traversal, or
evaluation, use the project skill at
`.claude/skills/extend-hybrid-retrieval/SKILL.md`.

Keep Aurora retrieval in the canonical SQL and API boundary. Do not duplicate
ranking in prompts, the frontend, MCP adapters, or agent harnesses.

The participant path is live-data-only. Bootstrap generates 5,000 disposable
customers and 3,000,000 related orders, but the evidence store starts empty and
may index only PostgreSQL, CloudWatch, and Database Insights observations from
the participant's current `make live-workshop` run. Never substitute fixtures,
authored records, prior captures, offline embeddings, or canned answers. The
Overview main graphic is the only illustrative exception and is not data.
