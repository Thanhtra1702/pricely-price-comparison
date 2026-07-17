from app.search_index import content_hash, offer_search_text


def test_offer_search_document_keeps_useful_product_context():
    document = offer_search_text({
        "product_name": "Sữa tươi không đường 1L",
        "canonical_name": "Sữa tươi Vinamilk 1 lít",
        "brand": "Vinamilk",
        "category_raw": "Sữa tươi",
        "measurement_type": "volume",
        "comparison_unit": "ml",
    })
    assert "Sữa tươi không đường 1L" in document
    assert "Vinamilk" in document
    assert "Sữa tươi" in document


def test_offer_search_document_hash_is_stable_and_content_sensitive():
    first = content_hash("nước giặt | omo")
    assert first == content_hash("nước giặt | omo")
    assert first != content_hash("nước giặt | aba")
