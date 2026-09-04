import { AlertTriangle, Check, LoaderCircle, Minus, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import { Link } from "wouter";
import { api } from "../api";
import { formatPriceCompact, leafCategory } from "../format";
import { productImageMap } from "../media";
import { Criteria, Searches } from "./agentAnswerParts";
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
  AgentPlanStep,
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
 *
 * The chain audits an answer, so the answer comes first. Above it, in the order
 * the run produced them: the filters retrieval enforced and the searches issued
 * (`response.plan`), the products those searches returned
 * (`response.recommendations`), the answer of record itself (`response.answer`),
 * and the quote, product, source URI and revision behind every claim
 * (`response.citations`). Without them a participant who repaired Lab 3 watched
 * six rows turn green and never read the sentence the repair bought.
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
  const [draft, setDraft] = useState(question);
  const [response, setResponse] = useState<AgentResponse | null>(null);
  const [partial, setPartial] = useState<AgentPartial | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [records, setRecords] = useState<EvidenceRecord[] | null>(null);
  const [recordsError, setRecordsError] = useState("");
  const [recordsPending, setRecordsPending] = useState(false);
  const [contracts, setContracts] = useState<ToolContract[] | null>(null);
  const [contractsError, setContractsError] = useState("");
  const [contractsPending, setContractsPending] = useState(false);
  const runVersion = useRef(0);
  const recordsRequestVersion = useRef(0);
  const contractsRequestVersion = useRef(0);

  useEffect(() => {
    setDraft(question);
  }, [question]);

  const trace: ToolTraceStep[] = response?.trace ?? partial?.trace ?? [];
  const plan: AgentPlanStep[] = response?.plan ?? partial?.plan ?? [];
  const citations: AgentCitation[] = response?.citations ?? [];
  const products: ProductSummary[] =
    response?.recommendations ?? partial?.candidates ?? [];
  const productImages = productImageMap(products);
  const productById = new Map(
    products.map((product) => [product.product_id, product]),
  );
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

  function resolveEvidenceRecords(
    nextCitations: AgentCitation[],
    requestRun: number,
  ) {
    const ids = Array.from(
      new Set(nextCitations.map((citation) => citation.evidence_id)),
    );
    const request = ++recordsRequestVersion.current;
    setRecords(null);
    setRecordsError("");
    if (!ids.length) {
      setRecords([]);
      setRecordsPending(false);
      return;
    }
    setRecordsPending(true);
    Promise.all(
      ids.map((id) => Promise.resolve(api.evidence(id)).catch(() => null)),
    ).then((results) => {
      if (
        request !== recordsRequestVersion.current
        || requestRun !== runVersion.current
      ) {
        return;
      }
      const found = results.filter((record): record is EvidenceRecord => Boolean(record));
      setRecords(found);
      if (found.length < ids.length) {
        setRecordsError(
          `${ids.length - found.length} of ${ids.length} cited evidence ids did not resolve.`,
        );
      }
    }).finally(() => {
      if (
        request === recordsRequestVersion.current
        && requestRun === runVersion.current
      ) {
        setRecordsPending(false);
      }
    });
  }

  async function run(requestedQuestion = draft.trim()) {
    if (requestedQuestion.length < 2) return;
    const request = ++runVersion.current;
    recordsRequestVersion.current += 1;
    setLoading(true);
    setError("");
    setResponse(null);
    setPartial(null);
    setRecords(null);
    setRecordsError("");
    setRecordsPending(false);
    try {
      // The streaming path, so the tool receipts arrive even when the run fails
      // closed: a blocked synthesis is the Lab 3 broken state, and its trace is
      // the evidence that the tool succeeded while the application did not
      // register what it returned.
      await api.agentStream(requestedQuestion, filters, (event) => {
        if (request !== runVersion.current) return;
        if (event.type === "partial") setPartial(event.partial);
        else if (event.type === "answer_start" || event.type === "complete") {
          setResponse(event.response);
          if (event.type === "complete") {
            resolveEvidenceRecords(event.response.citations, request);
          }
        }
      });
    } catch (cause) {
      if (request === runVersion.current) {
        setError(cause instanceof Error ? cause.message : "The agent run failed");
      }
    } finally {
      if (request === runVersion.current) setLoading(false);
    }
  }

  function loadEvidenceRecords() {
    if (recordsPending || (records !== null && !recordsError)) return;
    resolveEvidenceRecords(citations, runVersion.current);
  }

  function loadContracts() {
    if (contractsPending || contracts !== null) return;
    const request = ++contractsRequestVersion.current;
    setContractsError("");
    setContractsPending(true);
    api
      .toolContracts("agent")
      .then((value) => {
        if (request === contractsRequestVersion.current) setContracts(value);
      })
      .catch((cause: unknown) => {
        if (request === contractsRequestVersion.current) {
          setContractsError(
            cause instanceof Error ? cause.message : "Tool contracts are unavailable",
          );
        }
      })
      .finally(() => {
        if (request === contractsRequestVersion.current) {
          setContractsPending(false);
        }
      });
  }

  const runLabel = loading
    ? "Running agent"
    : response || error
      ? "Run agent again"
      : "Run the agent";

  return (
    <div className="labs-reason">
      <form
        className="labs-reason-composer"
        onSubmit={(event) => {
          event.preventDefault();
          void run();
        }}
      >
        <label className="sr-only" htmlFor="labs-reason-question">
          Question for Mosaic
        </label>
        <textarea
          aria-label="Question for Mosaic"
          autoComplete="off"
          id="labs-reason-question"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          placeholder="Ask Mosaic to compare products and cite the evidence"
          rows={4}
          value={draft}
        />
        {/* A labelled button, the same shape as Run pipeline in the masthead:
            the two things this page can run look like the same kind of control,
            and the control names its action. */}
        <div className="labs-reason-composer-actions">
          <small>Enter to run. Shift+Enter for a new line.</small>
          <button
            aria-busy={loading}
            className="labs-reason-submit"
            disabled={loading || draft.trim().length < 2}
            type="submit"
          >
            {loading ? (
              <LoaderCircle aria-hidden="true" className="spin" size={17} />
            ) : (
              <Play aria-hidden="true" size={17} fill="currentColor" />
            )}
            {runLabel}
          </button>
        </div>
      </form>

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

          {/* The plan the agent executed, before anything it concluded from it:
              the filters retrieval enforced, then the searches it issued. Both
              are the same components Shop prints, over the same `plan`, so the
              two surfaces cannot drift into two accounts of one run. */}
          {plan.length ? <Criteria plan={plan} /> : null}
          {plan.length ? <Searches plan={plan} /> : null}

          {products.length ? (
            <section
              className="labs-reason-products"
              aria-labelledby="reason-products-title"
            >
              <header>
                <h3 id="reason-products-title">Products carried into reasoning</h3>
                <small>{products.length} from this agent run</small>
              </header>
              <ul>
                {products.map((product) => (
                  <li key={product.product_id}>
                    <img
                      alt={product.title}
                      src={productImages.get(product.product_id)}
                    />
                    <div>
                      {/* The recommendation is a row a reader can open. The
                          product page holds the record the evidence was drawn
                          from, and it was one page away with no way to get there. */}
                      <strong>
                        <Link href={`/products/${product.product_id}`}>
                          {product.title}
                        </Link>
                      </strong>
                      <span>
                        {product.brand} · {leafCategory(product.category_path)} ·{" "}
                        {formatPriceCompact(product.price_cents, product.currency)}
                      </span>
                      <small>product {product.product_id}</small>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {/* Lab 3's payoff, and until now the one thing this stage never showed.
              Six green rows say the repair worked; they do not say what it bought.
              Markdown because that is what synthesis writes, and the answer is
              printed as authored -- no emphasis added here, because on this stage
              the text is the artifact under inspection. */}
          {response?.answer ? (
            <section
              className="labs-reason-answer"
              aria-labelledby="reason-answer-title"
            >
              <h3 id="reason-answer-title">The grounded answer</h3>
              <div className="labs-reason-prose">
                <Markdown>{response.answer}</Markdown>
              </div>
            </section>
          ) : null}

          {/* Every field that makes a citation checkable rather than asserted:
              the quote the claim rests on, the product it is about, and the
              source URI and revision of the record it came from. */}
          {citations.length ? (
            <section
              className="labs-reason-citations"
              aria-labelledby="reason-citations-title"
            >
              <h3 id="reason-citations-title">What each claim cites</h3>
              <ol>
                {citations.map((citation) => (
                  <li key={`${citation.number}-${citation.evidence_id}`}>
                    <span>[{citation.number}]</span>
                    <div>
                      <strong>{citation.title}</strong>
                      <blockquote>{citation.quote}</blockquote>
                      <small>
                        product {citation.product_id} · evidence{" "}
                        {citation.evidence_id} · {citation.revision}
                      </small>
                      <code>{citation.source_uri}</code>
                    </div>
                  </li>
                ))}
              </ol>
            </section>
          ) : null}

          <div className="labs-citation-boundary">
            <span>Answer evidence boundary</span>
            <strong>
              Retrieval makes evidence visible. Registration makes it citable.
            </strong>
            <p>
              Only records registered for this run may support the answer. Synthesis
              rejects a citation outside that set, even when the model has seen the
              record.
            </p>
          </div>

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
              key={`evidence-${response?.agent_run_id ?? "pending"}`}
              label="View evidence records"
              hint="fetches every cited id"
              onOpen={loadEvidenceRecords}
            >
              {recordsError ? (
                <p className="labs-disclosure-error" role="alert">{recordsError}</p>
              ) : null}
              {recordsError ? (
                <button
                  className="secondary-button"
                  disabled={recordsPending}
                  onClick={loadEvidenceRecords}
                  type="button"
                >
                  Retry evidence records
                </button>
              ) : null}
              {records === null ? (
                <p role="status">
                  {recordsPending
                    ? "Resolving cited evidence ids."
                    : "Open to resolve cited evidence ids."}
                </p>
              ) : records.length ? (
                <ol className="labs-evidence-records">
                  {records.map((record) => {
                    const product = productById.get(record.product_id);
                    const image = product
                      ? productImages.get(product.product_id)
                      : null;
                    return (
                      <li
                        className={image ? "has-product-image" : undefined}
                        key={record.evidence_id}
                      >
                        <span>#{record.evidence_id}</span>
                        {image && product ? (
                          <img
                            alt=""
                            aria-hidden="true"
                            src={image}
                          />
                        ) : null}
                        <div>
                          <strong>{record.title}</strong>
                          <small>
                            {record.evidence_type} · {record.source_name} ·{" "}
                            {record.revision} · product {record.product_id}
                          </small>
                          <p>{record.text}</p>
                          <code>{record.source_uri}</code>
                        </div>
                      </li>
                    );
                  })}
                </ol>
              ) : citations.length ? (
                <p>No cited evidence records resolved.</p>
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
              ) : null}
              {contractsError ? (
                <button
                  className="secondary-button"
                  disabled={contractsPending}
                  onClick={loadContracts}
                  type="button"
                >
                  Retry tool contract
                </button>
              ) : contracts === null ? (
                <p role="status">
                  {contractsPending
                    ? "Loading the registered contracts."
                    : "Open to load the registered contracts."}
                </p>
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
            "Authorized for synthesis",
            "Citations resolved",
            "Grounded answer",
          ]}
          hint="Run the agent to trace one question from retrieval to a grounded answer. These six are different things, and the Lab 3 repair is the difference between evidence returned to the model and evidence registered into application state."
        />
      )}

      {/* A footnote, not a feature. Every claim here is a table this page already
          reads back, and it says plainly what Mosaic does not remember, so the
          question every agent session gets asked is answered on screen without
          a memory store that would hide exactly what Lab 3 makes visible. */}
      <p className="labs-memory-note">
        <strong>Where memory lives.</strong> Every run on this page is written to
        Aurora before it is shown: the search and its candidates, the agent run,
        the evidence records it cited, and the citations it was allowed to use. A
        follow-up in Ask Mosaic reuses the shortlist from the run before it, and
        the server, not the model, decides what that shortlist holds. Nothing here
        remembers a shopper between visits. Adding that would be one more
        retrieval over these same tables, with the same filters and the same
        evidence rules, rather than a separate memory store.
      </p>
    </div>
  );
}
