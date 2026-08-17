import { Search, Sparkles } from "lucide-react";

export function GenerativeSearchIcon({ size = 20 }: { size?: number }) {
  return (
    <span
      className="generative-search-icon"
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <Search className="generative-search-lens" size={size} />
      <Sparkles
        className="generative-search-sparkles"
        size={Math.round(size * 0.62)}
      />
    </span>
  );
}
