# Claude Code Entry Point

Read `AGENTS.md` before changing this repository.

For source connectors, retrieval SQL, ranking, citations, diagnostics, or
evaluation, use the project skill at
`.claude/skills/extend-hybrid-retrieval/SKILL.md`.

Keep Aurora retrieval in the canonical SQL and API boundary. Do not duplicate
ranking in prompts, the frontend, MCP adapters, or agent harnesses.
