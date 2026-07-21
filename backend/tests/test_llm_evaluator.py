import asyncio
import json
from app import main
from app.intent import Intent


def test_evaluate_llm_answer_calculates_metrics_and_score(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {
                "response": json.dumps({
                    "grounding": 4.5,
                    "relevance": 5.0,
                    "tone": 4.0,
                    "completeness": 4.5,
                    "feedback": "Phản hồi rất tốt"
                })
            }

    class Client:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def post(self, *_args, **_kwargs): return Response()

    monkeypatch.setattr(main.httpx, "AsyncClient", Client)
    passed, score, metrics, feedback = asyncio.run(main._evaluate_llm_answer(
        "Sữa Vinamilk bao nhiêu?",
        Intent(name="product_search", query="sua vinamilk", retailers=[]),
        "Sữa Vinamilk 1L tại WinMart có giá 30.000đ.",
        [{"product_name": "Sữa Vinamilk 1L", "current_price": "30.000đ", "price": "30000"}]
    ))
    assert passed is True
    assert score >= 4.0
    assert metrics["grounding"] == 4.5
    assert metrics["relevance"] == 5.0
    assert "tốt" in feedback


def test_refine_llm_answer_generates_improved_response(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {"response": json.dumps({"answer": "Sữa Vinamilk 1L giá 30.000đ tại WinMart."})}

    class Client:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def post(self, *_args, **_kwargs): return Response()

    monkeypatch.setattr(main.httpx, "AsyncClient", Client)
    refined = asyncio.run(main._refine_llm_answer(
        "Sữa Vinamilk bao nhiêu?",
        Intent(name="product_search", query="sua vinamilk", retailers=[]),
        "Sữa ngon 30000đ",
        [{"product_name": "Sữa Vinamilk 1L", "current_price": "30000", "price": "30000"}],
        "Hãy nêu tên siêu thị cụ thể"
    ))
    assert refined is not None
    assert "30.000đ" in refined or "30000" in refined
