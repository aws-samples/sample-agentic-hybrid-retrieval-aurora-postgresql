import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
// This sequence is one stylesheet, split into files by surface for
// maintainability. Import order is the cascade order: it must match the
// original concatenation exactly. See docs/ui-design-system.md.
import "./styles.css";
import "./ask-mosaic-panel.css";
import "./catalog-cards.css";
import "./shared-states.css";
import "./shop-storefront.css";
import "./labs-agentic.css";
import "./commerce.css";
import "./surfaces.css";
import "./agent-answer-parts.css";
import "./surfaces-labs-shell.css";
import "./surfaces-hnsw.css";
import "./surfaces-playground.css";
import "./source-products.css";
import "./world.css";
import "./ask-mosaic.css";

// A browser driven by automation (guide captures, rehearsal scripts) reports
// navigator.webdriver; the first-visit tour would cover every page they capture,
// so it waits for the header's Take the tour button there instead.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App autoStartTour={!navigator.webdriver} />
  </StrictMode>,
);
