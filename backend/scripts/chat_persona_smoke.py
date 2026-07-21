"""Run realistic chatbot personas against a running Pricebot API.

Usage (from backend/):
    python scripts/chat_persona_smoke.py

Set PRICEBOT_API_URL to target another environment.  This intentionally checks
the SSE contract and behaviour rather than exact prices, which change on sync.
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
    response = client.post(f"{API}/api/chat/stream", json=payload, timeout=50)
    response.raise_for_status()
    events: dict[str, dict[str, Any]] = {}
    for block in response.text.strip().split("\n\n"):
        lines = block.splitlines()
        if len(lines) < 2 or not lines[0].startswith("event: ") or not lines[1].startswith("data: "):
            continue
        events[lines[0][7:]] = json.loads(lines[1][6:])
    required = {"conversation", "answer", "results", "done"}
    missing = required - events.keys()
    if missing:
        raise AssertionError(f"{message!r}: missing SSE events {sorted(missing)}")
    if not str(events["answer"].get("content") or "").strip():
        raise AssertionError(f"{message!r}: empty answer")
    return events


def expect(events: dict[str, dict[str, Any]], intent: str, label: str) -> None:
    actual = events["results"].get("intent")
    if actual != intent:
        raise AssertionError(f"{label}: expected intent={intent!r}, got {actual!r}")


def main() -> int:
    with httpx.Client() as client:
        health = client.get(f"{API}/api/health", timeout=10)
        health.raise_for_status()
        if health.json().get("database") != "ok":
            raise AssertionError("database health check failed")

        # Basic discovery, structured budget filtering, and broad promotion browse.
        simple = chat(client, "Sữa Vinamilk giá bao nhiêu?")
        expect(simple, "product_search", "simple search")
        budget = chat(client, "Tìm dầu ăn Neptune dưới 100k")
        expect(budget, "product_search", "budget filter")
        deals = chat(client, "Ưu đãi giảm trên 20%")
        expect(deals, "deals", "promotion browse")

        # A per-item 180ml declaration must be treated as a 4 × 180ml bundle.
        bundle = chat(client, "So sánh lốc 4 hộp sữa Cô Gái Hà Lan có đường 180ml, chỗ nào rẻ nhất?")
        expect(bundle, "compare_prices", "multipack comparison")
        context = bundle["results"].get("context", {})
        if context.get("package") != "4x180ml":
            raise AssertionError(f"multipack comparison: expected package 4x180ml, got {context.get('package')!r}")

        # Follow-up relies on compact persisted conversation context, not a new prompt history.
        follow_up = chat(client, "Còn Lotte thì sao?", bundle["conversation"]["conversation_id"])
        expect(follow_up, "compare_prices", "retailer follow-up")

        basket = chat(client, "Tối ưu danh sách mua của tôi")
        expect(basket, "basket", "basket action")
        if not basket["results"].get("requires_client_basket"):
            raise AssertionError("basket action must request client-side basket handling")

    print("chat persona smoke: passed (simple, filter, deals, multipack, follow-up, basket)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (httpx.HTTPError, AssertionError, KeyError, ValueError) as exc:
        print(f"chat persona smoke: failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
