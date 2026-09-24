import { AlertTriangle, Download } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { toolPurpose } from "../retrievalLanguage";
import type { ToolContract } from "../types";

/**
 * The unnumbered finale after the Retrieval Scorecard, inside stage 04 Prove.
 *
 * `Retrieve -> Rank -> Reason -> Prove -> Package` is the intended progression
 * (`docs/superpowers/specs/2026-08-27-prove-and-package-architecture.md`, R5).
 * A fifth numbered stage would read as a fourth curriculum item, which the
 * owner ruled out, so this renders as a sibling of the scorecard within stage
 * 04. Its larger heading and accent edge mark it as the conclusion, while the
 * missing stage number keeps it outside the numbered curriculum.
 *
 * This used to be a `PlaygroundDisclosure` inside stage 03 Reason, opened on
 * click. Packaging is not part of agent reasoning, and the owner's mockup
 * shows the adapter statuses visible rather than behind a click, so this
 * loads on mount instead -- the same lifecycle `RetrievalScorecard` already
 * uses for its own fetch, now that there is no disclosure left to hang the
 * fetch on.
 *
 * The four capabilities are read live from `GET /api/tools?surface=skill`.
 * HTTP and MCP are only ever "Implemented" because their own tool-contract
 * surfaces resolved with at least one entry; A2A carries no measurement, so
 * it is rendered as documentation and never as available, connected, or
 * deployed -- no link, no button, ever.
 */
export function PackageFinale() {
  const [skill, setSkill] = useState<ToolContract[] | null>(null);
  const [skillError, setSkillError] = useState<string | null>(null);
  const [mcpCount, setMcpCount] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([api.toolContracts("skill"), api.toolContracts("mcp")])
      .then(([skillTools, mcpTools]) => {
        if (!active) return;
        setSkill(skillTools);
        setMcpCount(mcpTools.length);
      })
      .catch((cause: unknown) => {
        if (!active) return;
        setSkillError(
          cause instanceof Error ? cause.message : "Could not read the registry.",
        );
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <section className="labs-package-finale" aria-labelledby="labs-package-title">
      <header className="labs-package-heading">
        <h3 id="labs-package-title">Take hybrid agentic search into your own agent</h3>
        <p>
          Carry forward tsvector + pg_trgm + pgvector → RRF → Cohere Rerank →
          evidence-backed answers, with checks for filters, recall, ranking and citations.
        </p>
      </header>

      {skillError ? (
        <p className="labs-disclosure-error" role="alert">
          <AlertTriangle aria-hidden="true" size={16} />
          {skillError}
        </p>
      ) : skill === null ? (
        <p role="status">Loading the available tools.</p>
      ) : (
        <>
          <p className="labs-contract-note">
            The implementation guide maps the SQL, evaluation runner and citation checks
            in the full Mosaic checkout. The agent-independent skill includes the workflow,
            HTTP requests and quality checks. Aurora runs retrieval. Connect a running Mosaic-compatible
            service and use its answer endpoint or your application’s citation validator.
          </p>
          <div className="labs-package-actions">
            <a className="secondary-button labs-package-download" href="/api/builder-package" download>
              <Download size={16} aria-hidden="true" /> Adapt the implementation
            </a>
            <a className="secondary-button labs-package-download" href="/api/skill-package" download>
              <Download size={16} aria-hidden="true" /> Download the skill
            </a>
          </div>
          <ul className="labs-contracts labs-skill-capabilities">
            {skill.map((contract) => (
              <li key={contract.name}>
                <code>{contract.name}</code>
                <b>{contract.read_only ? "catalog read-only" : "writes"}</b>
                <small>{toolPurpose[contract.name] ?? "Read this tool’s inputs and outputs in the downloaded package."}</small>
              </li>
            ))}
          </ul>
          <p className="labs-skill-adapters-label">Reachable through</p>
          <ul className="labs-skill-adapters">
            <li data-testid="adapter-http">
              <code>HTTP</code>
              <b>Implemented</b>
              <span>{skill.length} operations</span>
            </li>
            <li data-testid="adapter-mcp">
              <code>MCP</code>
              <b>{mcpCount ? "Implemented" : "Not declared"}</b>
              <span>{mcpCount ?? 0} operations</span>
            </li>
            <li data-testid="adapter-a2a" className="labs-skill-adapter-doc">
              <code>A2A</code>
              <span>Documented, not deployed</span>
            </li>
          </ul>
          <p className="labs-skill-closing">
            For your own application, filter products before applying result limits,
            cap the candidate list, save each search, and keep comparisons within
            the returned products. Require sources for claims. Adapt the schema,
            copy, models, settings, user IDs, retention rules and test searches
            to your use case.
          </p>
        </>
      )}
    </section>
  );
}
