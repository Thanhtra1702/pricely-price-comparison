"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { addBasketItem } from "./basket";
import type { BasketProduct } from "./basket";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Offer = {
  price_snapshot_id: string;
  product_name: string;
  brand?: string;
  retailer_id: string;
  store_code: string;
  current_price: number;
  listed_price?: number;
  discount_percent?: number;
  effective_unit_price?: number;
  comparison_unit?: string;
  observed_at?: string;
  snapshot_date?: string;
  promotion_text?: string;
  source_url?: string;
  image_url?: string;
  unit_price_publishable?: boolean;
  silver_data_quality_status?: string;
  match_confidence?: number;
};

type ResultPayload = {
  offers?: Offer[];
  near_matches?: Offer[];
  retailer_count?: number;
  basket_action?: "add" | "view" | "optimize";
  suggested_price_snapshot_id?: string;
  requires_client_basket?: boolean;
};

type Message = { role: "user" | "assistant"; content: string; payload?: ResultPayload };

type ChatPanelProps = {
  resetKey: number;
  onOpenBasket: (optimize: boolean) => void;
};

const money = (value?: number) => value == null ? "—" : new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 }).format(value) + "₫";
const retailer = (id: string) => ({ bachhoaxanh: "Bách Hóa Xanh", go: "GO!", lottemart: "Lotte Mart", mmvietnam: "MM Mega Market", winmart: "WinMart" }[id] || id);

function basketProduct(offer: Offer): BasketProduct {
  return {
    price_snapshot_id: offer.price_snapshot_id,
    product_name: offer.product_name,
    retailer_id: offer.retailer_id,
    current_price: offer.current_price,
    image_url: offer.image_url,
    source_url: offer.source_url,
    brand: offer.brand,
    effective_unit_price: offer.effective_unit_price,
    comparison_unit: offer.comparison_unit,
  };
}

function ChatQuantityAdd({ offer, compact = false }: { offer: Offer; compact?: boolean }) {
  const [quantity, setQuantity] = useState(1);
  const [confirmed, setConfirmed] = useState(false);
  const timer = useRef<number | null>(null);
  const update = (next: number) => setQuantity(Math.max(1, Math.min(99, next)));
  const add = () => {
    addBasketItem(basketProduct(offer), quantity);
    setConfirmed(true);
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setConfirmed(false), 1800);
  };
  return <div className={`chat-quantity-add${compact ? " compact" : ""}`}>
    <div className="add-quantity-picker compact" aria-label="Chọn số lượng">
      <button type="button" onClick={() => update(quantity - 1)} disabled={quantity <= 1} aria-label="Giảm số lượng">−</button>
      <input type="number" min="1" max="99" value={quantity} onChange={(event) => update(Number(event.target.value) || 1)} aria-label="Số lượng sản phẩm" />
      <button type="button" onClick={() => update(quantity + 1)} disabled={quantity >= 99} aria-label="Tăng số lượng">+</button>
    </div>
    <button className={`chat-add-basket${compact ? " table-add" : ""}${confirmed ? " confirmed" : ""}`} type="button" onClick={add}>{confirmed ? `✓ Đã thêm ${quantity}` : compact ? "+ Thêm" : "+ Giỏ hàng"}</button>
  </div>;
}

function Mark({ name, size = 20, ...rest }: { name: "search" | "send" | "user" | "grid" | "table"; size?: number; [key: string]: any }) {
  const paths = {
    search: <><circle cx="11" cy="11" r="6"/><path d="m16 16 4 4"/></>,
    send: <><path d="m21 3-8.7 18-2.2-7.1L3 11.7 21 3Z"/><path d="m10.2 13.8 4.3-4.3"/></>,
    user: <><circle cx="12" cy="8" r="3.5"/><path d="M4.5 21a7.5 7.5 0 0 1 15 0"/></>,
    grid: <><rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/></>,
    table: <path d="M3 3h18v18H3zM21 9H3M21 15H3M12 3v18"/>,
  };
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...rest}>{paths[name]}</svg>;
}

function OfferCards({ offers = [], title, subtle = false }: { offers?: Offer[]; title?: string; subtle?: boolean }) {
  const [localViewMode, setLocalViewMode] = useState<"grid" | "table">("grid");
  if (!offers.length) return null;

  const minPrice = Math.min(...offers.map((offer) => Number(offer.current_price)));
  const getRetailerClass = (id: string) => ["bachhoaxanh", "go", "lottemart", "mmvietnam", "winmart"].includes(id) ? id : "generic";

  return <section className={`offers ${subtle ? "subtle" : ""}`}>
    <div className="offers-head">
      <div className="offers-head-left"><span>{title || "Kết quả phù hợp"}</span></div>
      <div className="offers-head-right">
        <b>{offers.length} sản phẩm</b>
        <div className="view-toggle">
          <button type="button" className={`view-toggle-btn ${localViewMode === "grid" ? "active" : ""}`} onClick={() => setLocalViewMode("grid")} title="Hiển thị dạng lưới"><Mark name="grid" size={14} /></button>
          <button type="button" className={`view-toggle-btn ${localViewMode === "table" ? "active" : ""}`} onClick={() => setLocalViewMode("table")} title="Hiển thị dạng bảng"><Mark name="table" size={14} /></button>
        </div>
      </div>
    </div>
    {localViewMode === "grid" ? <div className="offers-grid">
      {offers.map((offer) => {
        const isBestPrice = Number(offer.current_price) === minPrice;
        return <article className={`offer-card ${isBestPrice ? "best-price" : ""}`} key={offer.price_snapshot_id}>
          <div className="offer-top"><span className={`retailer-pill ${getRetailerClass(offer.retailer_id)}`}>{retailer(offer.retailer_id)}</span>{isBestPrice ? <span className="best-price-badge">⭐ Giá tốt nhất</span> : offer.discount_percent ? <span className="discount">-{Number(offer.discount_percent).toFixed(0)}%</span> : null}</div>
          <h3>{offer.product_name}</h3>
          {offer.brand ? <p className="brand-name">{offer.brand}</p> : <p className="brand-name">&nbsp;</p>}
          <div className="price-row"><strong>{money(Number(offer.current_price))}</strong>{offer.listed_price ? <del>{money(Number(offer.listed_price))}</del> : null}</div>
          <div className="offer-meta"><span>{offer.store_code === "unknown_store" ? "Cửa hàng chưa xác định" : `Cửa hàng ${offer.store_code}`}</span>{offer.effective_unit_price ? <span>{money(Number(offer.effective_unit_price))}/{offer.comparison_unit || "đv"}</span> : null}</div>
          {offer.promotion_text ? <p className="promotion-text" title={offer.promotion_text}>🎁 {offer.promotion_text}</p> : null}
          <footer><span>{offer.match_confidence != null ? `Độ khớp ${Math.round(offer.match_confidence * 100)}%` : offer.snapshot_date || (offer.observed_at ? `Cập nhật ${new Date(offer.observed_at).toLocaleDateString("vi-VN")}` : "Dữ liệu mới nhất")}</span>{offer.source_url ? <a href={offer.source_url} target="_blank" rel="noreferrer">Xem nguồn</a> : null}</footer>
          <ChatQuantityAdd offer={offer} />
        </article>;
      })}
    </div> : <div className="offers-table-wrap"><table className="offers-table"><thead><tr><th>Sản phẩm</th><th>Siêu thị</th><th>Giá hiện tại</th><th>Giá niêm yết</th><th>Quy đổi</th><th>Cập nhật</th></tr></thead><tbody>
      {offers.map((offer) => {
        const isBestPrice = Number(offer.current_price) === minPrice;
        return <tr className={isBestPrice ? "best-price" : ""} key={offer.price_snapshot_id}>
          <td><div className="table-product-cell"><span className="table-product-title">{offer.product_name}</span>{offer.brand && <span className="table-product-brand">{offer.brand}</span>}</div></td>
          <td><span className={`retailer-pill ${getRetailerClass(offer.retailer_id)}`}>{retailer(offer.retailer_id)}</span></td>
          <td><div style={{ display: "flex", alignItems: "center", gap: "8px" }}><span className="table-price-current">{money(Number(offer.current_price))}</span>{isBestPrice && <span className="best-price-badge" style={{ padding: "2px 4px", fontSize: "9px" }}>⭐ Tốt nhất</span>}</div></td>
          <td>{offer.listed_price ? <div><span className="table-price-original">{money(Number(offer.listed_price))}</span>{offer.discount_percent ? <span className="discount" style={{ padding: "2px 4px", fontSize: "9px", marginLeft: "4px" }}>-{Number(offer.discount_percent).toFixed(0)}%</span> : null}</div> : "—"}</td>
          <td>{offer.effective_unit_price ? <span>{money(Number(offer.effective_unit_price))}/{offer.comparison_unit || "đv"}</span> : "—"}</td>
          <td><span style={{ fontSize: "11px", color: "var(--text-muted)" }}>{offer.snapshot_date || (offer.observed_at ? new Date(offer.observed_at).toLocaleDateString("vi-VN") : "Mới nhất")}</span><ChatQuantityAdd offer={offer} compact /></td>
        </tr>;
      })}
    </tbody></table></div>}
  </section>;
}

export default function ChatPanel({ resetKey, onOpenBasket }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([{ role: "assistant", content: "Chào bạn! Tôi sẽ tìm ưu đãi phù hợp và so sánh giá giữa các siêu thị cho bạn." }]);
  const [conversationId, setConversationId] = useState<string>();
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const previousResetKey = useRef(resetKey);

  const startNew = useCallback(() => {
    setConversationId(undefined);
    setInput("");
    setMessages([{ role: "assistant", content: "Bạn đang muốn tìm giá tốt hay xem ưu đãi sản phẩm nào?" }]);
  }, []);

  useEffect(() => {
    if (previousResetKey.current === resetKey) return;
    previousResetKey.current = resetKey;
    startNew();
  }, [resetKey, startNew]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  async function send(event: FormEvent) {
    event.preventDefault();
    const message = input.trim();
    if (!message || loading) return;
    setInput("");
    setMessages((items) => [...items, { role: "user", content: message }]);
    setLoading(true);
    try {
      const response = await fetch(`${API}/api/chat/stream`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, conversation_id: conversationId }) });
      if (!response.body) throw new Error("Không nhận được phản hồi");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let answer = "";
      let payload: ResultPayload | undefined;
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() || "";
        for (const block of blocks) {
          const dataLine = block.split("\n").find((line) => line.startsWith("data: "));
          const eventLine = block.split("\n").find((line) => line.startsWith("event: "));
          if (!dataLine) continue;
          const data = JSON.parse(dataLine.slice(6));
          const kind = eventLine?.slice(7);
          if (kind === "conversation") setConversationId(data.conversation_id);
          if (kind === "answer") answer = data.content;
          if (kind === "results") payload = data;
        }
      }
      if (payload?.requires_client_basket) {
        if (payload.basket_action === "add" && payload.suggested_price_snapshot_id) {
          const previousOffers = messages.flatMap((item) => [...(item.payload?.offers || []), ...(item.payload?.near_matches || [])]);
          const suggested = previousOffers.find((offer) => offer.price_snapshot_id === payload?.suggested_price_snapshot_id);
          if (suggested) addBasketItem(basketProduct(suggested));
        } else if (payload.basket_action === "view" || payload.basket_action === "optimize") {
          onOpenBasket(payload.basket_action === "optimize");
        }
      }
      setMessages((items) => [...items, { role: "assistant", content: answer || "Chưa tìm thấy kết quả phù hợp.", payload }]);
    } catch (error) {
      setMessages((items) => [...items, { role: "assistant", content: `Không thể kết nối trợ lý: ${error instanceof Error ? error.message : "lỗi không xác định"}` }]);
    } finally {
      setLoading(false);
    }
  }

  const isChatEmpty = messages.length <= 1;
  const renderComposer = (isCentered = false) => <form className={`composer ${isCentered ? "centered" : ""}`} onSubmit={send}>
    <div className="composer-icon"><Mark name="search" size={19}/></div>
    <input value={input} onChange={(event) => setInput(event.target.value)} placeholder="Nhập tên sản phẩm cần tìm giá tốt nhất..." disabled={loading} />
    <button type="submit" disabled={loading || !input.trim()} aria-label="Gửi câu hỏi"><Mark name="send" size={18}/></button>
  </form>;

  return <div className="assistant-panel-content">
    <main className="app-shell embedded-chat">
      <section className="workspace expanded">
        {isChatEmpty ? <div className="chat-area centered"><div className="welcome-container shopping-welcome"><div className="welcome-header shopping-welcome-header"><div className="welcome-mascot"><img src="/brand/pricely-mascot.png" alt="Mascot PriceLy" /></div><div className="welcome-copy"><span className="welcome-kicker">TRỢ LÝ MUA SẮM PRICE-LY</span><h1>Tìm đúng sản phẩm.<br/>Mua đúng giá.</h1><p>So sánh giá và ưu đãi giữa các siêu thị để chọn nơi mua phù hợp nhất.</p></div></div>{renderComposer(true)}<div className="chat-suggestions" aria-label="Câu hỏi gợi ý"><span>Thử hỏi:</span><button type="button" onClick={() => setInput("So sánh giá sữa Vinamilk 1L")}>So sánh sữa Vinamilk 1L</button><button type="button" onClick={() => setInput("Ưu đãi giảm trên 20%")}>Ưu đãi giảm trên 20%</button><button type="button" onClick={() => setInput("Dầu ăn dưới 100.000đ")}>Dầu ăn dưới 100.000đ</button></div></div></div> : <><div className="chat-area"><div className="messages">{messages.map((message, index) => <article className={`message ${message.role}`} key={index}><div className={`avatar ${message.role === "user" ? "user-avatar" : "assistant-avatar"}`}>{message.role === "user" ? <Mark name="user" size={19}/> : <img src="/brand/pricely-mascot.png" alt="Trợ lý PriceLy" />}</div><div className="message-content"><p>{message.content}</p>{message.payload?.retailer_count != null && <div className="coverage">Đã kiểm tra <b>{message.payload.retailer_count}</b> nhà bán lẻ phù hợp</div>}<OfferCards offers={message.payload?.offers}/><OfferCards title="Kết quả gần đúng · cần xác nhận quy cách" offers={message.payload?.near_matches} subtle/></div></article>)}{loading && <article className="message assistant"><div className="avatar assistant-avatar"><img src="/brand/pricely-mascot.png" alt="Trợ lý PriceLy" /></div><div className="thinking"><i></i><i></i><i></i><span>Đang tìm giá tốt nhất cho bạn...</span></div></article>}<div ref={end}/></div></div><div className="composer-wrap">{renderComposer(false)}</div></>}
      </section>
    </main>
  </div>;
}
