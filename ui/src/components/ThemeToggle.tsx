import { Moon, Sun } from "lucide-react";
import type { Theme } from "../theme";

/** The header's theme switch; the header owns the theme so its menu item agrees with it. */
export function ThemeToggle({ theme, onToggle }: { theme: Theme; onToggle: () => void }) {
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button className="site-icon site-theme" type="button" aria-label={`Switch to ${next} mode`} onClick={onToggle}>
      {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
    </button>
  );
}
