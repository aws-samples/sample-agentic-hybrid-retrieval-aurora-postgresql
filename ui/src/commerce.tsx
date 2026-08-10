import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { productImage } from "./media";
import type { ProductSummary } from "./types";

export type CartLine = {
  product: ProductSummary;
  quantity: number;
};

export type DeliveryMethod = "standard" | "express";

export type OrderSummary = {
  subtotal: number;
  shipping: number;
  tax: number;
  total: number;
};

const freeShippingThreshold = 7500;
const standardShipping = 895;
const expressShipping = 1695;
const estimatedTaxRate = 0.0825;

export function calculateOrderSummary(
  lines: CartLine[],
  deliveryMethod: DeliveryMethod = "standard",
): OrderSummary {
  const subtotal = lines.reduce(
    (sum, line) => sum + line.product.price_cents * line.quantity,
    0,
  );
  const shipping =
    subtotal === 0
      ? 0
      : deliveryMethod === "express"
        ? expressShipping
        : subtotal >= freeShippingThreshold
          ? 0
          : standardShipping;
  const tax = Math.round(subtotal * estimatedTaxRate);

  return {
    subtotal,
    shipping,
    tax,
    total: subtotal + shipping + tax,
  };
}

type CommerceContextValue = {
  lines: CartLine[];
  itemCount: number;
  summary: OrderSummary;
  isCartOpen: boolean;
  openCart: () => void;
  closeCart: () => void;
  addItem: (product: ProductSummary) => void;
  setQuantity: (productId: number, quantity: number) => void;
  removeItem: (productId: number) => void;
  clearCart: () => void;
  itemQuantity: (productId: number) => number;
  isFavorite: (productId: number) => boolean;
  toggleFavorite: (productId: number) => void;
};

const CommerceContext = createContext<CommerceContextValue | null>(null);
const cartStorageKey = "mosaic-demo-cart-v1";
const favoriteStorageKey = "mosaic-demo-favorites-v1";

function readStoredCart(): CartLine[] {
  try {
    const value = window.localStorage.getItem(cartStorageKey);
    if (!value) return [];
    const parsed = JSON.parse(value) as CartLine[];
    return Array.isArray(parsed)
      ? parsed.filter(
          (line) =>
            line?.product &&
            Number.isInteger(line.product.product_id) &&
            Number.isInteger(line.quantity) &&
            line.quantity > 0,
        )
      : [];
  } catch {
    return [];
  }
}

function readStoredFavorites(): number[] {
  try {
    const value = window.localStorage.getItem(favoriteStorageKey);
    if (!value) return [];
    const parsed = JSON.parse(value) as number[];
    return Array.isArray(parsed)
      ? parsed.filter((productId) => Number.isInteger(productId))
      : [];
  } catch {
    return [];
  }
}

export function CommerceProvider({ children }: { children: ReactNode }) {
  const [lines, setLines] = useState<CartLine[]>(readStoredCart);
  const [favoriteIds, setFavoriteIds] = useState<number[]>(readStoredFavorites);
  const [isCartOpen, setCartOpen] = useState(false);

  useEffect(() => {
    try {
      window.localStorage.setItem(cartStorageKey, JSON.stringify(lines));
    } catch {
      // Storage is an enhancement; private browsing must not break the shop.
    }
  }, [lines]);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        favoriteStorageKey,
        JSON.stringify(favoriteIds),
      );
    } catch {
      // Favorites remain available for the current session.
    }
  }, [favoriteIds]);

  const favoriteSet = useMemo(() => new Set(favoriteIds), [favoriteIds]);
  const itemCount = lines.reduce((sum, line) => sum + line.quantity, 0);
  const summary = calculateOrderSummary(lines);

  function addItem(product: ProductSummary) {
    setLines((current) => {
      const existing = current.find(
        (line) => line.product.product_id === product.product_id,
      );
      if (!existing) return [...current, { product, quantity: 1 }];
      return current.map((line) =>
        line.product.product_id === product.product_id
          ? { ...line, quantity: Math.min(line.quantity + 1, 9) }
          : line,
      );
    });
    setCartOpen(true);
  }

  function setQuantity(productId: number, quantity: number) {
    if (quantity < 1) {
      setLines((current) =>
        current.filter((line) => line.product.product_id !== productId),
      );
      return;
    }
    setLines((current) =>
      current.map((line) =>
        line.product.product_id === productId
          ? { ...line, quantity: Math.min(quantity, 9) }
          : line,
      ),
    );
  }

  function toggleFavorite(productId: number) {
    setFavoriteIds((current) =>
      current.includes(productId)
        ? current.filter((id) => id !== productId)
        : [...current, productId],
    );
  }

  const value: CommerceContextValue = {
    lines,
    itemCount,
    summary,
    isCartOpen,
    openCart: () => setCartOpen(true),
    closeCart: () => setCartOpen(false),
    addItem,
    setQuantity,
    removeItem: (productId) =>
      setLines((current) =>
        current.filter((line) => line.product.product_id !== productId),
      ),
    clearCart: () => setLines([]),
    itemQuantity: (productId) =>
      lines.find((line) => line.product.product_id === productId)?.quantity ?? 0,
    isFavorite: (productId) => favoriteSet.has(productId),
    toggleFavorite,
  };

  return (
    <CommerceContext.Provider value={value}>
      {children}
    </CommerceContext.Provider>
  );
}

export function useCommerce() {
  const context = useContext(CommerceContext);
  if (!context) {
    throw new Error("useCommerce must be used within CommerceProvider");
  }
  return context;
}

export function cartProductImage(product: ProductSummary) {
  return productImage(product);
}
