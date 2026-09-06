# Mosaic workshop project

## Session
AWS re:Invent 2026 L400 Builder's Session:
Build agentic hybrid retrieval with Amazon Aurora PostgreSQL.

## Core workshop model
Retrieve -> Rank -> Reason

Required labs:
1. Build hybrid retrieval
2. Fuse, rerank, and inspect
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

## Keep the front doors current

`README.md` and `workshop.md` are the two files a reader meets first, and they
are the two that rot silently. **Any session that makes a significant change
must update both before it ends** — a new participant-facing affordance, a
removed surface or route, a changed lab flow, a new required step, a renamed
concept. Not a changelog: edit the prose so it describes what ships now.

A change is significant if a participant or a facilitator would do something
different because of it. Bug fixes with no visible behaviour change are not.

When a surface is deleted, grep `docs/` for it in the same session. `docs/` is
where a removed route survives longest, and a spec describing a page that no
longer exists is worse than no spec. Historical records (`rewrite-losses.md`
and similar) keep their past-tense references — they document what happened.

## Review behavior
- Prefer evidence from actual source files over assumptions.
- Cite file paths and line ranges in technical review findings.
- Distinguish static verification from runtime verification.
- Do not allow unavailable network/database connectivity to block offline review.
- Do not create parallel replacement workshop structures.
