import asyncio
from types import SimpleNamespace
from app import intent
from app.intent import apply_conversation_context, clean_query, fallback_intent


def test_compare_intent_and_retailer_filter():
    intent = fallback_intent("So sánh giá dầu ăn Neptune giữa WinMart và GO")
    assert intent.name == "compare_prices"
    assert set(intent.retailers) == {"winmart", "go"}


def test_deals_intent():
    intent = fallback_intent("Có ưu đãi nước giặt nào?")
    assert intent.name == "deals"
    assert intent.promotion_only


def test_long_question_keeps_only_the_product_terms():
    intent = fallback_intent("So sanh dau an Neptune 2L giua cac cua hang")
    assert intent.name == "compare_prices"
    assert intent.query == "dau an neptune 2l"
    assert clean_query("Sua Vinamilk nao re nhat?") == "sua vinamilk"
    assert clean_query("Toi muon mua nuoc Sting") == "nuoc sting"
    assert clean_query("Bot giat thi sao?") == "bot giat"
    assert clean_query("Toi cung muon mua 1 it kem danh rang") == "1 kem danh rang"
    assert clean_query("tôi muốn mua chả giò") == "cha gio"
    assert clean_query("Bánh bao Thọ Phát") == "banh bao tho phat"
    assert clean_query("Tương ớt cay") == "tuong ot cay"
    assert clean_query("Bia 333 330ml") == "bia 333 330ml"
    assert clean_query("Trà ô long Tea+ Plus") == "tra o long tea plus"


def test_multipack_keeps_item_size_for_search_but_filters_bundle_total():
    result = fallback_intent("So sánh lốc 4 hộp sữa Cô Gái Hà Lan có đường 180ml")
    assert result.package == "4x180ml"
    assert "180ml" in result.query
    assert "4x180ml" not in result.query
    assert result.name_phrases == ["co duong"]


def test_parser_repairs_invalid_model_json_once(monkeypatch):
    responses = ["not json", '{"name":"deals","product":"nuoc giat","brand":null,"package":null,"retailers":["winmart"]}']

    class Response:
        def raise_for_status(self): pass
        def json(self): return {"response": responses.pop(0)}

    class Client:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def post(self, *_args, **_kwargs): return Response()

    monkeypatch.setattr(intent.httpx, "AsyncClient", Client)
    result = asyncio.run(intent.parse_intent("Co uu dai nuoc giat nao?", SimpleNamespace(ollama_base_url="http://ollama", ollama_model="test")))
    assert result.name == "deals"
    assert result.retailers == ["winmart"]


def test_parser_uses_structured_product_from_model(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"response": '{"name":"product_search","product":"kem danh rang","brand":null,"package":null,"retailers":[]}'}

    class Client:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def post(self, *_args, **_kwargs): return Response()

    monkeypatch.setattr(intent.httpx, "AsyncClient", Client)
    result = asyncio.run(intent.parse_intent("Toi muon mua kem danh rang", SimpleNamespace(ollama_base_url="http://ollama", ollama_model="test")))
    assert result.query == "kem danh rang"


def test_parser_rejects_unrelated_product_from_model(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"response": '{"name":"product_search","product":"bot giat","brand":null,"package":null,"retailers":[]}'}

    class Client:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def post(self, *_args, **_kwargs): return Response()

    monkeypatch.setattr(intent.httpx, "AsyncClient", Client)
    result = asyncio.run(intent.parse_intent("Toi muon mua kem danh rang", SimpleNamespace(ollama_base_url="http://ollama", ollama_model="test")))
    assert result.query == "kem danh rang"


def test_structured_budget_unit_and_quality_filters_are_deterministic():
    result = fallback_intent("T\u00ecm n\u01b0\u1edbc gi\u1eb7t d\u01b0\u1edbi 150.000\u0111 \u1edf WinMart")
    assert result.retailers == ["winmart"]
    assert result.max_price == 150000
    assert result.query == "nuoc giat"

    unit = fallback_intent("D\u1ea7u \u0103n lo\u1ea1i 1 l\u00edt gi\u00e1 theo l\u00edt r\u1ebb nh\u1ea5t")
    assert unit.comparison_unit == "ml"
    assert unit.unit_price_only is True
    assert unit.sort == "unit_price"

    deals = fallback_intent("\u01afu \u0111\u00e3i gi\u1ea3m tr\u00ean 30% c\u00f3 d\u1eef li\u1ec7u valid")
    assert deals.name == "deals"
    assert deals.min_discount_percent == 30
    assert deals.data_quality == "valid"


def test_follow_up_uses_previous_product_but_replaces_retailer_and_package():
    previous = {
        "name": "compare_prices",
        "query": "dau an neptune 2l",
        "retailers": ["go"],
        "package": "2l",
    }
    lotte = apply_conversation_context(fallback_intent("C\u00f2n Lotte th\u00ec sao?"), previous, "C\u00f2n Lotte th\u00ec sao?")
    assert lotte.name == "compare_prices"
    assert lotte.query == "dau an neptune 2l"
    assert lotte.retailers == ["lottemart"]

    one_kg = apply_conversation_context(fallback_intent("Ch\u1ec9 l\u1ea5y lo\u1ea1i 1kg"), previous, "Ch\u1ec9 l\u1ea5y lo\u1ea1i 1kg")
    assert one_kg.query == "dau an neptune 1kg"
    assert one_kg.package == "1kg"


def test_basket_requests_are_recognized_without_server_basket_state():
    result = fallback_intent("T\u1ed1i \u01b0u danh s\u00e1ch mua c\u1ee7a t\u00f4i")
    assert result.name == "basket"
    assert result.basket_action == "optimize"


def test_retailer_follow_up_with_filler_words_retains_previous_query():
    previous = {
        "name": "product_search",
        "query": "khau trang",
        "retailers": ["bachhoaxanh"],
    }
    lotte_follow_up = apply_conversation_context(
        fallback_intent("ở lottemart không có sao"),
        previous,
        "ở lottemart không có sao"
    )
    assert lotte_follow_up.name == "product_search"
    assert lotte_follow_up.query == "khau trang"
    assert lotte_follow_up.retailers == ["lottemart"]

    go_follow_up = apply_conversation_context(
        fallback_intent("Ở GO không có bán hả"),
        previous,
        "Ở GO không có bán hả"
    )
    assert go_follow_up.name == "product_search"
    assert go_follow_up.query == "khau trang"
    assert go_follow_up.retailers == ["go"]

    other_retailers_follow_up = apply_conversation_context(
        fallback_intent("ở các siêu thị khác không có bán sao"),
        previous,
        "ở các siêu thị khác không có bán sao"
    )
    assert other_retailers_follow_up.name == "product_search"
    assert other_retailers_follow_up.query == "khau trang"
    assert other_retailers_follow_up.retailers == []

    exclude_retailer_follow_up = apply_conversation_context(
        fallback_intent("có nơi nào khác có bán ngoài bách hóa xanh không"),
        previous,
        "có nơi nào khác có bán ngoài bách hóa xanh không"
    )
    assert exclude_retailer_follow_up.name == "product_search"
    assert exclude_retailer_follow_up.query == "khau trang"
    assert exclude_retailer_follow_up.retailers == []


def test_new_product_query_resets_previous_context_and_brand():
    previous = {
        "name": "product_search",
        "query": "khau trang",
        "brand": "An Phuc",
        "retailers": ["bachhoaxanh"],
    }
    sting_intent = apply_conversation_context(
        fallback_intent("vậy có sting không?"),
        previous,
        "vậy có sting không?"
    )
    assert sting_intent.query == "sting"
    assert sting_intent.brand is None
    assert sting_intent.retailers == []
