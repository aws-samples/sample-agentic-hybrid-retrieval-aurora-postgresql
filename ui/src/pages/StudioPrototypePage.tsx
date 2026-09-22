import { ArrowLeft, ArrowRight, Bookmark, Check, ChevronRight, CircleHelp, ExternalLink, Headphones, ImageOff, ListFilter, Monitor, PanelRightClose, Search, SlidersHorizontal, Table2, X, Armchair } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { readPreviewData } from "./CatalogPreviewPage";
import { alexBrief } from "../alexBrief";
import reviewedExamples from "../../../data/real-catalog-examples.json";
import "../studio-prototype.css";

type Samples = ReturnType<typeof readPreviewData>;
type SampleGroup = Samples["groups"][number];
type SampleProduct = SampleGroup["products"][number];
type SampleFact = SampleProduct["facts"][number];
type View = "discover" | "shop" | "playground";
type Stage = "retrieve" | "rank" | "reason";
type Pane = { kind: "source"; product: SampleProduct } | { kind: "shortlist" } | null;

const viewLabels: Record<View, string> = { discover: "Discover", shop: "Shop", playground: "Playground" };
const stageLabels: Record<Stage, string> = { retrieve: "Retrieve", rank: "Rank", reason: "Reason" };
const selectedProducts = new Set(reviewedExamples.examples.filter((example) => example.selected_in_bulk).map((example) => example.product_id));

function Membership({ product }: { product: SampleProduct }) {
  return <span className="studio-membership">{selectedProducts.has(product.id) ? "In selected catalog" : "Reference sample"}</span>;
}

function CategoryIcon({ id }: { id: string }) {
  const Icon = id === "headphones" ? Headphones : id === "chairs" ? Armchair : Monitor;
  return <Icon size={18} aria-hidden="true" />;
}

function fit(product: SampleProduct, requirements: string[]) {
  if (!requirements.length) return "unset";
  const facts = requirements.map((label) => product.facts.find((fact) => fact.label === label));
  if (facts.some((fact) => fact?.meetsNeed === false)) return "mismatch";
  return facts.every((fact) => fact?.meetsNeed === true) ? "documented" : "unknown";
}

function FitStatus({ product, requirements }: { product: SampleProduct; requirements: string[] }) {
  const state = fit(product, requirements);
  return <span className={`studio-fit studio-fit-${state}`}>
    {state === "documented" ? <Check size={14} aria-hidden="true" /> : state === "mismatch" ? <X size={14} aria-hidden="true" /> : <CircleHelp size={14} aria-hidden="true" />}
    {state === "documented" ? "Requirements documented" : state === "mismatch" ? "Requirement mismatch" : state === "unknown" ? "Needs verification" : "No requirements selected"}
  </span>;
}

function FactValue({ fact, required = true }: { fact: SampleFact | undefined; required?: boolean }) {
  const state = fact?.meetsNeed === true ? "yes" : fact?.meetsNeed === false ? "no" : "unknown";
  return <span className={`studio-fact-value studio-fact-${state}`}>
    {state === "yes" ? <Check size={14} aria-label="Documented" /> : state === "no" ? <X size={14} aria-label="Does not meet requirement" /> : required ? <CircleHelp size={14} aria-label="Not established" /> : null}
    {fact?.value ?? "Not supplied"}
  </span>;
}

function ProductPhoto({ product }: { product: SampleProduct }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [product.image]);
  return <div className="studio-product-photo">
    {failed ? <span className="studio-photo-missing"><ImageOff size={26} aria-hidden="true" />Photo unavailable</span>
      : <img src={product.image} alt={product.title} width="800" height="600" loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setFailed(true)} />}
  </div>;
}

function ProductCard({ product, requirements, saved, onSave, onSource }: {
  product: SampleProduct; requirements: string[]; saved: boolean;
  onSave: () => void; onSource: (trigger: HTMLButtonElement) => void;
}) {
  return <article className="studio-product">
    <ProductPhoto product={product} />
    <div className="studio-product-copy">
      <p className="studio-product-brand">{product.brand}</p>
      <h2>{product.model}</h2>
      <p className="studio-product-description">{product.description}</p>
      <Membership product={product} />
      <FitStatus product={product} requirements={requirements} />
      <dl className="studio-product-facts">
        {requirements.map((label) => <div key={label}><dt>{label}</dt><dd><FactValue fact={product.facts.find((fact) => fact.label === label)} /></dd></div>)}
      </dl>
      <div className="studio-product-actions">
        <button type="button" aria-pressed={saved} onClick={onSave}><Bookmark size={15} fill={saved ? "currentColor" : "none"} aria-hidden="true" />{saved ? "Saved" : "Shortlist"}</button>
        <button type="button" onClick={(event) => onSource(event.currentTarget)}>View source<ArrowRight size={15} aria-hidden="true" /></button>
      </div>
    </div>
  </article>;
}

function Comparison({ products, group, onSource, onRemove }: {
  products: SampleProduct[]; group: SampleGroup;
  onSource: (product: SampleProduct, trigger: HTMLButtonElement) => void;
  onRemove: (id: string) => void;
}) {
  const labels = [...new Set(products.flatMap((product) => product.facts.map((fact) => fact.label)))];
  if (products.length < 2) return <div className="studio-empty">
    <Table2 size={26} aria-hidden="true" /><h2>Choose two products to compare.</h2>
    <p>Shortlist products from {group.label.toLowerCase()}, then compare their documented features here. Your choices stay in this prototype.</p>
  </div>;
  return <div className="studio-compare-scroll" role="region" aria-label={`${group.label} shortlist comparison`} tabIndex={0}>
    <table className="studio-compare"><caption>Selected {group.label.toLowerCase()} · reviewed features, without live ranking</caption>
      <thead><tr><th scope="col">Feature</th>{products.map((product) => <th scope="col" key={product.id}><ProductPhoto product={product} /><span>{product.brand}</span><strong>{product.model}</strong><button type="button" onClick={() => onRemove(product.id)} aria-label={`Remove ${product.model} from shortlist`}><X size={14} aria-hidden="true" />Remove</button></th>)}</tr></thead>
      <tbody>{labels.map((label) => <tr key={label}><th scope="row">{label}</th>{products.map((product) => <td key={product.id}><FactValue fact={product.facts.find((fact) => fact.label === label)} required={group.requirements.includes(label)} /></td>)}</tr>)}
        <tr><th scope="row">Source record</th>{products.map((product) => <td key={product.id}><button type="button" onClick={(event) => onSource(product, event.currentTarget)}>Inspect source<ArrowRight size={14} aria-hidden="true" /></button></td>)}</tr>
      </tbody>
    </table>
  </div>;
}

export function StudioPrototypePage() {
  const [data, setData] = useState<Samples | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [view, setView] = useState<View>("discover");
  const [groupId, setGroupId] = useState("");
  const [required, setRequired] = useState<Record<string, string[]>>({});
  const [query, setQuery] = useState("");
  const [onlyFits, setOnlyFits] = useState(false);
  const [saved, setSaved] = useState<string[]>([]);
  const [compare, setCompare] = useState(false);
  const [pane, setPane] = useState<Pane>(null);
  const [stage, setStage] = useState<Stage>("retrieve");
  const [inspectionId, setInspectionId] = useState("");
  const [pairIds, setPairIds] = useState<[string, string]>(["", ""]);
  const paneRef = useRef<HTMLElement>(null);
  const paneTrigger = useRef<HTMLButtonElement | null>(null);
  const shortlistTrigger = useRef<HTMLButtonElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    void fetch("/__catalog-preview/data", { signal: controller.signal }).then(async (response) => {
      if (!response.ok) throw new Error("The reviewed product sample could not be loaded.");
      const value = readPreviewData(await response.json());
      setData(value);
      setGroupId(value.groups[0].id);
      setRequired(Object.fromEntries(value.groups.map((group) => [group.id, [...group.requirements]])));
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "The reviewed sample is unavailable.");
    });
    return () => controller.abort();
  }, [attempt]);

  useEffect(() => {
    if (pane) paneRef.current?.focus({ preventScroll: window.innerWidth > 1250 });
  }, [pane]);

  function navigate(next: View) {
    setView(next);
    setPane(null);
    requestAnimationFrame(() => {
      window.scrollTo({ top: 0, behavior: "instant" });
      headingRef.current?.focus({ preventScroll: true });
    });
  }

  function selectGroup(id: string) {
    setGroupId(id);
    setQuery("");
    setOnlyFits(false);
    setInspectionId("");
    setPairIds(["", ""]);
    setPane(null);
  }

  function toggleSaved(id: string) {
    setSaved((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]);
  }

  function openSource(product: SampleProduct, trigger: HTMLButtonElement) {
    paneTrigger.current = trigger;
    setPane({ kind: "source", product });
  }

  function closePane() {
    setPane(null);
    (paneTrigger.current?.isConnected ? paneTrigger.current : shortlistTrigger.current)?.focus({ preventScroll: window.innerWidth > 1250 });
  }

  const group = data?.groups.find((entry) => entry.id === groupId) ?? data?.groups[0];
  const requirements = group ? required[group.id] ?? group.requirements : [];
  const allProducts = data?.groups.flatMap((entry) => entry.products) ?? [];
  const savedProducts = allProducts.filter((product) => saved.includes(product.id));
  const groupSaved = group?.products.filter((product) => saved.includes(product.id)) ?? [];
  const products = group?.products.filter((product) => {
    const matchesQuery = `${product.brand} ${product.model} ${product.title}`.toLowerCase().includes(query.trim().toLowerCase());
    return matchesQuery && (!onlyFits || fit(product, requirements) === "documented");
  }) ?? [];
  const inspected = group?.products.find((product) => product.id === inspectionId) ?? group?.products[0];
  const pair = group ? [
    group.products.find((product) => product.id === pairIds[0]) ?? group.products[0],
    group.products.find((product) => product.id === pairIds[1]) ?? group.products[1] ?? group.products[0],
  ] : [];

  return <div className="studio-prototype">
    <div className="studio-concept-notice"><span><strong>Design prototype</strong> — sample data</span><a href="/discover"><ArrowLeft size={14} aria-hidden="true" />Back to Mosaic</a></div>
    <header className="studio-header">
      <button type="button" className="studio-wordmark" onClick={() => navigate("discover")} aria-label="Mosaic Precision Studio home"><span>M</span>Mosaic <small>Precision Studio</small></button>
      <nav className="studio-navigation" aria-label="Prototype views">{(Object.keys(viewLabels) as View[]).map((name) => <button key={name} type="button" aria-current={view === name ? "page" : undefined} onClick={() => navigate(name)}>{viewLabels[name]}</button>)}</nav>
      <div className="studio-header-tools"><span className="studio-profile"><img src="/assets/images/mosaic/alex-headshot-v1.jpg" alt="" width="28" height="28" />Alex</span><button ref={shortlistTrigger} type="button" className="studio-shortlist-button" onClick={(event) => { paneTrigger.current = event.currentTarget; setPane({ kind: "shortlist" }); }}><Bookmark size={17} aria-hidden="true" /><span>Shortlist</span><b>{saved.length}</b></button></div>
    </header>

    {error ? <section className="studio-load-state" role="alert"><h1>Product sample unavailable</h1><p>{error}</p><button className="studio-primary" type="button" onClick={() => setAttempt((value) => value + 1)}>Try again</button></section> : !data || !group ? <div className="studio-load-state" role="status"><p>Loading the reviewed product sample…</p><div className="studio-loading-placeholder" /></div> : <div className={`studio-workspace ${pane ? "studio-has-pane" : ""}`}>
      <aside className="studio-brief-rail" aria-label="Shopping brief">
        <div className="studio-person"><img src="/assets/images/mosaic/alex-headshot-v1.jpg" alt="" width="40" height="40" /><div><strong>Alex’s workspace</strong><span>{alexBrief.role}</span></div></div>
        <h2>What are you choosing?</h2>
        <div className="studio-category-list">{data.groups.map((entry) => <button type="button" key={entry.id} aria-pressed={group.id === entry.id} onClick={() => selectGroup(entry.id)}><CategoryIcon id={entry.id} /><span>{entry.label}</span><ChevronRight size={14} aria-hidden="true" /></button>)}</div>
        <fieldset className="studio-requirements"><legend><SlidersHorizontal size={15} aria-hidden="true" />Your requirements</legend>{group.requirements.map((label) => <label key={label}><input type="checkbox" checked={requirements.includes(label)} onChange={() => setRequired((current) => ({ ...current, [group.id]: requirements.includes(label) ? requirements.filter((value) => value !== label) : [...requirements, label] }))} /><span>{label}</span></label>)}</fieldset>
        <p className="studio-rail-note">Requirements change this sample view. They do not run a search.</p>
        <div className="studio-rail-footer"><Check size={15} aria-hidden="true" /><span>Source records stay one click away.</span></div>
      </aside>

      <section className="studio-main" aria-label={`${viewLabels[view]} view`}>
        {view === "discover" ? <>
          <div className="studio-page-heading"><h1 ref={headingRef} tabIndex={-1}>Make room for better work.</h1><p>{alexBrief.description}</p></div>
          <div className="studio-overview">
            <figure><img src="/assets/images/mosaic/alex-workspace-editorial-v3.webp" alt="An illustrative home office with a desk, monitors and adjustable chair" width="1200" height="900" /><figcaption>Workspace illustration · not a product photograph</figcaption></figure>
            <div className="studio-overview-brief"><h2>{group.heading}</h2><p>{group.request}</p><ul>{requirements.length ? requirements.map((label) => <li key={label}><Check size={16} aria-hidden="true" />{label}</li>) : <li>Select what matters in your brief.</li>}</ul><button type="button" className="studio-primary" onClick={() => navigate("shop")}>Explore {group.label.toLowerCase()}<ArrowRight size={16} aria-hidden="true" /></button><span>{group.products.length} real product samples to inspect</span></div>
          </div>
          <div className="studio-next-heading"><h2>Choose with the details in view.</h2><p>Move from a broad need to a shortlist you can explain.</p></div>
          <div className="studio-decision-rows">{data.groups.map((entry) => <button type="button" key={entry.id} onClick={() => { selectGroup(entry.id); navigate("shop"); }}><CategoryIcon id={entry.id} /><span><strong>{entry.label}</strong><small>{entry.requirements.join(" · ")}</small></span><ArrowRight size={18} aria-hidden="true" /></button>)}</div>
        </> : view === "shop" ? <>
          <div className="studio-page-heading studio-heading-with-action"><div><h1 ref={headingRef} tabIndex={-1}>{group.label}, with the facts.</h1><p>{group.request}</p></div><div className="studio-view-switch" aria-label="Product layout"><button type="button" aria-pressed={!compare} onClick={() => setCompare(false)}><ListFilter size={16} aria-hidden="true" />Browse</button><button type="button" aria-pressed={compare} onClick={() => setCompare(true)}><Table2 size={16} aria-hidden="true" />Compare{groupSaved.length ? ` (${groupSaved.length})` : ""}</button></div></div>
          {compare ? <Comparison products={groupSaved} group={group} onSource={openSource} onRemove={toggleSaved} /> : <>
            <div className="studio-shop-controls"><label className="studio-search"><Search size={17} aria-hidden="true" /><input type="search" aria-label="Search this product sample" placeholder={`Find a brand or model in ${group.label.toLowerCase()}`} value={query} onChange={(event) => setQuery(event.target.value)} /></label><label className="studio-filter-toggle"><input type="checkbox" checked={onlyFits} onChange={(event) => setOnlyFits(event.target.checked)} />Only documented fits</label></div>
            <p className="studio-results-note" aria-live="polite">{products.length} of {group.products.length} samples · source order, without live ranking</p>
            {products.length ? <div className="studio-product-grid">{products.map((product) => <ProductCard product={product} key={product.id} requirements={requirements} saved={saved.includes(product.id)} onSave={() => toggleSaved(product.id)} onSource={(trigger) => openSource(product, trigger)} />)}</div> : <div className="studio-empty"><Search size={26} aria-hidden="true" /><h2>No samples meet these selections.</h2><p>Unknown features need verification; they do not count as a documented fit.</p><button type="button" onClick={() => { setQuery(""); setOnlyFits(false); }}>Clear text and fit filters</button></div>}
          </>}
        </> : <>
          <div className="studio-page-heading"><h1 ref={headingRef} tabIndex={-1}>Follow the decision.</h1><p>Explore how candidates, comparisons and sources fit together.</p></div>
          <p className="studio-walkthrough-notice"><CircleHelp size={17} aria-hidden="true" /><span><strong>Design walkthrough.</strong> These controls inspect the reviewed sample. No retrieval, reranking or agent request is made.</span></p>
          <nav className="studio-stage-tabs" aria-label="Walkthrough stage">{(Object.keys(stageLabels) as Stage[]).map((name, index) => <button type="button" aria-current={stage === name ? "step" : undefined} key={name} onClick={() => setStage(name)}><span>{index + 1}</span>{stageLabels[name]}</button>)}</nav>
          {stage === "retrieve" ? <section className="studio-stage-content"><h2>Start with the requirements.</h2><p>See which reviewed features meet the current brief. A missing fact remains unknown.</p><div className="studio-request-record"><span>Alex’s request</span><p>{group.request}</p></div><div className="studio-record-list">{group.products.map((product) => <button type="button" key={product.id} onClick={(event) => openSource(product, event.currentTarget)}><ProductPhoto product={product} /><span><strong>{product.brand} {product.model}</strong><FitStatus product={product} requirements={requirements} /></span><ArrowRight size={16} aria-hidden="true" /></button>)}</div><p className="studio-technical-boundary">Live candidate channels and their SQL records belong in the production Playground. This view only checks the supplied sample facts.</p></section> : stage === "rank" ? <section className="studio-stage-content"><h2>Compare the features that matter.</h2><p>Select a pair and inspect the same requirements side by side. There are no model scores or ranked positions in this walkthrough.</p><div className="studio-pair-selectors">{pair.map((product, index) => <label key={index}>Product {index + 1}<select value={product.id} onChange={(event) => setPairIds((current) => index === 0 ? [event.target.value, current[1]] : [current[0], event.target.value])}>{group.products.map((option) => <option key={option.id} value={option.id}>{option.brand} {option.model}</option>)}</select></label>)}</div><div className="studio-pair-grid">{pair.map((product, index) => <ProductCard key={`${product.id}-${index}`} product={product} requirements={requirements} saved={saved.includes(product.id)} onSave={() => toggleSaved(product.id)} onSource={(trigger) => openSource(product, trigger)} />)}</div></section> : <section className="studio-stage-content"><h2>Read the source before the claim.</h2><p>A listed feature and an experience claim need different evidence. Open the original record and decide what it establishes.</p><label className="studio-inspect-select">Product to inspect<select value={inspected?.id} onChange={(event) => setInspectionId(event.target.value)}>{group.products.map((product) => <option key={product.id} value={product.id}>{product.brand} {product.model}</option>)}</select></label>{inspected ? <div className="studio-reason-record"><div><ProductPhoto product={inspected} /><h3>{inspected.brand} {inspected.model}</h3><FitStatus product={inspected} requirements={requirements} /><button type="button" className="studio-primary" onClick={(event) => openSource(inspected, event.currentTarget)}>Inspect full source<ArrowRight size={16} aria-hidden="true" /></button></div><div><h3>Original listing text</h3><blockquote>{inspected.originalBulletPoints || inspected.originalDescription || "No descriptive text was supplied for this sample."}</blockquote><p className="studio-technical-boundary">This is source text, not a generated recommendation or a validated citation. The prototype makes no claim about comfort, call quality or compatibility beyond the supplied facts.</p></div></div> : null}</section>}
        </>}
        <footer className="studio-view-footer"><span>Real public-catalog samples · local interactions only</span><span>Prices and stock are not supplied.</span></footer>
      </section>

      {pane ? <aside className="studio-evidence-pane" ref={paneRef} tabIndex={-1} aria-label={pane.kind === "source" ? "Product source" : "Your shortlist"} onKeyDown={(event) => { if (event.key === "Escape") closePane(); }}>
        <div className="studio-pane-heading"><h2>{pane.kind === "source" ? "Product source" : "Your shortlist"}</h2><button type="button" onClick={closePane} aria-label="Close side pane"><PanelRightClose size={19} aria-hidden="true" /></button></div>
        {pane.kind === "source" ? <><ProductPhoto product={pane.product} /><h3>{pane.product.brand} {pane.product.model}</h3><p className="studio-source-id">{pane.product.id}</p><dl className="studio-source-facts">{pane.product.facts.map((fact) => <div key={fact.label}><dt>{fact.label}</dt><dd>{fact.value}</dd></div>)}</dl><details open><summary>Original listing text</summary><h4>Title</h4><p>{pane.product.title}</p><h4>Description</h4><p>{pane.product.originalDescription || "No description supplied in the dataset."}</p><h4>Listing highlights</h4><p className="studio-original-text">{pane.product.originalBulletPoints || "No listing highlights supplied in the dataset."}</p></details><p className="studio-source-dataset">{pane.product.sourceDataset ?? data.textSource ?? "Public product metadata"}</p><a className="studio-source-link" href={pane.product.sourceUrl} target="_blank" rel="noreferrer">{pane.product.sourceLabel}<ExternalLink size={14} aria-hidden="true" /></a>{pane.product.listingUrl ? <a className="studio-source-link" href={pane.product.listingUrl} target="_blank" rel="noreferrer">Original product listing<ExternalLink size={14} aria-hidden="true" /></a> : null}<p className="studio-rail-note">Opening this record does not establish that a live agent retrieved or cited it.</p></> : <><p className="studio-pane-intro">Keep the options you want to examine. This list stays in memory until you reload.</p>{savedProducts.length ? <>{savedProducts.map((product) => <div className="studio-saved-item" key={product.id}><ProductPhoto product={product} /><div><strong>{product.brand} {product.model}</strong><button type="button" onClick={(event) => openSource(product, event.currentTarget)}>View source</button></div><button type="button" onClick={() => toggleSaved(product.id)} aria-label={`Remove ${product.model} from shortlist`}><X size={15} aria-hidden="true" /></button></div>)}<button type="button" className="studio-primary" onClick={() => { navigate("shop"); setCompare(true); }}>Compare {group.label.toLowerCase()}<ArrowRight size={16} aria-hidden="true" /></button><p className="studio-rail-note">Comparison uses the shortlisted products in the selected category.</p></> : <div className="studio-shortlist-empty"><Bookmark size={28} aria-hidden="true" /><h3>Save a closer look.</h3><p>Choose Shortlist on a product in Shop to keep it here.</p><button type="button" onClick={() => navigate("shop")}>Browse {group.label.toLowerCase()}<ArrowRight size={15} aria-hidden="true" /></button></div>}</>}
      </aside> : null}
    </div>}
  </div>;
}
