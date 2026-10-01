import { AlertTriangle, Download } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { toolPurpose } from "../retrievalLanguage";
import type { ToolContract } from "../types";
import { RETRIEVAL_CONNECTION_GUIDE, RetrievalTakeawayLinks } from "./RetrievalTakeawayLinks";

/** Registry projections describe implemented adapters, not live connection health. */
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
        <h3 id="labs-package-title">Take this retrieval into your own agent</h3>
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
            Connect retrieval tools through MCP or HTTP, then add the skill to guide the
            workflow. The implementation guide maps the SQL, evaluation runner and citation checks
            in the full Mosaic checkout. Aurora runs retrieval. Connect a running Mosaic-compatible
            service and use its answer endpoint or your application’s citation validator.
          </p>
          <p className="labs-contract-note">
            The tools read catalog records; searches still save audit records.
            Service checks and database privileges enforce access. MCP annotations
            and skill instructions do not grant permissions.
          </p>
          <div className="labs-package-actions">
            <a className="secondary-button labs-package-download" href={RETRIEVAL_CONNECTION_GUIDE} target="_blank" rel="noreferrer">
              Connect retrieval tools
            </a>
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
          <p className="labs-contract-note">
            MCP names ranking inspection <code>inspect_retrieval_run</code> and takes
            <code> run_id</code>; the HTTP skill maps it to <span>explain_retrieval</span> with
            <code> retrieval_scope_id</code>. Check the connected tools’ inputs.
            The portable adapter requires a running process; this registry does not test its connection.
          </p>
          <RetrievalTakeawayLinks />
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
