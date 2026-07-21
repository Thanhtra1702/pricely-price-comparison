import json
from decimal import Decimal

from fastapi.testclient import TestClient
from app.intent import Intent
from app import main


def test_chat_package_filter_does_not_turn_one_litre_into_80ml():
    offer = {"measurement_type": "volume", "package_total_base_quantity": 480}
    assert main._matches_requested_package(offer, "1l") is False
    offer["package_total_base_quantity"] = 1000
    assert main._matches_requested_package(offer, "1l") is True


def test_chat_package_filter_accepts_matching_multipack_total():
    offer = {"measurement_type": "volume", "package_total_base_quantity": 720}
    assert main._matches_requested_package(offer, "4x180ml") is True
    offer["package_total_base_quantity"] = 180
    assert main._matches_requested_package(offer, "4x180ml") is False


def test_answer_facts_are_json_safe_for_postgresql_decimals():
    facts = main._answer_facts(
        Intent(name="product_search", query="sua", retailers=[]),
        [{
            "product_name": "Sữa mẫu", "retailer_id": "go", "current_price": Decimal("26900"),
            "discount_percent": Decimal("15.142"), "effective_unit_price": Decimal("37.361111"),
            "comparison_unit": "ml",
        }],
    )
    assert json.loads(json.dumps(facts, ensure_ascii=False, default=str))[0]["discount_percent"] == "15.142"


def test_grounded_answer_rejects_unsupported_absence_claim(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"response": '{"answer":"Không có ưu đãi nào khác."}'}

    class Client:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def post(self, *_args, **_kwargs): return Response()

    monkeypatch.setattr(main.httpx, "AsyncClient", Client)
    import asyncio
    result = asyncio.run(main._generate_grounded_answer(
        "Có ưu đãi gì?", Intent(name="deals", query="", retailers=[]),
        [{"product_name": "Sản phẩm", "retailer_id": "go", "current_price": 10000}], "fallback",
    ))
    assert result is None


def test_grounded_answer_requires_an_exact_verified_price(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"response": '{"answer":"Tất cả sản phẩm đều đang giảm giá."}'}

    class Client:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def post(self, *_args, **_kwargs): return Response()

    monkeypatch.setattr(main.httpx, "AsyncClient", Client)
    import asyncio
    result = asyncio.run(main._generate_grounded_answer(
        "Có ưu đãi gì?", Intent(name="deals", query="", retailers=[]),
        [{"product_name": "Sản phẩm", "retailer_id": "go", "current_price": 10000}], "fallback",
    ))
    assert result is None


def test_chat_stream_returns_facts_not_generated_sql(monkeypatch):
    monkeypatch.setattr(main, "init_db", lambda: None)
    async def fake_intent(*_):
        return Intent(name="product_search", query="vinamilk", retailers=[])
    monkeypatch.setattr(main, "parse_intent", fake_intent)
    monkeypatch.setattr(main, "save_conversation", lambda *_: "conversation-1")
    monkeypatch.setattr(main, "save_assistant", lambda *_: None)
    monkeypatch.setattr(main, "search_offers", lambda *_, **__: [{"price_snapshot_id": "p1", "retailer_id": "winmart", "product_name": "Sua Vinamilk", "current_price": 30000}])
    async def fake_grounded(*_):
        return "Sữa Vinamilk tại WinMart hiện là lựa chọn phù hợp giá 30.000đ."
    async def fake_eval(*_):
        return True, 4.5, {"grounding": 4.5, "relevance": 4.5, "tone": 4.5, "completeness": 4.5}, "Phù hợp"
    monkeypatch.setattr(main, "_generate_grounded_answer", fake_grounded)
    monkeypatch.setattr(main, "_evaluate_llm_answer", fake_eval)
    with TestClient(main.app) as client:
        response = client.post("/api/chat/stream", json={"message": "Sua Vinamilk gia bao nhieu?"})
    assert response.status_code == 200
    assert "event: results" in response.text
    assert "Sua Vinamilk" in response.text
    assert "llm_grounded_evaluated" in response.text
    assert "SELECT" not in response.text


def test_chat_stream_evaluation_failure_shows_fallback_notice(monkeypatch):
    monkeypatch.setattr(main, "init_db", lambda: None)
    async def fake_intent(*_):
        return Intent(name="product_search", query="vinamilk", retailers=[])
    monkeypatch.setattr(main, "parse_intent", fake_intent)
    monkeypatch.setattr(main, "save_conversation", lambda *_: "conversation-1")
    monkeypatch.setattr(main, "save_assistant", lambda *_: None)
    monkeypatch.setattr(main, "search_offers", lambda *_, **__: [{"price_snapshot_id": "p1", "retailer_id": "winmart", "product_name": "Sua Vinamilk", "current_price": 30000}])
    async def fake_grounded(*_):
        return "Sữa tươi ngon lắm mua ngay đi 30.000đ."
    async def fake_eval(*_):
        return False, 2.0, {"grounding": 2.0, "relevance": 2.0, "tone": 4.0, "completeness": 2.0}, "Cần cải thiện"
    monkeypatch.setattr(main, "_generate_grounded_answer", fake_grounded)
    monkeypatch.setattr(main, "_evaluate_llm_answer", fake_eval)
    with TestClient(main.app) as client:
        response = client.post("/api/chat/stream", json={"message": "Sua Vinamilk gia bao nhieu?"})
    assert response.status_code == 200
    assert "llm_eval_failed_notice" in response.text
    assert "câu trả lời tự động chưa đảm bảo giải đáp chính xác" in response.text


def test_deals_overview_is_public_and_grouped_by_retailer(monkeypatch):
    monkeypatch.setattr(main, "init_db", lambda: None)
    calls = []
    def fake_browse(retailer_id, *_):
        calls.append(retailer_id)
        return ([{"price_snapshot_id": retailer_id, "retailer_id": retailer_id, "snapshot_date": "2026-07-16"}], 16)
    monkeypatch.setattr(main, "browse_deals", fake_browse)
    with TestClient(main.app) as client:
        response = client.get("/api/deals/overview?sort=discount&promotion_type=all")
    assert response.status_code == 200
    assert calls == ["bachhoaxanh", "go", "lottemart", "mmvietnam", "winmart"]
    body = response.json()
    assert len(body["sections"]) == 5
    assert body["sections"][0]["has_more"] is True
    assert body["snapshot_date"] == "2026-07-16"


def test_seeded_chat_handoff_prefers_seed_results(monkeypatch):
    monkeypatch.setattr(main, "init_db", lambda: None)
    async def fake_intent(*_): return Intent(name="compare_prices", query="ignored", retailers=[])
    monkeypatch.setattr(main, "parse_intent", fake_intent)
    monkeypatch.setattr(main, "save_conversation", lambda *_: "conversation-1")
    monkeypatch.setattr(main, "save_assistant", lambda *_: None)
    monkeypatch.setattr(main, "seeded_offers", lambda identifier: [{"price_snapshot_id": "p1", "retailer_id": "go", "product_name": "Seed", "current_price": 10000}] if identifier == "seed-1" else [])
    monkeypatch.setattr(main, "search_offers", lambda *_, **__: [])
    with TestClient(main.app) as client:
        response = client.post("/api/chat/stream", json={"message": "so sanh", "seed_price_snapshot_id": "seed-1"})
    assert response.status_code == 200
    assert "Seed" in response.text
