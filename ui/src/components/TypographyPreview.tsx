import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearch } from "wouter";
import "../typography-preview.css";

type Typography = "editorial" | "system";
const storageKey = "mosaic-typography-preview";

function readMode(value: string | null): Typography | null {
  return value === "editorial" || value === "system" ? value : null;
}

function initialMode(): Typography | null {
  const query = readMode(new URLSearchParams(window.location.search).get("type"));
  if (query) return query;
  try {
    return readMode(sessionStorage.getItem(storageKey));
  } catch {
    return null;
  }
}

export function TypographyPreview() {
  const search = useSearch();
  const [mode, setMode] = useState<Typography | null>(initialMode);

  useEffect(() => {
    const selected = readMode(new URLSearchParams(search).get("type"));
    if (selected) setMode(selected);
  }, [search]);

  useEffect(() => {
    if (mode) document.documentElement.dataset.typePreview = mode;
    else delete document.documentElement.dataset.typePreview;
    try {
      if (mode) sessionStorage.setItem(storageKey, mode);
      else sessionStorage.removeItem(storageKey);
    } catch {
      // The in-memory preview still works when browser storage is unavailable.
    }
    return () => { delete document.documentElement.dataset.typePreview; };
  }, [mode]);

  function choose(next: Typography | null) {
    setMode(next);
    const url = new URL(window.location.href);
    if (next) url.searchParams.set("type", next);
    else url.searchParams.delete("type");
    window.history.replaceState(window.history.state, "", url);
  }

  if (!mode) return null;

  return (
    <aside className="typography-preview" aria-label="Typography preview">
      <label htmlFor="typography-preview-choice">Typography</label>
      <select
        id="typography-preview-choice"
        value={mode}
        onChange={event => choose(event.target.value as Typography)}
      >
        <option value="system">Modern · current</option>
        <option value="editorial">Editorial · serif</option>
      </select>
      <button type="button" aria-label="Close preview and restore modern typography" onClick={() => choose(null)}>
        <X size={16} aria-hidden="true" />
      </button>
    </aside>
  );
}
