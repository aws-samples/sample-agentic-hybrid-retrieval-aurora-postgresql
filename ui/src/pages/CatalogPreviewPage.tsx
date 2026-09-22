import { ArrowRight, Check, CircleHelp, ExternalLink, ImageOff, LayoutGrid, Star, Table2, X } from "lucide-react";
import { useEffect, useState } from "react";
import reviewedExamples from "../../../data/real-catalog-examples.json";
import { StagedProductEvidence } from "../components/StagedProductEvidence";
import "../catalog-preview.css";

type Fact = { label: string; value: string; meetsNeed?: boolean };
type PreviewProduct = {
  id: string;
  brand: string;
  model: string;
  title: string;
  originalDescription: string | null;
  originalBulletPoints: string | null;
  image: string;
  description: string;
  facts: Fact[];
  sourceUrl: string;
  sourceLabel: string;
  sourceDataset?: string;
  listingUrl?: string;
  rating?: { average: number; count: number };
  selectedInBulk?: boolean;
};
type PreviewGroup = {
  id: string;
  label: string;
  heading: string;
  request: string;
  requirements: string[];
  products: PreviewProduct[];
  catalogSamples?: PreviewProduct[];
};
type PreviewData = { groups: PreviewGroup[]; imageSource: string; textSource?: string };

const reviewedMembership = new Map<string, boolean>(reviewedExamples.examples.map((example) => [
  example.product_id, "selected_in_bulk" in example && example.selected_in_bulk === true,
]));

function inSelectedCatalog(product: PreviewProduct) {
  return product.selectedInBulk ?? reviewedMembership.get(product.id);
}

function fitFor(product: PreviewProduct, requirements: string[]) {
  const facts = requirements.map((label) => product.facts.find((fact) => fact.label === label));
  if (facts.some((fact) => fact?.meetsNeed === false)) return "mismatch";
  return facts.every((fact) => fact?.meetsNeed === true) ? "documented" : "unknown";
}

function FitLabel({ product, requirements }: { product: PreviewProduct; requirements: string[] }) {
  const fit = fitFor(product, requirements);
  return <span className={`catalog-preview-fit fit-${fit}`}>
    {fit === "documented" ? <Check size={15} aria-hidden="true" />
      : fit === "mismatch" ? <X size={15} aria-hidden="true" /> : <CircleHelp size={15} aria-hidden="true" />}
    {fit === "documented" ? "Documented fit" : fit === "mismatch" ? "Requirement mismatch" : "Needs verification"}
  </span>;
}

function FactValue({ fact, required = false }: { fact: Fact; required?: boolean }) {
  return <span className={fact.meetsNeed === false ? "need-missing" : fact.meetsNeed === true ? "need-met" : required ? "need-unknown" : ""}>
    {fact.meetsNeed === false ? <X size={16} aria-label="Does not meet this requirement" />
      : fact.meetsNeed === true ? <Check size={16} aria-label="Meets this requirement" />
        : required ? <CircleHelp size={16} aria-label="Not established by the supplied source" /> : null}
    {fact.value}
  </span>;
}

function safeHttps(value: unknown): value is string {
  if (typeof value !== "string") return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password;
  } catch {
    return false;
  }
}

export function readPreviewData(value: unknown): PreviewData {
  const data = value as PreviewData;
  if (!data || typeof data.imageSource !== "string" || !Array.isArray(data.groups)
      || !data.groups.length) throw new Error("The product preview is empty or incomplete.");
  if (data.textSource !== undefined && typeof data.textSource !== "string") {
    throw new Error("The product preview is missing its text source.");
  }
  const identities = new Set<string>();
  for (const group of data.groups) {
    if (!group || ![group.id, group.label, group.heading, group.request].every((item) => typeof item === "string" && item.trim())
        || !Array.isArray(group.requirements) || !group.requirements.length
        || group.requirements.some((item) => typeof item !== "string" || !item.trim())
        || new Set(group.requirements).size !== group.requirements.length
        || !Array.isArray(group.products) || !group.products.length) {
      throw new Error("A product group is missing its description or products.");
    }
    if (group.catalogSamples !== undefined && (!Array.isArray(group.catalogSamples) || !group.catalogSamples.length)) {
      throw new Error("A catalog sample is missing its products.");
    }
    for (const product of [...group.products, ...(group.catalogSamples ?? [])]) {
      const sampled = group.catalogSamples?.includes(product) ?? false;
      if (!product || ![product.id, product.brand, product.model, product.title, product.description, product.sourceLabel]
        .every((item) => typeof item === "string" && item.trim())
          || ![product.originalDescription, product.originalBulletPoints].every((item) => item === null || typeof item === "string")
          || !safeHttps(product.image) || !safeHttps(product.sourceUrl)
          || (product.listingUrl !== undefined && !safeHttps(product.listingUrl))
          || (product.sourceDataset !== undefined && typeof product.sourceDataset !== "string")
          || (product.selectedInBulk !== undefined && typeof product.selectedInBulk !== "boolean")
          || (sampled && product.selectedInBulk !== true)
          || !Array.isArray(product.facts) || !product.facts.length
          || product.facts.some((fact) => !fact || typeof fact.label !== "string"
            || typeof fact.value !== "string"
            || (fact.meetsNeed !== undefined && typeof fact.meetsNeed !== "boolean"))
          || new Set(product.facts.map((fact) => fact.label)).size !== product.facts.length
          || (!sampled && group.requirements.some((label) => !product.facts.some((fact) => fact.label === label)))) {
        throw new Error("A product is missing its photograph, specifications or source link.");
      }
      if (product.rating !== undefined && (!product.rating
          || !Number.isFinite(product.rating.average) || product.rating.average < 1 || product.rating.average > 5
          || !Number.isSafeInteger(product.rating.count) || product.rating.count < 1)) {
        throw new Error("A product rating is outside the source's supported range.");
      }
      if (identities.has(product.id)) throw new Error("The preview contains a repeated product.");
      identities.add(product.id);
    }
  }
  return data;
}

function ProductPhoto({ product }: { product: PreviewProduct }) {
  const [imageFailed, setImageFailed] = useState(false);
  return <div className="catalog-preview-image">
    {imageFailed ? <div className="catalog-preview-image-error"><ImageOff size={32} /><p>Photo unavailable from the source</p></div>
      : <img src={product.image} alt={product.title} width="1000" height="800" loading="lazy" decoding="async"
          referrerPolicy="no-referrer" onError={() => setImageFailed(true)} />}
  </div>;
}

function ProductOriginLink({ product }: { product: PreviewProduct }) {
  const url = product.listingUrl ?? product.sourceUrl;
  const label = product.listingUrl ? "View original listing" : "View source website";
  const host = new URL(url).hostname.replace(/^www\./, "");
  return <div className="catalog-preview-origin">
    <a href={url} target="_blank" rel="noopener noreferrer"
      aria-label={`${label} for ${product.title} (opens in a new tab)`}>
      {label}<ExternalLink size={15} aria-hidden="true" />
    </a>
    <span>{host}</span>
  </div>;
}

function ProductSource({ product }: { product: PreviewProduct }) {
  const [inspectEvidence, setInspectEvidence] = useState(false);
  return <details className="catalog-preview-source" onToggle={event => { if (event.currentTarget.open) setInspectEvidence(true); }}>
    <summary>Product details and source <ArrowRight size={17} aria-hidden="true" /></summary>
    <h3>Original listing title</h3>
    <p className="catalog-preview-original">{product.title}</p>
    <h3>Original description</h3>
    <p className="catalog-preview-original">{product.originalDescription || "No description supplied in the dataset."}</p>
    <h3>Original listing highlights</h3>
    <p className="catalog-preview-original">{product.originalBulletPoints || "No listing highlights supplied in the dataset."}</p>
    <h3>Listed specifications</h3>
    <dl className="catalog-preview-source-specifications">{product.facts.map((fact) => <div key={fact.label}><dt>{fact.label}</dt><dd>{fact.value}</dd></div>)}</dl>
    <p>Product reference: <span className="catalog-preview-id">{product.id}</span></p>
    {product.sourceDataset ? <p>Dataset: {product.sourceDataset}</p> : null}
    <div className="catalog-preview-source-links">
      <a href={product.sourceUrl} target="_blank" rel="noopener noreferrer">{product.sourceLabel} <ExternalLink size={14} aria-hidden="true" /></a>
    </div>
    {inspectEvidence && inSelectedCatalog(product) === true ? <StagedProductEvidence productId={product.id} /> : null}
  </details>;
}

function MembershipLabel({ product }: { product: PreviewProduct }) {
  const selected = inSelectedCatalog(product);
  return <span className="catalog-preview-membership">{selected === true ? "In selected catalog" : selected === false ? "Reference sample" : "Source sample"}</span>;
}

function ProductRating({ product }: { product: PreviewProduct }) {
  return product.rating ? <p className="catalog-preview-rating">
    <Star size={14} aria-hidden="true" />
    <span>{product.rating.average.toFixed(1)} out of 5 · {product.rating.count.toLocaleString("en-US")} {product.rating.count === 1 ? "rating" : "ratings"}</span>
    <small>Dataset rating</small>
  </p> : null;
}

function PreviewCard({ product, requirements, reviewed = true }: { product: PreviewProduct; requirements: string[]; reviewed?: boolean }) {
  return (
    <article className={`catalog-preview-card${reviewed ? "" : " catalog-preview-sample"}`}>
      <ProductPhoto product={product} />
      <div className="catalog-preview-card-heading">
        <div className="catalog-preview-card-status">{reviewed ? <FitLabel product={product} requirements={requirements} /> : <span className="catalog-preview-brand">{product.brand}</span>}<MembershipLabel product={product} /></div>
        <h2>{reviewed ? <>{product.brand} <span>{product.model}</span></> : product.title}</h2>
        <p>{product.description}</p>
        <ProductRating product={product} />
      </div>
      <ProductOriginLink product={product} />
      <dl className="catalog-preview-facts">
        {product.facts.map((fact) => <div key={fact.label}>
          <dt>{fact.label}</dt>
          <dd><FactValue fact={fact} required={reviewed && requirements.includes(fact.label)} /></dd>
        </div>)}
      </dl>
      <ProductSource product={product} />
    </article>
  );
}

function ProductComparison({ products, group, reviewed = true }: { products: PreviewProduct[]; group: PreviewGroup; reviewed?: boolean }) {
  const labels = reviewed ? group.requirements : [...new Set(products.flatMap((product) => product.facts.map((fact) => fact.label)))];
  return <><p className="catalog-preview-comparison-hint">Read down for one product, across to compare. Scroll sideways for more products.</p>
    <div className="catalog-preview-comparison" role="region" aria-label={`${group.label} comparison, scroll for more products`} tabIndex={0}>
    <table>
      <caption className="sr-only">Compare {group.label.toLowerCase()} using their listed specifications.</caption>
      <thead><tr><th scope="col" className="catalog-preview-row-label">{reviewed ? "Alex’s requirements" : "Product details"}<p>Read across to compare the same feature.</p></th>
        {products.map((product) => <th scope="col" key={product.id} className={reviewed ? undefined : "catalog-preview-sample"}>
          <ProductPhoto product={product} />
          <MembershipLabel product={product} />
          <h2>{reviewed ? <>{product.brand} <span>{product.model}</span></> : product.title}</h2>
          <p>{product.description}</p>
        </th>)}
      </tr></thead>
      <tbody>
        {reviewed ? <tr><th scope="row">Fit to the brief</th>{products.map((product) => <td key={product.id}><FitLabel product={product} requirements={group.requirements} /></td>)}</tr> : null}
        {labels.map((label) => <tr key={label}><th scope="row">{label}</th>
          {products.map((product) => <td key={product.id}><FactValue fact={product.facts.find((fact) => fact.label === label) ?? { label, value: "Not supplied" }} required={reviewed} /></td>)}
        </tr>)}
        <tr><th scope="row">Source rating<p>Historical dataset values.</p></th>{products.map((product) => <td key={product.id}>{product.rating ? <ProductRating product={product} /> : <span className="catalog-preview-muted">Not supplied</span>}</td>)}</tr>
        <tr><th scope="row">Check the source</th>{products.map((product) => <td key={product.id}><ProductOriginLink product={product} /><ProductSource product={product} /></td>)}</tr>
      </tbody>
    </table>
  </div></>;
}

export function CatalogPreviewPage() {
  const [data, setData] = useState<PreviewData | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState("");
  const [onlyMatches, setOnlyMatches] = useState(false);
  const [sampleSet, setSampleSet] = useState<"sample" | "all" | "selected">("all");
  const [view, setView] = useState<"gallery" | "compare">("gallery");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    void fetch("/__catalog-preview/data", { signal: controller.signal }).then(async (response) => {
      if (!response.ok) throw new Error("The local product preview is not available. Load the preview file and try again.");
      const next = readPreviewData(await response.json());
      setData(next);
      setSelected(next.groups[0].id);
      setSampleSet(next.groups.every((group) => group.catalogSamples?.length) ? "sample" : "all");
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "The preview could not be loaded.");
    });
    return () => controller.abort();
  }, [attempt]);
  if (error) return <section className="catalog-preview-error" role="alert"><h1>Preview unavailable</h1><p>{error}</p><button type="button" onClick={() => setAttempt((value) => value + 1)}>Try again</button></section>;
  if (!data) return <p className="route-loading" role="status">Loading product photos and specifications…</p>;
  const group = data.groups.find((item) => item.id === selected) ?? data.groups[0];
  const sampled = sampleSet === "sample";
  const collection = sampled ? group.catalogSamples ?? [] : group.products;
  const scoped = collection.filter((product) => sampleSet !== "selected" || inSelectedCatalog(product) === true);
  const products = scoped.filter((product) => sampled || !onlyMatches || fitFor(product, group.requirements) === "documented");
  const documented = scoped.filter((product) => fitFor(product, group.requirements) === "documented").length;
  return (
    <section className="catalog-preview">
      <div className="catalog-preview-intro">
        <div><h1>{group.heading}</h1><p>{sampled ? "Explore more products from the selected catalog, with their original photos and details." : "Compare the features Alex needs for his home office."}</p></div>
        <div className="catalog-preview-alex"><img src="/assets/images/mosaic/alex-headshot-v1.jpg" alt="" width="56" height="56" /><div><strong>Alex’s next three choices</strong><span>Headphones · Chair · Monitor</span></div></div>
      </div>
      <div className="catalog-preview-notice"><strong>Catalog preview</strong><span>Original product photos and descriptions. Open each listing to check the source.</span></div>
      <nav className="catalog-preview-tabs" aria-label="Product categories">
        {data.groups.map((item) => <button type="button" key={item.id} aria-pressed={group.id === item.id}
          onClick={() => { setSelected(item.id); setOnlyMatches(false); }}>{item.label}<span>{sampled ? item.catalogSamples?.length ?? 0 : item.products.length}</span></button>)}
      </nav>
      <div className="catalog-preview-request">
        <div><h2>What Alex needs</h2><p>“{group.request}”</p></div>
        <p className="catalog-preview-fit-count">{sampled ? <><strong>{scoped.length} additional products</strong>{" "}Specifications shown as listed.</> : <><strong>{documented} of {scoped.length}</strong> have every requirement documented.</>}</p>
      </div>
      <div className="catalog-preview-toolbar">
        <div className="catalog-preview-view" role="group" aria-label="Product view">
          <button type="button" aria-pressed={view === "gallery"} onClick={() => setView("gallery")}><LayoutGrid size={16} aria-hidden="true" />Gallery</button>
          <button type="button" aria-pressed={view === "compare"} onClick={() => setView("compare")}><Table2 size={16} aria-hidden="true" />Compare features</button>
        </div>
        <div className="catalog-preview-filters">
          <label className="catalog-preview-scope"><span>Sample set</span><select value={sampleSet} onChange={(event) => { setSampleSet(event.target.value as typeof sampleSet); setOnlyMatches(false); }}>{data.groups.every((item) => item.catalogSamples?.length) ? <option value="sample">More catalog products</option> : null}<option value="all">All reviewed samples</option><option value="selected">Selected catalog only</option></select></label>
          {!sampled ? <label className="catalog-preview-match-filter"><input type="checkbox" checked={onlyMatches} onChange={(event) => setOnlyMatches(event.target.checked)} />Documented fits only</label> : null}
        </div>
      </div>
      {products.length > 0 ? view === "gallery" ? <div className="catalog-preview-grid">
        {products.map((product) => <PreviewCard key={product.id} product={product} requirements={group.requirements} reviewed={!sampled} />)}
      </div> : <ProductComparison products={products} group={group} reviewed={!sampled} /> : <div className="catalog-preview-empty" role="status"><h2>No documented fit in this sample set</h2><p>A missing specification does not mean the feature is absent. Show all samples to inspect the gaps.</p><button type="button" onClick={() => { setOnlyMatches(false); setSampleSet("all"); }}>Show all samples</button></div>}
      <p className="catalog-preview-count" aria-live="polite">Showing {products.length} of {collection.length} products in this preview. These controls compare listed specifications; they do not run retrieval.</p>
      <p className="catalog-preview-legend"><CircleHelp size={16} aria-hidden="true" />{sampled ? "These additional products have not been assessed against every part of Alex’s brief. Switch to reviewed samples for those comparisons." : "“Needs verification” means the source does not establish every requested feature. Reference samples are not confirmed members of the selected catalog."}</p>
      <p className="catalog-preview-footnote">Product text: {data.textSource ?? "Amazon Shopping Queries Dataset"}. Photos: {data.imageSource}. Ratings reflect the source dataset; they are not live values. Current prices and stock are not supplied here. This preview is separate from the live catalog.</p>
    </section>
  );
}
