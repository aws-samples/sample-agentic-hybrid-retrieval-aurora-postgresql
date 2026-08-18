import {
  ArrowRight,
  Building2,
  LoaderCircle,
  Package,
  Search,
  Tags,
} from "lucide-react";
import {
  FocusEvent,
  FormEvent,
  KeyboardEvent,
  Ref,
  ReactNode,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { api } from "../api";
import { formatCategoryKey } from "../format";
import { productBoundImage } from "../media";
import type { CatalogSuggestion } from "../types";

interface CatalogSearchComposerProps {
  initialValue?: string;
  idleSuggestions?: string[];
  inputLabel?: string;
  inputRef?: Ref<HTMLInputElement>;
  pending?: boolean;
  leadingIcon?: ReactNode;
  placeholder?: string;
  onValueChange?: (value: string) => void;
  onSubmit: (query: string) => void;
}

// Alternate exact catalog identities with natural-language shopping intent.
// The idle examples teach both retrieval modes without changing the input.
export const catalogGhostQueries = [
  "quiet mechanical keyboard for a shared office",
  "Sonora WH-C720",
  "carbon-plated marathon shoes under $220",
  "Ergonomic Office Chairs",
  "comfortable headphones for a 14-hour flight",
  "Mosaic Auraluxe H9",
];

const suggestionIcons = {
  product: Package,
  brand: Building2,
  category: Tags,
};

function suggestionDetail(suggestion: CatalogSuggestion) {
  if (suggestion.kind === "product") {
    return [
      suggestion.brand,
      suggestion.category_key
        ? formatCategoryKey(suggestion.category_key)
        : null,
    ].filter(Boolean).join(" · ");
  }
  if (suggestion.kind === "category") {
    return suggestion.category_path ?? "Product category";
  }
  return "Brand";
}

export function CatalogSearchComposer({
  initialValue = "",
  idleSuggestions = [],
  inputLabel = "Product search",
  inputRef,
  pending = false,
  leadingIcon,
  placeholder = "Search a product, model, or describe what you need",
  onValueChange,
  onSubmit,
}: CatalogSearchComposerProps) {
  const [value, setValue] = useState(initialValue);
  const [suggestions, setSuggestions] = useState<CatalogSuggestion[]>([]);
  const [suggestionsPending, setSuggestionsPending] = useState(false);
  const [suggestionsError, setSuggestionsError] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [idleSuggestionIndex, setIdleSuggestionIndex] = useState(0);
  const [showIdleSuggestion, setShowIdleSuggestion] = useState(false);
  const listboxId = useId();
  const requestVersion = useRef(0);
  const trimmed = value.trim();
  const hasQuery = trimmed.length >= 2;
  const optionCount = suggestions.length + (hasQuery ? 1 : 0);
  const idleSuggestion = idleSuggestions[idleSuggestionIndex] ?? "";

  useEffect(() => setValue(initialValue), [initialValue]);

  useEffect(() => {
    setShowIdleSuggestion(false);
    if (trimmed || !idleSuggestions.length) return;

    const reveal = window.setTimeout(() => setShowIdleSuggestion(true), 1200);
    const rotate = window.setInterval(() => {
      setIdleSuggestionIndex((index) => (index + 1) % idleSuggestions.length);
      setShowIdleSuggestion(true);
    }, 5200);
    return () => {
      window.clearTimeout(reveal);
      window.clearInterval(rotate);
    };
  }, [idleSuggestions, trimmed]);

  useEffect(() => {
    const version = requestVersion.current + 1;
    requestVersion.current = version;
    setActiveIndex(-1);
    setSuggestionsError("");

    if (!hasQuery || trimmed === initialValue.trim()) {
      setSuggestions([]);
      setSuggestionsPending(false);
      setOpen(false);
      return;
    }

    setSuggestionsPending(true);
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setOpen(true);
      api
        .suggestions(trimmed, controller.signal)
        .then((response) => {
          if (version !== requestVersion.current) return;
          setSuggestions(response.suggestions);
        })
        .catch((cause: unknown) => {
          if (controller.signal.aborted || version !== requestVersion.current) return;
          setSuggestions([]);
          setSuggestionsError(
            cause instanceof Error
              ? cause.message
              : "Catalog suggestions are unavailable.",
          );
        })
        .finally(() => {
          if (version === requestVersion.current) setSuggestionsPending(false);
        });
    }, 180);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [hasQuery, initialValue, trimmed]);

  function submit(query: string) {
    const normalized = query.trim();
    if (normalized.length < 2 || pending) return;
    requestVersion.current += 1;
    setValue(normalized);
    onValueChange?.(normalized);
    setOpen(false);
    setActiveIndex(-1);
    onSubmit(normalized);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (open && activeIndex >= 0) {
      const suggestion = suggestions[activeIndex];
      submit(suggestion?.query ?? trimmed);
      return;
    }
    submit(trimmed || idleSuggestion);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (
      event.key === "ArrowRight"
      && !trimmed
      && showIdleSuggestion
      && idleSuggestion
    ) {
      event.preventDefault();
      setValue(idleSuggestion);
      onValueChange?.(idleSuggestion);
      setShowIdleSuggestion(false);
      return;
    }
    if (!hasQuery) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((index) => (index + 1) % optionCount);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((index) => (index <= 0 ? optionCount - 1 : index - 1));
    } else if (event.key === "Escape") {
      setOpen(false);
      setActiveIndex(-1);
    }
  }

  function handleBlur(event: FocusEvent<HTMLFormElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setOpen(false);
      setActiveIndex(-1);
    }
  }

  return (
    <form
      className="search-composer compact catalog-autocomplete"
      onSubmit={handleSubmit}
      onBlur={handleBlur}
    >
      {leadingIcon ?? <Search size={18} aria-hidden="true" />}
      {showIdleSuggestion && !trimmed ? (
        <span
          aria-hidden="true"
          className="catalog-idle-suggestion"
          key={idleSuggestion}
        >
          {idleSuggestion}
        </span>
      ) : null}
      <input
        aria-activedescendant={
          open && activeIndex >= 0
            ? `${listboxId}-option-${activeIndex}`
            : undefined
        }
        aria-autocomplete="list"
        aria-controls={listboxId}
        aria-expanded={open}
        aria-label={inputLabel}
        autoComplete="off"
        ref={inputRef}
        minLength={2}
        placeholder={showIdleSuggestion ? "" : placeholder}
        role="combobox"
        value={value}
        onChange={(event) => {
          setValue(event.target.value);
          onValueChange?.(event.target.value);
          setShowIdleSuggestion(false);
          setOpen(event.target.value.trim().length >= 2);
        }}
        onFocus={() => {
          if (hasQuery && trimmed !== initialValue.trim()) setOpen(true);
        }}
        onKeyDown={handleKeyDown}
      />
      <button type="submit" disabled={pending} aria-label="Search">
        {pending ? (
          <LoaderCircle className="spin" size={20} aria-hidden="true" />
        ) : (
          <>
            <span>Search</span>
            <ArrowRight size={16} aria-hidden="true" />
          </>
        )}
      </button>

      {open ? (
        <div
          aria-label="Catalog suggestions"
          className="catalog-suggestions"
          id={listboxId}
          role="listbox"
        >
          <div className="catalog-suggestions-label" role="presentation">
            <span>Catalog matches</span>
            {suggestionsPending ? (
              <span role="status">
                <LoaderCircle className="spin" size={13} aria-hidden="true" />
                Matching
              </span>
            ) : null}
          </div>

          {!suggestionsPending && suggestionsError ? (
            <p className="catalog-suggestions-message" role="presentation">
              Suggestions are unavailable. Press Enter to search.
            </p>
          ) : null}

          {!suggestionsPending && !suggestionsError && !suggestions.length ? (
            <p className="catalog-suggestions-message" role="presentation">
              No direct catalog matches yet.
            </p>
          ) : null}

          {suggestions.map((suggestion, index) => {
            const Icon = suggestionIcons[suggestion.kind];
            const imageSrc = suggestion.kind === "product" && suggestion.product_id !== null
              ? productBoundImage(suggestion.product_id)
              : null;
            return (
              <button
                className={activeIndex === index ? "active" : ""}
                id={`${listboxId}-option-${index}`}
                key={`${suggestion.kind}-${suggestion.product_id ?? suggestion.label}`}
                role="option"
                aria-selected={activeIndex === index}
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => submit(suggestion.query)}
              >
                {imageSrc ? (
                  <span className="catalog-suggestion-thumbnail">
                    <img src={imageSrc} alt="" decoding="async" />
                  </span>
                ) : (
                  <span className={`catalog-suggestion-icon ${suggestion.kind}`}>
                    <Icon size={16} aria-hidden="true" />
                  </span>
                )}
                <span>
                  <strong>{suggestion.label}</strong>
                  <small>{suggestionDetail(suggestion)}</small>
                </span>
                <em>{suggestion.kind}</em>
              </button>
            );
          })}

          <button
            className={
              activeIndex === suggestions.length
                ? "catalog-search-all active"
                : "catalog-search-all"
            }
            id={`${listboxId}-option-${suggestions.length}`}
            role="option"
            aria-selected={activeIndex === suggestions.length}
            type="button"
            onMouseDown={(event) => event.preventDefault()}
            onMouseEnter={() => setActiveIndex(suggestions.length)}
            onClick={() => submit(trimmed)}
          >
            <span className="catalog-suggestion-icon search">
              <Search size={16} aria-hidden="true" />
            </span>
            <span>
              <strong>Search all products</strong>
              <small>{trimmed}</small>
            </span>
          </button>
        </div>
      ) : null}
    </form>
  );
}
