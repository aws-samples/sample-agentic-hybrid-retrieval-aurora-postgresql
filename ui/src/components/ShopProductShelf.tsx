import { ChevronLeft, ChevronRight } from "lucide-react";
import { useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { Link } from "wouter";
import { categoryHref, editorialStories } from "../shopStories";
import type { ProductSummary } from "../types";
import { ProductCard } from "./ProductCard";
import { CatalogLoadingState, ErrorState } from "./States";

/** Keep real products within reach without turning the editorial into a long grid. */
export function ShopProductShelf({ products, images, real, pending, error, onRetry }: {
  products: ProductSummary[];
  images: Map<number, string>;
  real: boolean;
  pending: boolean;
  error: string;
  onRetry: () => void;
}) {
  const shelf = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ start: true, end: true });
  const reduceMotion = useReducedMotion();

  function syncEdges() {
    const element = shelf.current;
    if (!element) return;
    setEdges({
      start: element.scrollLeft <= 1,
      end: element.scrollLeft + element.clientWidth >= element.scrollWidth - 1,
    });
  }

  useEffect(() => {
    syncEdges();
    const element = shelf.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(syncEdges);
    observer.observe(element);
    return () => observer.disconnect();
  }, [products]);

  function move(direction: number) {
    const element = shelf.current;
    if (!element) return;
    element.scrollBy({
      left: direction * element.clientWidth,
      behavior: reduceMotion ? "instant" : "smooth",
    });
  }

  return (
    <section className="shop-shelf" aria-labelledby="shop-shelf-title" aria-busy={pending}>
      <header className="shop-shelf-heading">
        <h2 id="shop-shelf-title">Shop the workspace.</h2>
        <Link className="primary-button" href="/catalog?collection=all">
          Browse all products
        </Link>
      </header>
      <div className="shop-shelf-links">
        <nav aria-label="Shop workspace categories">
          {editorialStories.map((story) => (
            <Link key={story.topic} href={categoryHref(story, real)}>{story.topic}</Link>
          ))}
        </nav>
        <a href="#alex-profile">Meet Alex</a>
      </div>
      {error ? <ErrorState message={error} onRetry={onRetry} /> : pending && !products.length ? (
        <CatalogLoadingState />
      ) : products.length ? (
        <>
          <div
            id="shop-workspace-products"
            className="shop-shelf-products"
            role="region"
            aria-label="Workspace products"
            tabIndex={0}
            ref={shelf}
            onScroll={syncEdges}
          >
            {products.map((product) => (
              <ProductCard key={product.product_id} product={product} imageSrc={images.get(product.product_id)} variant="catalog" />
            ))}
          </div>
          <div className="shop-shelf-footer">
            <p>{real ? "Original product listings. Prices and ratings are historical." : "Headphones, chairs and monitors for your workspace."}</p>
            <div className="shop-shelf-arrows" aria-label="Browse workspace products">
              <button type="button" aria-label="Previous workspace products" aria-controls="shop-workspace-products" disabled={edges.start} onClick={() => move(-1)}>
                <ChevronLeft size={20} aria-hidden="true" />
              </button>
              <button type="button" aria-label="Next workspace products" aria-controls="shop-workspace-products" disabled={edges.end} onClick={() => move(1)}>
                <ChevronRight size={20} aria-hidden="true" />
              </button>
            </div>
          </div>
        </>
      ) : <p className="shop-shelf-empty">No workspace picks are available. Browse all products to explore the catalog.</p>}
    </section>
  );
}
