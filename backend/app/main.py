from __future__ import annotations
import asyncio, datetime, json, os, re, uuid

FEW_SHOT_EXAMPLES = (
    "VÍ DỤ MẪU CHUẨN (FEW-SHOT EXAMPLES):\n"
    "Ví dụ 1:\n"
    "  FACTS: [{\"product_name\": \"Sữa Vinamilk 1L\", \"retailer_name\": \"WinMart\", \"price\": \"30.000đ\", \"discount\": \"10%\"}]\n"
    "  Câu hỏi: \"Sữa Vinamilk giá bao nhiêu?\"\n"
    "  Mẫu trả lời tốt: \"Dạ em thấy Sữa Vinamilk 1L tại WinMart đang có giá tốt nhất là 30.000đ (đang giảm 10%). Bạn có thể tham khảo mua tại siêu thị WinMart gần nhất nhé! 😊\"\n\n"
    "Ví dụ 2:\n"
    "  FACTS: [{\"product_name\": \"Dầu ăn Neptune 1L\", \"retailer_name\": \"GO!\", \"price\": \"54.500đ\"}, {\"product_name\": \"Dầu ăn Neptune 1L\", \"retailer_name\": \"Lotte Mart\", \"price\": \"58.000đ\"}]\n"
    "  Câu hỏi: \"So sánh giá dầu ăn Neptune giữa GO! và Lotte Mart\"\n"
    "  Mẫu trả lời tốt: \"Dạ qua so sánh, Dầu ăn Neptune 1L tại GO! có giá tốt hơn là 54.500đ, rẻ hơn so với Lotte Mart đang bán 58.000đ. Bạn mua ở GO! sẽ tiết kiệm được 3.500đ nhé!\"\n\n"
    "Ví dụ 3:\n"
    "  FACTS: [{\"product_name\": \"Nước giặt OMO 3kg\", \"retailer_name\": \"Bách Hóa Xanh\", \"price\": \"145.000đ\", \"discount\": \"25%\"}]\n"
    "  Câu hỏi: \"Có ưu đãi nước giặt nào trên 20% không?\"\n"
    "  Mẫu trả lời tốt: \"Dạ tại Bách Hóa Xanh đang có ưu đãi Nước giặt OMO 3kg giảm đến 25%, giá chỉ còn 145.000đ. Đây là mức giảm rất tốt để bạn mua sắm đợt này ạ.\"\n\n"
)


async def _generate_grounded_answer(
    message: str, intent: Intent, offers: list[dict], fallback_answer: str,
) -> str | None:
    """Ask Ollama to phrase verified facts in warm, friendly, non-technical Vietnamese."""
    if not settings.ollama_answer_generation or not offers:
        return None
    facts = _answer_facts(intent, offers)
    prompt = (
        "Bạn là Trợ lý PriceLy thân thiện, ấm áp và chu đáo giúp người dùng so sánh giá siêu thị.\n"
        "Hãy trả lời người dùng bằng giọng văn tự nhiên, lịch sự, dễ hiểu với người tiêu dùng bình thường (xưng 'Em', gọi người dùng là 'Bạn' hoặc 'Anh/Chị').\n"
        "KHÔNG DÙNG ngôn ngữ kỹ thuật hoặc thuật ngữ máy tính (như 'snapshot', 'data quality', 'valid', 'facts', 'query', 'database', 'SQL').\n\n"
        f"{FEW_SHOT_EXAMPLES}"
        "Chỉ dựa vào danh sách sản phẩm thực tế đã xác minh dưới đây:\n"
        f"FACTS:\n{json.dumps(facts, ensure_ascii=False, default=str)}\n\n"
        "Câu hỏi người dùng:\n"
        f"{json.dumps(message, ensure_ascii=False)}\n\n"
        "Yêu cầu:\n"
        "1. Trả lời ngắn gọn, nêu rõ tên siêu thị thực tế và sản phẩm có giá tốt nhất.\n"
        "2. Giữ nguyên đúng giá trị tiền tệ và phần trăm giảm giá trong FACTS.\n"
        "3. Trả về đúng 1 JSON object có dạng {\"answer\": \"câu trả lời tự nhiên của bạn\"}.\n"
    )
    try:
        async with httpx.AsyncClient(timeout=settings.ollama_answer_timeout_seconds) as client:
            response = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={"model": settings.ollama_model, "prompt": prompt, "format": "json", "stream": False},
            )
            response.raise_for_status()
        data = json.loads(response.json()["response"])
        answer = data.get("answer")
        if not isinstance(answer, str):
            return None
        answer = re.sub(r"\s+", " ", answer).strip()
        if not 8 <= len(answer) <= 800 or re.search(
            r"\b(select|insert|update|delete|sql|json|prompt)\b|\bt[aấ]t c[aả]\b|\bm[oọ]i\b|kh[oô]ng \w+ cung c[aấ]p",
            answer,
            re.I,
        ):
            return None
        if not _has_fact_price(answer, facts):
            return None
        return answer
    except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
from contextlib import asynccontextmanager
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
import httpx
from .config import get_settings
from .database import engine, init_db
from .intent import Intent, apply_conversation_context, clean_query, parse_intent
from .matching import normalize_text
from .repository import autocomplete_offers, browse_deals, compare_offers, conversation_context, latest_snapshot_date, latest_sync, offer_insights, optimize_basket, price_history, recent_conversation_history, save_assistant, save_conversation, search_offers, seeded_offers
from .sync import run_sync

settings = get_settings()


def _trigger_auto_sync() -> str | None:
    run_id = str(uuid.uuid4())
    try:
        with engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(913401)"))
            already_running = conn.execute(text("SELECT 1 FROM sync_runs WHERE status='running' LIMIT 1")).first()
            if already_running:
                return None
            conn.execute(
                text("INSERT INTO sync_runs(id,status,details) VALUES (:id,'running',CAST(:details AS jsonb))"),
                {
                    "id": run_id,
                    "details": json.dumps({
                        "progress": {
                            "completed": 0, "total": 0, "percent": 0,
                            "stage": "queued", "message": "Tự động đồng bộ MinIO 8h00…"
                        },
                        "trigger": "scheduled_8am"
                    }, ensure_ascii=False)
                },
            )
        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, _execute_auto_sync_worker, run_id)
        except RuntimeError:
            pass
        return run_id
    except Exception:
        return None


def _execute_auto_sync_worker(run_id: str):
    try:
        run_sync(settings, run_id)
    except Exception as exc:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE sync_runs SET status='failed',finished_at=now(),details=jsonb_build_object('error',CAST(:error AS text),'progress',jsonb_build_object('stage','failed','message','Tự động đồng bộ thất bại')) WHERE id=:id"),
                {"id": run_id, "error": str(exc)},
            )


async def daily_sync_scheduler():
    """Check every 60s. At 8:00 AM daily (or startup past 8 AM), if latest DB snapshot < today, auto-trigger MinIO sync."""
    last_triggered_date = None
    while True:
        try:
            now = datetime.datetime.now()
            today_str = now.date().isoformat()
            if now.hour >= 8 and last_triggered_date != today_str:
                snapshot_date = latest_snapshot_date()
                if snapshot_date and snapshot_date < today_str:
                    last_triggered_date = today_str
                    _trigger_auto_sync()
                else:
                    last_triggered_date = today_str
        except Exception:
            pass
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    task = asyncio.create_task(daily_sync_scheduler())
    yield
    task.cancel()

app = FastAPI(title="Pricebot API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_methods=["*"], allow_headers=["*"], allow_credentials=False)

class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    seed_price_snapshot_id: str | None = None

class BasketItem(BaseModel):
    price_snapshot_id: str = Field(min_length=1, max_length=256)
    quantity: int = Field(default=1, ge=1, le=99)


class BasketOptimizeRequest(BaseModel):
    items: list[BasketItem] = Field(min_length=1, max_length=50)

def event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def snapshot_context(offers: list[dict]) -> tuple[list[str], str]:
    dates = sorted({str(offer["snapshot_date"]) for offer in offers if offer.get("snapshot_date")})
    return dates, f" (Dữ liệu cập nhật ngày {', '.join(dates)})." if dates else ""


RETAILER_LABELS = {
    "bachhoaxanh": "Bách Hóa Xanh",
    "go": "GO!",
    "lottemart": "Lotte Mart",
    "mmvietnam": "MM Mega Market",
    "winmart": "WinMart",
}
PACKAGE_PATTERN = re.compile(r"^(?:(\d+)\s*x\s*)?(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l)$", re.I)


def _money(value: object) -> str:
    try:
        return f"{float(value):,.0f}".replace(",", ".") + "đ"
    except (TypeError, ValueError):
        return "không rõ giá"


def _retailer_name(retailer_id: object) -> str:
    return RETAILER_LABELS.get(str(retailer_id), str(retailer_id or "nhà bán lẻ này"))


def _matches_requested_package(offer: dict, requested: str) -> bool:
    """Require the requested sellable quantity when the user stated one.

    Full-text search is intentionally fuzzy, but a 1L request must not become an
    80ml recommendation.  Gold's package total is already normalized to g/ml.
    """
    match = PACKAGE_PATTERN.match(requested.strip())
    if not match:
        return True
    requested_multiplier = int(match.group(1) or 1)
    requested_value = float(match.group(2).replace(",", "."))
    requested_unit = match.group(3).lower()
    requested_base = requested_multiplier * requested_value * (1000 if requested_unit in {"kg", "l"} else 1)
    requested_kind = "mass" if requested_unit in {"kg", "g"} else "volume"
    measurement = str(offer.get("measurement_type") or "")
    if measurement and measurement != requested_kind:
        return False
    total = offer.get("package_total_base_quantity")
    if total is None:
        try:
            total = float(offer.get("package_quantity")) * int(offer.get("package_multiplier") or 1)
        except (TypeError, ValueError):
            total = None
    try:
        return abs(float(total) - requested_base) < 0.01
    except (TypeError, ValueError):
        # Do not manufacture an exact match if the source lacks package metadata.
        return False


def _history_trend(offer: dict) -> str:
    """Describe only an observed, retailer-scoped day-to-day movement.

    The price-history endpoint can contain multiple retailers for a canonical
    product.  A recommendation must never compare their separate histories as
    though they were one store, so this deliberately stays within the selected
    retailer and uses its lowest recorded quote for each date.
    """
    try:
        history = price_history(str(offer["price_snapshot_id"]), 7)
    except Exception:
        return ""
    if not history:
        return ""
    by_date: dict[str, float] = {}
    for point in history.get("series", []):
        if point.get("retailer_id") != offer.get("retailer_id") or not point.get("snapshot_date"):
            continue
        try:
            price = float(point["current_price"])
        except (TypeError, ValueError):
            continue
        date = str(point["snapshot_date"])
        by_date[date] = min(by_date.get(date, price), price)
    dates = sorted(by_date)
    if len(dates) < 2:
        return ""
    previous_date, latest_date = dates[-2:]
    previous, latest = by_date[previous_date], by_date[latest_date]
    difference = latest - previous
    retailer = _retailer_name(offer.get("retailer_id"))
    if abs(difference) < 0.5:
        return f"Giá thấp nhất ghi nhận tại {retailer} đang giữ nguyên so với {previous_date}."
    percent = abs(difference) / previous * 100 if previous else 0
    direction = "giảm" if difference < 0 else "tăng"
    return (
        f"Giá thấp nhất ghi nhận tại {retailer} ngày {latest_date} đã {direction} "
        f"{_money(abs(difference))} ({percent:.1f}%) so với {previous_date}."
    )


def _shopping_advice(intent: Intent, offers: list[dict], *, comparable: bool = False) -> str:
    """Turn verified search results into a concise, purchase-oriented answer."""
    if not offers:
        return ""
    best = offers[0]
    product = str(best.get("product_name") or "sản phẩm này")
    retailer = _retailer_name(best.get("retailer_id"))
    price = _money(best.get("current_price"))
    if comparable:
        advice = f"Dạ em gợi ý bạn nên chọn {product} tại {retailer} với giá tốt nhất là {price}."
        if len(offers) > 1:
            runner_up = offers[1]
            try:
                saving = float(runner_up["current_price"]) - float(best["current_price"])
            except (TypeError, ValueError):
                saving = 0
            if saving > 0:
                advice += f" Giá này tiết kiệm hơn nơi tiếp theo {_money(saving)}."
    elif intent.name == "deals":
        discount = best.get("discount_percent")
        discount_text = f", đang giảm {float(discount):.0f}%" if discount is not None else ""
        advice = f"Dạ có ưu đãi hấp dẫn: {product} tại {retailer}, giá chỉ {price}{discount_text}."
    else:
        advice = f"Dạ em thấy {product} tại {retailer} đang có giá tốt nhất: {price}."

    if best.get("effective_unit_price") is not None and best.get("comparison_unit"):
        advice += f" Tính ra đơn giá khoảng {_money(best['effective_unit_price'])}/{best['comparison_unit']}."
    if best.get("silver_data_quality_status") not in (None, "valid"):
        advice += " Thông tin này bạn nên kiểm tra lại trên website siêu thị trước khi đặt mua nha."
    trend = _history_trend(best)
    return f"{advice} {trend}".strip()


def _filter_chat_offers(offers: list[dict], intent: Intent) -> list[dict]:
    """Apply every structured chat constraint to searched or seeded offers."""
    filters = intent.filters()
    result: list[dict] = []
    for offer in offers:
        price = float(offer.get("current_price") or 0)
        if filters.get("min_price") is not None and price < float(filters["min_price"]):
            continue
        if filters.get("max_price") is not None and price > float(filters["max_price"]):
            continue
        if filters.get("min_discount_percent") is not None and float(offer.get("discount_percent") or 0) < float(filters["min_discount_percent"]):
            continue
        if filters.get("brand") and normalize_text(str(filters["brand"])) not in normalize_text(str(offer.get("brand") or "")):
            continue
        if filters.get("comparison_unit") and offer.get("comparison_unit") != filters["comparison_unit"]:
            continue
        if filters.get("unit_price_only") and (not offer.get("unit_price_publishable") or offer.get("effective_unit_price") is None):
            continue
        if filters.get("data_quality") and offer.get("silver_data_quality_status") != filters["data_quality"]:
            continue
        if intent.package and not _matches_requested_package(offer, intent.package):
            continue
        result.append(offer)
    return result


def _search_for_intent(intent: Intent) -> list[dict]:
    """Search with the same structured filters used by the public discovery API."""
    return search_offers(
        intent.query, intent.retailers, intent.promotion_only, 30,
        filters=intent.filters(), sort=intent.sort, settings=settings,
    )


def _browse_for_intent(intent: Intent) -> list[dict]:
    """Handle a broad deal request with filters but no product phrase."""
    rows, _ = browse_deals(
        None, "", "discount" if intent.min_discount_percent is not None else "featured", "all", 1, 30,
        brand=intent.brand, min_price=intent.min_price, max_price=intent.max_price,
        min_discount_percent=intent.min_discount_percent, comparison_unit=intent.comparison_unit,
        unit_price_only=intent.unit_price_only, data_quality=intent.data_quality or "all", settings=settings,
    )
    return rows


def _offer_ids(offers: list[dict]) -> list[str]:
    return [str(offer["price_snapshot_id"]) for offer in offers if offer.get("price_snapshot_id")][:10]


def _answer_facts(intent: Intent, offers: list[dict]) -> list[dict]:
    """Return a deliberately small, JSON-safe set of facts for answer phrasing.

    Search, filtering and ranking have already happened before this point.  The
    model receives no database access, SQL, or untrusted offer fields beyond the
    facts it may mention in its response.
    """
    return [
        {
            "product": offer.get("product_name"),
            "retailer": _retailer_name(offer.get("retailer_id")),
            "price": _money(offer.get("current_price")),
            "discount_percent": offer.get("discount_percent"),
            "unit_price": (
                f"{_money(offer['effective_unit_price'])}/{offer['comparison_unit']}"
                if offer.get("effective_unit_price") is not None and offer.get("comparison_unit")
                else None
            ),
            "promotion": offer.get("promotion_text"),
        }
        for offer in offers[:3]
    ]


def _has_fact_price(answer: str, facts: list[dict]) -> bool:
    for fact in facts:
        raw_price = str(fact.get("price") or "")
        if not raw_price or raw_price == "không rõ giá":
            continue
        digits = re.sub(r"[^\d]", "", raw_price)
        if not digits:
            continue
        formatted = f"{int(digits):,}".replace(",", ".")
        price_k = f"{int(digits)//1000}k" if int(digits) >= 1000 and int(digits) % 1000 == 0 else ""
        if formatted in answer or (price_k and price_k in answer.lower()) or raw_price in answer or digits in answer:
            return True
    return False


async def _generate_grounded_answer(
    message: str, intent: Intent, offers: list[dict], fallback_answer: str,
) -> str | None:
    """Ask Ollama to phrase verified facts in warm, friendly, non-technical Vietnamese."""
    if not settings.ollama_answer_generation or not offers:
        return None
    facts = _answer_facts(intent, offers)
    prompt = (
        "Bạn là Trợ lý PriceLy thân thiện, ấm áp và chu đáo giúp người dùng so sánh giá siêu thị.\n"
        "Hãy trả lời người dùng bằng giọng văn tự nhiên, lịch sự, dễ hiểu với người tiêu dùng bình thường (xưng 'Em', gọi người dùng là 'Bạn' hoặc 'Anh/Chị').\n"
        "KHÔNG DÙNG ngôn ngữ kỹ thuật hoặc thuật ngữ máy tính (như 'snapshot', 'data quality', 'valid', 'facts', 'query', 'database', 'SQL').\n\n"
        "Chỉ dựa vào danh sách sản phẩm thực tế đã xác minh dưới đây:\n"
        f"FACTS:\n{json.dumps(facts, ensure_ascii=False, default=str)}\n\n"
        "Câu hỏi người dùng:\n"
        f"{json.dumps(message, ensure_ascii=False)}\n\n"
        "Yêu cầu:\n"
        "1. Trả lời ngắn gọn, nêu rõ sản phẩm nào ở siêu thị nào có giá tốt nhất.\n"
        "2. Giữ nguyên đúng giá trị tiền tệ và phần trăm giảm giá trong FACTS.\n"
        "3. Trả về đúng 1 JSON object có dạng {\"answer\": \"câu trả lời tự nhiên của bạn\"}.\n"
    )
    try:
        async with httpx.AsyncClient(timeout=settings.ollama_answer_timeout_seconds) as client:
            response = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={"model": settings.ollama_model, "prompt": prompt, "format": "json", "stream": False},
            )
            response.raise_for_status()
        data = json.loads(response.json()["response"])
        answer = data.get("answer")
        if not isinstance(answer, str):
            return None
        answer = re.sub(r"\s+", " ", answer).strip()
        if not 8 <= len(answer) <= 800 or re.search(
            r"\b(select|insert|update|delete|sql|json|prompt)\b|\bt[aấ]t c[aả]\b|\bm[oọ]i\b|kh[oô]ng \w+ cung c[aấ]p",
            answer,
            re.I,
        ):
            return None
        if not _has_fact_price(answer, facts):
            return None
        return answer
    except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


async def _evaluate_llm_answer(
    message: str, intent: Intent, answer: str, facts: list[dict]
) -> tuple[bool, float, dict[str, float], str]:
    """Ask Ollama to evaluate candidate `answer` on Grounding, Relevance, Tone, Completeness (1-5 scale)."""
    if not settings.ollama_answer_evaluation:
        return True, 5.0, {"grounding": 5.0, "relevance": 5.0, "tone": 5.0, "completeness": 5.0}, "Evaluation disabled"
    if not answer or not message:
        return False, 0.0, {"grounding": 0.0, "relevance": 0.0, "tone": 0.0, "completeness": 0.0}, "Empty answer or message"

    prompt = (
        "Bạn là Chuyên gia Đánh giá (LLM-as-a-Judge) cho hệ thống chatbot mua sắm PriceLy.\n"
        "Hãy chấm điểm CÂU TRẢ LỜI dựa trên CÂU HỎI NGƯỜI DÙNG và DỮ LIỆU THỰC TẾ (FACTS).\n\n"
        f"DỮ LIỆU THỰC TẾ (FACTS):\n{json.dumps(facts, ensure_ascii=False, default=str)}\n\n"
        f"CÂU HỎI NGƯỜI DÙNG:\n{json.dumps(message, ensure_ascii=False)}\n\n"
        f"CÂU TRẢ LỜI CẦN ĐÁNH GIÁ:\n{json.dumps(answer, ensure_ascii=False)}\n\n"
        "Hãy chấm điểm từ 1 đến 5 cho 4 tiêu chí sau:\n"
        "1. grounding: Mức độ trung thực với FACTS (không tự bịa giá, phần trăm giảm giá hay siêu thị).\n"
        "2. relevance: Mức độ trả lời trực tiếp đúng sản phẩm người dùng hỏi (nếu nêu được giá sản phẩm đúng trong FACTS thì điểm relevance >= 4.0).\n"
        "3. tone: Giọng văn thân thiện (xưng Em, gọi Bạn/Anh/Chị), tự nhiên, không từ ngữ kỹ thuật.\n"
        "4. completeness: Thông tin đầy đủ, rõ ràng về giá và siêu thị tốt nhất.\n\n"
        "Trả về duy nhất 1 JSON object có dạng:\n"
        "{\n"
        '  "grounding": 1.0 đến 5.0,\n'
        '  "relevance": 1.0 đến 5.0,\n'
        '  "tone": 1.0 đến 5.0,\n'
        '  "completeness": 1.0 đến 5.0,\n'
        '  "feedback": "gợi ý cải thiện ngắn gọn nếu có"\n'
        "}\n"
    )
    try:
        async with httpx.AsyncClient(timeout=settings.ollama_eval_timeout_seconds) as client:
            response = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={"model": settings.ollama_model, "prompt": prompt, "format": "json", "stream": False},
            )
            response.raise_for_status()
        data = json.loads(response.json()["response"])
        g = float(data.get("grounding", 3.0))
        r = float(data.get("relevance", 3.0))
        t = float(data.get("tone", 4.0))
        c = float(data.get("completeness", 3.0))
        metrics = {"grounding": g, "relevance": r, "tone": t, "completeness": c}
        avg_score = round((g + r + t + c) / 4.0, 2)
        feedback = str(data.get("feedback") or ("Đạt yêu cầu đánh giá" if avg_score >= settings.ollama_eval_pass_score else "Cần cải thiện độ chính xác và mức độ đáp ứng câu hỏi"))
        passed = (avg_score >= settings.ollama_eval_pass_score) and (g >= 3.0) and (r >= 3.0)
        return passed, avg_score, metrics, feedback
    except Exception as exc:
        return False, 0.0, {"grounding": 0.0, "relevance": 0.0, "tone": 0.0, "completeness": 0.0}, f"Lỗi khi đánh giá hoặc quá thời gian: {exc}"


async def _refine_llm_answer(
    message: str, intent: Intent, candidate_answer: str, facts: list[dict], feedback: str
) -> str | None:
    """Ask LLM to self-refine candidate_answer using feedback from the LLM Evaluator."""
    if not settings.ollama_answer_generation or not facts:
        return None

    prompt = (
        "Bạn là Trợ lý PriceLy. Câu trả lời ban đầu của bạn chưa đạt yêu cầu đánh giá chất lượng.\n"
        f"GỢI Ý CẢI THIỆN TỪ CHUYÊN GIA:\n\"{feedback}\"\n\n"
        f"DỮ LIỆU THỰC TẾ (FACTS):\n{json.dumps(facts, ensure_ascii=False, default=str)}\n\n"
        f"CÂU HỎI NGƯỜI DÙNG:\n{json.dumps(message, ensure_ascii=False)}\n\n"
        f"CÂU TRẢ LỜI CỦ:\n{json.dumps(candidate_answer, ensure_ascii=False)}\n\n"
        "Hãy viết lại một CÂU TRẢ LỜI MỚI hoàn chỉnh, tự nhiên, thân thiện (xưng 'Em', gọi 'Bạn' hoặc 'Anh/Chị'), "
        "khắc phục hoàn toàn các điểm chưa tốt ở câu trả lời cũ và bám sát FACTS.\n\n"
        "Trả về đúng 1 JSON object dạng {\"answer\": \"câu trả lời cải thiện của bạn\"}.\n"
    )
    try:
        async with httpx.AsyncClient(timeout=settings.ollama_answer_timeout_seconds) as client:
            response = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={"model": settings.ollama_model, "prompt": prompt, "format": "json", "stream": False},
            )
            response.raise_for_status()
        data = json.loads(response.json()["response"])
        refined = data.get("answer")
        if not isinstance(refined, str):
            return None
        refined = re.sub(r"\s+", " ", refined).strip()
        if not 8 <= len(refined) <= 800 or re.search(
            r"\b(select|insert|update|delete|sql|json|prompt)\b|\bt[aấ]t c[aả]\b|\bm[oọ]i\b",
            refined,
            re.I,
        ):
            return None
        if not _has_fact_price(refined, facts):
            return None
        return refined
    except Exception:
        return None


def _log_evaluation_result(cid: str, message: str, intent: Intent, answer: str, eval_result: dict) -> None:
    """Append evaluation event to backend/logs/eval_history.jsonl for continuous tracking."""
    try:
        log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "eval_history.jsonl")
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "conversation_id": cid,
            "message": message,
            "intent": intent.name,
            "query": intent.query,
            "answer_snippet": answer[:200],
            "eval_result": eval_result,
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


@app.get("/api/health")
async def health():
    database = "ok"
    try:
        with engine.connect() as conn: conn.execute(text("SELECT 1"))
    except Exception: database = "error"
    ollama = "unavailable"
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            ollama = "ok" if (await client.get(f"{settings.ollama_base_url}/api/tags")).is_success else "error"
    except Exception: pass
    return {"database": database, "ollama": ollama, "latest_sync": latest_sync()}


@app.get("/api/deals")
def deals(
    retailer_id: str | None = None,
    retailer_ids: list[str] = Query(default=[]),
    q: str = "",
    brand: str | None = None,
    min_price: float | None = Query(default=None, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    min_discount_percent: float | None = Query(default=None, ge=0, le=100),
    comparison_unit: str | None = None,
    unit_price_only: bool = False,
    data_quality: str = Query("all", pattern="^(all|valid|warning)$"),
    sort: str = Query("featured", pattern="^(featured|discount|price|unit_price|newest)$"),
    promotion_type: str = Query("all", pattern="^(all|discount|mechanic|flag)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=48),
):
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(422, "min_price must not exceed max_price")
    items, total = browse_deals(
        retailer_id, q, sort, promotion_type, page, page_size, retailer_ids or None,
        brand, min_price, max_price, min_discount_percent, comparison_unit,
        unit_price_only, data_quality, settings,
    )
    dates = sorted({str(item["snapshot_date"]) for item in items if item.get("snapshot_date")}, reverse=True)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
        "snapshot_date": dates[0] if dates else None,
        "applied_filters": {
            "retailer_id": retailer_id,
            "retailer_ids": retailer_ids,
            "brand": brand,
            "min_price": min_price,
            "max_price": max_price,
            "min_discount_percent": min_discount_percent,
            "comparison_unit": comparison_unit,
            "unit_price_only": unit_price_only,
            "data_quality": data_quality,
            "promotion_type": promotion_type,
        },
    }


@app.get("/api/deals/overview")
def deals_overview(
    q: str = "",
    retailer_id: str | None = None,
    brand: str | None = None,
    min_price: float | None = Query(default=None, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    min_discount_percent: float | None = Query(default=None, ge=0, le=100),
    comparison_unit: str | None = None,
    unit_price_only: bool = False,
    data_quality: str = Query("all", pattern="^(all|valid|warning)$"),
    sort: str = Query("featured", pattern="^(featured|discount|price|unit_price|newest)$"),
    promotion_type: str = Query("all", pattern="^(all|discount|mechanic|flag)$"),
):
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(422, "min_price must not exceed max_price")
    retailer_ids = ["bachhoaxanh", "go", "lottemart", "mmvietnam", "winmart"]
    if retailer_id:
        retailer_ids = [retailer_id] if retailer_id in retailer_ids else []
    sections = []
    for retailer_id in retailer_ids:
        items, total = browse_deals(
            retailer_id, q, sort, promotion_type, 1, 15,
            None, brand, min_price, max_price, min_discount_percent,
            comparison_unit, unit_price_only, data_quality, settings,
        )
        sections.append({"retailer_id": retailer_id, "items": items, "total": total, "has_more": total > 15})
    dates = sorted({str(item["snapshot_date"]) for section in sections for item in section["items"] if item.get("snapshot_date")}, reverse=True)
    return {"sections": sections, "snapshot_date": dates[0] if dates else None}


@app.get("/api/deals/autocomplete")
def deals_autocomplete(
    q: str = Query(min_length=1, max_length=160),
    retailer_ids: list[str] = Query(default=[]),
    limit: int = Query(8, ge=1, le=12),
):
    return {"items": autocomplete_offers(q, retailer_ids or None, limit)}


@app.get("/api/deals/{price_snapshot_id}/insights")
def deal_insights(price_snapshot_id: str, similar_limit: int = Query(8, ge=1, le=20)):
    result = offer_insights(price_snapshot_id, similar_limit)
    if not result:
        raise HTTPException(404, "Offer not found in the current snapshot")
    return result


@app.get("/api/deals/{price_snapshot_id}/history")
def deal_price_history(price_snapshot_id: str, days: int = Query(90, ge=1, le=3650)):
    result = price_history(price_snapshot_id, days)
    if not result:
        raise HTTPException(404, "Offer not found in current or historical data")
    return result


@app.post("/api/basket/optimize")
def basket_optimize(payload: BasketOptimizeRequest):
    return optimize_basket([item.model_dump() for item in payload.items])

@app.post("/api/chat/stream")
async def chat(request: ChatRequest):
    async def stream():
        try: cid = save_conversation(request.message, request.conversation_id)
        except PermissionError: raise HTTPException(404, "Không tìm thấy cuộc trò chuyện")
        yield event("conversation", {"conversation_id": cid})
        previous = conversation_context(cid)
        history = recent_conversation_history(cid, limit=5)
        intent = apply_conversation_context(await parse_intent(request.message, settings, previous, history), previous, request.message)
        if intent.name == "clarification":
            answer = intent.clarification or "Bạn muốn tiếp tục tìm hoặc so sánh sản phẩm nào?"
            payload = {"intent": "clarification", "offers": [], "needs_clarification": True, "context": previous}
            save_assistant(cid, answer, payload)
            yield event("answer", {"content": answer})
            yield event("results", payload)
            yield event("done", {})
            return
        if intent.name == "out_of_scope":
            answer = (
                "Dạ em là Trợ lý PriceLy, chuyên giúp bạn tìm giá tốt và so sánh sản phẩm "
                "tại các siêu thị như Bách Hóa Xanh, GO!, Lotte Mart, WinMart và MM Mega Market. 😊\n\n"
                "Bạn cần em tìm giá sản phẩm nào không ạ? Ví dụ:\n"
                "• \"Sữa Vinamilk 1L giá bao nhiêu?\"\n"
                "• \"So sánh giá dầu ăn ở các siêu thị\"\n"
                "• \"Có ưu đãi gì đang giảm trên 30% không?\""
            )
            payload = {"intent": "out_of_scope", "offers": [], "context": previous}
            save_assistant(cid, answer, payload)
            yield event("answer", {"content": answer})
            yield event("results", payload)
            yield event("done", {})
            return
        if intent.name == "product_search" and not intent.query:
            answer = "Bạn muốn tìm sản phẩm nào? Ví dụ: “so sánh sữa Vinamilk 1L”, “dầu ăn dưới 100.000đ” hoặc “ưu đãi giảm trên 20%”."
            payload = {"intent": "clarification", "offers": [], "needs_clarification": True, "context": previous}
            save_assistant(cid, answer, payload)
            yield event("answer", {"content": answer})
            yield event("results", payload)
            yield event("done", {})
            return
        if intent.name == "basket":
            offer_ids = previous.get("offer_ids") if isinstance(previous, dict) else []
            action = intent.basket_action
            if action == "optimize":
                answer = "Mở Giỏ hàng để xem phương án mua tại một sàn hoặc chia đơn tiết kiệm nhất."
            elif action == "add" and len(offer_ids or []) == 1:
                answer = "Mình đã nhận yêu cầu thêm sản phẩm vừa xem vào Giỏ hàng."
            elif action == "add":
                answer = "Bạn muốn thêm sản phẩm nào? Hãy chọn một sản phẩm trong kết quả gần nhất."
            else:
                answer = "Mở Giỏ hàng để xem và điều chỉnh các sản phẩm đã chọn."
            payload = {
                "intent": "basket", "offers": [], "basket_action": action,
                "suggested_price_snapshot_id": offer_ids[0] if action == "add" and len(offer_ids or []) == 1 else None,
                "requires_client_basket": True, "context": previous,
            }
            save_assistant(cid, answer, payload)
            yield event("answer", {"content": answer})
            yield event("results", payload)
            yield event("done", {})
            return
        offers = seeded_offers(request.seed_price_snapshot_id) if request.seed_price_snapshot_id else (_search_for_intent(intent) if intent.query else _browse_for_intent(intent))
        offers = _filter_chat_offers(offers, intent)
        fallback_query = clean_query(request.message)
        if not offers and fallback_query != intent.query:
            intent.query = fallback_query
            offers = _filter_chat_offers(_search_for_intent(intent), intent)
        snapshot_dates, freshness = snapshot_context(offers)
        if intent.name == "compare_prices":
            reliable, near = compare_offers(offers)
            selected = reliable
            if len({x['retailer_id'] for x in reliable}) >= 2:
                answer = _shopping_advice(intent, reliable, comparable=True)
                answer += f" Đã xác minh {len(reliable)} lựa chọn tại {len({x['retailer_id'] for x in reliable})} nhà bán lẻ và xếp theo giá tăng dần.{freshness}"
            elif near:
                answer = f"Chưa đủ bằng chứng để khẳng định các sản phẩm này cùng một quy cách, nên mình chưa khuyến nghị nơi mua rẻ nhất. Đây là các kết quả gần đúng để bạn kiểm tra quy cách.{freshness}"
                selected = near
            else: answer = "Chưa tìm thấy sản phẩm có thể so sánh đủ tin cậy. Bạn có thể nêu rõ thương hiệu hoặc quy cách, ví dụ 1L hay 500g."
            payload = {
                "intent": intent.name,
                "offers": selected,
                "near_matches": near,
                "exact_matches": reliable,
                "similar_offers": near,
                "retailer_count": len({x['retailer_id'] for x in reliable}),
                "snapshot_dates": snapshot_dates,
            }
        elif intent.name == "deals":
            selected = sorted(offers, key=lambda x: (x.get("discount_percent") or 0, -(float(x["current_price"]))), reverse=True)
            with_offer_terms = sum(1 for offer in selected if offer.get("promotion_text"))
            if selected:
                answer = _shopping_advice(intent, selected)
                answer += f" Có {len(selected)} ưu đãi phù hợp; {with_offer_terms} kết quả có điều kiện ưu đãi để bạn kiểm tra trước khi mua.{freshness}"
            else:
                answer = "Chưa tìm thấy ưu đãi khớp điều kiện. Bạn có thể thử nêu mức giảm mong muốn hoặc nhóm sản phẩm."
            payload = {"intent": intent.name, "offers": selected, "retailer_count": len({x['retailer_id'] for x in selected}), "snapshot_dates": snapshot_dates}
        else:
            selected = sorted(offers, key=lambda x: float(x["current_price"]))
            if selected:
                answer = _shopping_advice(intent, selected)
                answer += f" Có {len(selected)} kết quả cho “{intent.query}”, đã xếp từ thấp đến cao.{freshness}"
            else:
                answer = f"Chưa tìm thấy kết quả phù hợp cho “{intent.query}”. Bạn hãy thử tên ngắn hơn, thương hiệu hoặc quy cách sản phẩm."
            payload = {"intent": intent.name, "offers": selected, "retailer_count": len({x['retailer_id'] for x in selected}), "snapshot_dates": snapshot_dates}
        payload["filters"] = intent.filters()
        payload["context"] = intent.context_payload(_offer_ids(selected))
        facts = _answer_facts(intent, selected)
        generated_answer = await _generate_grounded_answer(request.message, intent, selected, answer)
        if generated_answer:
            passed, score, metrics, feedback = await _evaluate_llm_answer(request.message, intent, generated_answer, facts)
            refined_used = False
            if not passed and settings.ollama_max_refine_attempts > 0:
                refined_candidate = await _refine_llm_answer(request.message, intent, generated_answer, facts, feedback)
                if refined_candidate:
                    ref_passed, ref_score, ref_metrics, ref_feedback = await _evaluate_llm_answer(request.message, intent, refined_candidate, facts)
                    if ref_score >= score:
                        generated_answer = refined_candidate
                        passed, score, metrics, feedback = ref_passed, ref_score, ref_metrics, ref_feedback
                        refined_used = True

            payload["eval_result"] = {
                "passed": passed,
                "score": score,
                "metrics": metrics,
                "feedback": feedback,
                "refined": refined_used,
            }
            if passed:
                answer = generated_answer
                payload["answer_source"] = "llm_grounded_evaluated"
            else:
                answer = (
                    "Dạ em tìm thấy một số sản phẩm liên quan bên dưới, nhưng câu trả lời tự động chưa đảm bảo giải đáp chính xác câu hỏi của bạn. "
                    "Bạn có thể thử điều chỉnh câu hỏi rõ hơn (ví dụ: nêu thương hiệu, quy cách hoặc siêu thị cụ thể) để em hỗ trợ tốt hơn nhé! 😊"
                )
                payload["answer_source"] = "llm_eval_failed_fallback_notice"
        else:
            payload["answer_source"] = "template_fallback"
        save_assistant(cid, answer, payload)
        _log_evaluation_result(cid, request.message, intent, answer, payload.get("eval_result", {}))
        yield event("answer", {"content": answer})
        yield event("results", payload)
        yield event("done", {})
    return StreamingResponse(stream(), media_type="text/event-stream")

@app.post("/api/admin/sync")
async def start_sync(background_tasks: BackgroundTasks):
    run_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(913401)"))
        already_running = conn.execute(text("SELECT 1 FROM sync_runs WHERE status='running' LIMIT 1")).first()
        if already_running:
            raise HTTPException(409, "Đồng bộ đang chạy")
        conn.execute(
            text("INSERT INTO sync_runs(id,status,details) VALUES (:id,'running',CAST(:details AS jsonb))"),
            {"id": run_id, "details": json.dumps({"progress": {"completed": 0, "total": 0, "percent": 0, "stage": "queued", "message": "Đang xếp hàng đồng bộ…"}}, ensure_ascii=False)},
        )
    def worker():
        try: run_sync(settings, run_id)
        except Exception as exc:
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE sync_runs SET status='failed',finished_at=now(),details=jsonb_build_object('error',CAST(:error AS text),'progress',jsonb_build_object('stage','failed','message','Đồng bộ thất bại')) WHERE id=:id"),
                    {"id": run_id, "error": str(exc)},
                )
    background_tasks.add_task(worker)
    return {"id": run_id, "status": "running"}

@app.get("/api/admin/sync/{run_id}")
def sync_status(run_id: str):
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id::text,status,started_at,finished_at,details FROM sync_runs WHERE id=:id"), {"id":run_id}).first()
    if not row: raise HTTPException(404, "Không tìm thấy lần đồng bộ")
    return dict(row._mapping)
