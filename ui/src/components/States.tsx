import { AlertTriangle, LoaderCircle } from "lucide-react";

const catalogSkeletonItems = Array.from({ length: 8 }, (_, index) => index);

export function CatalogLoadingState() {
  return (
    <section
      className="catalog-skeleton"
      role="status"
      aria-label="Loading products"
    >
      <span className="sr-only">Loading products</span>
      <div className="catalog-skeleton-grid" aria-hidden="true">
        {catalogSkeletonItems.map((item) => (
          <article className="catalog-skeleton-card" key={item}>
            <div className="catalog-skeleton-media" />
            <div className="catalog-skeleton-copy">
              <span />
              <strong />
              <span />
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className="state-panel" role="status">
      <LoaderCircle className="spin" size={22} />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="state-panel error" role="alert">
      <AlertTriangle size={22} />
      <span>{message}</span>
      {onRetry ? (
        <button type="button" className="secondary-button" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}
