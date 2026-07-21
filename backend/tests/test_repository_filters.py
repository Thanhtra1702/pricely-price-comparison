from app import repository


def test_brand_filter_matches_product_name_when_gold_brand_is_empty():
    filters: list[str] = []
    params: dict[str, object] = {}
    repository._add_common_offer_filters(filters, params, brand="Vinamilk")
    assert "o.normalized_brand LIKE :brand_token_0 OR o.normalized_name LIKE :brand_token_0" in filters[0]
    assert params["brand_token_0"] == "%vinamilk%"
