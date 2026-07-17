from fastapi.testclient import TestClient

from app import main


def _client(monkeypatch):
    monkeypatch.setattr(main, "init_db", lambda: None)
    return TestClient(main.app)


def test_deals_accepts_extended_discovery_filters(monkeypatch):
    captured = {}

    def fake_browse(*args):
        captured["args"] = args
        return ([{"price_snapshot_id": "p1", "snapshot_date": "2026-07-16"}], 1)

    monkeypatch.setattr(main, "browse_deals", fake_browse)
    with _client(monkeypatch) as client:
        response = client.get(
            "/api/deals?retailer_ids=go&brand=Neptune&min_price=10000&max_price=80000"
            "&min_discount_percent=20&comparison_unit=l&unit_price_only=true"
            "&data_quality=valid&sort=unit_price"
        )

    assert response.status_code == 200
    assert captured["args"][6] == ["go"]
    assert captured["args"][7:14] == ("Neptune", 10000.0, 80000.0, 20.0, "l", True, "valid")
    assert response.json()["applied_filters"]["comparison_unit"] == "l"


def test_autocomplete_and_insights_are_public(monkeypatch):
    monkeypatch.setattr(main, "autocomplete_offers", lambda *args: [{"price_snapshot_id": "p1", "product_name": "Dau an"}])
    monkeypatch.setattr(main, "offer_insights", lambda *args: {"offer": {"price_snapshot_id": "p1"}, "same_product_offers": [], "similar_offers": [], "summary": {}})
    with _client(monkeypatch) as client:
        autocomplete = client.get("/api/deals/autocomplete?q=dau%20an")
        insights = client.get("/api/deals/p1/insights")

    assert autocomplete.status_code == 200
    assert autocomplete.json()["items"][0]["price_snapshot_id"] == "p1"
    assert insights.status_code == 200
    assert insights.json()["offer"]["price_snapshot_id"] == "p1"


def test_price_history_is_public(monkeypatch):
    monkeypatch.setattr(main, "price_history", lambda *_: {
        "offer": {"price_snapshot_id": "p1"},
        "series": [{"snapshot_date": "2026-07-14", "current_price": 30000}],
        "summary": {"point_count": 1},
    })
    with _client(monkeypatch) as client:
        response = client.get("/api/deals/p1/history?days=30")

    assert response.status_code == 200
    assert response.json()["summary"]["point_count"] == 1


def test_basket_optimize_validates_and_returns_public_plan(monkeypatch):
    expected = {"items": [], "selected_total": 0, "single_retailer_options": [], "split_order": {"lines": [], "total": 0}, "unavailable_items": [], "snapshot_date": "2026-07-16"}
    monkeypatch.setattr(main, "optimize_basket", lambda items: expected)
    with _client(monkeypatch) as client:
        response = client.post("/api/basket/optimize", json={"items": [{"price_snapshot_id": "p1", "quantity": 2}]})
        invalid = client.post("/api/basket/optimize", json={"items": [{"price_snapshot_id": "p1", "quantity": 0}]})

    assert response.status_code == 200
    assert response.json()["snapshot_date"] == "2026-07-16"
    assert invalid.status_code == 422
