import { AlertTriangle, Check, LoaderCircle, Minus, Play } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { CodeBlock } from "./CodeBlock";
import {
  PlaygroundDisclosure,
  PlaygroundDisclosureShelf,
  PlaygroundDormant,
  PlaygroundFigure,
  PlaygroundFigures,
} from "./PlaygroundStage";
import type {
  AgentCitation,
  AgentPartial,
  AgentResponse,
  EvidenceRecord,
  ProductSummary,
  SearchFilters,
  ToolContract,
  ToolTraceStep,
} from "../types";

/**
 * Stage 03, Reason: what the agent was given, what the application registered,
 * what it authorized, and which citations resolve.
 *
 * Lab 3's repair is four lines inside `service/agent_tools.get_product_evidence`,
 * between the `LAB3_EVIDENCE_STATE` markers, that write each retrieved record into
 * `state["evidence"]` and index it under its product in
 * `state["evidence_by_product"]`. Delete them and the tool still succeeds and still
 * hands the model its evidence — `outcome: "success"`, `result_count: 6` — while
 * the application has registered nothing, so `synthesize_cited_answer` refuses and
 * the run fails closed.
 *
 * Four different things, in other words, and a surface that prints one number
 * called "evidence" collapses all of them. Each row below names the field it was
 * read from, because that is what makes it checkable rather than asserted:
 *
 *   returned to the model  ->  successful get_product_evidence steps, result_count
 *   registered             ->  whether synthesis was blocked for lack of it
 *   authorized             ->  the synthesize_cited_answer step's own outcome
 *   citations resolved     ->  GET /api/evidence/{id} for every cited id
 *
 * The last one is a real fetch, not an assertion: a citation "resolves" when the
 * evidence id it names comes back as a record with a source URI and a revision.
 *
 * Two bookends complete the chain a participant actually needs to read: without
 * a first row for retrieval itself, nothing here shows that the break sits
 * *downstream* of a successful search rather than in it; without a last row for
 * the run's own outcome, a fail-closed run only ever implies its own failure
 * through four rows of qualified language, never states it. Both are read from
 * data the other four rows already use -- a successful `search_products` step,
 * and the same `answered`/`running` facts the middle rows already condition on
 * -- never a fifth input this component did not already have.
 *
 *   product retrieved      ->  successful search_products steps, result_count
 *   grounded answer         ->  whether this run produced the answer of record
 */

type ChainState = "pass" | "blocked" | "pending";

interface EvidenceStep {
  key: string;
  title: string;
  value: string;
  source: string;
  state: ChainState;
}

const SEARCH_TOOL = "search_products";
const EVIDENCE_TOOL = "get_product_evidence";
const SYNTHESIS_TOOL = "synthesize_cited_answer";

function successful(trace: ToolTraceStep[], tool: string): ToolTraceStep[] {
  return trace.filter(
    (step) => step.tool === tool && step.outcome === "success",
  );
}

function blockedForMissingEvidence(trace: ToolTraceStep[]): ToolTraceStep | undefined {
  return trace.find(
    (step) =>
      step.tool === SYNTHESIS_TOOL
      && step.outcome === "error"
      && /missing evidence/i.test(step.detail),
  );
}

/**
 * The four states, derived only from the trace, the citations and the error.
 *
 * `resolvedCitations` is null until the reader opens the evidence disclosure and
 * the fetches land, so the row reads "not checked yet" rather than claiming a
 * verification that has not run.
 *
 * `running` is the same discipline applied to time. Mid-run the trace has two
 * receipts and no evidence lookup yet, and reading that as "returned: none,
 * authorized: refused" told a participant the run had failed while it was still
 * working. A step that has not reported is pending, not refused; nothing turns red
 * until the run is over.
 */
export function evidenceChain(
  trace: ToolTraceStep[],
  citations: AgentCitation[],
  answered: boolean,
  resolvedCitations: number | null,
  running = false,
): EvidenceStep[] {
  const searchCalls = successful(trace, SEARCH_TOOL);
  const retrieved = searchCalls.reduce(
    (total, step) => total + (step.result_count ?? 0),
    0,
  );
  const evidenceCalls = successful(trace, EVIDENCE_TOOL);
  const returned = evidenceCalls.reduce(
    (total, step) => total + (step.result_count ?? 0),
    0,
  );
  const evidenceProducts = new Set(
    evidenceCalls
      .map((step) => step.arguments.product_id)
      .filter((value): value is number => typeof value === "number"),
  );
  const blocked = blockedForMissingEvidence(trace);
  const synthesized = successful(trace, SYNTHESIS_TOOL).length > 0 || answered;
  const registered = synthesized && !blocked;
  const citedIds = new Set(citations.map((citation) => citation.evidence_id));
  /** A negative verdict is only a verdict once the run has stopped. */
  const failed = (settled: ChainState): ChainState => (running ? "pending" : settled);

  return [
    {
      key: "retrieved",
      title: "Product retrieved",
      value: retrieved
        ? `${retrieved} product${retrieved === 1 ? "" : "s"} across ${searchCalls.length} search${
          searchCalls.length === 1 ? "" : "es"
        }`
        : running
          ? "not yet"
          : "none",
      source: `${searchCalls.length} successful ${SEARCH_TOOL} call${
        searchCalls.length === 1 ? "" : "s"
      }`,
      state: retrieved ? "pass" : failed("blocked"),
    },
    {
      key: "returned",
      title: "Evidence returned to the model",
      value: returned
        ? `${returned} record${returned === 1 ? "" : "s"} over ${evidenceProducts.size} product${
          evidenceProducts.size === 1 ? "" : "s"
        }`
        : running
          ? "not yet"
          : "none",
      source: `${evidenceCalls.length} successful ${EVIDENCE_TOOL} call${
        evidenceCalls.length === 1 ? "" : "s"
      }`,
      state: returned ? "pass" : failed("blocked"),
    },
    {
      key: "registered",
      title: "Evidence registered into application state",
      value: registered
        ? `indexed under ${evidenceProducts.size} product${
          evidenceProducts.size === 1 ? "" : "s"
        }`
        : blocked
          ? "nothing registered"
          : running
            ? "not yet"
            : "not reached",
      source: blocked
        ? blocked.detail
        : registered
          ? "synthesis was not blocked for missing evidence"
          : running
            ? "waiting for synthesis to report"
            : "the run stopped before synthesis reported",
      state: registered ? "pass" : blocked ? failed("blocked") : "pending",
    },
    {
      key: "authorized",
      title: "Evidence authorized for synthesis",
      value: synthesized ? "authorized" : running ? "not yet" : "refused",
      source: synthesized
        ? `${SYNTHESIS_TOOL} completed`
        : running
          ? `${SYNTHESIS_TOOL} has not reported`
          : `${SYNTHESIS_TOOL} did not complete`,
      state: synthesized ? "pass" : failed("blocked"),
    },
    {
      key: "resolved",
      title: "Citations resolved to evidence records",
      value: resolvedCitations === null
        ? `${citedIds.size} cited, not checked yet`
        : `${resolvedCitations} of ${citedIds.size} resolved`,
      source: resolvedCitations === null
        ? "open the evidence records below to fetch each one"
        : "GET /api/evidence/{evidence_id}",
      state: resolvedCitations === null
        ? "pending"
        : resolvedCitations === citedIds.size && citedIds.size > 0
          ? "pass"
          : "blocked",
    },
    {
      key: "answer",
      title: "Grounded answer",
      value: answered ? "answered" : running ? "not yet" : "blocked",
      source: answered
        ? "a citation-bounded answer of record was persisted"
        : running
          ? `${SYNTHESIS_TOOL} has not reported`
          : "the run stopped without a citation-bounded answer of record",
      state: answered ? "pass" : failed("blocked"),
    },
  ];
}

function ChainMark({ state }: { state: ChainState }) {
  if (state === "pass") {
    return <Check aria-hidden="true" className="labs-chain-mark is-good" size={15} />;
  }
  if (state === "blocked") {
    return (
      <AlertTriangle aria-hidden="true" className="labs-chain-mark is-warn" size={15} />
    );
  }
  return <Minus aria-hidden="true" className="labs-chain-mark" size={15} />;
}

interface ReasonStageProps {
  question: string;
  filters: SearchFilters;
}

export function ReasonStage({ question, filters }: ReasonStageProps) {
  const [response, setResponse] = useState<AgentResponse | null>(null);
  const [partial, setPartial] = useState<AgentPartial | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [records, setRecords] = useState<EvidenceRecord[] | null>(null);
  const [recordsError, setRecordsError] = useState("");
  const [contracts, setContracts] = useState<ToolContract[] | null>(null);
  const [contractsError, setContractsError] = useState("");

  const trace: ToolTraceStep[] = response?.trace ?? partial?.trace ?? [];
  const citations: AgentCitation[] = response?.citations ?? [];
  const products: ProductSummary[] =
    response?.recommendations ?? partial?.candidates ?? [];
  const resolved = records
    ? records.filter((record) => record.evidence_id > 0).length
    : null;
  const chain = evidenceChain(
    trace,
    citations,
    Boolean(response) && !loading,
    resolved,
    loading,
  );

  async function run() {
    setLoading(true);
    setError("");
    setResponse(null);
    setPartial(null);
    setRecords(null);
    setRecordsError("");
    try {
      // The streaming path, so the tool receipts arrive even when the run fails
      // closed: a blocked synthesis is the Lab 3 broken state, and its trace is
      // the evidence that the tool succeeded while the application did not
      // register what it returned.
      await api.agentStream(question, filters, (event) => {
        if (event.type === "partial") setPartial(event.partial);
        else if (event.type === "answer_start" || event.type === "complete") {
          setResponse(event.response);
        }
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The agent run failed");
    } finally {
      setLoading(false);
    }
  }

  function loadEvidenceRecords() {
    if (records || recordsError) return;
    const ids = Array.from(
      new Set(citations.map((citation) => citation.evidence_id)),
    );
    if (!ids.length) {
      setRecords([]);
      return;
    }
    Promise.all(
      ids.map((id) => api.evidence(id).catch(() => null)),
    ).then((results) => {
      const found = results.filter((record): record is EvidenceRecord => Boolean(record));
      setRecords(found);
      if (found.length < ids.length) {
        setRecordsError(
          `${ids.length - found.length} of ${ids.length} cited evidence ids did not resolve.`,
        );
      }
    });
  }

  function loadContracts() {
    if (contracts || contractsError) return;
    api
      .toolContracts("agent")
      .then(setContracts)
      .catch((cause: unknown) => {
        setContractsError(
          cause instanceof Error ? cause.message : "Tool contracts are unavailable",
        );
      });
  }

  return (
    <div className="labs-reason">
      <div className="labs-reason-run">
        <p className="labs-reason-question">{question}</p>
        <button
          className="primary-button"
          type="button"
          aria-busy={loading}
          disabled={loading}
          onClick={() => void run()}
        >
          {loading ? (
            <LoaderCircle aria-hidden="true" className="spin" size={17} />
          ) : (
            <Play aria-hidden="true" size={17} fill="currentColor" />
          )}
          {loading ? "Running agent" : response || error ? "Run agent again" : "Run the agent"}
        </button>
      </div>

      {error ? (
        <p className="labs-reason-error" role="alert">
          <AlertTriangle aria-hidden="true" size={16} />
          {error}
        </p>
      ) : null}

      {trace.length || response ? (
        <>
          <PlaygroundFigures label="Agent run figures">
            <PlaygroundFigure
              label="Products retrieved"
              value={products.length}
              detail="returned by the agent's own searches"
            />
            <PlaygroundFigure
              label="Tool calls"
              value={trace.length}
              detail={`${successful(trace, EVIDENCE_TOOL).length} evidence lookups`}
            />
            {/* "none authorized" is a verdict, so it waits for the run to stop. */}
            <PlaygroundFigure
              label="Evidence IDs cited"
              value={
                new Set(citations.map((citation) => citation.evidence_id)).size
              }
              detail={
                citations.length
                  ? citations
                    .slice(0, 3)
                    .map((citation) => `#${citation.evidence_id}`)
                    .join(", ")
                  : loading
                    ? "still running"
                    : "none authorized"
              }
            />
          </PlaygroundFigures>

          {/* "Authorization" reads as login, RBAC, or row-level security to most
              participants, and this lab is none of those. It is citation scope: a
              retrieval-correctness invariant over which evidence records may
              support this answer. The disclaimer is deliberately adjacent to the
              teaching line rather than buried in a disclosure, because the
              misreading happens on first glance. */}
          <p className="labs-teaching-line">
            The model requests. The application decides which evidence may be cited.
          </p>
          <p className="labs-teaching-aside">
            This is not user authentication or RBAC. The application controls which
            retrieved evidence may support this answer, and synthesis fails closed
            when a citation falls outside that set.
          </p>

          <ol className="labs-chain" aria-label="Evidence state chain">
            {chain.map((step) => (
              <li className={`is-${step.state}`} key={step.key}>
                <ChainMark state={step.state} />
                <strong>{step.title}</strong>
                <b>{step.value}</b>
                <small>{step.source}</small>
              </li>
            ))}
          </ol>

          <PlaygroundDisclosureShelf>
            <PlaygroundDisclosure
              label="View tool calls"
              hint={`${trace.length} receipts`}
            >
              <ol className="labs-trace">
                {trace.map((step) => (
                  <li className={step.outcome} key={step.sequence}>
                    <span>{String(step.sequence).padStart(2, "0")}</span>
                    <div>
                      <code>{step.tool}</code>
                      <small>{step.detail}</small>
                      <p>
                        <em>{step.outcome}</em>
                        {step.result_count != null ? (
                          <em>{step.result_count} rows</em>
                        ) : null}
                        {step.latency_ms != null ? (
                          <em>{Math.round(step.latency_ms)} ms</em>
                        ) : null}
                        {step.retrieval_run_id ? (
                          <em>run {step.retrieval_run_id.slice(0, 8)}</em>
                        ) : null}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            </PlaygroundDisclosure>

            <PlaygroundDisclosure
              label="View evidence records"
              hint="fetches every cited id"
              onOpen={loadEvidenceRecords}
            >
              {recordsError ? (
                <p className="labs-disclosure-error" role="alert">{recordsError}</p>
              ) : null}
              {records === null ? (
                <p role="status">Resolving cited evidence ids.</p>
              ) : records.length ? (
                <ol className="labs-evidence-records">
                  {records.map((record) => (
                    <li key={record.evidence_id}>
                      <span>#{record.evidence_id}</span>
                      <div>
                        <strong>{record.title}</strong>
                        <p>{record.text}</p>
                        <small>
                          {record.evidence_type} · {record.source_name} ·{" "}
                          {record.revision} · product {record.product_id}
                        </small>
                        <code>{record.source_uri}</code>
                      </div>
                    </li>
                  ))}
                </ol>
              ) : (
                <p>
                  This run authorized no citations, so there is no evidence id to
                  resolve.
                </p>
              )}
            </PlaygroundDisclosure>

            <PlaygroundDisclosure
              label="View tool contract"
              hint="GET /api/tools"
              onOpen={loadContracts}
            >
              {contractsError ? (
                <p className="labs-disclosure-error" role="alert">{contractsError}</p>
              ) : contracts === null ? (
                <p role="status">Loading the registered contracts.</p>
              ) : (
                <>
                  <p className="labs-contract-note">
                    Every call above is audited against one of these. Typed
                    arguments only, and each contract declares whether it may
                    write.
                  </p>
                  <ul className="labs-contracts">
                    {contracts.map((contract) => (
                      <li key={contract.name}>
                        <code>{contract.name}</code>
                        <em>v{contract.tool_version}</em>
                        <b>{contract.read_only ? "read-only" : "writes"}</b>
                        <small>{contract.description}</small>
                      </li>
                    ))}
                  </ul>
                  <CodeBlock
                    code={JSON.stringify(contracts, null, 2)}
                    label="tools.agent.json"
                  />
                </>
              )}
            </PlaygroundDisclosure>
          </PlaygroundDisclosureShelf>
        </>
      ) : loading ? (
        <p className="labs-reason-awaiting" role="status">
          Planning, retrieving, comparing, looking up evidence, and writing the
          cited answer.
        </p>
      ) : (
        /* The six states the chain will report, in order, with nothing in them.
           Retrieve and Rank draw their shape while dormant; this stage did not, so
           the page went from two structured placeholders to one grey sentence. */
        <PlaygroundDormant
          steps={[
            "Product retrieved",
            "Returned to the model",
            "Registered",
            "Authorized",
            "Citations resolved",
            "Grounded answer",
          ]}
          hint="Run the agent to trace one question from retrieval to a grounded answer. These six are different things, and the Lab 3 repair is the difference between evidence returned to the model and evidence registered into application state."
        />
      )}
    </div>
  );
}
