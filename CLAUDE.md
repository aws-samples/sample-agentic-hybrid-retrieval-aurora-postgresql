# Mosaic workshop project

## Session
AWS re:Invent 2026 L400 Builder's Session:
Build agentic hybrid retrieval with Amazon Aurora PostgreSQL.

## Core workshop model
Retrieve -> Rank -> Reason

Required labs:
1. Build hybrid retrieval
2. Fuse, rerank, and explain
3. Build the retrieval agent

## Design principles
- Easy to navigate.
- Easy to execute.
- Deep to inspect.
- Hard to exhaust.
- Each lab uses Broken -> Diagnose -> Fix -> Prove.
- Aurora PostgreSQL and retrieval mechanics must remain inspectable.
- The agent orchestrates retrieval. It does not replace retrieval.
- Do not increase required lab count beyond three.
- Protect the 45-minute hands-on budget. The two-minute recovery buffer is
  part of the 60-minute session, not hidden lab time.
- Treat measured behavior as authoritative. Never invent benchmark or eval data.

## Review behavior
- Prefer evidence from actual source files over assumptions.
- Cite file paths and line ranges in technical review findings.
- Distinguish static verification from runtime verification.
- Do not allow unavailable network/database connectivity to block offline review.
- Do not create parallel replacement workshop structures.
