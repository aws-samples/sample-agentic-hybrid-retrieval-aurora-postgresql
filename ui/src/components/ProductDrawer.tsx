import { ArrowRight, Check, ShoppingBag, Star, X } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { Link } from "wouter";
import { api } from "../api";
import { cartQuantityLimit, useCommerce } from "../commerce";
import {
  formatAvailability,
  formatPrice,
  isPurchasable,
  leafCategory,
} from "../format";
import { productImage } from "../media";
import { lockBodyScroll } from "../scrollLock";
import type { ProductDetail } from "../types";

const EASE_OUT = [0.16, 1, 0.3, 1] as const;

interface ProductDrawerProps {
  productId: number | null;
  imageByProductId: Map<number, string>;
  onClose: () => void;
}

/**
 * Slide-over product detail for picks chosen inside Ask Mosaic. Going deeper
 * on a recommendation should not tear the shopper away from the conversation,
 * so the full catalog row arrives beside it instead of as a navigation.
 */
export function ProductDrawer({
  productId,
  imageByProductId,
  onClose,
}: ProductDrawerProps) {
  const open = productId !== null;
  const reduceMotion = useReducedMotion();
  const { addItem, itemQuantity } = useCommerce();
  const [detail, setDetail] = useState<ProductDetail | null>(null);
  const [error, setError] = useState("");
  const drawerRef = useRef<HTMLElement | null>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);
  const closeRef = useRef(onClose);

  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (productId === null) return undefined;
    let active = true;
    setDetail(null);
    setError("");
    api.product(productId).then(
      (product) => {
        if (active) setDetail(product);
      },
      (cause: unknown) => {
        if (active) {
          setError(
            cause instanceof Error
              ? cause.message
              : "The catalog row could not be loaded.",
          );
        }
      },
    );
    return () => {
      active = false;
    };
  }, [productId]);

  useEffect(() => {
    if (!open) return undefined;
    previouslyFocused.current = (
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
    );
    const unlockScroll = lockBodyScroll();
    // Capture phase, so Escape peels this drawer alone: Ask Mosaic's modal
    // keeps its own window-level Escape listener underneath, and letting the
    // event reach it would close both layers at once.
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      closeRef.current();
    };
    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        drawerRef.current?.querySelectorAll<HTMLElement>(
          [
            'button:not([disabled])',
            '[href]',
            'input:not([disabled])',
            'select:not([disabled])',
            'textarea:not([disabled])',
            '[tabindex]:not([tabindex="-1"])',
          ].join(", "),
        ) ?? [],
      ).filter((element) => !element.hasAttribute("hidden"));
      if (!focusable.length) {
        event.preventDefault();
        drawerRef.current?.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", closeOnEscape, true);
    window.addEventListener("keydown", trapFocus);
    const frame = window.requestAnimationFrame(() => {
      drawerRef.current
        ?.querySelector<HTMLElement>('button[aria-label="Close product details"]')
        ?.focus();
    });
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", closeOnEscape, true);
      window.removeEventListener("keydown", trapFocus);
      unlockScroll();
      if (previouslyFocused.current?.isConnected) {
        previouslyFocused.current.focus();
      }
    };
  }, [open]);

  const image = detail
    ? imageByProductId.get(detail.product_id) ?? productImage(detail)
    : productId !== null
      ? imageByProductId.get(productId)
      : undefined;
  const attributes = detail ? Object.entries(detail.attributes) : [];
  const review = detail?.reviews[0];
  const quantity = detail ? itemQuantity(detail.product_id) : 0;
  const quantityLimit = detail ? cartQuantityLimit(detail) : 0;
  const quantityAtLimit = quantity > 0 && quantity >= quantityLimit;

  return (
    <AnimatePresence initial={false}>
      {open ? (
        <div className="product-drawer-layer">
          <motion.button
            className="product-drawer-backdrop"
            type="button"
            aria-label="Dismiss product details"
            onClick={onClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduceMotion ? 0.1 : 0.18 }}
          />
          <motion.aside
            ref={drawerRef}
            className="product-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="Product details"
            aria-busy={!detail && !error}
            tabIndex={-1}
            initial={reduceMotion ? { opacity: 0 } : { x: "100%" }}
            animate={reduceMotion ? { opacity: 1 } : { x: 0 }}
            exit={reduceMotion ? { opacity: 0 } : { x: "100%" }}
            transition={{ duration: reduceMotion ? 0.12 : 0.28, ease: EASE_OUT }}
          >
            <header>
              <div>
                <p className="eyebrow">
                  {detail
                    ? `${detail.brand} · ${leafCategory(detail.category_path)}`
                    : "Mosaic catalog"}
                </p>
                <h2>{detail ? detail.title : "Opening the catalog row"}</h2>
              </div>
              <button
                type="button"
                aria-label="Close product details"
                onClick={onClose}
              >
                <X size={18} />
              </button>
            </header>

            <div className="product-drawer-body">
              {image ? (
                <div className="product-drawer-media">
                  <img src={image} alt={detail?.title ?? ""} />
                </div>
              ) : null}

              {error ? (
                <p className="product-drawer-error" role="alert">{error}</p>
              ) : null}
              {!detail && !error ? (
                <p className="product-drawer-loading" role="status" aria-atomic="true">
                  Pulling the full catalog row…
                </p>
              ) : null}
              {detail ? (
                <p className="sr-only" role="status" aria-atomic="true">
                  Product details loaded for {detail.title}.
                </p>
              ) : null}

              {detail ? (
                <>
                  <div className="product-drawer-price-row">
                    <strong>
                      {formatPrice(detail.price_cents, detail.currency)}
                    </strong>
                    {detail.list_price_cents > detail.price_cents ? (
                      <s>
                        {formatPrice(detail.list_price_cents, detail.currency)}
                      </s>
                    ) : null}
                    <span
                      className={
                        isPurchasable(detail.availability) ? "stock" : "muted"
                      }
                    >
                      {isPurchasable(detail.availability) ? (
                        <Check size={14} />
                      ) : null}
                      {formatAvailability(detail.availability)}
                    </span>
                  </div>

                  {/* A rating with no reviews behind it is not evidence, so
                      the stars only appear when the row carries reviews. */}
                  {detail.review_count && detail.rating !== null ? (
                    <div className="rating-row">
                      {Array.from({ length: 5 }).map((_, index) => (
                        <Star
                          key={index}
                          size={14}
                          fill={
                            index < Math.round(detail.rating ?? 0)
                              ? "currentColor"
                              : "none"
                          }
                        />
                      ))}
                      <strong>{detail.rating.toFixed(1)}</strong>
                      <span>
                        {detail.review_count.toLocaleString()} reviews
                      </span>
                    </div>
                  ) : null}

                  <p className="product-drawer-description">
                    {detail.long_description || detail.short_description}
                  </p>

                  {attributes.length ? (
                    <dl className="spec-table">
                      {attributes.slice(0, 6).map(([key, value]) => (
                        <div key={key}>
                          <dt>{key.replaceAll("_", " ")}</dt>
                          <dd>
                            {Array.isArray(value)
                              ? value.join(", ")
                              : String(value)}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  ) : null}

                  {review ? (
                    <blockquote>
                      <p>“{review.body}”</p>
                      <cite>
                        {review.source_name}
                        {review.verified_purchase ? " · Verified purchase" : ""}
                        {review.rating !== null
                          ? ` / ${review.rating.toFixed(1)} stars`
                          : ""}
                      </cite>
                    </blockquote>
                  ) : null}
                </>
              ) : null}
            </div>

            <footer>
              <button
                className="product-drawer-add"
                type="button"
                disabled={!detail || !quantityLimit || quantityAtLimit}
                onClick={() => detail && addItem(detail)}
              >
                <ShoppingBag size={16} />
                {detail && !quantityLimit
                  ? formatAvailability(detail.availability)
                  : quantityAtLimit
                    ? `Maximum in bag (${quantity})`
                    : quantity
                      ? `Add another (${quantity} in bag)`
                      : "Add to bag"}
              </button>
              {productId !== null ? (
                <Link
                  className="product-drawer-full-link"
                  href={`/products/${productId}`}
                  onClick={onClose}
                >
                  Full product page <ArrowRight size={15} />
                </Link>
              ) : null}
            </footer>
          </motion.aside>
        </div>
      ) : null}
    </AnimatePresence>
  );
}
