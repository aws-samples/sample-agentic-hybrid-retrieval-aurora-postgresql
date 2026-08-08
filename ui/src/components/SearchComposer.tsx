import { ArrowRight, LoaderCircle, Search } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

interface SearchComposerProps {
  initialValue?: string;
  placeholder?: string;
  pending?: boolean;
  compact?: boolean;
  submitLabel?: string;
  onSubmit: (query: string) => void;
}

export function SearchComposer({
  initialValue = "",
  placeholder = "Describe the product, constraint, or use case",
  pending = false,
  compact = false,
  submitLabel,
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
        aria-label="Product search"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder={placeholder}
        minLength={2}
      />
      <button type="submit" disabled={pending || value.trim().length < 2}>
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
