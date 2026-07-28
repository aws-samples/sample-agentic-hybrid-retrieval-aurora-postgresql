"""Single source of truth for Hybrid Retrieval Workbench's agent tool contract (T4).

The six model-facing tools plus the full-loop ``answer_with_citations`` are
defined once in :mod:`agent.registry`. The Strands tool specs, the stdio MCP
server, and the AgentCore Gateway (Lambda-ARN) dispatch are all generated from
that registry, so a description edited on one transport cannot silently diverge
from another. Gate G-17 regenerates each artifact and fails CI on any diff.
"""
