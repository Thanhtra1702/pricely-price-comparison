from fastapi.testclient import TestClient
from app.intent import Intent
from app import main


def test_chat_package_filter_does_not_turn_one_litre_into_80ml():
    offer = {"measurement_type": "volume", "package_total_base_quantity": 480}
    assert main._matches_requested_package(offer, "1l") is False
    offer["package_total_base_quantity"] = 1000
    assert main._matches_requested_package(offer, "1l") is True


def test_chat_stream_returns_facts_not_generated_sql(monkeypatch):
    monkeypatch.setattr(main, "init_db", lambda: None)
    async def fake_intent(*_):
        return Intent(name="product_search", query="vinamilk", retailers=[])
    monkeypatch.setattr(main, "parse_intent", fake_intent)
    monkeypatch.setattr(main, "save_conversation", lambda *_: "conversation-1")
    monkeypatch.setattr(main, "save_assistant", lambda *_: None)
    monkeypatch.setattr(main, "search_offers", lambda *_, **__: [{"price_snapshot_id": "p1", "retailer_id": "winmart", "product_name": "Sua Vinamilk", "current_price": 30000}])
    with TestClient(main.app) as client:
        response = client.post("/api/chat/stream", json={"message": "Sua Vinamilk gia bao nhieu?"})
    assert response.status_code == 200
    assert "event: results" in response.text
    assert "Sua Vinamilk" in response.text
    assert "SELECT" not in response.text


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
