"use client";

export type BasketProduct = {
  price_snapshot_id: string;
  product_name: string;
  retailer_id: string;
  current_price: number | string;
  image_url?: string;
  source_url?: string;
  brand?: string;
  effective_unit_price?: number | string;
  comparison_unit?: string;
};

export type BasketItem = BasketProduct & { quantity: number };

export const BASKET_STORAGE_KEY = "pricely_basket_v1";
const BASKET_EVENT = "pricely:basket-changed";

function isBasketProduct(value: unknown): value is BasketProduct {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.price_snapshot_id === "string"
    && typeof candidate.product_name === "string"
    && typeof candidate.retailer_id === "string";
}

function sanitize(items: unknown): BasketItem[] {
  if (!Array.isArray(items)) return [];
  return items
    .filter(isBasketProduct)
    .map((item) => ({ ...item, quantity: Math.max(1, Number((item as Partial<BasketItem>).quantity) || 1) }));
}

export function getBasket(): BasketItem[] {
  if (typeof window === "undefined") return [];
  try {
    return sanitize(JSON.parse(window.localStorage.getItem(BASKET_STORAGE_KEY) || "[]"));
  } catch {
    return [];
  }
}

export function setBasket(items: BasketItem[]): BasketItem[] {
  const next = sanitize(items);
  if (typeof window === "undefined") return next;
  window.localStorage.setItem(BASKET_STORAGE_KEY, JSON.stringify(next));
  window.dispatchEvent(new CustomEvent<BasketItem[]>(BASKET_EVENT, { detail: next }));
  return next;
}

export function addBasketItem(product: BasketProduct, quantity = 1): BasketItem[] {
  const current = getBasket();
  const found = current.find((item) => item.price_snapshot_id === product.price_snapshot_id);
  const next = found
    ? current.map((item) => item.price_snapshot_id === product.price_snapshot_id
      ? { ...item, quantity: item.quantity + Math.max(1, quantity) }
      : item)
    : [...current, { ...product, quantity: Math.max(1, quantity) }];
  return setBasket(next);
}

export function removeBasketItem(priceSnapshotId: string): BasketItem[] {
  return setBasket(getBasket().filter((item) => item.price_snapshot_id !== priceSnapshotId));
}

export function updateBasketQuantity(priceSnapshotId: string, quantity: number): BasketItem[] {
  const next = getBasket()
    .map((item) => item.price_snapshot_id === priceSnapshotId ? { ...item, quantity: Math.max(0, quantity) } : item)
    .filter((item) => item.quantity > 0);
  return setBasket(next);
}

export function clearBasket(): BasketItem[] {
  return setBasket([]);
}

export function subscribeBasket(listener: (items: BasketItem[]) => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  const onChange = (event: Event) => listener((event as CustomEvent<BasketItem[]>).detail || getBasket());
  const onStorage = (event: StorageEvent) => {
    if (event.key === BASKET_STORAGE_KEY) listener(getBasket());
  };
  window.addEventListener(BASKET_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(BASKET_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}
