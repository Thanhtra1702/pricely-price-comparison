import json
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import text

from .database import engine
from .matching import normalize_text


def save_conversation(message: str, conversation_id: str | None = None) -> str:
    cid = conversation_id or str(uuid.uuid4())
    with engine.begin() as conn:
        if conversation_id is None:
            conn.execute(text("INSERT INTO conversations(id,title) VALUES (:id,:title)"), {"id": cid, "title": message[:80]})
        else:
            allowed = conn.execute(
                text("SELECT 1 FROM conversations WHERE id=:id"),
                {"id": cid},
            ).first()
            if not allowed:
                raise PermissionError("Không có quyền truy cập cuộc trò chuyện này")
        conn.execute(text("INSERT INTO messages(conversation_id,role,content) VALUES (:id,'user',:content)"), {"id": cid, "content": message})
        conn.execute(text("UPDATE conversations SET updated_at=now() WHERE id=:id"), {"id": cid})
    return cid


def save_assistant(conversation_id: str, content: str, payload: dict) -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO messages(conversation_id,role,content,payload) VALUES (:id,'assistant',:content,:payload)"), {"id": conversation_id, "content": content, "payload": __import__('json').dumps(payload, ensure_ascii=False, default=str)})


def conversation_context(conversation_id: str | None) -> dict:
    """Read the latest compact chat state from the existing assistant payload.

    A random UUID conversation id preserves follow-up context locally.
    """
    if not conversation_id:
        return {}
    try:
        uuid.UUID(str(conversation_id))
    except (TypeError, ValueError, AttributeError):
        return {}
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT payload
                FROM messages
                WHERE conversation_id=:id
                  AND role='assistant'
                  AND payload IS NOT NULL
                ORDER BY id DESC
                LIMIT 1
            """),
            {"id": conversation_id},
        ).first()
    if not row:
        return {}
    payload = row._mapping.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            return {}
    context = payload.get("context") if isinstance(payload, dict) else None
    return context if isinstance(context, dict) else {}


def recent_conversation_history(conversation_id: str | None, limit: int = 5) -> list[dict]:
    """Read the last N raw chat messages for LLM prompt context."""
    if not conversation_id:
        return []
    try:
        uuid.UUID(str(conversation_id))
    except (TypeError, ValueError, AttributeError):
        return []
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT role, content
                FROM messages
                WHERE conversation_id = :id
                ORDER BY id DESC
                LIMIT :limit
            """),
            {"id": conversation_id, "limit": limit},
        ).fetchall()
    return [{"role": row.role, "content": row.content} for row in reversed(rows)]


PROMOTION_FILTER = """(
    o.is_on_promotion OR o.is_price_discount OR o.has_promo_mechanic OR EXISTS (
        SELECT 1 FROM promotion_items_current pi
        WHERE pi.retailer_id = o.retailer_id
          AND (pi.retailer_product_key = o.retailer_product_key
            OR (pi.retailer_product_key IS NULL AND pi.retailer_product_id = o.retailer_product_id))
    )
)"""


# Discovery layer ----------------------------------------------------------
#
# A single implementation serves the public deals page and the chatbot.  This
# keeps filtering, ranking and promotion semantics consistent across both UIs.

CURRENT_OFFER_FILTER = "o.current_price IS NOT NULL AND COALESCE(o.run_status, 'success') = 'success'"

PROMOTION_LATERAL = """
    LEFT JOIN LATERAL (
        SELECT string_agg(DISTINCT COALESCE(NULLIF(p.offer_text_raw, ''), p.promotion_type, pi.promotion_type), ' | ') AS promotion_text,
               min(COALESCE(p.promotion_type, pi.promotion_type)) AS promotion_type,
               min(p.promotion_start_date) AS promotion_start_date,
               max(p.promotion_end_date) AS promotion_end_date
        FROM promotion_items_current pi
        LEFT JOIN promotions_current p ON p.promotion_key = pi.promotion_key
        WHERE pi.retailer_id = o.retailer_id
          AND (pi.retailer_product_key = o.retailer_product_key
            OR (pi.retailer_product_key IS NULL AND pi.retailer_product_id = o.retailer_product_id))
    ) promo ON true
"""


def _tokens(value: str | None) -> list[str]:
    return [token for token in normalize_text(value).split() if len(token) >= 2][:5]


def _quality_order(alias: str = "o") -> str:
    """Prefer valid serving records before warnings in all public rankings."""
    return f"CASE WHEN {alias}.silver_data_quality_status = 'valid' THEN 0 ELSE 1 END"


def _add_common_offer_filters(
    filters: list[str],
    params: dict[str, Any],
    *,
    retailer_id: str | None = None,
    retailer_ids: list[str] | None = None,
    query: str = "",
    brand: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    min_discount_percent: float | None = None,
    comparison_unit: str | None = None,
    unit_price_only: bool = False,
    data_quality: str = "all",
    name_phrases: list[str] | None = None,
) -> None:
    """Compose parameterised marketplace filters without interpolating user input."""
    if retailer_id:
        filters.append("o.retailer_id = :retailer_id")
        params["retailer_id"] = retailer_id
    if retailer_ids:
        filters.append("o.retailer_id = ANY(:retailer_ids)")
        params["retailer_ids"] = retailer_ids

    for index, token in enumerate(_tokens(query)):
        key = f"query_token_{index}"
        if len(token) <= 3:
            filters.append(f"(concat(' ', o.normalized_name, ' ') LIKE :{key} OR concat(' ', o.normalized_brand, ' ') LIKE :{key})")
            params[key] = f"% {token} %"
        else:
            filters.append(f"(o.normalized_name LIKE :{key} OR o.normalized_brand LIKE :{key})")
            params[key] = f"%{token}%"
    for index, token in enumerate(_tokens(brand)):
        key = f"brand_token_{index}"
        # Gold may leave brand empty even though the retailer product name
        # contains it (for example many Vinamilk rows).  Requiring only the
        # dimension field turns a valid natural-language brand query into zero
        # results, so accept the same normalized token in the product name.
        if len(token) <= 3:
            filters.append(f"(concat(' ', o.normalized_brand, ' ') LIKE :{key} OR concat(' ', o.normalized_name, ' ') LIKE :{key})")
            params[key] = f"% {token} %"
        else:
            filters.append(f"(o.normalized_brand LIKE :{key} OR o.normalized_name LIKE :{key})")
            params[key] = f"%{token}%"
    for index, phrase in enumerate(name_phrases or []):
        key = f"name_phrase_{index}"
        filters.append(f"o.normalized_name LIKE :{key}")
        params[key] = f"%{normalize_text(phrase)}%"

    if min_price is not None:
        filters.append("o.current_price >= :min_price")
        params["min_price"] = min_price
    if max_price is not None:
        filters.append("o.current_price <= :max_price")
        params["max_price"] = max_price
    if min_discount_percent is not None:
        filters.append("COALESCE(o.discount_percent, 0) >= :min_discount_percent")
        params["min_discount_percent"] = min_discount_percent

    normalized_unit = normalize_text(comparison_unit).replace(" ", "")
    measurement_types = {
        "kg": "mass", "g": "mass", "mass": "mass",
        "l": "volume", "lit": "volume", "ml": "volume", "volume": "volume",
        "cai": "count", "each": "count", "count": "count",
    }
    if normalized_unit:
        if normalized_unit in measurement_types:
            filters.append("o.measurement_type = :measurement_type")
            params["measurement_type"] = measurement_types[normalized_unit]
        else:
            filters.append("o.comparison_unit = :comparison_unit")
            params["comparison_unit"] = normalized_unit
    if unit_price_only:
        filters.append("o.unit_price_publishable = true AND o.effective_unit_price IS NOT NULL AND o.effective_unit_price > 0")

    if data_quality == "valid":
        filters.append("o.silver_data_quality_status = 'valid'")
    elif data_quality == "warning":
        filters.append("COALESCE(o.silver_data_quality_status, 'warning') = 'warning'")


def _promotion_type_filter(filters: list[str], promotion_type: str) -> None:
    if promotion_type == "discount":
        filters.append("(o.is_price_discount OR COALESCE(o.discount_percent, 0) > 0)")
    elif promotion_type == "mechanic":
        filters.append("o.has_promo_mechanic")
    elif promotion_type == "flag":
        filters.append("o.is_on_promotion AND NOT o.is_price_discount AND NOT o.has_promo_mechanic")


def _semantic_rerank(rows: list[dict], query: str, settings: Any | None) -> list[dict]:
    """Blend optional semantic scores without making lexical search depend on Ollama.

    `search_index.semantic_scores` is intentionally imported lazily.  This keeps the
    API useful during a first sync, while embedding backfill is in progress, or when
    Ollama is offline.
    """
    if not rows or settings is None:
        return rows
    try:
        from .search_index import semantic_scores
        scores = semantic_scores(settings, query)
    except Exception:
        return rows
    if not scores:
        return rows
    lexical_positions = {str(row["price_snapshot_id"]): index for index, row in enumerate(rows)}
    usable = [row for row in rows if str(row["price_snapshot_id"]) in scores]
    if not usable:
        return rows

    # Reciprocal-rank fusion avoids assuming a score range for cosine distance while
    # preserving the existing lexical ordering for candidates without semantic data.
    semantic_positions = {
        identifier: index
        for index, (identifier, _) in enumerate(
            sorted(((identifier, score) for identifier, score in scores.items() if identifier in lexical_positions), key=lambda item: item[1], reverse=True)
        )
    }
    fused = sorted(
        usable,
        key=lambda row: -(
            1 / (60 + lexical_positions[str(row["price_snapshot_id"])])
            + 1 / (60 + semantic_positions[str(row["price_snapshot_id"])])
        ),
    )
    fused_ids = {str(row["price_snapshot_id"]) for row in fused}
    return fused + [row for row in rows if str(row["price_snapshot_id"]) not in fused_ids]


def search_offers(
    query: str,
    retailers: list[str],
    promotion_only: bool = False,
    limit: int = 30,
    filters: dict[str, Any] | None = None,
    sort: str = "relevance",
    settings: Any | None = None,
) -> list[dict]:
    """Search offers with a deterministic lexical fallback and optional hybrid rerank."""
    tokens = _tokens(query)
    if not tokens:
        return []
    extra = filters or {}
    pool_limit = min(max(limit * 5, 80), 200) if settings is not None else limit
    params: dict[str, Any] = {"search_query": " ".join(tokens), "limit": pool_limit}
    base_filters = [CURRENT_OFFER_FILTER]
    _add_common_offer_filters(
        base_filters,
        params,
        retailer_ids=retailers or extra.get("retailer_ids"),
        brand=extra.get("brand"),
        min_price=extra.get("min_price"),
        max_price=extra.get("max_price"),
        min_discount_percent=extra.get("min_discount_percent"),
        comparison_unit=extra.get("comparison_unit"),
        unit_price_only=bool(extra.get("unit_price_only")),
        data_quality=extra.get("data_quality", "all"),
        name_phrases=extra.get("name_phrases"),
    )
    if promotion_only:
        base_filters.append(PROMOTION_FILTER)
    if extra.get("promotion_type"):
        _promotion_type_filter(base_filters, str(extra["promotion_type"]))

    token_conditions: list[str] = []
    match_terms: list[str] = []
    for index, token in enumerate(tokens):
        key = f"search_token_{index}"
        if len(token) <= 3:
            condition = f"(concat(' ', o.normalized_name, ' ') LIKE :{key} OR concat(' ', o.normalized_brand, ' ') LIKE :{key})"
            params[key] = f"% {token} %"
        else:
            condition = f"(o.normalized_name LIKE :{key} OR o.normalized_brand LIKE :{key})"
            params[key] = f"%{token}%"
        token_conditions.append(condition)
        match_terms.append(f"CASE WHEN {condition} THEN 1 ELSE 0 END")

    order_by = {
        "relevance": "matched_terms DESC, quality_rank ASC, search_score DESC, o.current_price ASC",
        "price": "quality_rank ASC, o.current_price ASC, search_score DESC",
        "unit_price": "quality_rank ASC, o.effective_unit_price ASC NULLS LAST, o.current_price ASC",
        "discount": "quality_rank ASC, COALESCE(o.discount_percent, 0) DESC, o.current_price ASC",
    }.get(sort, "matched_terms DESC, quality_rank ASC, search_score DESC, o.current_price ASC")

    def execute(where: list[str], matched_terms: str) -> list[dict]:
        sql = f"""
            SELECT o.*, {matched_terms} AS matched_terms,
                   {_quality_order()} AS quality_rank,
                   GREATEST(
                     similarity(concat_ws(' ', o.normalized_name, o.normalized_brand), :search_query),
                     word_similarity(:search_query, concat_ws(' ', o.normalized_name, o.normalized_brand)),
                     ts_rank_cd(
                       to_tsvector('simple', concat_ws(' ', o.normalized_name, o.normalized_brand, o.category_raw)),
                       websearch_to_tsquery('simple', :search_query)
                     )
                   ) AS search_score,
                   promo.promotion_text, promo.promotion_type, promo.promotion_start_date, promo.promotion_end_date
            FROM offers_current o {PROMOTION_LATERAL}
            WHERE {' AND '.join(where)}
            ORDER BY {order_by}
            LIMIT :limit
        """
        with engine.connect() as conn:
            return [dict(row._mapping) for row in conn.execute(text(sql), params)]

    rows = execute(base_filters + token_conditions, str(len(tokens)))
    if not rows:
        # Natural-language cleanup occasionally retains a conversational word; retain
        # the strongest multi-token candidates before declaring the product unavailable.
        params["minimum_matches"] = min(2, len(tokens))
        matches = " + ".join(match_terms)
        rows = execute(base_filters + [f"({matches}) >= :minimum_matches"], f"({matches})")
    return _semantic_rerank(rows, query, settings)[:limit]


def browse_deals(
    retailer_id: str | None = None,
    query: str = "",
    sort: str = "featured",
    promotion_type: str = "all",
    page: int = 1,
    page_size: int = 12,
    retailer_ids: list[str] | None = None,
    brand: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    min_discount_percent: float | None = None,
    comparison_unit: str | None = None,
    unit_price_only: bool = False,
    data_quality: str = "all",
    settings: Any | None = None,
) -> tuple[list[dict], int]:
    """Return current promoted offers for public discovery with composable filters."""
    filters = [PROMOTION_FILTER, CURRENT_OFFER_FILTER]
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    _add_common_offer_filters(
        filters,
        params,
        retailer_id=retailer_id,
        retailer_ids=retailer_ids,
        query=query,
        brand=brand,
        min_price=min_price,
        max_price=max_price,
        min_discount_percent=min_discount_percent,
        comparison_unit=comparison_unit,
        unit_price_only=unit_price_only,
        data_quality=data_quality,
    )
    _promotion_type_filter(filters, promotion_type)
    where = " AND ".join(filters)
    order_by = {
        "discount": f"{_quality_order()} ASC, COALESCE(o.discount_percent, 0) DESC, o.current_price ASC",
        "price": f"{_quality_order()} ASC, o.current_price ASC, COALESCE(o.discount_percent, 0) DESC",
        "unit_price": f"{_quality_order()} ASC, o.effective_unit_price ASC NULLS LAST, o.current_price ASC",
        "newest": f"{_quality_order()} ASC, o.snapshot_date DESC NULLS LAST, o.observed_at DESC NULLS LAST, o.current_price ASC",
        "featured": f"{_quality_order()} ASC, CASE WHEN o.is_price_discount THEN 0 ELSE 1 END, COALESCE(o.discount_percent, 0) DESC, o.snapshot_date DESC NULLS LAST, o.current_price ASC",
    }.get(sort, f"{_quality_order()} ASC, COALESCE(o.discount_percent, 0) DESC, o.current_price ASC")
    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT count(*) FROM offers_current o WHERE {where}"), params).scalar_one()
        rows = [dict(row._mapping) for row in conn.execute(text(f"""
            SELECT o.*, promo.promotion_text, promo.promotion_type, promo.promotion_start_date, promo.promotion_end_date
            FROM offers_current o {PROMOTION_LATERAL}
            WHERE {where}
            ORDER BY {order_by}
            LIMIT :limit OFFSET :offset
        """), params)]
    # Search result pages can opt into semantic reranking without changing default
    # marketplace browsing order or pagination semantics.
    if query and settings is not None and page == 1:
        rows = _semantic_rerank(rows, query, settings)
    return rows, int(total)


def autocomplete_offers(query: str, retailer_ids: list[str] | None = None, limit: int = 8) -> list[dict]:
    """Compact, deduplicated suggestions for the marketplace toolbar."""
    tokens = _tokens(query)
    if not tokens:
        return []
    params: dict[str, Any] = {"query": " ".join(tokens), "limit": min(max(limit * 4, 8), 80)}
    filters = [CURRENT_OFFER_FILTER]
    _add_common_offer_filters(filters, params, retailer_ids=retailer_ids)
    token_filters: list[str] = []
    for index, token in enumerate(tokens):
        key = f"suggestion_token_{index}"
        token_filters.append(f"(o.normalized_name LIKE :{key} OR o.normalized_brand LIKE :{key})")
        params[key] = f"%{token}%"
    with engine.connect() as conn:
        candidates = [dict(row._mapping) for row in conn.execute(text(f"""
            SELECT o.price_snapshot_id, o.product_name, o.brand, o.retailer_id, o.current_price,
                   o.effective_unit_price, o.comparison_unit, o.image_url, o.source_url,
                   o.silver_data_quality_status,
                   GREATEST(
                     similarity(concat_ws(' ', o.normalized_name, o.normalized_brand), :query),
                     word_similarity(:query, concat_ws(' ', o.normalized_name, o.normalized_brand))
                   ) AS search_score
            FROM offers_current o
            WHERE {' AND '.join(filters + token_filters)}
            ORDER BY {_quality_order()} ASC, search_score DESC, o.current_price ASC
            LIMIT :limit
        """), params)]
    seen: set[tuple[str, str]] = set()
    suggestions: list[dict] = []
    for candidate in candidates:
        key = (normalize_text(candidate.get("product_name")), normalize_text(candidate.get("brand")))
        if key not in seen:
            seen.add(key)
            suggestions.append(candidate)
        if len(suggestions) >= limit:
            break
    return suggestions


def _current_offer(price_snapshot_id: str) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(text(f"""
            SELECT o.*, promo.promotion_text, promo.promotion_type, promo.promotion_start_date, promo.promotion_end_date
            FROM offers_current o {PROMOTION_LATERAL}
            WHERE o.price_snapshot_id = :price_snapshot_id AND {CURRENT_OFFER_FILTER}
        """), {"price_snapshot_id": price_snapshot_id}).mappings().first()
    return dict(row) if row else None


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _with_price_deltas(rows: list[dict]) -> list[dict]:
    if not rows:
        return rows
    lowest = min(_as_float(row.get("current_price")) for row in rows)
    for row in rows:
        current = _as_float(row.get("current_price"))
        delta = max(current - lowest, 0)
        row["price_difference_from_lowest"] = delta
        row["price_difference_percent_from_lowest"] = round((delta / lowest) * 100, 2) if lowest else None
        row["is_lowest_price"] = current == lowest
    return rows


def offer_insights(price_snapshot_id: str, similar_limit: int = 8) -> dict | None:
    """Return explicitly separated canonical comparisons and lower-price alternatives.

    A canonical mapping is the only source for `same_product_offers`.  Similar rows
    are deliberately marked as alternatives and never gain a canonical confidence.
    """
    anchor = _current_offer(price_snapshot_id)
    if not anchor:
        return None

    canonical_id = anchor.get("canonical_product_id")
    same_product_offers: list[dict] = []
    if canonical_id:
        with engine.connect() as conn:
            same_product_offers = [dict(row._mapping) for row in conn.execute(text(f"""
                SELECT o.*, promo.promotion_text, promo.promotion_type, promo.promotion_start_date, promo.promotion_end_date
                FROM offers_current o {PROMOTION_LATERAL}
                WHERE o.canonical_product_id = :canonical_product_id AND {CURRENT_OFFER_FILTER}
                ORDER BY o.current_price ASC, {_quality_order()} ASC, o.retailer_id ASC
            """), {"canonical_product_id": canonical_id})]
        for row in same_product_offers:
            row["match_type"] = "canonical"
            row["match_confidence"] = 1.0
            row["is_anchor"] = row["price_snapshot_id"] == price_snapshot_id
        _with_price_deltas(same_product_offers)

    similar_filters = [CURRENT_OFFER_FILTER, "o.price_snapshot_id <> :price_snapshot_id", "o.current_price < :anchor_price"]
    params: dict[str, Any] = {
        "price_snapshot_id": price_snapshot_id,
        "anchor_price": anchor["current_price"],
        "anchor_name": anchor.get("normalized_name") or normalize_text(anchor.get("product_name")),
        "similar_limit": min(max(similar_limit, 1), 20),
    }
    if canonical_id:
        similar_filters.append("o.canonical_product_id IS DISTINCT FROM :canonical_product_id")
        params["canonical_product_id"] = canonical_id
    if anchor.get("normalized_brand"):
        similar_filters.append("o.normalized_brand = :normalized_brand")
        params["normalized_brand"] = anchor["normalized_brand"]
    if anchor.get("measurement_type") and anchor.get("measurement_type") != "unknown":
        similar_filters.append("o.measurement_type = :measurement_type")
        params["measurement_type"] = anchor["measurement_type"]
    # Similarity is deliberately conservative: same brand + compatible measurement,
    # with product-name evidence.  The UI labels these as alternatives, never as the
    # exact product.
    similar_filters.append("word_similarity(:anchor_name, o.normalized_name) >= 0.18")
    with engine.connect() as conn:
        similar_offers = [dict(row._mapping) for row in conn.execute(text(f"""
            SELECT o.*, promo.promotion_text, promo.promotion_type, promo.promotion_start_date, promo.promotion_end_date,
                   word_similarity(:anchor_name, o.normalized_name) AS similarity_score
            FROM offers_current o {PROMOTION_LATERAL}
            WHERE {' AND '.join(similar_filters)}
            ORDER BY similarity_score DESC, {_quality_order()} ASC, o.current_price ASC
            LIMIT :similar_limit
        """), params)]
    for row in similar_offers:
        row["match_type"] = "similar"
        row["match_confidence"] = None
    _with_price_deltas(similar_offers)

    prices = [_as_float(row.get("current_price")) for row in same_product_offers]
    retailers = {row["retailer_id"] for row in same_product_offers}
    return {
        "offer": anchor,
        "same_product_offers": same_product_offers,
        "similar_offers": similar_offers,
        "summary": {
            "canonical_product_id": canonical_id,
            "retailer_count": len(retailers),
            "can_compare_exactly": len(retailers) >= 2,
            "lowest_price": min(prices) if prices else None,
            "highest_price": max(prices) if prices else None,
            "price_spread": max(prices) - min(prices) if prices else None,
            "snapshot_date": str(anchor["snapshot_date"]) if anchor.get("snapshot_date") else None,
            "data_quality_warning": anchor.get("silver_data_quality_status") != "valid",
        },
    }


def price_history(price_snapshot_id: str, days: int = 90) -> dict | None:
    """Return the retained daily history for an exact canonical product when possible.

    A selected offer without canonical mapping is intentionally scoped to its own
    retailer product, so the response never turns a name-only match into a
    cross-retailer time series.
    """
    anchor = _current_offer(price_snapshot_id)
    if not anchor:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM offer_price_history WHERE price_snapshot_id=:price_snapshot_id"),
                {"price_snapshot_id": price_snapshot_id},
            ).mappings().first()
        anchor = dict(row) if row else None
    if not anchor:
        return None

    filters = ["snapshot_date IS NOT NULL"]
    params: dict[str, Any] = {"days": max(1, min(int(days), 3650))}
    canonical_id = anchor.get("canonical_product_id")
    if canonical_id:
        filters.append("canonical_product_id = :canonical_product_id")
        params["canonical_product_id"] = canonical_id
    elif anchor.get("retailer_product_key"):
        filters.append("retailer_product_key = :retailer_product_key")
        params["retailer_product_key"] = anchor["retailer_product_key"]
    else:
        filters.extend(["retailer_id = :retailer_id", "retailer_product_id = :retailer_product_id"])
        params["retailer_id"] = anchor.get("retailer_id")
        params["retailer_product_id"] = anchor.get("retailer_product_id")

    where = " AND ".join(filters)
    with engine.connect() as conn:
        rows = [dict(row._mapping) for row in conn.execute(text(f"""
            WITH matching AS (
                SELECT price_snapshot_id, snapshot_date, retailer_id, store_code,
                       canonical_product_id, retailer_product_key, retailer_product_id,
                       product_name, brand, current_price, listed_price, promo_price,
                       effective_unit_price, comparison_unit, discount_percent,
                       is_on_promotion, is_price_discount, has_promo_mechanic,
                       silver_data_quality_status, observed_at, source_run_id,
                       max(snapshot_date) OVER () AS latest_snapshot_date
                FROM offer_price_history
                WHERE {where}
            )
            SELECT *
            FROM matching
            WHERE snapshot_date >= latest_snapshot_date - (:days - 1)
            ORDER BY snapshot_date ASC, retailer_id ASC, store_code ASC, current_price ASC
        """), params)]

    prices = [_as_float(row.get("current_price")) for row in rows]
    snapshot_dates = [row["snapshot_date"] for row in rows if row.get("snapshot_date")]
    return {
        "offer": anchor,
        "series": rows,
        "summary": {
            "canonical_product_id": canonical_id,
            "scope": "canonical_product" if canonical_id else "retailer_product",
            "point_count": len(rows),
            "retailer_count": len({row["retailer_id"] for row in rows}),
            "first_snapshot_date": str(min(snapshot_dates)) if snapshot_dates else None,
            "latest_snapshot_date": str(max(snapshot_dates)) if snapshot_dates else None,
            "lowest_price": min(prices) if prices else None,
            "highest_price": max(prices) if prices else None,
        },
    }


def _offer_line(offer: dict, quantity: int, *, match_type: str, optimized: bool) -> dict:
    current_price = _as_float(offer.get("current_price"))
    return {
        "price_snapshot_id": offer.get("price_snapshot_id"),
        "canonical_product_id": offer.get("canonical_product_id"),
        "retailer_id": offer.get("retailer_id"),
        "product_name": offer.get("product_name"),
        "brand": offer.get("brand"),
        "image_url": offer.get("image_url"),
        "source_url": offer.get("source_url"),
        "current_price": current_price,
        "effective_unit_price": _as_float(offer.get("effective_unit_price")) if offer.get("effective_unit_price") is not None else None,
        "comparison_unit": offer.get("comparison_unit"),
        "silver_data_quality_status": offer.get("silver_data_quality_status"),
        "quantity": quantity,
        "line_total": round(current_price * quantity, 2),
        "match_type": match_type,
        "optimized": optimized,
    }


def _best_candidate(rows: list[dict]) -> dict | None:
    if not rows:
        return None
    valid = [row for row in rows if row.get("silver_data_quality_status") == "valid"]
    return min(valid or rows, key=lambda row: (_as_float(row.get("current_price")), str(row.get("price_snapshot_id"))))


def _cheapest_candidate(rows: list[dict]) -> dict | None:
    """Return the lowest exact-canonical price, using quality only as a tie-breaker.

    The split plan is explicitly a cost optimizer. Preferring a more expensive
    ``valid`` row over a cheaper selected ``warning`` row made the UI claim that
    26,500đ was the cheapest option when the current 22,700đ offer was still live.
    """
    if not rows:
        return None
    return min(
        rows,
        key=lambda row: (
            _as_float(row.get("current_price")),
            0 if row.get("silver_data_quality_status") == "valid" else 1,
            str(row.get("price_snapshot_id")),
        ),
    )


def _offers_for_snapshot_ids(price_snapshot_ids: list[str]) -> dict[str, dict]:
    if not price_snapshot_ids:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT o.*, promo.promotion_text, promo.promotion_type, promo.promotion_start_date, promo.promotion_end_date
            FROM offers_current o {PROMOTION_LATERAL}
            WHERE o.price_snapshot_id = ANY(:price_snapshot_ids) AND {CURRENT_OFFER_FILTER}
        """), {"price_snapshot_ids": price_snapshot_ids})
        return {str(row._mapping["price_snapshot_id"]): dict(row._mapping) for row in rows}


def _canonical_candidates(canonical_ids: list[str]) -> dict[str, list[dict]]:
    if not canonical_ids:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT o.*
            FROM offers_current o
            WHERE o.canonical_product_id = ANY(:canonical_ids) AND {CURRENT_OFFER_FILTER}
        """), {"canonical_ids": canonical_ids})
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            item = dict(row._mapping)
            grouped[str(item["canonical_product_id"])].append(item)
    return grouped


def optimize_basket(items: list[dict]) -> dict:
    """Find exact-canonical single-store and split-store purchase plans.

    Items without a canonical mapping remain in the split plan at the selected store,
    but are surfaced in `unavailable_items` so callers never mistake them for an
    exact cross-store comparison.
    """
    quantities: dict[str, int] = {}
    order: list[str] = []
    for item in items:
        identifier = str(item.get("price_snapshot_id") or "").strip()
        if not identifier:
            continue
        try:
            quantity = int(item.get("quantity", 1))
        except (TypeError, ValueError):
            quantity = 1
        if quantity < 1:
            continue
        if identifier not in quantities:
            order.append(identifier)
            quantities[identifier] = 0
        quantities[identifier] += min(quantity, 99)

    selected_by_id = _offers_for_snapshot_ids(order)
    missing_ids = [identifier for identifier in order if identifier not in selected_by_id]
    selected_lines = [_offer_line(selected_by_id[identifier], quantities[identifier], match_type="selected", optimized=False) for identifier in order if identifier in selected_by_id]
    selected_total = round(sum(line["line_total"] for line in selected_lines), 2)
    unavailable_items: list[dict] = [
        {"price_snapshot_id": identifier, "quantity": quantities[identifier], "reason": "Offer is no longer available in the current snapshot."}
        for identifier in missing_ids
    ]

    canonical_ids = list({str(offer["canonical_product_id"]) for offer in selected_by_id.values() if offer.get("canonical_product_id")})
    candidates_by_canonical = _canonical_candidates(canonical_ids)
    for identifier in order:
        offer = selected_by_id.get(identifier)
        if offer and not offer.get("canonical_product_id"):
            unavailable_items.append({
                "price_snapshot_id": identifier,
                "product_name": offer.get("product_name"),
                "quantity": quantities[identifier],
                "reason": "This product has no canonical mapping, so it cannot be compared exactly across retailers.",
            })

    # A one-store option is only valid when every requested, available item is an
    # exact canonical match at that retailer.  It is intentionally omitted otherwise.
    single_retailer_options: list[dict] = []
    comparable_selected = [selected_by_id[identifier] for identifier in order if identifier in selected_by_id and selected_by_id[identifier].get("canonical_product_id")]
    all_selected_are_canonical = len(comparable_selected) == len(selected_lines) and bool(comparable_selected)
    if all_selected_are_canonical:
        common_retailers: set[str] | None = None
        for offer in comparable_selected:
            retailers = {row["retailer_id"] for row in candidates_by_canonical.get(str(offer["canonical_product_id"]), [])}
            common_retailers = retailers if common_retailers is None else common_retailers & retailers
        for retailer_id in sorted(common_retailers or set()):
            lines: list[dict] = []
            for identifier in order:
                selected = selected_by_id[identifier]
                candidates = [row for row in candidates_by_canonical[str(selected["canonical_product_id"])] if row["retailer_id"] == retailer_id]
                candidate = _best_candidate(candidates)
                if candidate is None:
                    lines = []
                    break
                lines.append(_offer_line(candidate, quantities[identifier], match_type="canonical", optimized=candidate["price_snapshot_id"] != identifier))
            if lines:
                total = round(sum(line["line_total"] for line in lines), 2)
                single_retailer_options.append({
                    "retailer_id": retailer_id,
                    "lines": lines,
                    "total": total,
                    "savings_vs_selected": round(selected_total - total, 2),
                    "uses_warning_data": any(line["silver_data_quality_status"] != "valid" for line in lines),
                })
        single_retailer_options.sort(key=lambda option: (option["total"], option["retailer_id"]))

    split_lines: list[dict] = []
    for identifier in order:
        selected = selected_by_id.get(identifier)
        if not selected:
            continue
        canonical_id = selected.get("canonical_product_id")
        candidate = _cheapest_candidate(candidates_by_canonical.get(str(canonical_id), [])) if canonical_id else None
        if candidate:
            split_lines.append(_offer_line(candidate, quantities[identifier], match_type="canonical", optimized=candidate["price_snapshot_id"] != identifier))
        else:
            split_lines.append(_offer_line(selected, quantities[identifier], match_type="selected_unmapped", optimized=False))
    split_total = round(sum(line["line_total"] for line in split_lines), 2)
    split_retailers = {line["retailer_id"] for line in split_lines if line.get("retailer_id")}
    snapshot_dates = sorted({str(offer["snapshot_date"]) for offer in selected_by_id.values() if offer.get("snapshot_date")}, reverse=True)
    return {
        "items": selected_lines,
        "selected_total": selected_total,
        "single_retailer_options": single_retailer_options,
        "split_order": {
            "lines": split_lines,
            "total": split_total,
            "savings_vs_selected": round(selected_total - split_total, 2),
            "retailer_id": next(iter(split_retailers)) if len(split_retailers) == 1 else None,
            "retailer_count": len(split_retailers),
            "uses_warning_data": any(line["silver_data_quality_status"] != "valid" for line in split_lines),
        },
        "unavailable_items": unavailable_items,
        "snapshot_date": snapshot_dates[0] if snapshot_dates else None,
    }


def seeded_offers(price_snapshot_id: str, limit: int = 30) -> list[dict]:
    """Use Gold's canonical mapping for a discovery-card-to-chat handoff."""
    with engine.connect() as conn:
        seed = conn.execute(text("SELECT * FROM offers_current WHERE price_snapshot_id=:id"), {"id": price_snapshot_id}).mappings().first()
    if not seed:
        return []
    if seed.get("canonical_product_id"):
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT * FROM offers_current
                WHERE canonical_product_id=:canonical_id
                ORDER BY current_price ASC
                LIMIT :limit
            """), {"canonical_id": seed["canonical_product_id"], "limit": limit})
            return [dict(row._mapping) for row in rows]
    return search_offers(seed["product_name"], [], False, limit)


def compare_offers(offers: list[dict]) -> tuple[list[dict], list[dict]]:
    if not offers:
        return [], []
    # Canonical mappings from Gold are stronger evidence than matching text/packaging
    # heuristics. Select the mapped group with the broadest retailer coverage first.
    canonical_groups: dict[str, list[dict]] = {}
    for offer in offers:
        canonical_id = offer.get("canonical_product_id")
        if canonical_id:
            canonical_groups.setdefault(canonical_id, []).append(offer)
    comparable_groups = [
        group for group in canonical_groups.values() if len({item["retailer_id"] for item in group}) >= 2
    ]
    if comparable_groups:
        reliable = max(comparable_groups, key=lambda group: (len({item["retailer_id"] for item in group}), len(group)))
        reliable_ids = {item["price_snapshot_id"] for item in reliable}
        for offer in reliable:
            offer["match_confidence"] = 1.0
        near = [offer for offer in offers if offer["price_snapshot_id"] not in reliable_ids]
        return sorted(reliable, key=lambda item: item["current_price"]), near
    # Name/package similarity is useful for discovery, but is not evidence that two
    # records are the exact same sellable SKU. Keep those rows explicitly separate
    # until Gold provides a canonical mapping.
    for offer in offers:
        offer["match_confidence"] = None
        offer["match_type"] = "similar"
    return [], sorted(offers, key=lambda item: item["current_price"])


def latest_sync() -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id::text,status,started_at,finished_at,details FROM sync_runs ORDER BY started_at DESC LIMIT 1")).first()
        return dict(row._mapping) if row else None


def latest_snapshot_date() -> str | None:
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT max(snapshot_date)::text FROM offers_current")).scalar()
            return str(row) if row else None
    except Exception:
        return None
