# Session abstract

## Title

Build agentic hybrid retrieval with Amazon Aurora PostgreSQL

## Abstract

As applications evolve into agentic workflows, retrieval must support more than top-k semantic matches. In this session, use Aurora PostgreSQL as the core search and context engine for agentic hybrid retrieval, with Workshop Studio provisioning the database, Code Editor, and assets ahead of the lab. The workshop frames Aurora as a materialized evidence index: source systems remain authoritative, while connectors, exports, or MCP tools keep searchable evidence fresh and provide live lookups or actions when needed. Implement PostgreSQL full-text search for lexical retrieval, pgvector semantic similarity, SQL and metadata filters, fuzzy matching, reciprocal rank fusion, SQL final scoring, source attribution, and retrieval diagnostics. Then expose these capabilities through harness-portable Strands Agent tools that decompose complex questions, gather targeted evidence, compare sources, explain ranking signals, and synthesize cited answers. The answer path routes work to the best model for the job: Sonnet 5 for planning/tool routing and Claude Code support, Opus 4.8 for synthesis when live composition is enabled. Leave with working code, schema patterns, ranking templates, and techniques for trustworthy retrieval-heavy AI applications.
