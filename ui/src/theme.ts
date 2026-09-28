import { useEffect, useState } from "react";

/**
 * Light or dark follows the system until the viewer picks one; the pick is a
 * per-browser convenience, so storage may be unavailable and nothing breaks.
 * `index.html` applies the same rule before first paint so the page never
 * flashes the other theme.
 */
export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "mosaic-theme";

function storedTheme(): Theme | null {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
}

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => storedTheme() ?? systemTheme());
  useEffect(() => applyTheme(theme), [theme]);
  useEffect(() => {
    const query = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!query) return;
    const follow = (event: MediaQueryListEvent) => {
      if (!storedTheme()) setTheme(event.matches ? "dark" : "light");
    };
    query.addEventListener("change", follow);
    return () => query.removeEventListener("change", follow);
  }, []);
  const toggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // A private window can refuse storage; the switch still works for this visit.
    }
    setTheme(next);
  };
  return [theme, toggle];
}
