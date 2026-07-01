import hashlib
import math
import time
from typing import Any, Dict, List, Optional

from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from ..core.config import get_settings

settings = get_settings()
_STATUS_CACHE: Optional[tuple[float, Dict[str, Any]]] = None
_STATUS_TTL_SECONDS = 60.0

MEMORY_CATEGORIES = {
    "tutor_preferences",
    "behavior_guidelines",
    "approved_instructions",
    "automation_knowledge",
}


def _client() -> QdrantClient:
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
        timeout=10,
        check_compatibility=False,
    )


def collection_name(category: str) -> str:
    if category not in MEMORY_CATEGORIES:
        raise ValueError(f"Categoria inválida: {category}")
    return f"{settings.qdrant_collection_prefix}_{category}"


def _embed(text: str) -> List[float]:
    size = settings.qdrant_vector_size
    vector = [0.0] * size
    words = [w.strip().lower() for w in text.split() if w.strip()]
    for word in words or [text]:
        digest = hashlib.sha256(word.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % size
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[idx] += sign
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def ensure_collections() -> None:
    client = _client()
    for category in MEMORY_CATEGORIES:
        name = collection_name(category)
        try:
            exists = client.collection_exists(name)
        except Exception:
            exists = False
        if not exists:
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=settings.qdrant_vector_size,
                    distance=Distance.COSINE,
                ),
            )


def status(*, force: bool = False, ttl_seconds: float = _STATUS_TTL_SECONDS) -> Dict[str, Any]:
    global _STATUS_CACHE
    now = time.monotonic()
    if (
        not force
        and _STATUS_CACHE is not None
        and now - _STATUS_CACHE[0] < ttl_seconds
    ):
        cached = dict(_STATUS_CACHE[1])
        if isinstance(cached.get("collections"), list):
            cached["collections"] = list(cached["collections"])
        return cached

    try:
        client = _client()
        collections = client.get_collections()
        names = [c.name for c in collections.collections]
        result = {
            "ok": True,
            "url": settings.qdrant_url,
            "collections": names,
        }
    except Exception as e:
        result = {
            "ok": False,
            "url": settings.qdrant_url,
            "error": str(e),
        }
    _STATUS_CACHE = (now, result)
    return dict(result)


def upsert_memory(
    *,
    point_id: str,
    tutor_id: str,
    category: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    ensure_collections()
    payload = {
        "id": point_id,
        "tutor_id": tutor_id,
        "category": category,
        "content": content,
        "metadata": metadata or {},
    }
    _client().upsert(
        collection_name=collection_name(category),
        points=[
            PointStruct(
                id=point_id,
                vector=_embed(content),
                payload=payload,
            )
        ],
    )
    return point_id


def search_memory(
    *,
    tutor_id: str,
    query: str,
    category: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    ensure_collections()
    categories = [category] if category else sorted(MEMORY_CATEGORIES)
    query_vector = _embed(query)
    results: List[Dict[str, Any]] = []
    query_filter = Filter(
        must=[
            FieldCondition(
                key="tutor_id",
                match=MatchValue(value=tutor_id),
            )
        ]
    )

    for item in categories:
        try:
            hits = _client().search(
                collection_name=collection_name(item),
                query_vector=query_vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
        except Exception as e:
            logger.warning(f"Qdrant search failed ({item}): {e}")
            continue

        for hit in hits:
            payload = hit.payload or {}
            results.append({
                "id": str(payload.get("id") or hit.id),
                "score": float(hit.score),
                "category": str(payload.get("category") or item),
                "content": str(payload.get("content") or ""),
                "metadata": payload.get("metadata") or {},
            })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]
