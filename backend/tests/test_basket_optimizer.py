from app import repository


def _offer(identifier, retailer, price, quality):
    return {
        "price_snapshot_id": identifier,
        "canonical_product_id": "prod_susu_cam",
        "retailer_id": retailer,
        "product_name": "Lốc 6 chai Vinamilk Susu hương cam 80ml",
        "current_price": price,
        "silver_data_quality_status": quality,
        "snapshot_date": "2026-07-16",
    }


def test_split_plan_never_replaces_a_cheaper_live_offer_with_expensive_valid_row(monkeypatch):
    winmart = _offer("winmart-susu", "winmart", 22700, "warning")
    lotte = _offer("lotte-susu", "lottemart", 26500, "valid")
    monkeypatch.setattr(repository, "_offers_for_snapshot_ids", lambda _: {"winmart-susu": winmart})
    monkeypatch.setattr(repository, "_canonical_candidates", lambda _: {"prod_susu_cam": [winmart, lotte]})

    result = repository.optimize_basket([{"price_snapshot_id": "winmart-susu", "quantity": 1}])

    assert result["selected_total"] == 22700
    assert result["split_order"]["total"] == 22700
    assert result["split_order"]["savings_vs_selected"] == 0
    assert result["split_order"]["retailer_id"] == "winmart"
    assert result["split_order"]["lines"][0]["price_snapshot_id"] == "winmart-susu"
    assert result["split_order"]["uses_warning_data"] is True
