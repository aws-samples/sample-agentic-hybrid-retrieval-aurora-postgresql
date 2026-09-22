import { BookOpen, Download, ExternalLink, X } from "lucide-react";
import { useRef } from "react";
import { createPortal } from "react-dom";
import embedScript from "../../../scripts/embed_real_catalog.py?url";
import loadScript from "../../../scripts/stage_real_catalog.py?url";
import indexScript from "../../../scripts/prepare_staged_catalog_search.py?url";
import probeScript from "../../../scripts/probe_staged_catalog_search.py?url";

const steps = [
  {
    title: "Generate",
    description: "Group product descriptions into batches for Cohere Embed v4. Pace requests against each Region’s quota, adjust from actual usage, and retry temporary failures.",
    scripts: [{ name: "embed_real_catalog.py", url: embedScript }],
  },
  {
    title: "Verify",
    description: "Check product IDs, source-text hashes and saved-vector checksums. Require the expected dimensions, valid numbers and one vector per selected product.",
    scripts: [{ name: "embed_real_catalog.py", url: embedScript }],
  },
  {
    title: "Load",
    description: "Use binary COPY into a temporary table. Update matching products and save their checkpoints in the same transaction, so a restart resumes safely.",
    scripts: [{ name: "stage_real_catalog.py", url: loadScript }],
  },
  {
    title: "Index",
    description: "Build full-text, spelling and vector-search indexes. Then check real queries and filters: a finished index alone does not establish useful results.",
    scripts: [
      { name: "prepare_staged_catalog_search.py", url: indexScript },
      { name: "probe_staged_catalog_search.py", url: probeScript },
    ],
  },
];

export function CatalogBuildDrawer() {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  return <>
    <button type="button" ref={trigger} className="catalog-build-link" aria-haspopup="dialog" onClick={() => dialog.current?.showModal()}>
      <BookOpen size={16} aria-hidden="true" /> How this catalog was built
    </button>
    {createPortal(<dialog ref={dialog} className="catalog-build-drawer" aria-labelledby="catalog-build-title" onClose={() => trigger.current?.focus()}>
      <header>
        <h2 id="catalog-build-title">How this catalog was built</h2>
        <button type="button" className="catalog-build-close" aria-label="Close catalog preparation" onClick={() => dialog.current?.close()}><X size={20} aria-hidden="true" /></button>
      </header>
      <div className="catalog-build-body">
        <p className="catalog-build-intro">Four steps prepare the replacement catalog from Amazon Reviews 2023. Original descriptions, photos and listing links stay attached to each product.</p>
        <ol>
          {steps.map((step, index) => <li key={step.title}>
            <span className="catalog-build-number" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
            <div><h3>{step.title}</h3><p>{step.description}</p>
              <div className="catalog-build-scripts">{step.scripts.map(script => <a key={script.name} href={script.url} download={script.name}>
                <Download size={14} aria-hidden="true" /><span>{script.name}</span>
              </a>)}</div>
            </div>
          </li>)}
        </ol>
        <p className="catalog-build-note">Switching to <code>halfvec</code> or binary values reuses the saved embeddings. It does not require generating them again.</p>
        <footer>
          <p>Downloads contain the scripts from this app build. Run them from the full project checkout.</p>
          <a href="https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql" target="_blank" rel="noreferrer">View the project on GitHub <ExternalLink size={14} aria-hidden="true" /></a>
        </footer>
      </div>
    </dialog>, document.body)}
  </>;
}
