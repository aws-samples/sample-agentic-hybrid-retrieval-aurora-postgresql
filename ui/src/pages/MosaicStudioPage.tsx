import { ArrowRight, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "wouter";
import { api } from "../api";
import { MosaicLabsTabs } from "../components/MosaicLabsTabs";
import { formatPrice } from "../format";
import { productImage } from "../media";
import type { ProductDetail } from "../types";

const studioProductIds = [370001, 420001, 429001] as const;

const studioPieces = [
  { productId: 370001, zone: "Focus seating", className: "studio-piece-seat" },
  { productId: 420001, zone: "Creative display", className: "studio-piece-display" },
  { productId: 429001, zone: "Quiet input", className: "studio-piece-input" },
] as const;

/**
 * An optional visual composition study using real Mosaic catalog products.
 *
 * It intentionally does not represent a retrieval or ranking result: it is
 * separated from the Workshop tab until compositional retrieval is real.
 */
export function MosaicStudioPage() {
  const [assembled, setAssembled] = useState(false);
  const [products, setProducts] = useState<ProductDetail[]>([]);
  const [unavailable, setUnavailable] = useState(false);
  const productById = new Map(products.map((product) => [product.product_id, product]));
  const hasProducts = products.length === studioPieces.length;

  useEffect(() => {
    let cancelled = false;
    Promise.all(studioProductIds.map((productId) => api.product(productId)))
      .then((loadedProducts) => {
        if (!cancelled) {
          setProducts(loadedProducts);
          setUnavailable(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setProducts([]);
          setUnavailable(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="page mosaic-labs-page labs-premium mosaic-studio-page">
      <MosaicLabsTabs active="studio" />

      <header className="mosaic-studio-intro">
        <p className="eyebrow">Optional exploration</p>
        <h1>Compose a creative workspace.</h1>
        <p>
          A visual study built from real Mosaic catalog records. It is a
          selected composition, not a generated recommendation.
        </p>
      </header>

      <section className="discover-studio" aria-labelledby="mosaic-studio-title">
        <div className="discover-studio-copy">
          <p>Mosaic Studio</p>
          <h2 id="mosaic-studio-title">A creative studio, in motion.</h2>
          <span>
            A quiet, capable starting point for long creative days: an ergonomic
            seat, a precise display, and tactile input.
          </span>
          <p className="discover-studio-brief">A selected creative-workday composition.</p>
          <div className="discover-studio-actions">
            {hasProducts ? (
              <button type="button" onClick={() => setAssembled((current) => !current)}>
                <Sparkles size={15} aria-hidden="true" />
                {assembled ? "Reset the studio" : "Assemble the studio"}
              </button>
            ) : (
              <span className="discover-studio-status" role={unavailable ? "alert" : "status"}>
                {unavailable ? "Studio pieces are unavailable." : "Preparing the studio."}
              </span>
            )}
            <Link href="/catalog?domain=home_office">
              Shop the workspace
              <ArrowRight size={15} aria-hidden="true" />
            </Link>
          </div>
        </div>

        <div
          className={assembled ? "discover-studio-canvas assembled" : "discover-studio-canvas"}
          aria-live="polite"
        >
          <span className="discover-studio-grid" aria-hidden="true" />
          <span className="discover-studio-orbit discover-studio-orbit-one" aria-hidden="true" />
          <span className="discover-studio-orbit discover-studio-orbit-two" aria-hidden="true" />
          <span className="discover-studio-route discover-studio-route-one" aria-hidden="true" />
          <span className="discover-studio-route discover-studio-route-two" aria-hidden="true" />
          {studioPieces.map(({ productId, zone, className }, index) => {
            const product = productById.get(productId);
            return assembled && product ? (
              <Link
                className={`discover-studio-piece ${className}`}
                href={`/products/${product.product_id}`}
                key={product.product_id}
              >
                <span className="discover-studio-piece-image">
                  <img
                    src={productImage(product)}
                    alt={product.title}
                    width={1200}
                    height={800}
                    loading="lazy"
                    decoding="async"
                  />
                </span>
                <span>
                  <small>{zone}</small>
                  <strong>{product.model}</strong>
                  <em>{formatPrice(product.price_cents, product.currency)}</em>
                </span>
                <i>{String(index + 1).padStart(2, "0")}</i>
              </Link>
            ) : (
              <span className={`discover-studio-placeholder ${className}`} key={productId} />
            );
          })}
          <span className="discover-studio-state">
            {assembled ? "Studio assembled" : "Three pieces"}
          </span>
        </div>
      </section>

      <section className="mosaic-studio-boundary" aria-label="Studio scope">
        <div>
          <span>What this shows</span>
          <strong>Real premium catalog products in a composed workspace.</strong>
        </div>
        <div>
          <span>What it does not claim</span>
          <strong>Candidate retrieval, bundle ranking, compatibility, or evidence-backed advice.</strong>
        </div>
        <Link href="/mosaic-labs">
          Inspect the retrieval system <ArrowRight size={15} />
        </Link>
      </section>
    </div>
  );
}
