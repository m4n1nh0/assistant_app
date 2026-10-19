"""Cliente do Qdrant: memoria de longo prazo e indice das transcricoes de aula.

Sao **duas colecoes**, separadas pela natureza do dado e nao por quem vai usar:

- **Aulas** (`assistant_lesson_transcripts`): trechos de transcricao, muitos e longos. Filtra por
  usuario, disciplina, aula e instante.
- **Memoria** (`assistant_memory`): fatos curtos aprovados pelo usuario - preferencias,
  diretrizes, instrucoes, conhecimento de automacoes. A categoria e a especialidade que pode usar
  cada fato sao **campos do ponto**, e nao colecoes: quem consulta filtra, e o Qdrant acha o que
  serve sem varrer o resto.

As duas usam embedding semantico de verdade (`app.services.embedding_service`) e guardam em cada
ponto qual modelo gerou o vetor.

**O filtro e o contrato.** Toda busca filtra por `tutor_id` (a colecao e compartilhada, o
isolamento entre usuarios e o filtro), e todo campo filtrado tem **indice de payload**, criado ao
garantir a colecao. Sem indice o filtro funciona, mas varre tudo; com milhares de pontos isso pesa.
O `tutor_id` e indexado como `tenant`, que o Qdrant usa para agrupar o armazenamento por usuario.
"""

import asyncio
import time
from typing import Any, Dict, List, Optional, Sequence

from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    IntegerIndexParams,
    IntegerIndexType,
    KeywordIndexParams,
    KeywordIndexType,
    MatchAny,
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

#: Categorias aceitas na memoria. Sao um campo do ponto (`category`), nao uma colecao cada.
MEMORY_CATEGORIES = {
    "tutor_preferences",
    "behavior_guidelines",
    "approved_instructions",
    "automation_knowledge",
}

#: Valor de `agents` que libera o fato para todas as especialidades.
ALL_AGENTS = "*"

MEMORY_COLLECTION = "memory"
LESSON_CATEGORY = "lesson_transcripts"


def _client() -> QdrantClient:
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
        timeout=10,
        check_compatibility=False,
    )


# --- Indices de payload -----------------------------------------------------


def _keyword(*, tenant: bool = False) -> KeywordIndexParams:
    return KeywordIndexParams(type=KeywordIndexType.KEYWORD, is_tenant=True if tenant else None)


def _integer() -> IntegerIndexParams:
    # So filtro por faixa (instante, data): o indice de igualdade nao e necessario.
    return IntegerIndexParams(type=IntegerIndexType.INTEGER, lookup=False, range=True)


#: Campo filtrado -> indice. Todo campo usado em `_lesson_filter` precisa estar aqui.
LESSON_INDEXES = {
    "tutor_id": _keyword(tenant=True),
    "discipline": _keyword(),
    "lesson_id": _keyword(),
    "class_group": _keyword(),
    "lesson_ts": _integer(),
}

#: Campo filtrado -> indice. Todo campo usado em `memory_filter` precisa estar aqui.
MEMORY_INDEXES = {
    "tutor_id": _keyword(tenant=True),
    "category": _keyword(),
    "agents": _keyword(),
    "source": _keyword(),
    "created_ts": _integer(),
}

# Colecoes cujos indices ja foram criados neste processo: criar a cada busca seria uma ida ao
# servidor por campo, e o indice so precisa existir uma vez.
_INDEXED: set[str] = set()


def _ensure_payload_indexes(client: QdrantClient, name: str, indexes: Dict[str, Any]) -> None:
    """Cria os indices de payload que faltam. Seguro repetir: o Qdrant ignora o que ja existe."""
    if name in _INDEXED:
        return
    complete = True
    for field, schema in indexes.items():
        try:
            client.create_payload_index(
                collection_name=name, field_name=field, field_schema=schema
            )
        except Exception as e:
            complete = False
            logger.warning(f"Indice de payload '{field}' em {name} nao foi criado: {e}")
    if complete:
        _INDEXED.add(name)


# --- Colecoes -----------------------------------------------------------------


class CollectionMismatch(Exception):
    """A colecao existente foi criada com outra dimensao de vetor."""


class LessonCollectionMismatch(CollectionMismatch):
    """A colecao de aulas foi criada com outra dimensao de vetor."""


class MemoryCollectionMismatch(CollectionMismatch):
    """A colecao de memoria foi criada com outra dimensao de vetor."""


def _existing_vector_size(client: QdrantClient, name: str) -> Optional[int]:
    info = client.get_collection(name)
    params = info.config.params.vectors
    if isinstance(params, dict):
        default = params.get("") or next(iter(params.values()), None)
        return getattr(default, "size", None)
    return getattr(params, "size", None)


def _sync_ensure_collection(
    name: str,
    dimensions: int,
    indexes: Dict[str, Any],
    mismatch: type[CollectionMismatch],
    what: str,
) -> None:
    """Cria a colecao (ou confere a dimensao da que existe) e garante os indices."""
    client = _client()

    try:
        exists = client.collection_exists(name)
    except Exception:
        exists = False

    if not exists:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dimensions, distance=Distance.COSINE),
        )
        _ensure_payload_indexes(client, name, indexes)
        return

    current = _existing_vector_size(client, name)
    if current is None or current == dimensions:
        _ensure_payload_indexes(client, name, indexes)
        return

    # Trocar de modelo de embedding muda a dimensao e invalida os vetores ja gravados. Recriar
    # sozinho apagaria dados do usuario, entao so fazemos isso quando nao ha nada a perder.
    points = client.count(collection_name=name, exact=True).count
    if points == 0:
        client.delete_collection(name)
        _INDEXED.discard(name)
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dimensions, distance=Distance.COSINE),
        )
        _ensure_payload_indexes(client, name, indexes)
        logger.info(f"Colecao {name} recriada com dimensao {dimensions}")
        return

    raise mismatch(
        f"A colecao '{name}' tem vetores de {current} dimensoes e o provedor "
        f"atual gera {dimensions}. Ela guarda {points} {what}: "
        f"reindexe ou volte ao modelo de embedding anterior antes de continuar."
    )


def status(*, force: bool = False, ttl_seconds: float = _STATUS_TTL_SECONDS) -> Dict[str, Any]:
    """Diagnostico do Qdrant: alcancavel, colecoes e contagem de pontos.

    Args:
        force: ignora o cache de status.
        ttl_seconds: validade do cache.
    """
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


# --- Memoria ------------------------------------------------------------------


def memory_collection_name() -> str:
    """Nome da colecao unica de memoria, com o prefixo configurado."""
    return f"{settings.qdrant_collection_prefix}_{MEMORY_COLLECTION}"


def _legacy_collection_name(category: str) -> str:
    """Nome da colecao que cada categoria tinha antes de virarem um campo."""
    return f"{settings.qdrant_collection_prefix}_{category}"


async def ensure_memory_collection() -> int:
    """Garante a colecao de memoria na dimensao do modelo em uso, com os indices de payload.

    Returns:
        A dimensao efetiva do vetor.

    Raises:
        MemoryCollectionMismatch: quando a colecao existente usa outra dimensao e tem dados.
    """
    dimensions = await embedding_service.resolve_dimensions()
    await asyncio.to_thread(
        _sync_ensure_collection,
        memory_collection_name(),
        dimensions,
        MEMORY_INDEXES,
        MemoryCollectionMismatch,
        "memorias",
    )
    return dimensions


def _validated_categories(categories: Sequence[str]) -> List[str]:
    invalid = sorted(set(categories) - MEMORY_CATEGORIES)
    if invalid:
        raise ValueError(f"Categoria inválida: {', '.join(invalid)}")
    return sorted(set(categories))


def memory_filter(
    tutor_id: str,
    *,
    categories: Sequence[str] = (),
    agent: Optional[str] = None,
    since_ts: Optional[int] = None,
    source: Optional[str] = None,
) -> Filter:
    """O filtro de uma busca de memoria. O dono (`tutor_id`) sempre entra.

    Args:
        tutor_id: dono das memorias.
        categories: restringe a estas categorias (qualquer uma); vazio nao restringe.
        agent: especialidade que vai usar o fato. Entram os fatos liberados para ela e os
            liberados para todas (`ALL_AGENTS`).
        since_ts: so fatos gravados desde este instante (epoch, em segundos).
        source: so fatos desta origem.
    """
    must: List[Any] = [FieldCondition(key="tutor_id", match=MatchValue(value=tutor_id))]
    if categories:
        must.append(
            FieldCondition(key="category", match=MatchAny(any=_validated_categories(categories)))
        )
    if agent:
        must.append(FieldCondition(key="agents", match=MatchAny(any=[agent, ALL_AGENTS])))
    if since_ts is not None:
        must.append(FieldCondition(key="created_ts", range=Range(gte=since_ts)))
    if source:
        must.append(FieldCondition(key="source", match=MatchValue(value=source)))
    return Filter(must=must)


async def upsert_memory(
    *,
    point_id: str,
    tutor_id: str,
    category: str,
    content: str,
    agents: Sequence[str] = (ALL_AGENTS,),
    source: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Grava (ou substitui) um fato de memoria de um usuario.

    Args:
        point_id: identificador estavel do ponto, para reescrita idempotente.
        tutor_id: dono da memoria.
        category: uma de `MEMORY_CATEGORIES`; e um campo do ponto.
        content: texto do fato.
        agents: especialidades que podem usar o fato; `("*",)` libera para todas.
        source: de onde veio (revisao, automacao, voz...), para filtrar e auditar.
        metadata: dados extras guardados junto do vetor.

    Returns:
        O id do ponto gravado.
    """
    _validated_categories([category])
    await ensure_memory_collection()
    vector = await embedding_service.embed_text(content)
    payload = {
        "id": point_id,
        "tutor_id": tutor_id,
        "category": category,
        "agents": [a for a in agents if a] or [ALL_AGENTS],
        "source": source,
        # Modelo que gerou o vetor: dois modelos podem ter a mesma dimensao e vetores
        # incomparaveis, e so este campo denuncia.
        "embedding": embedding_service.active_signature(),
        "created_ts": int(time.time()),
        "content": content,
        "metadata": metadata or {},
    }
    await asyncio.to_thread(
        lambda: _client().upsert(
            collection_name=memory_collection_name(),
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )
    )
    return point_id


async def search_memory(
    *,
    tutor_id: str,
    query: str,
    categories: Sequence[str] = (),
    agent: Optional[str] = None,
    since_ts: Optional[int] = None,
    source: Optional[str] = None,
    min_score: Optional[float] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Busca fatos de memoria de um usuario por similaridade, ja filtrados.

    Args:
        tutor_id: dono da memoria; sempre aplicado como filtro.
        query: texto da busca.
        categories: restringe a estas categorias; vazio busca em todas.
        agent: especialidade que vai usar o resultado (veja `memory_filter`).
        since_ts: so fatos gravados desde este instante.
        source: so fatos desta origem.
        min_score: descarta o que for menos parecido que isto.
        limit: maximo de resultados.

    Returns:
        Os fatos encontrados, do mais para o menos parecido, com conteudo, metadados e score.
    """
    query_filter = memory_filter(
        tutor_id, categories=categories, agent=agent, since_ts=since_ts, source=source
    )
    await ensure_memory_collection()
    vector = await embedding_service.embed_text(query)

    try:
        response = await asyncio.to_thread(
            lambda: _client().query_points(
                collection_name=memory_collection_name(),
                query=vector,
                query_filter=query_filter,
                limit=limit,
                score_threshold=min_score,
                with_payload=True,
            )
        )
    except Exception as e:
        logger.warning(f"Qdrant memory search failed: {e}")
        return []

    results = []
    for hit in response.points:
        payload = hit.payload or {}
        results.append({
            "id": str(payload.get("id") or hit.id),
            "score": float(hit.score),
            "category": str(payload.get("category") or ""),
            "agents": list(payload.get("agents") or [ALL_AGENTS]),
            "source": str(payload.get("source") or ""),
            "content": str(payload.get("content") or ""),
            "metadata": payload.get("metadata") or {},
        })
    return results


async def delete_memory(*, point_id: str, tutor_id: str) -> None:
    """Remove um fato da memoria. O dono e conferido: ninguem apaga o fato de outro usuario."""
    try:
        await asyncio.to_thread(
            lambda: _client().delete(
                collection_name=memory_collection_name(),
                points_selector=Filter(
                    must=[
                        FieldCondition(key="tutor_id", match=MatchValue(value=tutor_id)),
                        FieldCondition(key="id", match=MatchValue(value=point_id)),
                    ]
                ),
            )
        )
    except Exception as e:
        logger.warning(f"Qdrant memory delete failed ({point_id}): {e}")


async def migrate_legacy_memory() -> Dict[str, int]:
    """Traz para a colecao unica o que estiver nas quatro colecoes antigas, e as remove.

    Cada categoria tinha a sua colecao; agora e um campo. Colecao antiga **vazia** e apagada.
    Com dados, os pontos sao relidos, reembedados (os vetores antigos eram um hash de palavras) e
    gravados na colecao nova **antes** de a antiga ser apagada: se algo falhar no caminho, ela fica
    intacta para a proxima subida.

    Returns:
        Quantas colecoes vazias foram apagadas, quantos pontos migrados e quantas colecoes
        ficaram para tras por falha.
    """
    summary = {"dropped_empty": 0, "migrated": 0, "failed": 0}
    for category in sorted(MEMORY_CATEGORIES):
        name = _legacy_collection_name(category)
        try:
            client = _client()
            if not await asyncio.to_thread(client.collection_exists, name):
                continue
            count = (
                await asyncio.to_thread(lambda: client.count(collection_name=name, exact=True))
            ).count
            if count == 0:
                await asyncio.to_thread(client.delete_collection, name)
                summary["dropped_empty"] += 1
                continue

            moved = await _migrate_legacy_collection(client, name, category)
            await asyncio.to_thread(client.delete_collection, name)
            summary["migrated"] += moved
            logger.info(f"Memoria '{category}': {moved} fatos migrados e colecao {name} removida")
        except Exception as e:
            summary["failed"] += 1
            logger.warning(f"Migracao da colecao legada {name} falhou; ela foi mantida: {e}")
    return summary


async def _migrate_legacy_collection(client: QdrantClient, name: str, category: str) -> int:
    """Copia os pontos de uma colecao antiga para a de memoria. Levanta se algo falhar."""
    await ensure_memory_collection()
    moved = 0
    offset = None
    while True:
        batch, offset = await asyncio.to_thread(
            lambda: client.scroll(
                collection_name=name, limit=128, offset=offset, with_payload=True
            )
        )
        usable = [p for p in batch if (p.payload or {}).get("content")]
        if usable:
            vectors = await embedding_service.embed_texts(
                [str(p.payload["content"]) for p in usable]
            )
            signature = embedding_service.active_signature()
            points = []
            for point, vector in zip(usable, vectors):
                old = point.payload or {}
                points.append(
                    PointStruct(
                        id=point.id,
                        vector=vector,
                        payload={
                            "id": str(old.get("id") or point.id),
                            "tutor_id": old.get("tutor_id") or "",
                            "category": old.get("category") or category,
                            "agents": [ALL_AGENTS],
                            "source": "legacy-migration",
                            "embedding": signature,
                            "created_ts": int(time.time()),
                            "content": str(old["content"]),
                            "metadata": old.get("metadata") or {},
                        },
                    )
                )
            await asyncio.to_thread(
                lambda: client.upsert(collection_name=memory_collection_name(), points=points)
            )
            moved += len(points)
        if offset is None:
            return moved


# --- Transcricoes de aula (modo educacao) ---------------------------------


def lesson_collection_name() -> str:
    """Nome da colecao que guarda os trechos de aula."""
    return f"{settings.qdrant_collection_prefix}_{LESSON_CATEGORY}"


def _sync_ensure_lesson_collection(dimensions: int) -> None:
    _sync_ensure_collection(
        lesson_collection_name(),
        dimensions,
        LESSON_INDEXES,
        LessonCollectionMismatch,
        "trechos de aula",
    )


async def ensure_lesson_collection() -> int:
    """Garante a colecao de aulas com a dimensao do modelo em uso.

    Returns:
        A dimensao efetiva do vetor.

    Raises:
        LessonCollectionMismatch: quando a colecao existente usa outra dimensao.
    """
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
    _INDEXED.discard(name)
    client.create_collection(
        collection_name=name,
        vectors_config=VectorParams(size=dimensions, distance=Distance.COSINE),
    )
    _ensure_payload_indexes(client, name, LESSON_INDEXES)
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
    lesson_ids: Sequence[str] = (),
) -> Filter:
    must: List[Any] = [
        FieldCondition(key="tutor_id", match=MatchValue(value=tutor_id))
    ]
    if discipline:
        must.append(FieldCondition(key="discipline", match=MatchValue(value=discipline)))
    if lesson_id:
        must.append(FieldCondition(key="lesson_id", match=MatchValue(value=lesson_id)))
    elif lesson_ids:
        # Uma pergunta ancorada em disciplina e data ja sabe de quais aulas a
        # resposta pode sair; sem este filtro a busca traz a aula mais parecida
        # do semestre inteiro e a resposta fala do dia errado.
        must.append(
            FieldCondition(key="lesson_id", match=MatchAny(any=list(lesson_ids)))
        )
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
    lesson_ids: Sequence[str] = (),
    limit: int = 8,
) -> List[Dict[str, Any]]:
    """Busca semantica nos trechos de aula de um usuario.

    Args:
        tutor_id: dono das aulas.
        query: pergunta em linguagem natural.
        discipline: restringe a uma disciplina.
        lesson_id: restringe a uma aula.
        lesson_ids: restringe a um conjunto de aulas, quando a pergunta ja foi
            ancorada em disciplina e data no banco relacional.
        ts_from: inicio da janela de tempo dentro da aula, em segundos.
        ts_to: fim da janela de tempo dentro da aula, em segundos.
        limit: maximo de trechos devolvidos.

    Returns:
        Os trechos mais proximos, com aula de origem, instante e score.
    """
    await ensure_lesson_collection()
    vector = await embedding_service.embed_text(query)
    query_filter = _lesson_filter(
        tutor_id, discipline, lesson_id, ts_from, ts_to, lesson_ids
    )

    try:
        # `query_points` e a unica busca da versao fixada do cliente: o `search` antigo foi
        # removido. Quem ainda o chamasse levantava AttributeError, engolido pelo `except` abaixo,
        # e a busca devolvia sempre lista vazia sem nenhum aviso de que o indice nao era lido.
        response = await asyncio.to_thread(
            lambda: _client().query_points(
                collection_name=lesson_collection_name(),
                query=vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
        )
    except Exception as e:
        logger.warning(f"Qdrant lesson search failed: {e}")
        return []

    results = []
    for hit in response.points:
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
    """Remove do indice todos os trechos de uma aula."""
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
