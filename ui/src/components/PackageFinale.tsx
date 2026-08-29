import { AlertTriangle } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { ToolContract } from "../types";

/**
 * The unnumbered finale after the Retrieval Scorecard, inside stage 04 Prove.
 *
 * `Retrieve -> Rank -> Reason -> Prove -> Package` is the intended progression
 * (`docs/superpowers/specs/2026-08-27-prove-and-package-architecture.md`, R5).
 * A fifth numbered stage would read as a fourth curriculum item, which the
 * owner ruled out, so this renders as a sibling of the scorecard within stage
 * 04 -- set apart by its own rule, never boxed like the scorecard's own A-D
 * sections, so it never reads as a fifth one of those either.
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
      <hr className="labs-package-rule" aria-hidden="true" />
      <h3 id="labs-package-title">Package what you built</h3>
      <p className="labs-package-name">Mosaic Hybrid Retrieval Skill</p>

      {skillError ? (
        <p className="labs-disclosure-error" role="alert">
          <AlertTriangle aria-hidden="true" size={16} />
          {skillError}
        </p>
      ) : skill === null ? (
        <p role="status">Reading the declared capability.</p>
      ) : (
        <>
          <p className="labs-contract-note">
            The three labs built one bounded retrieval capability. Its package
            carries the callable contract, checked HTTP mapping, composition
            profile, and adaptation guide.
          </p>
          <p className="labs-skill-takeaway">
            <span>Participant takeaway</span>
            <code>skills/mosaic-hybrid-retrieval/</code>
            <small>Keep the whole folder together.</small>
          </p>
          <ul className="labs-contracts labs-skill-capabilities">
            {skill.map((contract) => (
              <li key={contract.name}>
                <code>{contract.name}</code>
                <b>{contract.read_only ? "catalog read-only" : "writes"}</b>
                <small>{contract.description}</small>
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
            The interface can move. Retrieval authority stays in Aurora. Keep
            pre-limit eligibility, bounded pools, receipts, grant scope, and
            source attribution; replace Mosaic&apos;s schema, language,
            models, tuning, identity, retention, and evaluation corpus.
          </p>
        </>
      )}
    </section>
  );
}
