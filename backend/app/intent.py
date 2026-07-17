import json
import re
from dataclasses import dataclass, replace
from typing import Any, Literal

import httpx

from .config import Settings
from .matching import normalize_text

IntentName = Literal["product_search", "compare_prices", "deals", "clarification", "basket"]
BasketAction = Literal["none", "add", "view", "optimize"]


@dataclass
class Intent:
    """A small, deterministic representation of a shopping request.

    The LLM is only used to improve product/brand extraction. Filters and actions
    are also parsed locally so a temporarily unavailable (or over-confident) model
    cannot turn a price question into a different search.
    """

    name: IntentName
    query: str
    retailers: list[str]
    promotion_only: bool = False
    brand: str | None = None
    package: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    min_discount_percent: float | None = None
    comparison_unit: str | None = None
    unit_price_only: bool = False
    data_quality: str | None = None
    sort: str = "relevance"
    basket_action: BasketAction = "none"
    needs_clarification: bool = False
    clarification: str | None = None

    def filters(self) -> dict[str, Any]:
        """Keyword filters understood by repository.search_offers()."""
        return {
            key: value
            for key, value in {
                "brand": self.brand,
                "min_price": self.min_price,
                "max_price": self.max_price,
                "min_discount_percent": self.min_discount_percent,
                "comparison_unit": self.comparison_unit,
                "unit_price_only": self.unit_price_only or None,
                "data_quality": self.data_quality,
            }.items()
            if value is not None
        }

    def context_payload(self, offer_ids: list[str] | None = None) -> dict[str, Any]:
        """Persist only safe, compact state in the existing message JSON payload."""
        data = {
            "name": self.name,
            "query": self.query,
            "retailers": self.retailers,
            "promotion_only": self.promotion_only,
            "brand": self.brand,
            "package": self.package,
            "min_price": self.min_price,
            "max_price": self.max_price,
            "min_discount_percent": self.min_discount_percent,
            "comparison_unit": self.comparison_unit,
            "unit_price_only": self.unit_price_only,
            "data_quality": self.data_quality,
            "sort": self.sort,
        }
        if offer_ids:
            data["offer_ids"] = offer_ids[:10]
        return {key: value for key, value in data.items() if value not in (None, "", [], False)}


RETAILERS = ("bachhoaxanh", "go", "lottemart", "mmvietnam", "winmart")
RETAILER_ALIASES: dict[str, tuple[str, ...]] = {
    "bachhoaxanh": ("bach hoa xanh", "bachhoaxanh", "bhx"),
    "go": ("go", "go mart", "go supermarket"),
    "lottemart": ("lotte mart", "lottemart", "lotte"),
    "mmvietnam": ("mm mega market", "mega market", "mmvietnam", "mm vietnam", "mm"),
    "winmart": ("win mart", "winmart", "win mart plus"),
}

# These terms describe the request, not the product. Keeping them in database
# search made a query such as "sữa Vinamilk nào rẻ nhất" much less likely to
# match. Product packaging tokens such as 1l/500g deliberately remain.
QUERY_NOISE = frozenset(
    "a anh bao ban bao nhieu cac cai can cho co cua de den gia giua hang hay "
    "khi la lam nao nay nhat o oi re san pham so sanh uu uu ve voi xem "
    "uu dai khuyen mai giam duoc khong toi minh chung ta muon mua tim kiem xin hay giup "
    "mot loai mat hang thi sao cung it duoi tren toi da qua khoang tu theo don vi "
    "gia tot valid warning xac minh tin cay chi lay con lai the them vao sach gio "
    "hang mua toi uu du lieu mon".split()
)

_PACKAGE_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l|lit)\b", re.I)
_PERCENT_RE = re.compile(r"\b(?:giam\s*)?(?:tren|tu|it nhat)?\s*(\d{1,2}(?:[.,]\d+)?)\s*(?:%|phan tram)\b", re.I)
_MONEY_RE = re.compile(
    r"\b(?P<amount>\d{1,3}(?:[\s.,]\d{3})+|\d+(?:[.,]\d+)?)\s*(?P<suffix>k|nghin|ngan|d|dong|vnd)\b",
    re.I,
)


def _retailers_in(message: str) -> list[str]:
    text = normalize_text(message)
    found: list[str] = []
    for retailer in RETAILERS:
        if any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text) for alias in RETAILER_ALIASES[retailer]):
            found.append(retailer)
    return found


def _remove_retailer_names(text: str) -> str:
    for aliases in RETAILER_ALIASES.values():
        for alias in aliases:
            text = re.sub(rf"(?<!\w){re.escape(alias)}(?!\w)", " ", text)
    return text


def _tokens(message: str) -> list[str]:
    text = _remove_retailer_names(normalize_text(message))
    tokens: list[str] = []
    for token in text.split():
        # Budget values should not become a product query. Leave 1 and 2 alone:
        # users often use them as a product/packaging qualifier.
        is_money_fragment = (token.endswith(("k", "d")) and token[:-1].isdigit()) or (token.isdigit() and len(token) >= 3)
        if token not in QUERY_NOISE and not is_money_fragment:
            tokens.append(token)
    return tokens


def clean_query(message: str) -> str:
    """Return only product-bearing words from the original user message."""
    return " ".join(_tokens(message)) or _remove_retailer_names(normalize_text(message)).strip()


def _query_with_package(message: str, package: str | None, unit_price_only: bool) -> str:
    """Keep a package in the searchable form used by normalized product names."""
    query = clean_query(message)
    if package:
        query = _PACKAGE_RE.sub(package, query)
    if unit_price_only:
        # In "giá theo lít", the second "lít" describes the requested comparison
        # unit rather than the product. The package itself has already been preserved.
        query = re.sub(r"\b(kg|g|ml|l|lit|cai|chiec|each)\b", " ", query)
    return re.sub(r"\s+", " ", query).strip()


def _money_value(amount: str, suffix: str) -> float:
    compact = amount.replace(" ", "")
    # A separator followed by three digits is a thousands separator, otherwise it
    # is treated as a decimal separator (for example 1,5k).
    if re.search(r"[.,]\d{3}(?:[.,]\d{3})*$", compact):
        number = float(re.sub(r"[.,]", "", compact))
    else:
        number = float(compact.replace(",", "."))
    return number * 1000 if suffix.lower() in {"k", "nghin", "ngan"} else number


def _money_mentions(message: str) -> list[tuple[float, int, int]]:
    text = normalize_text(message)
    mentions: list[tuple[float, int, int]] = []
    for match in _MONEY_RE.finditer(text):
        try:
            mentions.append((_money_value(match.group("amount"), match.group("suffix")), match.start(), match.end()))
        except ValueError:
            continue
    return mentions


def _price_bounds(message: str) -> tuple[float | None, float | None]:
    text = normalize_text(message)
    amounts = _money_mentions(message)
    if not amounts:
        return None, None
    # "từ 50k đến 100k" is the only case where we reliably set both bounds.
    if len(amounts) >= 2:
        between = text[amounts[0][2] : amounts[1][1]]
        before = text[max(0, amounts[0][1] - 16) : amounts[0][1]]
        if re.search(r"\btu\s*$", before) and re.search(r"\b(den|toi)\b", between):
            return amounts[0][0], amounts[1][0]
    value, start, _ = amounts[0]
    before = text[max(0, start - 24) : start]
    if re.search(r"\b(duoi|toi da|khong qua|den)\s*$", before):
        return None, value
    if re.search(r"\b(tren|it nhat|tu)\s*$", before):
        return value, None
    return None, None


def _package(message: str) -> str | None:
    match = _PACKAGE_RE.search(normalize_text(message))
    if not match:
        return None
    quantity = match.group(1).replace(",", ".")
    unit = "l" if match.group(2).lower() == "lit" else match.group(2).lower()
    return f"{quantity}{unit}"


def _unit_filter(message: str) -> tuple[str | None, bool]:
    text = normalize_text(message)
    if not any(phrase in text for phrase in ("gia theo", "don gia", "theo don vi", "moi kg", "moi lit", "moi cai")):
        return None, False
    if re.search(r"\b(kg|kilogram|g)\b", text):
        return "g", True
    if re.search(r"\b(lit|l|ml)\b", text):
        return "ml", True
    if re.search(r"\b(cai|chiec|each)\b", text):
        return "each", True
    return None, True


def _data_quality(message: str) -> str | None:
    text = normalize_text(message)
    if any(phrase in text for phrase in ("da xac minh", "tin cay", "chat luong tot", "valid")):
        return "valid"
    if any(phrase in text for phrase in ("canh bao", "warning")):
        return "warning"
    return None


def _discount_threshold(message: str) -> float | None:
    text = normalize_text(message)
    match = _PERCENT_RE.search(text)
    if not match:
        # normalize_text intentionally strips '%'. A number immediately after a
        # discount cue is still unambiguously a percentage for shopping queries.
        match = re.search(r"\bgiam\s+(?:tren|tu|it nhat)?\s*(\d{1,2}(?:[.,]\d+)?)\b", text)
    if not match or not any(term in text for term in ("giam", "phan tram")):
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _basket_action(message: str) -> BasketAction:
    text = normalize_text(message)
    if not any(phrase in text for phrase in ("danh sach mua", "gio hang", "them mon", "them vao", "toi uu don", "toi uu danh sach")):
        return "none"
    if "toi uu" in text:
        return "optimize"
    if "them" in text:
        return "add"
    return "view"


def _looks_like_follow_up(message: str, intent: Intent) -> bool:
    text = normalize_text(message)
    if intent.name in {"clarification", "basket"}:
        return True
    markers = ("con ", "the con", "the sao", "chi lay", "chi can", "loai ", "cai nay", "cai dau", "san pham nay", "o lotte", "o winmart", "o go", "o bhx")
    return text.startswith(markers)


def infer_name(message: str) -> IntentName:
    normalized = normalize_text(message)
    words = set(normalized.split())
    action = _basket_action(message)
    if action != "none":
        return "basket"
    if normalized.startswith(("con ", "the con", "the sao", "chi lay", "chi can", "loai ", "cai nay", "cai dau", "san pham nay")):
        return "clarification"
    if any(phrase in normalized for phrase in ("uu dai", "khuyen mai", "giam gia")) or words & {"promotion", "deal", "sale"}:
        return "deals"
    if "so sanh" in normalized or "compare" in words or "re nhat" in normalized or "cheapest" in words:
        return "compare_prices"
    return "product_search"


def fallback_intent(message: str) -> Intent:
    name = infer_name(message)
    min_price, max_price = _price_bounds(message)
    comparison_unit, unit_price_only = _unit_filter(message)
    package = _package(message)
    min_discount_percent = _discount_threshold(message)
    query = _query_with_package(message, package, unit_price_only)
    if min_discount_percent is not None:
        query = re.sub(rf"\b{int(min_discount_percent) if min_discount_percent.is_integer() else min_discount_percent}\b", " ", query)
        query = re.sub(r"\s+", " ", query).strip()
    return Intent(
        name=name,
        query=query,
        retailers=_retailers_in(message),
        promotion_only=name == "deals",
        package=package,
        min_price=min_price,
        max_price=max_price,
        min_discount_percent=min_discount_percent,
        comparison_unit=comparison_unit,
        unit_price_only=unit_price_only,
        data_quality=_data_quality(message),
        sort="unit_price" if unit_price_only else "relevance",
        basket_action=_basket_action(message),
        needs_clarification=name == "clarification" and not clean_query(message),
    )


def apply_conversation_context(intent: Intent, previous: dict[str, Any] | None, message: str) -> Intent:
    """Resolve a short follow-up without re-running or trusting an LLM history.

    Context comes from the prior assistant payload, not a new database column. It is
    therefore safe for anonymous conversations and is removed automatically when a
    conversation is deleted.
    """
    if not previous:
        return intent
    if intent.name == "basket":
        # The browser owns the actual local basket. Preserve the last offer ids so
        # it can resolve "thêm món này" when there was a single result.
        return intent
    if not _looks_like_follow_up(message, intent):
        return intent

    previous_name = previous.get("name")
    if previous_name not in {"product_search", "compare_prices", "deals"}:
        previous_name = "product_search"
    previous_query = str(previous.get("query") or "").strip()
    previous_package = str(previous.get("package") or "").strip() or None
    current_package = intent.package

    query = intent.query
    # A retailer-only reply ("còn Lotte thì sao?") or a qualifier-only reply
    # ("chỉ loại 1 kg") continues the preceding product search.
    qualifier_only = intent.name == "clarification" or not query or query in {"loai", "chi", "con"}
    if qualifier_only and previous_query:
        query = previous_query
        if current_package and previous_package and current_package != previous_package:
            query = re.sub(rf"\b{re.escape(previous_package)}\b", " ", query)
        if current_package and current_package not in query.split():
            query = f"{query} {current_package}"
        query = re.sub(r"\s+", " ", query).strip()

    return replace(
        intent,
        name=previous_name if intent.name == "clarification" else intent.name,
        query=query,
        retailers=intent.retailers or list(previous.get("retailers") or []),
        promotion_only=intent.promotion_only or bool(previous.get("promotion_only")),
        brand=intent.brand or previous.get("brand"),
        package=current_package or previous_package,
        min_price=intent.min_price if intent.min_price is not None else previous.get("min_price"),
        max_price=intent.max_price if intent.max_price is not None else previous.get("max_price"),
        min_discount_percent=(intent.min_discount_percent if intent.min_discount_percent is not None else previous.get("min_discount_percent")),
        comparison_unit=intent.comparison_unit or previous.get("comparison_unit"),
        unit_price_only=intent.unit_price_only or bool(previous.get("unit_price_only")),
        data_quality=intent.data_quality or previous.get("data_quality"),
        sort="unit_price" if intent.unit_price_only or previous.get("unit_price_only") else intent.sort,
        needs_clarification=not bool(query),
        clarification="Bạn muốn tìm hoặc so sánh sản phẩm nào?" if not query else None,
    )


async def parse_intent(message: str, settings: Settings) -> Intent:
    """Extract product/brand fields with Ollama, with deterministic validation."""
    deterministic = fallback_intent(message)
    prompt = (
        "Trả về JSON duy nhất theo schema: name (product_search|compare_prices|deals|clarification|basket), "
        "product, brand, package, retailers (mảng retailer_id trong bachhoaxanh, go, lottemart, "
        "mmvietnam, winmart). product chỉ gồm tên sản phẩm/nhóm sản phẩm, không gồm từ giao tiếp. "
        "brand và package dùng null nếu không rõ. Chỉ liệt kê nhà bán lẻ người dùng nêu rõ. "
        "Câu hỏi: " + message
    )
    raw = ""

    async def generate(instruction: str) -> str:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={"model": settings.ollama_model, "prompt": instruction, "format": "json", "stream": False},
            )
            response.raise_for_status()
            return response.json()["response"]

    def model_fields(response_text: str) -> tuple[str, str | None, str | None, list[str], IntentName | None]:
        data = json.loads(response_text)
        values = data.get("retailers", [])
        retailers = [value for value in values if value in RETAILERS] if isinstance(values, list) else []
        product = clean_query(str(data.get("product") or ""))
        brand = clean_query(str(data.get("brand") or "")) or None
        package = _package(str(data.get("package") or ""))
        query = " ".join(part for part in (product, brand, package) if part)
        name = data.get("name")
        valid_names = {"product_search", "compare_prices", "deals", "clarification", "basket"}
        return query, brand, package, retailers, name if name in valid_names else None

    try:
        raw = await generate(prompt)
        model_query, model_brand, model_package, model_retailers, model_name = model_fields(raw)
    except Exception:
        try:
            repaired = await generate(
                "Chỉ sửa thành JSON hợp lệ theo schema name, product, brand, package, retailers. Dữ liệu cần sửa: " + raw
            )
            model_query, model_brand, model_package, model_retailers, model_name = model_fields(repaired)
        except Exception:
            model_query = ""
            model_brand = None
            model_package = None
            model_retailers = []
            model_name = None

    # A model query must share a product token with the original request. This blocks
    # hallucinations (for example returning "bột giặt" for a toothpaste question).
    original_tokens = set(deterministic.query.split())
    model_tokens = set(model_query.split())
    safe_model_query = model_query if model_tokens & original_tokens else ""

    # Rules win on disagreement. The model query is only an optional, cleaner product
    # expression; main.py retries the deterministic query if it yields no records.
    return replace(
        deterministic,
        name=model_name if model_name == deterministic.name else deterministic.name,
        query=safe_model_query or deterministic.query,
        retailers=deterministic.retailers or model_retailers,
        brand=model_brand or deterministic.brand,
        package=model_package or deterministic.package,
    )
