import { ArrowRight, LoaderCircle, Search } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

interface SearchComposerProps {
  initialValue?: string;
  placeholder?: string;
  inputLabel?: string;
  pending?: boolean;
  compact?: boolean;
  submitLabel?: string;
  autoFocus?: boolean;
  onSubmit: (query: string) => void;
}

export function SearchComposer({
  initialValue = "",
  placeholder = "Describe the product, constraint, or use case",
  inputLabel = "Product search",
  pending = false,
  compact = false,
  submitLabel,
  autoFocus = false,
  onSubmit,
}: SearchComposerProps) {
  const [value, setValue] = useState(initialValue);

  useEffect(() => setValue(initialValue), [initialValue]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const query = value.trim();
    if (query.length >= 2 && !pending) onSubmit(query);
  }

  return (
    <form
      className={compact ? "search-composer compact" : "search-composer"}
      onSubmit={submit}
    >
      <Search size={compact ? 18 : 22} aria-hidden="true" />
      <input
        aria-label={inputLabel}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder={placeholder}
        minLength={2}
        autoFocus={autoFocus}
      />
      {/* Only disabled while a request is in flight. Disabling on an empty field
          made the primary action render at 50% opacity (the global
          button:disabled rule) on first paint, which reads as broken. */}
      <button type="submit" disabled={pending}>
        {pending ? (
          <LoaderCircle className="spin" size={20} aria-hidden="true" />
        ) : submitLabel ? (
          <span>{submitLabel}</span>
        ) : (
          <ArrowRight size={20} aria-hidden="true" />
        )}
        {submitLabel ? null : <span className="sr-only">Search</span>}
      </button>
    </form>
  );
}
