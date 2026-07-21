"""Continuous LLM Evaluation & Benchmark Runner for PriceLy Chatbot.

Usage (from workspace root or backend):
    python backend/scripts/eval_llm_chatbot.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx

API = os.getenv("PRICEBOT_API_URL", "http://localhost:8000").rstrip("/")


def chat(client: httpx.Client, message: str, conversation_id: str | None = None) -> dict[str, Any]:
    payload: dict[str, str] = {"message": message}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    response = client.post(f"{API}/api/chat/stream", json=payload, timeout=60)
    response.raise_for_status()
    events: dict[str, dict[str, Any]] = {}
    for block in response.text.strip().split("\n\n"):
        lines = block.splitlines()
        if len(lines) < 2 or not lines[0].startswith("event: ") or not lines[1].startswith("data: "):
            continue
        events[lines[0][7:]] = json.loads(lines[1][6:])
    return events


def run_benchmark() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("=" * 80)
    print("PRICELY CHATBOT - LLM CONTINUOUS EVALUATION BENCHMARK")
    print("=" * 80)

    scenarios = [
        {"name": "Single Product Search", "prompt": "Sữa Vinamilk giá bao nhiêu?", "expected_intent": "product_search"},
        {"name": "Budget & Brand Filter", "prompt": "Tìm dầu ăn Neptune dưới 100k", "expected_intent": "product_search"},
        {"name": "Deals & Promotion Browse", "prompt": "Ưu đãi giảm trên 20%", "expected_intent": "deals"},
        {"name": "Multipack Comparison", "prompt": "So sánh lốc 4 hộp sữa Cô Gái Hà Lan có đường 180ml, chỗ nào rẻ nhất?", "expected_intent": "compare_prices"},
        {"name": "Retailer Follow-up", "prompt": "Còn Lotte thì sao?", "expected_intent": "compare_prices", "requires_previous": True},
        {"name": "New Topic Transition", "prompt": "vậy có sting không?", "expected_intent": "product_search", "requires_previous": True},
        {"name": "Out of Scope Query", "prompt": "Thời tiết Hà Nội hôm nay thế nào?", "expected_intent": "out_of_scope"},
    ]

    total = len(scenarios)
    passed_count = 0
    scores: list[float] = []

    with httpx.Client() as client:
        # Verify API health
        try:
            health = client.get(f"{API}/api/health", timeout=10)
            health.raise_for_status()
            print(f"[+] Connected to API at {API} (Ollama status: {health.json().get('ollama')})\n")
        except Exception as exc:
            print(f"[-] API Health Check failed: {exc}", file=sys.stderr)
            return 1

        previous_cid: str | None = None

        for idx, sc in enumerate(scenarios, 1):
            cid = previous_cid if sc.get("requires_previous") else None
            try:
                events = chat(client, sc["prompt"], cid)
            except Exception as exc:
                print(f"[{idx}/{total}] FAIL: {sc['name']} -> HTTP Error: {exc}")
                continue

            results = events.get("results", {})
            answer = str(events.get("answer", {}).get("content") or "").strip()
            cid = events.get("conversation", {}).get("conversation_id")
            previous_cid = cid

            actual_intent = results.get("intent")
            answer_source = results.get("answer_source", "unknown")
            eval_res = results.get("eval_result", {})

            passed = eval_res.get("passed", True) if "eval_result" in results else True
            score = float(eval_res.get("score", 5.0 if answer_source == "llm_grounded_evaluated" else 3.5))
            metrics = eval_res.get("metrics", {})
            feedback = eval_res.get("feedback", "N/A")

            scores.append(score)
            if passed and actual_intent == sc["expected_intent"]:
                passed_count += 1
                status_str = "PASS"
            else:
                status_str = "REVIEW"

            print(f"[{idx}/{total}] {status_str} | {sc['name']}")
            print(f"   Prompt: \"{sc['prompt']}\"")
            print(f"   Intent: {actual_intent} (Expected: {sc['expected_intent']})")
            print(f"   Answer Source: {answer_source} | Refined: {eval_res.get('refined', False)}")
            print(f"   LLM-as-a-Judge Score: {score:.1f}/5.0 (Metrics: {metrics})")
            print(f"   Feedback: {feedback}")
            print(f"   Answer Snippet: {answer[:120]}...\n")

    avg_score = sum(scores) / len(scores) if scores else 0.0
    pass_rate = (passed_count / total) * 100

    print("=" * 80)
    print(f"EVALUATION SUMMARY: Pass Rate = {pass_rate:.1f}% ({passed_count}/{total}) | Average LLM Score = {avg_score:.2f}/5.0")
    print("=" * 80)
    return 0 if pass_rate >= 80 else 1


if __name__ == "__main__":
    sys.exit(run_benchmark())
