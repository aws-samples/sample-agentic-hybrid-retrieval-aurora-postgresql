import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { preloadDiscover } from "./discoverData";
import "./styles.css";
import "./surfaces.css";

if (["/", "/discover"].includes(window.location.pathname)) preloadDiscover();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
