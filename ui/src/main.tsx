import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { preloadDiscover } from "./discoverData";
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
import "./surfaces-ask-mosaic.css";
import "./surfaces-labs-shell.css";
import "./surfaces-hnsw.css";
import "./surfaces-playground.css";
import "./source-products.css";

if (["/", "/discover"].includes(window.location.pathname)) preloadDiscover();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
