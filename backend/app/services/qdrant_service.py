import asyncio
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
    Range,
    VectorParams,
)

from ..core.config import get_settings
from . import embedding_service

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


# --- Transcricoes de aula (modo educacao) ---------------------------------
#
# Colecao separada das memorias porque usa embedding semantico de verdade e,
# portanto, outra dimensao de vetor. As memorias continuam no hash legado ate
# que exista uma migracao explicita.

LESSON_CATEGORY = "lesson_transcripts"


def lesson_collection_name() -> str:
    return f"{settings.qdrant_collection_prefix}_{LESSON_CATEGORY}"


class LessonCollectionMismatch(Exception):
    """A colecao existente foi criada com outra dimensao de vetor."""


def _existing_vector_size(client: QdrantClient, name: str) -> Optional[int]:
    info = client.get_collection(name)
    params = info.config.params.vectors
    if isinstance(params, dict):
        default = params.get("") or next(iter(params.values()), None)
        return getattr(default, "size", None)
    return getattr(params, "size", None)


def _sync_ensure_lesson_collection(dimensions: int) -> None:
    client = _client()
    name = lesson_collection_name()

    try:
        exists = client.collection_exists(name)
    except Exception:
        exists = False

    if not exists:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dimensions, distance=Distance.COSINE),
        )
        return

    current = _existing_vector_size(client, name)
    if current is None or current == dimensions:
        return

    # Trocar de modelo de embedding muda a dimensao e invalida os vetores ja
    # gravados. Recriar sozinho apagaria transcricoes de aulas passadas, entao
    # so fazemos isso quando nao ha nada a perder.
    points = client.count(collection_name=name, exact=True).count
    if points == 0:
        client.delete_collection(name)
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dimensions, distance=Distance.COSINE),
        )
        logger.info(f"Colecao {name} recriada com dimensao {dimensions}")
        return

    raise LessonCollectionMismatch(
        f"A colecao '{name}' tem vetores de {current} dimensoes e o provedor "
        f"atual gera {dimensions}. Ela guarda {points} trechos de aula: "
        f"reindexe as aulas ou volte ao modelo de embedding anterior antes de "
        f"continuar."
    )


async def ensure_lesson_collection() -> int:
    dimensions = await embedding_service.resolve_dimensions()
    await asyncio.to_thread(_sync_ensure_lesson_collection, dimensions)
    return dimensions


def _sync_rebuild_lesson_collection(dimensions: int) -> None:
    client = _client()
    name = lesson_collection_name()
    try:
        if client.collection_exists(name):
            client.delete_collection(name)
    except Exception as e:
        logger.warning(f"Falha ao remover a colecao {name}: {e}")
    client.create_collection(
        collection_name=name,
        vectors_config=VectorParams(size=dimensions, distance=Distance.COSINE),
    )
    logger.warning(
        f"Colecao {name} recriada com {dimensions} dimensoes: os vetores "
        "antigos foram descartados e precisam ser reindexados a partir do MySQL"
    )


async def rebuild_lesson_collection() -> int:
    """Recria a colecao na dimensao do provedor atual, jogando fora os vetores.

    So faz sentido acompanhada de reindexacao: a transcricao continua no MySQL,
    entao o que se perde aqui e recuperavel.
    """
    dimensions = await embedding_service.resolve_dimensions()
    await asyncio.to_thread(_sync_rebuild_lesson_collection, dimensions)
    return dimensions


async def index_lesson_segments(
    *,
    tutor_id: str,
    lesson_id: str,
    discipline: str,
    segments: List[Dict[str, Any]],
) -> int:
    """Grava trechos da aula no Qdrant. Retorna quantos foram indexados."""
    usable = [item for item in segments if str(item.get("text", "")).strip()]
    if not usable:
        return 0

    await ensure_lesson_collection()
    vectors = await embedding_service.embed_texts(
        [str(item["text"]) for item in usable]
    )
    signature = embedding_service.active_signature()

    points = [
        PointStruct(
            id=str(item["id"]),
            vector=vector,
            payload={
                "id": str(item["id"]),
                "tutor_id": tutor_id,
                "lesson_id": lesson_id,
                "discipline": discipline,
                # Modelo que gerou o vetor: dois modelos podem ter a mesma
                # dimensao e vetores incomparaveis, e so este campo denuncia.
                "embedding": signature,
                "class_group": item.get("class_group") or "",
                "lesson_date": item.get("lesson_date") or "",
                "lesson_ts": int(item.get("lesson_ts") or 0),
                "sequence": int(item.get("sequence") or 0),
                "content": str(item["text"]),
            },
        )
        for item, vector in zip(usable, vectors)
    ]

    await asyncio.to_thread(
        lambda: _client().upsert(
            collection_name=lesson_collection_name(),
            points=points,
        )
    )
    return len(points)


def _lesson_filter(
    tutor_id: str,
    discipline: Optional[str],
    lesson_id: Optional[str],
    ts_from: Optional[int],
    ts_to: Optional[int],
) -> Filter:
    must: List[Any] = [
        FieldCondition(key="tutor_id", match=MatchValue(value=tutor_id))
    ]
    if discipline:
        must.append(FieldCondition(key="discipline", match=MatchValue(value=discipline)))
    if lesson_id:
        must.append(FieldCondition(key="lesson_id", match=MatchValue(value=lesson_id)))
    if ts_from is not None or ts_to is not None:
        # Epoch inteiro em vez de data textual: o Qdrant exige RFC3339 completo
        # em DatetimeRange, e "2026-08-04" sozinho nao passa na validacao.
        must.append(
            FieldCondition(key="lesson_ts", range=Range(gte=ts_from, lte=ts_to))
        )
    return Filter(must=must)


async def search_lesson_transcripts(
    *,
    tutor_id: str,
    query: str,
    discipline: Optional[str] = None,
    lesson_id: Optional[str] = None,
    ts_from: Optional[int] = None,
    ts_to: Optional[int] = None,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    await ensure_lesson_collection()
    vector = await embedding_service.embed_text(query)
    query_filter = _lesson_filter(tutor_id, discipline, lesson_id, ts_from, ts_to)

    try:
        hits = await asyncio.to_thread(
            lambda: _client().search(
                collection_name=lesson_collection_name(),
                query_vector=vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
        )
    except Exception as e:
        logger.warning(f"Qdrant lesson search failed: {e}")
        return []

    results = []
    for hit in hits:
        payload = hit.payload or {}
        results.append({
            "id": str(payload.get("id") or hit.id),
            "score": float(hit.score),
            "lesson_id": str(payload.get("lesson_id") or ""),
            # `subject` era o nome antigo do campo: os vetores gravados antes
            # do rename continuam com ele ate serem reindexados.
            "discipline": str(
                payload.get("discipline") or payload.get("subject") or ""
            ),
            "lesson_date": str(payload.get("lesson_date") or ""),
            "sequence": int(payload.get("sequence") or 0),
            "content": str(payload.get("content") or ""),
        })
    return results


async def delete_lesson_points(*, lesson_id: str) -> None:
    try:
        await asyncio.to_thread(
            lambda: _client().delete(
                collection_name=lesson_collection_name(),
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="lesson_id", match=MatchValue(value=lesson_id)
                        )
                    ]
                ),
            )
        )
    except Exception as e:
        logger.warning(f"Qdrant lesson delete failed ({lesson_id}): {e}")
