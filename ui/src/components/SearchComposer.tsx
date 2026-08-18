import { ArrowRight, LoaderCircle, Search } from "lucide-react";
import { FormEvent, ReactNode, useEffect, useState } from "react";

interface SearchComposerProps {
  initialValue?: string;
  placeholder?: string;
  inputLabel?: string;
  pending?: boolean;
  compact?: boolean;
  submitLabel?: string;
  submitIcon?: ReactNode;
  leadingIcon?: ReactNode;
  autoFocus?: boolean;
  /** Empty the field after a submit, for a composer that keeps a thread. */
  clearOnSubmit?: boolean;
  onSubmit: (query: string) => void;
}

export function SearchComposer({
  initialValue = "",
  placeholder = "Describe the product, constraint, or use case",
  inputLabel = "Product search",
  pending = false,
  compact = false,
  submitLabel,
  submitIcon,
  leadingIcon,
  autoFocus = false,
  clearOnSubmit = false,
  onSubmit,
}: SearchComposerProps) {
  const [value, setValue] = useState(initialValue);

  useEffect(() => setValue(initialValue), [initialValue]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const query = value.trim();
    if (query.length < 2 || pending) return;
    onSubmit(query);
    if (clearOnSubmit) setValue("");
  }

  return (
    <form
      className={compact ? "search-composer compact" : "search-composer"}
      onSubmit={submit}
    >
      {leadingIcon ?? (
        <Search size={compact ? 18 : 22} aria-hidden="true" />
      )}
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
      <button
        type="submit"
        disabled={pending}
        aria-label={submitIcon ? submitLabel ?? "Submit search" : undefined}
        title={submitIcon ? submitLabel ?? "Submit search" : undefined}
      >
        {pending ? (
          <LoaderCircle className="spin" size={20} aria-hidden="true" />
        ) : submitIcon ? (
          submitIcon
        ) : submitLabel ? (
          <span>{submitLabel}</span>
        ) : (
          <ArrowRight size={20} aria-hidden="true" />
        )}
        {submitIcon || submitLabel ? null : <span className="sr-only">Search</span>}
      </button>
    </form>
  );
}
