# Session abstract

## Title

Build agentic hybrid retrieval with Amazon Aurora PostgreSQL

## Abstract

As applications evolve into agentic workflows, retrieval must support more than top-k semantic matches. In this session, use Aurora PostgreSQL as the core search and context engine for agentic hybrid retrieval, with Workshop Studio provisioning the database, Code Editor, and a managed AgentCore Gateway ahead of the lab. Systems of record remain authoritative for the workflows they own; Aurora provides a rebuildable evidence index that makes approved evidence comparable for cross-system ranking, joins, citations, evaluation, and reproducible retrieval. Connectors and exports keep that projection fresh, while live tools revalidate mutable facts or perform actions in the source. Implement PostgreSQL full-text search for lexical retrieval, pgvector semantic similarity, SQL and metadata filters, fuzzy matching, reciprocal rank fusion, SQL final scoring, source attribution, and retrieval diagnostics. Then expose the stable search and cited-answer API through Strands tools and an `AWS_IAM`-authorized AgentCore Gateway with a Lambda MCP target. The answer path routes work to the best model for the job: Sonnet 5 for planning/tool routing and Claude Code support, Opus 4.8 for synthesis when live composition is enabled. Leave with a portable API/tool contract, working code, schema patterns, ranking templates, and techniques for trustworthy retrieval-heavy AI applications.
