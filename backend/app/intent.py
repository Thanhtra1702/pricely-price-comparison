import json
import re
from dataclasses import dataclass, replace
from typing import Any, Literal

import httpx

from .config import Settings
from .matching import normalize_text

IntentName = Literal["product_search", "compare_prices", "deals", "clarification", "basket", "out_of_scope"]
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
    name_phrases: list[str] | None = None
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
                "name_phrases": self.name_phrases,
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
            "name_phrases": self.name_phrases,
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

# Multi-word noise phrases that describe intent/actions rather than products.
QUERY_NOISE_PHRASES = (
    "bao nhieu", "san pham", "so sanh", "uu dai", "khuyen mai", "giam gia",
    "tim kiem", "chung ta", "mat hang", "thi sao", "don vi", "gia tot",
    "xac minh", "tin cay", "chi lay", "con lai", "them vao", "gio hang",
    "toi uu", "du lieu", "danh sach", "chua co", "khong co", "co dua",
    "khong co sao", "co sao", "sao khong", "co khong", "co ban", "gia sao",
    "the sao", "the con", "o dau", "co o", "khong a", "co a", "khong co ban",
    "khong ban ha", "khong co ban ha", "co ban ha", "co ban khong", "khong ha",
    "o dau ban", "o dau co", "co ban a", "khong ban a", "sieu thi khac",
    "cac sieu thi khac", "cac sieu thi", "sieu thi", "cua hang khac", "cac cua hang",
    "o cac sieu thi khac", "o sieu thi khac",
    "noi nao khac", "noi khac", "co noi nao khac", "noi nao khac ngoai",
    "cho nao khac", "cho khac", "co cho nao khac",
    "ngoai bach hoa xanh", "ngoai go", "ngoai lotte", "ngoai lottemart",
    "ngoai winmart", "ngoai mm", "ngoai mega market",
)

# Single noise words describing the query/conversational filler.
# Note: words like "gio" (giò/giỏ), "cay" (cay), "bao" (bao), "mat" (mát),
# "lieu" (liệu), "tin" (tin), "xac" (xác), "don" (đơn), "tot" (tốt) are omitted
# so they are not stripped when present in product names (e.g., "chả giò", "tương ớt cay", "bánh bao").
QUERY_NOISE = frozenset(
    "a anh ban cac cai can cho co cua de den gia giua hang hay "
    "khi la lam nao nay nhat o oi re uu ve voi xem "
    "giam duoc khong toi minh muon mua tim xin hay giup "
    "mot loai cung it duoi tren toi da qua khoang tu theo "
    "valid warning mon sao ban sau ha nhi nhe nha day do u "
    "ngoai khac vay".split()
)

_PACKAGE_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l|lit)\b", re.I)
# A user often states the size of each item in a bundle ("lốc 4 hộp ...
# 180ml").  The offer's sellable quantity is 720ml, not 180ml, so retain the
# multiplier for strict package filtering while keeping 180ml searchable.
_MULTIPACK_RE = re.compile(
    r"\b(?:loc\s*)?(\d+)\s*(?:hop|chai|goi|lon|cai)\b"
    r"(?:(?!\b\d+(?:[.,]\d+)?\s*(?:kg|g|ml|l|lit)\b).){0,80}?"
    r"\b(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l|lit)\b",
    re.I,
)
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
    raw_norm = normalize_text(message)
    # Remove raw money mentions (e.g. 150.000đ) before tokenizing so number fragments don't leak into query
    cleaned_message = _MONEY_RE.sub(" ", raw_norm)
    text = _remove_retailer_names(cleaned_message)
    for phrase in QUERY_NOISE_PHRASES:
        text = re.sub(rf"\b{re.escape(phrase)}\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    words = text.split()
    tokens: list[str] = []
    for token in words:
        is_money_suffix = token.endswith(("k", "d")) and token[:-1].isdigit()
        is_large_number = token.isdigit() and len(token) >= 5
        is_money_fragment = is_money_suffix or is_large_number
        is_noise = token in QUERY_NOISE and not (token == "o" and "long" in words)
        if not is_noise and not is_money_fragment:
            tokens.append(token)
    return tokens


def clean_query(message: str) -> str:
    """Return only product-bearing words from the original user message."""
    return " ".join(_tokens(message))


def _query_with_package(message: str, package: str | None, unit_price_only: bool) -> str:
    """Keep a package in the searchable form used by normalized product names."""
    query = clean_query(message)
    if package:
        # Product names generally contain each-item size (180ml), rather than
        # the normalized bundle total (4x180ml). Keep that lexical signal.
        query = _PACKAGE_RE.sub(package.split("x", 1)[-1], query)
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
    normalized = normalize_text(message)
    multipack = _MULTIPACK_RE.search(normalized)
    if multipack:
        quantity = multipack.group(2).replace(",", ".")
        unit = "l" if multipack.group(3).lower() == "lit" else multipack.group(3).lower()
        return f"{int(multipack.group(1))}x{quantity}{unit}"
    match = _PACKAGE_RE.search(normalized)
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


def _name_phrases(message: str) -> list[str]:
    """Keep product-defining phrases that token cleanup would otherwise lose.

    Accent-insensitive normalization makes "có" (sweetened) and "Cô" in a
    brand look alike.  Phrase filters preserve meaningful variants such as
    "có đường" without making conversational filler part of the search query.
    """
    text = normalize_text(message)
    phrases = ("khong duong", "it duong", "co duong", "socola", "chocolate", "dau", "vi dau")
    return [phrase for phrase in phrases if re.search(rf"\b{re.escape(phrase)}\b", text)]


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
    if intent.retailers:
        return True
    markers = ("con ", "the con", "the sao", "chi lay", "chi can", "loai ", "cai nay", "cai dau", "san pham nay", "o ", "tai ", "ben ")
    return text.startswith(markers)


def infer_name(message: str) -> IntentName:
    normalized = normalize_text(message)
    words = set(normalized.split())
    if any(phrase in normalized for phrase in ("thoi tiet", "chinh tri", "viet code", "lam toan", "tam su", "suc khoe y te", "the thao")):
        return "out_of_scope"
    action = _basket_action(message)
    if action != "none":
        return "basket"
    if not clean_query(message) and (_retailers_in(message) or normalized.startswith(("con", "the", "chi", "loai", "o ", "tai ", "ben "))):
        return "clarification"
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
        name_phrases=_name_phrases(message),
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

    previous_query = str(previous.get("query") or "").strip()
    previous_package = str(previous.get("package") or "").strip() or None
    current_package = intent.package
    query = intent.query

    if not _looks_like_follow_up(message, intent):
        return intent

    previous_name = previous.get("name")
    if previous_name not in {"product_search", "compare_prices", "deals"}:
        previous_name = "product_search"

    # A reply is qualifier-only if there is no non-retailer product query, or if it only specifies a retailer/package modifier.
    retailer_words = {"lotte", "lottemart", "bachhoaxanh", "go", "winmart", "mmvietnam", "mm"}
    non_retailer_query = " ".join(w for w in query.split() if w not in retailer_words)
    qualifier_only = (
        not non_retailer_query
        or non_retailer_query in {"loai", "chi", "con"}
        or (bool(current_package) and non_retailer_query == current_package)
        or (bool(_retailers_in(message)) and not non_retailer_query)
    )
    if qualifier_only and previous_query:
        query = previous_query
        if current_package and previous_package and current_package != previous_package:
            previous_token = previous_package.split("x", 1)[-1]
            query = re.sub(rf"\b{re.escape(previous_token)}\b", " ", query)
        current_token = current_package.split("x", 1)[-1] if current_package else None
        if current_token and current_token not in query.split():
            query = f"{query} {current_token}"
        query = re.sub(r"\s+", " ", query).strip()

    # If this is a standalone query for a DIFFERENT product than the previous conversation,
    # reset all previous brand, package, budget, retailer and promotion filters.
    is_new_product_search = bool(
        not qualifier_only
        and query
        and previous_query
        and normalize_text(query) != normalize_text(previous_query)
    )
    if is_new_product_search:
        new_name = "product_search" if intent.name in ("clarification", "compare_prices", "deals") else intent.name
        return Intent(
            name=new_name,
            query=query,
            brand=intent.brand,
            package=intent.package,
            retailers=intent.retailers,
            min_price=intent.min_price,
            max_price=intent.max_price,
            min_discount_percent=intent.min_discount_percent,
            promotion_only=intent.promotion_only,
            comparison_unit=intent.comparison_unit,
            unit_price_only=intent.unit_price_only,
            data_quality=intent.data_quality,
        )

    normalized_msg = normalize_text(message)
    asks_all_retailers = any(phrase in normalized_msg for phrase in (
        "cac sieu thi", "sieu thi khac", "cac cua hang", "cua hang khac",
        "noi nao khac", "noi khac", "cho nao khac", "cho khac",
        "ngoai bach hoa xanh", "ngoai go", "ngoai lotte", "ngoai lottemart",
        "ngoai winmart", "ngoai mm", "ngoai mega market",
    ))
    target_retailers = [] if asks_all_retailers else (intent.retailers or list(previous.get("retailers") or []))

    return replace(
        intent,
        name=previous_name if intent.name == "clarification" else intent.name,
        query=query,
        retailers=target_retailers,
        promotion_only=intent.promotion_only or bool(previous.get("promotion_only")),
        brand=intent.brand or previous.get("brand"),
        package=current_package or previous_package,
        min_price=intent.min_price if intent.min_price is not None else previous.get("min_price"),
        max_price=intent.max_price if intent.max_price is not None else previous.get("max_price"),
        min_discount_percent=(intent.min_discount_percent if intent.min_discount_percent is not None else previous.get("min_discount_percent")),
        comparison_unit=intent.comparison_unit or previous.get("comparison_unit"),
        unit_price_only=intent.unit_price_only or bool(previous.get("unit_price_only")),
        data_quality=intent.data_quality or previous.get("data_quality"),
        name_phrases=intent.name_phrases or previous.get("name_phrases"),
        sort="unit_price" if intent.unit_price_only or previous.get("unit_price_only") else intent.sort,
        needs_clarification=not bool(query),
        clarification="Bạn muốn tìm hoặc so sánh sản phẩm nào?" if not query else None,
    )
async def parse_intent(
    message: str,
    settings: Settings,
    previous: dict[str, Any] | None = None,
    history: list[dict] | None = None,
) -> Intent:
    """Extract product/brand/retailer fields using Ollama LLM with historical context support."""
    deterministic = fallback_intent(message)

    context_str = ""
    if history:
        history_lines = [
            f"- {'Người dùng' if item.get('role') == 'user' else 'Trợ lý'}: \"{item.get('content')}\""
            for item in history
        ]
        context_str = "\nLịch sử hội thoại gần nhất:\n" + "\n".join(history_lines) + "\n"
    elif previous:
        prev_q = previous.get("query") or ""
        prev_ret = previous.get("retailers") or []
        context_str = f"\nLịch sử trò chuyện trước đó:\n- Sản phẩm đang tìm: '{prev_q}'\n- Siêu thị đã chọn: {prev_ret}\n"

    prompt = (
        "Bạn là bộ trích xuất ý định tìm kiếm cho trợ lý mua sắm siêu thị Việt Nam.\n"
        f"{context_str}"
        "Hãy phân tích câu hỏi của người dùng và trả về JSON duy nhất theo schema:\n"
        "{\n"
        '  "name": "product_search" | "compare_prices" | "deals" | "clarification" | "basket" | "out_of_scope",\n'
        '  "product": "tên sản phẩm/nhóm sản phẩm (ví dụ: khẩu trang, sữa Vinamilk)",\n'
        '  "brand": "thương hiệu hoặc null",\n'
        '  "package": "quy cách (ví dụ: 1L, 180ml, 1kg) hoặc null",\n'
        '  "retailers": ["mảng id siêu thị được nêu: bachhoaxanh, go, lottemart, mmvietnam, winmart"]\n'
        "}\n\n"
        "Quy tắc quan trọng:\n"
        "1. Các câu hỏi hỏi giá thông thường (ví dụ: 'Sữa Vinamilk giá bao nhiêu?', 'tìm giá dầu ăn') thuộc name: \"product_search\". "
        "Chỉ dùng \"compare_prices\" khi người dùng dùng từ 'so sánh' hoặc hỏi 'chỗ nào rẻ nhất', 'ở đâu bán rẻ nhất'.\n"
        "2. Nếu đây là câu hỏi nối tiếp về siêu thị khác cho CÙNG sản phẩm (ví dụ: 'còn lotte thì sao', 'ở GO không có bán hả'), kế thừa sản phẩm cũ. "
        "NHƯNG nếu người dùng hỏi sang một SẢN PHẨM MỚI (ví dụ: 'vậy có sting không?', 'còn nước giặt thì sao?'), đây là yêu cầu tìm kiếm sản phẩm mới, "
        "phải đặt name: \"product_search\" và product: tên sản phẩm mới, KHÔNG kế thừa name: \"compare_prices\" từ sản phẩm cũ.\n"
        "3. Nếu câu hỏi HOÀN TOÀN KHÔNG liên quan đến mua sắm, giá cả, sản phẩm tiêu dùng, siêu thị hay tạp hóa "
        "(ví dụ: hỏi thời tiết, viết code, làm toán, tâm sự, chính trị, y tế chuyên sâu...), trả về name: \"out_of_scope\" và product: null.\n"
        "4. Trả về định dạng JSON hợp lệ duy nhất, không kèm giải thích.\n\n"
        f"Câu hỏi người dùng: \"{message}\""
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
        valid_names = {"product_search", "compare_prices", "deals", "clarification", "basket", "out_of_scope"}
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

    # Require model query to share tokens with original request or previous context to prevent hallucinations
    original_tokens = set(deterministic.query.split())
    if previous and previous.get("query"):
        original_tokens.update(set(str(previous["query"]).split()))

    model_tokens = set(model_query.split())
    if original_tokens:
        safe_model_query = model_query if (model_tokens & original_tokens) else ""
    else:
        safe_model_query = model_query

    final_query = safe_model_query or deterministic.query
    final_retailers = model_retailers or deterministic.retailers
    final_name = model_name or deterministic.name

    resolved = replace(
        deterministic,
        name=final_name,
        query=final_query,
        retailers=final_retailers,
        brand=model_brand or deterministic.brand,
        package=model_package or deterministic.package,
    )
    return apply_conversation_context(resolved, previous, message)
