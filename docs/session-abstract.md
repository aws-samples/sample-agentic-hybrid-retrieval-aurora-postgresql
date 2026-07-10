# Session abstract

## Title

Build agentic hybrid retrieval with Amazon Aurora PostgreSQL

## Abstract

As applications evolve from RAG to agentic workflows, retrieval must support more than top-k semantic matches. In this session, use PostgreSQL as the core search and context engine for agentic hybrid retrieval, with the lab running on localhost PostgreSQL or a CDK-provisioned Aurora PostgreSQL 18.3 cluster. The workshop frames Aurora as a materialized evidence index: source systems remain authoritative, while connectors, exports, or MCP tools keep searchable evidence fresh and provide live lookups or actions when needed. Implement PostgreSQL full-text search for lexical retrieval, pgvector semantic similarity, SQL and metadata filters, fuzzy matching, reciprocal rank fusion, SQL final scoring, source attribution, and retrieval diagnostics. Then wire these capabilities into agent tools that decompose complex questions, gather targeted evidence, compare sources, explain ranking signals, and synthesize cited answers. Leave with working code, schema patterns, ranking templates, and techniques for trustworthy retrieval-heavy AI applications.
