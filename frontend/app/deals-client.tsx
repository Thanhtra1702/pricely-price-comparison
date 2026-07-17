"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  addBasketItem,
  clearBasket,
  getBasket,
  removeBasketItem,
  setBasket as persistBasket,
  subscribeBasket,
  updateBasketQuantity,
} from "./basket";
import type { BasketItem } from "./basket";
import ChatPanel from "./chat-panel";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const RETAILERS: Record<string, string> = {
  bachhoaxanh: "Bách Hóa Xanh",
  go: "GO!",
  lottemart: "Lotte Mart",
  mmvietnam: "MM Mega Market",
  winmart: "WinMart",
};
const BANNERS: Record<string, string[]> = {
  bachhoaxanh: ["banner-1800x480_202607141007527810.webp", "freecompress-1800x480_202606201320509618.webp", "freecompress-1800x480_202607061940200713.webp", "freecompress-hero-banner-pc_202607151543504698.webp", "freecompress-trang-chu-moi-pc_202606300956524625.webp", "freecompress-trang-chu-pc_202606302219487357.webp", "freecompress-trang-chu-pc_202607031125402775.webp", "main-pc-compressed_202607140922366175.webp", "tc-pc-37-1-4_202607151550400941.webp", "tc-pc-3_202607140909323171.webp", "tc-pc-4-2-1_202607011047415248.webp", "trang-chu-moi-pc-compressed_202607091423222162.webp"],
  go: ["3000x900-vie (1).png", "3000x900-vie.png", "web-home-banner-3000x900-vn.png"],
  lottemart: ["1200_COUPON_10K_CONFECTIONERY_CTA_VN.jpg.webp", "1200_COUPON_20K_KOTEX_VN.png.webp", "1200_FREESHIP_GIAO_60P_CTA_VN.jpg.webp", "1200_MUA_NHI_U_GI_M_NHI_U_CTA_VN.jpg.webp"],
  mmvietnam: ["oSHKPweZITRa12Q3OMFC9aiM08CwvSpO1TDHC1vo.png", "QUKyDpGLmrTfbUdVwwSCbAhHyU5hQQsFt3CVr4HX.png"],
  winmart: ["ban-sao-cua-home-banner-867x400--20260713041634.png"],
};

type Offer = {
  price_snapshot_id: string;
  product_name: string;
  brand?: string;
  retailer_id: string;
  current_price: number | string;
  listed_price?: number | string;
  discount_percent?: number | string;
  image_url?: string;
  source_url?: string;
  snapshot_date?: string;
  promotion_text?: string;
  is_price_discount?: boolean;
  has_promo_mechanic?: boolean;
  is_on_promotion?: boolean;
  effective_unit_price?: number | string;
  comparison_unit?: string;
  unit_price_publishable?: boolean;
  silver_data_quality_status?: string;
  data_quality_status?: string;
  canonical_product_id?: string;
  match_type?: "canonical" | "similar";
};

type Section = { retailer_id: string; items: Offer[]; total: number; has_more: boolean };
type AutocompleteItem = { product_name?: string; brand?: string; retailer_id?: string };
type QuickFilter = "all" | "discount" | "budget" | "unit";
type DealFilters = {
  query: string;
  sort: string;
  promotionType: string;
  retailerId: string;
  brand: string;
  minPrice: string;
  maxPrice: string;
  minDiscount: string;
  comparisonUnit: string;
  qualityStatus: string;
  unitPriceOnly: boolean;
};
type InsightSummary = {
  canonical_product_id?: string;
  retailer_count?: number;
  lowest_price?: number | string;
  highest_price?: number | string;
  price_spread?: number | string;
  snapshot_date?: string;
  data_quality_warning?: string | boolean;
};
type InsightResponse = {
  offer?: Offer;
  same_product_offers?: Offer[];
  similar_offers?: Offer[];
  summary?: InsightSummary;
};
type BasketPlanLine = Partial<Offer> & {
  quantity?: number;
  subtotal?: number | string;
  line_total?: number | string;
  offer?: Partial<Offer>;
};
type BasketPlan = {
  retailer_id?: string;
  retailer_name?: string;
  total?: number | string;
  retailer_count?: number;
  savings_vs_selected?: number | string;
  uses_warning_data?: boolean;
  lines?: BasketPlanLine[];
};
type BasketOptimization = {
  single_retailer_options?: BasketPlan[];
  split_order?: BasketPlan;
  unavailable_items?: Array<Partial<Offer>>;
  snapshot_date?: string;
};

function QuantityPicker({ value, onChange, compact = false }: { value: number; onChange: (value: number) => void; compact?: boolean }) {
  const update = (next: number) => onChange(Math.max(1, Math.min(99, next)));
  return <div className={`add-quantity-picker${compact ? " compact" : ""}`} aria-label="Chọn số lượng">
    <button type="button" onClick={() => update(value - 1)} disabled={value <= 1} aria-label="Giảm số lượng">−</button>
    <input type="number" min="1" max="99" value={value} onChange={(event) => update(Number(event.target.value) || 1)} aria-label="Số lượng sản phẩm" />
    <button type="button" onClick={() => update(value + 1)} disabled={value >= 99} aria-label="Tăng số lượng">+</button>
  </div>;
}

const DEFAULT_FILTERS: DealFilters = {
  query: "",
  sort: "featured",
  promotionType: "all",
  retailerId: "",
  brand: "",
  minPrice: "",
  maxPrice: "",
  minDiscount: "",
  comparisonUnit: "",
  qualityStatus: "",
  unitPriceOnly: false,
};

const money = (value?: number | string | null) => value == null ? "—" : new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 }).format(Number(value)) + "₫";
const retailerName = (retailerId?: string) => RETAILERS[retailerId || ""] || retailerId || "Sàn";

function promotionLabel(offer: Offer) {
  if (offer.is_price_discount || Number(offer.discount_percent || 0) > 0) {
    return "Giảm giá trực tiếp";
  }
  if (offer.has_promo_mechanic) return "Ưu đãi theo cơ chế";
  return "Sản phẩm có khuyến mãi";
}

function promotionTerms(offer: Offer) {
  const raw = offer.promotion_text?.trim();
  if (!raw || ["price_discount", "promo_mechanic_unparsed", "promotion_flag_only"].includes(raw)) return "Thông tin khuyến mãi do sàn cung cấp";
  return raw;
}

function unitPrice(offer: Partial<Offer>) {
  if (offer.unit_price_publishable === false || offer.effective_unit_price == null) return null;
  return money(offer.effective_unit_price) + "/" + (offer.comparison_unit || "đơn vị");
}

function qualityWarning(offer: Partial<Offer>) {
  return (offer.silver_data_quality_status || offer.data_quality_status || "").toLowerCase() === "warning";
}

function requestParams(filters: DealFilters, extra: Record<string, string> = {}) {
  const params = new URLSearchParams({ q: filters.query, sort: filters.sort, promotion_type: filters.promotionType, ...extra });
  if (filters.retailerId) params.set("retailer_id", filters.retailerId);
  if (filters.brand.trim()) params.set("brand", filters.brand.trim());
  if (filters.minPrice) params.set("min_price", filters.minPrice);
  if (filters.maxPrice) params.set("max_price", filters.maxPrice);
  if (filters.minDiscount) params.set("min_discount_percent", filters.minDiscount);
  if (filters.comparisonUnit) params.set("comparison_unit", filters.comparisonUnit);
  if (filters.qualityStatus) params.set("data_quality", filters.qualityStatus);
  if (filters.unitPriceOnly) params.set("unit_price_only", "true");
  return params;
}

function BannerSlider({ retailerId }: { retailerId: string }) {
  const banners = BANNERS[retailerId] || [];
  const [index, setIndex] = useState(0);
  useEffect(() => {
    setIndex(0);
    if (banners.length < 2) return;
    const timer = window.setInterval(() => setIndex((value) => (value + 1) % banners.length), 3500);
    return () => window.clearInterval(timer);
  }, [retailerId, banners.length]);
  if (!banners.length) return null;
  return <div className="retailer-banner">
    <img src={"/banners/" + retailerId + "/" + encodeURIComponent(banners[index])} alt={"Ưu đãi " + retailerName(retailerId)} />
    {banners.length > 1 && <div className="banner-dots">
      {banners.map((_, dot) => <button aria-label={"Banner " + (dot + 1)} className={dot === index ? "active" : ""} type="button" key={dot} onClick={() => setIndex(dot)} />)}
    </div>}
  </div>;
}

function PlanCard({ plan, title }: { plan: BasketPlan; title: string }) {
  const lines = plan.lines || [];
  return <section className="basket-plan">
    <header>
      <div><b>{title}</b><span>{plan.retailer_name || retailerName(plan.retailer_id)}{plan.retailer_count && !plan.retailer_id ? " · " + plan.retailer_count + " sàn" : ""}</span></div>
      <strong>{money(plan.total)}</strong>
    </header>
    {Number(plan.savings_vs_selected || 0) > 0 && <p className="basket-saving">Tiết kiệm {money(plan.savings_vs_selected)} so với lựa chọn hiện tại</p>}
    {plan.uses_warning_data && <p className="basket-quality-note">⚠ Giá thấp nhất đang dùng bản ghi cần kiểm tra lại trên trang nguồn.</p>}
    <ul>
      {lines.map((line, index) => {
        const offer = line.offer || line;
        return <li key={line.price_snapshot_id || index}>
          <span>{offer.product_name || "Sản phẩm"}</span>
          <small>{retailerName(offer.retailer_id)} · x{line.quantity || 1}{offer.source_url && <> · <a href={offer.source_url} target="_blank" rel="noreferrer">Mua tại sàn ↗</a></>}</small>
          <b>{money(line.line_total ?? line.subtotal ?? offer.current_price)}</b>
        </li>;
      })}
    </ul>
  </section>;
}

export default function DealsClient() {
  const [sections, setSections] = useState<Section[]>([]);
  const [snapshotDate, setSnapshotDate] = useState<string>();
  const [filters, setFilters] = useState<DealFilters>(DEFAULT_FILTERS);
  const [appliedFilters, setAppliedFilters] = useState<DealFilters>(DEFAULT_FILTERS);
  const [quickFilter, setQuickFilter] = useState<QuickFilter>("all");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [chatOpen, setChatOpen] = useState(false);
  const [chatResetKey, setChatResetKey] = useState(0);
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState("");
  const [assistantHint, setAssistantHint] = useState(true);
  const [basket, setBasket] = useState<BasketItem[]>([]);
  const [basketOpen, setBasketOpen] = useState(false);
  const [recentlyAddedId, setRecentlyAddedId] = useState("");
  const [addQuantities, setAddQuantities] = useState<Record<string, number>>({});
  const [basketOptimizing, setBasketOptimizing] = useState(false);
  const [basketError, setBasketError] = useState("");
  const [basketOptimization, setBasketOptimization] = useState<BasketOptimization | null>(null);
  const [detailOffer, setDetailOffer] = useState<Offer | null>(null);
  const [insight, setInsight] = useState<InsightResponse | null>(null);
  const [insightLoading, setInsightLoading] = useState(false);
  const [insightError, setInsightError] = useState("");
  const [autocomplete, setAutocomplete] = useState<AutocompleteItem[]>([]);
  const basketFeedbackTimer = useRef<number | null>(null);

  const loadOverview = useCallback(async (nextFilters: DealFilters) => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(API + "/api/deals/overview?" + requestParams(nextFilters).toString());
      if (!response.ok) throw new Error("Không thể tải ưu đãi lúc này.");
      const data = await response.json() as { sections?: Section[]; snapshot_date?: string };
      const loaded = data.sections || [];
      setSections(nextFilters.retailerId ? loaded.filter((section) => section.retailer_id === nextFilters.retailerId) : loaded);
      setSnapshotDate(data.snapshot_date);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể tải ưu đãi.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadOverview(appliedFilters); }, [appliedFilters, loadOverview]);
  useEffect(() => {
    const query = filters.query.trim();
    if (query.length < 2) {
      setAutocomplete([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const response = await fetch(API + "/api/deals/autocomplete?q=" + encodeURIComponent(query), { signal: controller.signal });
        if (response.ok) {
          const data = await response.json() as { items?: AutocompleteItem[] };
          setAutocomplete(data.items || []);
        }
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) setAutocomplete([]);
      }
    }, 220);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [filters.query]);
  useEffect(() => {
    let active = true;
    const stored = getBasket();
    setBasket(stored);
    const missingSources = stored.filter((item) => !item.source_url);
    if (missingSources.length) {
      void Promise.all(missingSources.map(async (item) => {
        try {
          const response = await fetch(API + "/api/deals/" + encodeURIComponent(item.price_snapshot_id) + "/insights");
          if (!response.ok) return item;
          const data = await response.json() as { offer?: Offer };
          return { ...item, source_url: data.offer?.source_url, image_url: item.image_url || data.offer?.image_url };
        } catch {
          return item;
        }
      })).then((hydrated) => {
        if (!active) return;
        const byId = new Map(hydrated.map((item) => [item.price_snapshot_id, item]));
        persistBasket(getBasket().map((item) => byId.get(item.price_snapshot_id) || item));
      });
    }
    const unsubscribe = subscribeBasket(setBasket);
    return () => { active = false; unsubscribe(); };
  }, []);

  const basketCount = useMemo(() => basket.reduce((total, item) => total + item.quantity, 0), [basket]);
  const basketTotal = useMemo(() => basket.reduce((total, item) => total + Number(item.current_price || 0) * item.quantity, 0), [basket]);
  const basketIds = useMemo(() => new Set(basket.map((item) => item.price_snapshot_id)), [basket]);

  const applyFilters = (next: DealFilters, quick: QuickFilter = "all") => {
    setFilters(next);
    setAppliedFilters(next);
    setQuickFilter(quick);
  };
  const editFilters = (patch: Partial<DealFilters>) => {
    setQuickFilter("all");
    setFilters((current) => ({ ...current, ...patch }));
  };
  const search = (event: FormEvent) => {
    event.preventDefault();
    applyFilters({ ...filters, query: filters.query.trim() }, "all");
  };
  const applyAdvanced = (event: FormEvent) => {
    event.preventDefault();
    applyFilters(filters, "all");
    setAdvancedOpen(false);
  };
  const applyQuickFilter = (kind: QuickFilter) => {
    if (kind === "all") {
      applyFilters({ ...DEFAULT_FILTERS, query: filters.query }, "all");
      return;
    }
    if (kind === "discount") {
      applyFilters({ ...filters, sort: "discount", minDiscount: "30", unitPriceOnly: false }, "discount");
      return;
    }
    if (kind === "budget") {
      applyFilters({ ...filters, sort: "price", maxPrice: "100000", unitPriceOnly: false }, "budget");
      return;
    }
    applyFilters({ ...filters, sort: "unit_price", unitPriceOnly: true }, "unit");
  };
  const showMore = async (retailerId: string) => {
    const section = sections.find((item) => item.retailer_id === retailerId);
    if (!section) return;
    const params = requestParams(appliedFilters, {
      retailer_id: retailerId,
      page: String(Math.floor(section.items.length / 15) + 1),
      page_size: "15",
    });
    const response = await fetch(API + "/api/deals?" + params.toString());
    if (!response.ok) return;
    const data = await response.json() as { items?: Offer[]; has_more?: boolean };
    setSections((current) => current.map((item) => item.retailer_id === retailerId
      ? { ...item, items: [...item.items, ...(data.items || [])], has_more: Boolean(data.has_more) }
      : item));
  };
  const quantityFor = (offer: Offer) => addQuantities[offer.price_snapshot_id] || 1;
  const setOfferQuantity = (offer: Offer, quantity: number) => setAddQuantities((current) => ({ ...current, [offer.price_snapshot_id]: quantity }));
  const addOfferToBasket = (offer: Offer, quantity = quantityFor(offer)) => {
    addBasketItem(offer, quantity);
    setRecentlyAddedId(offer.price_snapshot_id);
    if (basketFeedbackTimer.current) window.clearTimeout(basketFeedbackTimer.current);
    basketFeedbackTimer.current = window.setTimeout(() => {
      setRecentlyAddedId((current) => current === offer.price_snapshot_id ? "" : current);
    }, 2200);
  };
  const openInsight = async (offer: Offer) => {
    setDetailOffer(offer);
    setInsight(null);
    setInsightError("");
    setInsightLoading(true);
    try {
      const response = await fetch(API + "/api/deals/" + encodeURIComponent(offer.price_snapshot_id) + "/insights");
      if (!response.ok) throw new Error("Chưa thể tải thông tin so sánh cho sản phẩm này.");
      setInsight(await response.json() as InsightResponse);
    } catch (err) {
      setInsightError(err instanceof Error ? err.message : "Chưa thể tải thông tin so sánh.");
    } finally {
      setInsightLoading(false);
    }
  };
  const optimizeBasket = async () => {
    if (!basket.length) return;
    setBasketOptimizing(true);
    setBasketError("");
    try {
      const response = await fetch(API + "/api/basket/optimize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: basket.map((item) => ({ price_snapshot_id: item.price_snapshot_id, quantity: item.quantity })) }),
      });
      if (!response.ok) throw new Error("Chưa thể tối ưu giỏ hàng lúc này.");
      setBasketOptimization(await response.json() as BasketOptimization);
    } catch (err) {
      setBasketError(err instanceof Error ? err.message : "Chưa thể tối ưu giỏ hàng.");
    } finally {
      setBasketOptimizing(false);
    }
  };
  const sync = async () => {
    setSyncing(true);
    setSyncMessage("Đang khởi tạo cập nhật…");
    try {
      const start = await fetch(API + "/api/admin/sync", { method: "POST" });
      const run = await start.json() as { id?: string; detail?: string };
      if (!start.ok || !run.id) throw new Error(run.detail || "Không thể bắt đầu cập nhật.");
      while (true) {
        const statusResponse = await fetch(API + "/api/admin/sync/" + run.id);
        const status = await statusResponse.json() as { status?: string; detail?: string; details?: { progress?: { message?: string; total?: number; percent?: number; completed?: number } } };
        if (!statusResponse.ok) throw new Error(status.detail || "Không thể đọc tiến trình.");
        const progress = status.details?.progress;
        if (progress?.message) setSyncMessage(progress.total ? progress.message + " · " + progress.percent + "% (" + progress.completed + "/" + progress.total + ")" : progress.message);
        if (status.status !== "running") {
          if (status.status !== "success") throw new Error("Cập nhật dữ liệu không thành công.");
          setSyncMessage("Đã cập nhật dữ liệu mới nhất.");
          await loadOverview(appliedFilters);
          break;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1200));
      }
    } catch (err) {
      setSyncMessage(err instanceof Error ? err.message : "Không thể cập nhật dữ liệu.");
    } finally {
      setSyncing(false);
      window.setTimeout(() => setSyncMessage(""), 5000);
    }
  };

  const sameProductOffers = insight?.same_product_offers || [];
  const similarOffers = insight?.similar_offers || [];
  const summary = insight?.summary;
  const splitPlan = basketOptimization?.split_order;
  const splitRetailer = splitPlan?.retailer_count === 1 ? splitPlan.lines?.[0]?.retailer_id : undefined;
  const visibleSingleStoreOptions = (basketOptimization?.single_retailer_options || []).filter((plan) => {
    if (Number(plan.savings_vs_selected || 0) < 0) return false;
    return !(splitPlan && splitRetailer === plan.retailer_id && Number(splitPlan.total) === Number(plan.total));
  });

  return <main className="deals-page">
    <header className="deals-header market-toolbar">
      <a className="brand-logo" href="/deals" aria-label="PriceLy"><img src="/brand/pricely-logo.png" alt="PriceLy - So sánh giá bách hóa và siêu thị" /></a>
      <form className="toolbar-search" onSubmit={search}>
        <span aria-hidden="true">⌕</span>
        <input list="deal-autocomplete" value={filters.query} onChange={(event) => editFilters({ query: event.target.value })} placeholder="Tìm sản phẩm, thương hiệu, ưu đãi..." aria-label="Tìm ưu đãi" />
        <datalist id="deal-autocomplete">
          {autocomplete.map((item, index) => <option value={item.product_name || item.brand || ""} key={(item.product_name || item.brand || "") + index}>{item.brand || retailerName(item.retailer_id)}</option>)}
        </datalist>
        <button type="submit">Tìm kiếm</button>
      </form>
      <div className="deals-header-actions">
        <button className="header-basket" type="button" onClick={() => setBasketOpen(true)} aria-label={"Mở giỏ hàng, " + basketCount + " sản phẩm"}>
          <span aria-hidden="true">🛒</span><em>Giỏ hàng</em><b>{basketCount}</b>
        </button>
        <button className="sync-deals" type="button" onClick={() => void sync()} disabled={syncing}>{syncing ? "Đang cập nhật…" : "↻ Cập nhật dữ liệu"}</button>
      </div>
    </header>

    <nav className="market-subbar smart-filter-bar" aria-label="Bộ lọc ưu đãi">
      <span className="market-label">Khám phá ưu đãi</span>
      <div className="quick-filter-list">
        <button className={quickFilter === "all" ? "active" : ""} type="button" onClick={() => applyQuickFilter("all")}>Tất cả</button>
        <button className={quickFilter === "discount" ? "active" : ""} type="button" onClick={() => applyQuickFilter("discount")}>Giảm sâu</button>
        <button className={quickFilter === "budget" ? "active" : ""} type="button" onClick={() => applyQuickFilter("budget")}>Dưới 100.000đ</button>
        <button className={quickFilter === "unit" ? "active" : ""} type="button" onClick={() => applyQuickFilter("unit")}>Giá theo kg/lít/cái</button>
      </div>
      <select value={filters.sort} onChange={(event) => applyFilters({ ...filters, sort: event.target.value }, "all")} aria-label="Sắp xếp ưu đãi">
        <option value="featured">Ưu đãi nổi bật</option>
        <option value="discount">Giảm nhiều nhất</option>
        <option value="price">Giá thấp nhất</option>
        <option value="unit_price">Giá theo đơn vị tốt nhất</option>
        <option value="newest">Mới cập nhật</option>
      </select>
      <button className={"advanced-filter-toggle" + (advancedOpen ? " active" : "")} type="button" onClick={() => setAdvancedOpen((open) => !open)}>Bộ lọc</button>
      {snapshotDate && <small>Ngày cập nhật {new Date(snapshotDate + "T00:00:00").toLocaleDateString("vi-VN")}</small>}
    </nav>

    <section className="deals-content" aria-live="polite">
      {advancedOpen && <form className="advanced-deal-filters" onSubmit={applyAdvanced}>
        <label>Sàn
          <select value={filters.retailerId} onChange={(event) => editFilters({ retailerId: event.target.value })}>
            <option value="">Tất cả sàn</option>
            {Object.entries(RETAILERS).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        </label>
        <label>Thương hiệu<input value={filters.brand} onChange={(event) => editFilters({ brand: event.target.value })} placeholder="Ví dụ: Vinamilk" /></label>
        <label>Giá từ<input type="number" min="0" value={filters.minPrice} onChange={(event) => editFilters({ minPrice: event.target.value })} placeholder="0đ" /></label>
        <label>Đến<input type="number" min="0" value={filters.maxPrice} onChange={(event) => editFilters({ maxPrice: event.target.value })} placeholder="Không giới hạn" /></label>
        <label>Giảm tối thiểu (%)<input type="number" min="0" max="100" value={filters.minDiscount} onChange={(event) => editFilters({ minDiscount: event.target.value })} placeholder="Ví dụ: 20" /></label>
        <label>Đơn vị so sánh
          <select value={filters.comparisonUnit} onChange={(event) => editFilters({ comparisonUnit: event.target.value })}>
            <option value="">Tất cả đơn vị</option>
            <option value="g">Theo gram</option>
            <option value="ml">Theo ml</option>
            <option value="each">Theo cái</option>
            <option value="cm2">Theo cm²</option>
          </select>
        </label>
        <label>Khuyến mãi
          <select value={filters.promotionType} onChange={(event) => editFilters({ promotionType: event.target.value })}>
            <option value="all">Tất cả khuyến mãi</option>
            <option value="discount">Giảm giá trực tiếp</option>
            <option value="mechanic">Ưu đãi theo cơ chế</option>
            <option value="flag">Có cờ khuyến mãi</option>
          </select>
        </label>
        <label>Chất lượng dữ liệu
          <select value={filters.qualityStatus} onChange={(event) => editFilters({ qualityStatus: event.target.value })}>
            <option value="">Tất cả dữ liệu</option>
            <option value="valid">Đã kiểm tra</option>
            <option value="warning">Cần kiểm tra lại</option>
          </select>
        </label>
        <label className="unit-only-filter"><input type="checkbox" checked={filters.unitPriceOnly} onChange={(event) => editFilters({ unitPriceOnly: event.target.checked })} /> Chỉ hiện sản phẩm có giá quy đổi</label>
        <div className="advanced-filter-actions">
          <button type="button" onClick={() => applyQuickFilter("all")}>Đặt lại</button>
          <button type="submit">Áp dụng</button>
        </div>
      </form>}

      {loading && <p className="deals-state">Đang tải ưu đãi mới nhất…</p>}
      {error && <p className="deals-state error">{error}</p>}
      {!loading && !error && sections.map((section) => <section className={["retailer-deals", "retailer-" + section.retailer_id].join(" ")} key={section.retailer_id}>
        <div className="retailer-deals-head">
          <div><h2>{retailerName(section.retailer_id)}</h2><p>{section.total.toLocaleString("vi-VN")} sản phẩm có khuyến mãi</p></div>
          {section.has_more && <button className="retailer-view-all" type="button" onClick={() => void showMore(section.retailer_id)}>Xem tất cả <span aria-hidden="true">→</span></button>}
        </div>
        <BannerSlider retailerId={section.retailer_id} />
        {section.items.length ? <div className="deal-grid">{section.items.map((offer) => {
          const unit = unitPrice(offer);
          const alreadyAdded = basketIds.has(offer.price_snapshot_id);
          const justAdded = recentlyAddedId === offer.price_snapshot_id;
          return <article className="deal-card" key={offer.price_snapshot_id}>
            <button className="deal-image deal-image-button" type="button" onClick={() => void openInsight(offer)} aria-label={"Xem chi tiết " + offer.product_name}>
              {Number(offer.discount_percent || 0) > 0 && <span className="deal-discount-corner">-{Math.round(Number(offer.discount_percent))}%</span>}
              {offer.image_url ? <img src={offer.image_url} alt="" /> : <span>Ưu đãi</span>}
            </button>
            <div className="deal-card-body">
              <span className="deal-promotion">{promotionLabel(offer)}</span>
              <h3>{offer.product_name}</h3>
              <p className="deal-brand">{offer.brand || " "}</p>
              <div className="deal-price"><strong>{money(offer.current_price)}</strong>{offer.listed_price && Number(offer.listed_price) > Number(offer.current_price) ? <del>{money(offer.listed_price)}</del> : null}</div>
              <p className="deal-unit-price">{unit || "Không có giá quy đổi"}</p>
              {qualityWarning(offer) && <p className="deal-quality-warning">Thông tin cần kiểm tra lại</p>}
              <p className="deal-terms" title={offer.promotion_text}>{promotionTerms(offer)}</p>
              <div className="add-quantity-line"><span>Số lượng</span><QuantityPicker value={quantityFor(offer)} onChange={(quantity) => setOfferQuantity(offer, quantity)} compact /></div>
              <div className="deal-card-controls">
                <button className={"deal-add-basket" + (alreadyAdded ? " added" : "") + (justAdded ? " just-added" : "")} type="button" onClick={() => addOfferToBasket(offer)}>{justAdded ? "✓ Đã thêm" : "＋ Thêm giỏ hàng"}</button>
                {offer.source_url && <a className="deal-buy-source" href={offer.source_url} target="_blank" rel="noreferrer">Mua tại sàn ↗</a>}
              </div>
            </div>
          </article>;
        })}</div> : <p className="deals-empty">Chưa có sản phẩm phù hợp tại sàn này.</p>}
        {section.has_more && <button className="load-more" type="button" onClick={() => void showMore(section.retailer_id)}>Xem thêm ưu đãi của {retailerName(section.retailer_id)}</button>}
      </section>)}
    </section>

    {syncMessage && <div className="sync-toast" role="status">{syncMessage}</div>}
    {assistantHint && <div className="assistant-hint"><span>Hỏi trợ lý AI</span><button type="button" aria-label="Ẩn gợi ý trợ lý" onClick={() => setAssistantHint(false)}>×</button></div>}
    <button className="assistant-fab" type="button" onClick={() => setChatOpen(true)} aria-label="Mở AI Assistant"><img src="/brand/pricely-mascot.png" alt="" /></button>

    {detailOffer && <div className="commerce-drawer-backdrop" role="presentation" onMouseDown={() => setDetailOffer(null)}>
      <aside className="deal-insight-drawer" role="dialog" aria-modal="true" aria-label="Chi tiết và so sánh sản phẩm" onMouseDown={(event) => event.stopPropagation()}>
        <header><div><span>Chi tiết ưu đãi</span><h2>{detailOffer.product_name}</h2></div><button type="button" onClick={() => setDetailOffer(null)} aria-label="Đóng">×</button></header>
        <div className="insight-product-summary">
          <div className="insight-image">{detailOffer.image_url ? <img src={detailOffer.image_url} alt="" /> : <span>Ưu đãi</span>}</div>
          <div>
            <p>{detailOffer.brand || retailerName(detailOffer.retailer_id)}</p>
            <strong>{money(detailOffer.current_price)}</strong>
            {detailOffer.listed_price && Number(detailOffer.listed_price) > Number(detailOffer.current_price) && <del>{money(detailOffer.listed_price)}</del>}
            {unitPrice(detailOffer) && <small>{unitPrice(detailOffer)}</small>}
            <span>{promotionTerms(detailOffer)}</span>
            <dl className="insight-facts">
              <div><dt>Cập nhật</dt><dd>{detailOffer.snapshot_date ? new Date(detailOffer.snapshot_date + "T00:00:00").toLocaleDateString("vi-VN") : "Theo snapshot hiện tại"}</dd></div>
              <div><dt>Dữ liệu</dt><dd className={qualityWarning(detailOffer) ? "warning" : ""}>{qualityWarning(detailOffer) ? "Cần kiểm tra lại" : "Đã đồng bộ từ sàn"}</dd></div>
            </dl>
          </div>
        </div>
        <div className="add-quantity-line drawer-quantity"><span>Số lượng</span><QuantityPicker value={quantityFor(detailOffer)} onChange={(quantity) => setOfferQuantity(detailOffer, quantity)} /></div>
        <div className="insight-primary-actions">
          <button className={recentlyAddedId === detailOffer.price_snapshot_id ? "basket-confirm-button" : ""} type="button" onClick={() => addOfferToBasket(detailOffer)}>
            {recentlyAddedId === detailOffer.price_snapshot_id ? `✓ Đã thêm ${quantityFor(detailOffer)} vào giỏ hàng` : "Thêm vào giỏ hàng"}
          </button>
          {detailOffer.source_url && <a href={detailOffer.source_url} target="_blank" rel="noreferrer">Mua tại sàn ↗</a>}
        </div>
        {insightLoading && <p className="drawer-state">Đang tìm sản phẩm có thể so sánh…</p>}
        {insightError && <p className="drawer-state error">{insightError}</p>}
        {!insightLoading && !insightError && insight && <>
          <section className="insight-summary">
            <span>Cùng sản phẩm đã xác minh</span>
            <b>{summary?.retailer_count || sameProductOffers.length} sàn có thể so sánh</b>
            {summary?.lowest_price != null && <p>Giá từ <strong>{money(summary.lowest_price)}</strong>{summary?.price_spread != null && " · chênh " + money(summary.price_spread)}</p>}
            {summary?.data_quality_warning && <small>⚠ Một số thông tin giá cần được kiểm tra lại trước khi mua.</small>}
          </section>
          <section className="insight-results">
            <h3>Cùng sản phẩm đã xác minh</h3>
            {sameProductOffers.length ? sameProductOffers.map((offer) => <div className="insight-offer-row" key={offer.price_snapshot_id}>
              <div><b>{retailerName(offer.retailer_id)}</b><span>{offer.product_name}</span>{unitPrice(offer) && <small>{unitPrice(offer)}</small>}</div>
              <div><strong>{money(offer.current_price)}</strong><QuantityPicker value={quantityFor(offer)} onChange={(quantity) => setOfferQuantity(offer, quantity)} compact /><button className={recentlyAddedId === offer.price_snapshot_id ? "row-add-confirmed" : ""} type="button" onClick={() => addOfferToBasket(offer)}>{recentlyAddedId === offer.price_snapshot_id ? "✓ Đã thêm" : "Thêm"}</button></div>
            </div>) : <p>Chưa có cùng sản phẩm đã được map ở sàn khác.</p>}
          </section>
          <section className="insight-results similar-results">
            <h3>Lựa chọn tương tự giá thấp hơn</h3>
            <p className="match-explainer">Các sản phẩm này tương tự về nhu cầu; không phải cùng sản phẩm.</p>
            {similarOffers.length ? similarOffers.map((offer) => <div className="insight-offer-row" key={offer.price_snapshot_id}>
              <div><b>{retailerName(offer.retailer_id)}</b><span>{offer.product_name}</span>{unitPrice(offer) && <small>{unitPrice(offer)}</small>}</div>
              <div><strong>{money(offer.current_price)}</strong><QuantityPicker value={quantityFor(offer)} onChange={(quantity) => setOfferQuantity(offer, quantity)} compact /><button className={recentlyAddedId === offer.price_snapshot_id ? "row-add-confirmed" : ""} type="button" onClick={() => addOfferToBasket(offer)}>{recentlyAddedId === offer.price_snapshot_id ? "✓ Đã thêm" : "Thêm"}</button></div>
            </div>) : <p>Chưa có lựa chọn tương tự phù hợp hơn.</p>}
          </section>
        </>}
      </aside>
    </div>}

    {basketOpen && <div className="commerce-drawer-backdrop" role="presentation" onMouseDown={() => setBasketOpen(false)}>
      <aside className="basket-drawer" role="dialog" aria-modal="true" aria-label="Giỏ hàng" onMouseDown={(event) => event.stopPropagation()}>
        <header><div><span>Giỏ hàng</span><h2>{basketCount ? basketCount + " sản phẩm" : "Chưa có sản phẩm"}</h2></div><button type="button" onClick={() => setBasketOpen(false)} aria-label="Đóng">×</button></header>
        {!basket.length ? <div className="basket-empty"><b>Chưa có sản phẩm nào</b><p>Thêm sản phẩm từ các ưu đãi để PriceLy giúp bạn chọn cách mua tiết kiệm hơn.</p></div> : <>
          <ul className="basket-lines">{basket.map((item) => <li key={item.price_snapshot_id}>
            <div className="basket-line-image">{item.image_url && <img src={item.image_url} alt="" />}</div>
            <div className="basket-line-copy"><b>{item.product_name}</b><span>{retailerName(item.retailer_id)}</span><strong>{money(item.current_price)}</strong>{item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer">Mua tại sàn ↗</a>}</div>
            <div className="basket-quantity"><button type="button" onClick={() => updateBasketQuantity(item.price_snapshot_id, item.quantity - 1)} aria-label="Giảm số lượng">−</button><span>{item.quantity}</span><button type="button" onClick={() => updateBasketQuantity(item.price_snapshot_id, item.quantity + 1)} aria-label="Tăng số lượng">+</button></div>
            <button className="basket-remove" type="button" onClick={() => removeBasketItem(item.price_snapshot_id)} aria-label={"Xóa " + item.product_name}>×</button>
          </li>)}</ul>
          <div className="basket-total"><span>Tạm tính lựa chọn hiện tại</span><strong>{money(basketTotal)}</strong></div>
          <div className="basket-drawer-actions"><button type="button" onClick={() => clearBasket()}>Xóa tất cả</button><button type="button" onClick={() => void optimizeBasket()} disabled={basketOptimizing}>{basketOptimizing ? "Đang tối ưu…" : "Tối ưu giỏ hàng"}</button></div>
          {basketError && <p className="drawer-state error">{basketError}</p>}
          {basketOptimization && <div className="basket-optimization">
            <h3>{Number(splitPlan?.savings_vs_selected || 0) > 0 ? "Gợi ý mua tiết kiệm" : "Kết quả tối ưu"}</h3>
            {splitPlan && <PlanCard plan={splitPlan} title={Number(splitPlan.savings_vs_selected || 0) > 0 ? "Phương án chia đơn rẻ nhất" : "Lựa chọn hiện tại đã có giá thấp nhất"} />}
            {visibleSingleStoreOptions.map((plan, index) => <PlanCard plan={plan} title="Mua tại một sàn" key={plan.retailer_id || index} />)}
            {(basketOptimization.unavailable_items || []).length > 0 && <p className="unavailable-items">Một số món chưa có so sánh đủ tin cậy nên giữ nguyên lựa chọn hiện tại.</p>}
          </div>}
        </>}
      </aside>
    </div>}

    <div className={"assistant-panel" + (chatOpen ? "" : " assistant-panel-hidden")} role="dialog" aria-modal={chatOpen} aria-hidden={!chatOpen} aria-label="Chatbot so sánh giá">
       <div className="assistant-panel-head"><div><b>Trợ lý mua sắm AI</b><span>So sánh giá và tìm ưu đãi phù hợp</span></div><div className="assistant-panel-actions"><button type="button" onClick={() => setChatResetKey((key) => key + 1)}>＋ Chat mới</button><button className="assistant-basket" type="button" onClick={() => setBasketOpen(true)}>🛒 Giỏ hàng <b>{basketCount}</b></button><button type="button" onClick={() => setChatOpen(false)} aria-label="Quay lại trang ưu đãi">← Quay lại ưu đãi</button></div></div>
       <ChatPanel resetKey={chatResetKey} onOpenBasket={(optimize) => { setBasketOpen(true); if (optimize) window.setTimeout(() => void optimizeBasket(), 0); }} />
    </div>
  </main>;
}
