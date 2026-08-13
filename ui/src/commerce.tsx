import {
  useCallback,
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { isPurchasable } from "./format";
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

export const freeShippingThreshold = 7500;
export const standardShipping = 895;
export const expressShipping = 1695;
const estimatedTaxRate = 0.0825;
export const maxCartQuantity = 9;

export function cartQuantityLimit(product: ProductSummary): number {
  if (
    !isPurchasable(product.availability)
    || !Number.isInteger(product.inventory_count)
    || product.inventory_count < 1
  ) {
    return 0;
  }
  return Math.min(maxCartQuantity, product.inventory_count);
}

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
    if (!Array.isArray(parsed)) return [];

    const normalized = new Map<number, CartLine>();
    for (const line of parsed) {
      if (
        !line?.product
        || !Number.isInteger(line.product.product_id)
        || !Number.isInteger(line.quantity)
        || line.quantity < 1
      ) {
        continue;
      }
      const limit = cartQuantityLimit(line.product);
      if (!limit) continue;
      const existing = normalized.get(line.product.product_id);
      normalized.set(line.product.product_id, {
        product: line.product,
        quantity: Math.min((existing?.quantity ?? 0) + line.quantity, limit),
      });
    }
    return Array.from(normalized.values());
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

  const openCart = useCallback(() => setCartOpen(true), []);
  const closeCart = useCallback(() => setCartOpen(false), []);
  const clearCart = useCallback(() => setLines([]), []);

  const addItem = useCallback((product: ProductSummary) => {
    const limit = cartQuantityLimit(product);
    if (!limit) return;
    setLines((current) => {
      const existing = current.find(
        (line) => line.product.product_id === product.product_id,
      );
      if (!existing) return [...current, { product, quantity: 1 }];
      return current.map((line) =>
        line.product.product_id === product.product_id
          ? { ...line, product, quantity: Math.min(line.quantity + 1, limit) }
          : line,
      );
    });
    setCartOpen(true);
  }, []);

  const setQuantity = useCallback((productId: number, quantity: number) => {
    setLines((current) =>
      current.flatMap((line) => {
        if (line.product.product_id !== productId) return [line];
        const limit = cartQuantityLimit(line.product);
        if (quantity < 1 || !limit) return [];
        return [{ ...line, quantity: Math.min(Math.floor(quantity), limit) }];
      }),
    );
  }, []);

  const removeItem = useCallback((productId: number) => {
    setLines((current) =>
      current.filter((line) => line.product.product_id !== productId),
    );
  }, []);

  const toggleFavorite = useCallback((productId: number) => {
    setFavoriteIds((current) =>
      current.includes(productId)
        ? current.filter((id) => id !== productId)
        : [...current, productId],
    );
  }, []);

  const value: CommerceContextValue = {
    lines,
    itemCount,
    summary,
    isCartOpen,
    openCart,
    closeCart,
    addItem,
    setQuantity,
    removeItem,
    clearCart,
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
