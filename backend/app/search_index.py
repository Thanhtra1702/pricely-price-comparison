"""Small, dependency-light semantic index for the current offer snapshot.

The serving dataset is intentionally modest (a few thousand offers), so the index
uses Ollama embeddings plus a NumPy matrix instead of requiring pgvector or another
service.  Lexical search remains the source of truth and is always available.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Iterable

import httpx
import numpy as np
from sqlalchemy import text

from .config import Settings
from .database import engine


_cached_ids: list[str] = []
_cached_vectors: np.ndarray | None = None
_cached_marker: tuple[int, str] | None = None
_cached_query_scores: dict[tuple[str, str, tuple[int, str]], dict[str, float]] = {}


def offer_search_text(row: dict) -> str:
    """Create one stable, user-facing document per offer for semantic retrieval."""
    values = (
        row.get("product_name"),
        row.get("canonical_name"),
        row.get("brand"),
        # category_raw is useful semantic context, but is never exposed as a global
        # category facet because retailer taxonomies are inconsistent.
        row.get("category_raw"),
        row.get("measurement_type"),
        row.get("comparison_unit"),
    )
    return " | ".join(str(value).strip() for value in values if value and str(value).strip())


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _embed(settings: Settings, inputs: list[str]) -> list[list[float]]:
    if not inputs:
        return []
    response = httpx.post(
        f"{settings.ollama_base_url}/api/embed",
        json={"model": settings.embedding_model, "input": inputs},
        timeout=settings.embedding_timeout_seconds,
    )
    response.raise_for_status()
    values = response.json().get("embeddings")
    if not isinstance(values, list) or len(values) != len(inputs):
        raise RuntimeError("Ollama không trả về embedding hợp lệ")
    return values


def invalidate_cache() -> None:
    global _cached_ids, _cached_vectors, _cached_marker, _cached_query_scores
    _cached_ids, _cached_vectors, _cached_marker = [], None, None
    _cached_query_scores = {}


def _cache_marker() -> tuple[int, str]:
    with engine.connect() as conn:
        count, updated_at = conn.execute(
            text("SELECT count(*), COALESCE(max(updated_at)::text, '') FROM offer_search_embeddings_current")
        ).one()
    return int(count), str(updated_at)


def _load_cache() -> tuple[list[str], np.ndarray] | None:
    global _cached_ids, _cached_vectors, _cached_marker
    marker = _cache_marker()
    if _cached_vectors is not None and _cached_marker == marker:
        return _cached_ids, _cached_vectors
    if not marker[0]:
        return None
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT price_snapshot_id, embedding FROM offer_search_embeddings_current ORDER BY price_snapshot_id")
        ).mappings().all()
    ids = [str(row["price_snapshot_id"]) for row in rows]
    vectors = np.asarray([row["embedding"] for row in rows], dtype=np.float32)
    if vectors.ndim != 2 or not len(ids):
        return None
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    vectors = vectors / np.maximum(norms, 1e-12)
    _cached_ids, _cached_vectors, _cached_marker = ids, vectors, marker
    return ids, vectors


def semantic_scores(settings: Settings, query: str) -> dict[str, float]:
    """Return cosine scores when the optional local index is available.

    Any model/database issue is deliberately isolated: callers can retain lexical
    ranking without affecting public search or chatbot answers.
    """
    try:
        cached = _load_cache()
        if not cached:
            return {}
        ids, vectors = cached
        marker = _cached_marker or (len(ids), "")
        cache_key = (settings.embedding_model, query.strip().lower(), marker)
        if cache_key in _cached_query_scores:
            return _cached_query_scores[cache_key]
        query_vector = np.asarray(_embed(settings, [query])[0], dtype=np.float32)
        norm = float(np.linalg.norm(query_vector))
        if not norm:
            return {}
        scores = vectors @ (query_vector / norm)
        result = {identifier: float(score) for identifier, score in zip(ids, scores, strict=True)}
        if len(_cached_query_scores) >= 128:
            _cached_query_scores.pop(next(iter(_cached_query_scores)))
        _cached_query_scores[cache_key] = result
        return result
    except Exception:
        return {}


def refresh_embeddings(settings: Settings, *, limit: int | None = None) -> dict:
    """Incrementally persist changed offer embeddings.

    ``limit`` keeps a user-triggered MinIO sync responsive on CPU-only machines.
    Remaining records can be completed by subsequent syncs; lexical retrieval stays
    fully functional during warm-up.
    """
    with engine.connect() as conn:
        offers = [dict(row) for row in conn.execute(text("""
            SELECT price_snapshot_id, product_name, canonical_name, brand, category_raw,
                   measurement_type, comparison_unit
            FROM offers_current
            WHERE current_price > 0 AND COALESCE(run_status, 'success') = 'success'
            ORDER BY price_snapshot_id
        """)).mappings()]
        existing = {
            str(row["price_snapshot_id"]): str(row["content_hash"])
            for row in conn.execute(
                text("SELECT price_snapshot_id, content_hash FROM offer_search_embeddings_current WHERE model=:model"),
                {"model": settings.embedding_model},
            ).mappings()
        }
    pending = []
    for offer in offers:
        document = offer_search_text(offer)
        digest = content_hash(document)
        if document and existing.get(str(offer["price_snapshot_id"])) != digest:
            pending.append((str(offer["price_snapshot_id"]), document, digest))
    if limit is not None:
        pending = pending[:limit]

    indexed = 0
    for offset in range(0, len(pending), max(1, settings.embedding_batch_size)):
        batch = pending[offset : offset + max(1, settings.embedding_batch_size)]
        vectors = _embed(settings, [item[1] for item in batch])
        rows = [
            {
                "price_snapshot_id": identifier,
                "content_hash": digest,
                "model": settings.embedding_model,
                "search_text": document,
                "embedding": [float(value) for value in vector],
            }
            for (identifier, document, digest), vector in zip(batch, vectors, strict=True)
        ]
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO offer_search_embeddings_current
                    (price_snapshot_id, content_hash, model, search_text, embedding, updated_at)
                VALUES (:price_snapshot_id, :content_hash, :model, :search_text, :embedding, now())
                ON CONFLICT (price_snapshot_id) DO UPDATE SET
                    content_hash=EXCLUDED.content_hash, model=EXCLUDED.model,
                    search_text=EXCLUDED.search_text, embedding=EXCLUDED.embedding,
                    updated_at=EXCLUDED.updated_at
            """), rows)
        indexed += len(rows)

    valid_ids = [str(offer["price_snapshot_id"]) for offer in offers]
    with engine.begin() as conn:
        if valid_ids:
            conn.execute(text("DELETE FROM offer_search_embeddings_current WHERE price_snapshot_id <> ALL(:ids)"), {"ids": valid_ids})
        else:
            conn.execute(text("DELETE FROM offer_search_embeddings_current"))
    invalidate_cache()
    remaining = max(0, len([offer for offer in offers if existing.get(str(offer["price_snapshot_id"])) != content_hash(offer_search_text(offer))]) - indexed)
    return {"indexed": indexed, "remaining": remaining, "total": len(offers), "model": settings.embedding_model, "updated_at": datetime.now(timezone.utc).isoformat()}
