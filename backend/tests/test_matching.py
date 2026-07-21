from app.matching import extract_package, is_reliable_match, match_confidence, normalize_text, signature
from app.repository import compare_offers


def test_normalizes_vietnamese_and_symbols():
    assert normalize_text("Sữa Tươi Vinamilk – Không Đường!") == "sua tuoi vinamilk khong duong"


def test_extracts_equivalent_litre_and_millilitre():
    assert extract_package("Dầu ăn 2L") == (2000.0, "ml", 1)
    assert extract_package("Sua 6 x 180ml") == (180.0, "ml", 6)
    assert extract_package("Sua loc 4 hop x 180ml") == (180.0, "ml", 4)
    assert extract_package("Sua hat 1 lit") == (1000.0, "ml", 1)


def test_rejects_different_package_or_brand():
    assert match_confidence(signature("Dau an Neptune 1L", "Neptune"), signature("Dau an Neptune 2L", "Neptune")) == 0
    assert not is_reliable_match(signature("Sua tuoi 1L", "Vinamilk"), signature("Sua tuoi 1L", "TH True Milk"))


def test_accepts_same_product():
    left = signature("Sua tuoi Vinamilk khong duong 1L", "Vinamilk")
    right = signature("Sữa tươi không đường Vinamilk 1000ml", "Vinamilk")
    assert is_reliable_match(left, right)


def test_accepts_brand_with_country_suffix():
    assert is_reliable_match(signature("Sua Vinamilk khong duong 1L", "Vinamilk"), signature("Sua Vinamilk khong duong 1000ml", "Vinamilk Viet Nam"))


def test_compare_prefers_canonical_product_mapping():
    offers = [
        {"price_snapshot_id": "a", "retailer_id": "go", "product_name": "Tên khác nhau", "brand": "A", "current_price": 30000, "canonical_product_id": "canonical-1"},
        {"price_snapshot_id": "b", "retailer_id": "winmart", "product_name": "Tên khác hoàn toàn", "brand": "B", "current_price": 25000, "canonical_product_id": "canonical-1"},
        {"price_snapshot_id": "c", "retailer_id": "lottemart", "product_name": "Sản phẩm khác", "brand": "C", "current_price": 10000, "canonical_product_id": "canonical-2"},
    ]
    reliable, near = compare_offers(offers)
    assert [item["price_snapshot_id"] for item in reliable] == ["b", "a"]
    assert reliable[0]["match_confidence"] == 1.0
    assert [item["price_snapshot_id"] for item in near] == ["c"]
