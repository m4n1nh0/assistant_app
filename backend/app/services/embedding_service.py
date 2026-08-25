"""Embeddings semanticos com provedor plugavel, priorizando infra propria.

O `_embed` do qdrant_service e um hash de palavras: serve para casar termos
identicos, mas nao entende que "prova" e "avaliacao" sao a mesma coisa. Para
transcricao de aula isso inviabiliza a busca, entao aqui falamos com um modelo
de embedding de verdade — Ollama, LocalAI ou qualquer endpoint compativel com a
API da OpenAI que o usuario suba. O hash continua existindo como ultimo recurso
para o backend nunca ficar sem responder.
"""

import asyncio
import hashlib
import math
import time
from typing import Dict, List, Optional, Sequence

import httpx
from loguru import logger

from ..core.config import get_settings

settings = get_settings()

_TIMEOUT_SECONDS = 60
_PROBE_TEXT = "verificacao de dimensao do vetor"
_FAILURE_TTL_SECONDS = 120.0

_resolved_provider: Optional[str] = None
_resolved_dimensions: Optional[int] = None
_failed_providers: Dict[str, float] = {}
_lock = asyncio.Lock()
_local_model = None
_local_lock = asyncio.Lock()

DEFAULT_MODELS = {
    "ollama": "nomic-embed-text",
    "localai": "text-embedding-ada-002",
    "openai": "text-embedding-3-small",
    "custom": "text-embedding-3-small",
}


class EmbeddingError(Exception):
    """Falha ao gerar embeddings em um provedor especifico."""


def _model_for(provider: str) -> str:
    if provider == "local":
        # EMBEDDING_MODEL nomeia modelo de API e nao serve aqui: o provedor
        # local tem catalogo proprio, entao ele tem a sua propria variavel.
        return settings.embedding_local_model.strip()
    if provider == "hash":
        return "hash"
    configured = settings.embedding_model.strip()
    return configured or DEFAULT_MODELS.get(provider, "")


def _custom_base_url() -> str:
    base = settings.embedding_base_url.strip().rstrip("/")
    if not base or base.endswith("/v1"):
        return base
    return f"{base}/v1"


def _candidate_providers() -> List[str]:
    """Ordem de tentativa: infra propria primeiro, nuvem so como reserva."""
    configured = settings.embedding_provider.strip().lower()
    if configured and configured != "auto":
        return [configured]

    candidates: List[str] = []
    if _custom_base_url():
        candidates.append("custom")
    if settings.localai_base_url:
        candidates.append("localai")
    if settings.ollama_base_url:
        candidates.append("ollama")
    # Antes da nuvem: indexar aula nao pode parar porque uma chave paga venceu.
    candidates.append("local")
    if settings.openai_api_key:
        candidates.append("openai")
    candidates.append("hash")
    return candidates


def hash_embedding(text: str, size: int) -> List[float]:
    """Vetor deterministico offline — mesma tecnica do qdrant_service."""
    vector = [0.0] * size
    words = [w.strip().lower() for w in text.split() if w.strip()]
    for word in words or [text]:
        digest = hashlib.sha256(word.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % size
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[idx] += sign
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


async def _post_openai_compatible(
    url: str,
    api_key: str,
    model: str,
    texts: Sequence[str],
) -> List[List[float]]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            url,
            headers=headers,
            json={"model": model, "input": list(texts)},
        )

    try:
        data = resp.json()
    except Exception as exc:
        raise EmbeddingError(f"HTTP {resp.status_code}: resposta nao-JSON") from exc

    if resp.is_error:
        detail = data.get("error", data) if isinstance(data, dict) else data
        raise EmbeddingError(f"HTTP {resp.status_code}: {detail}")

    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise EmbeddingError("resposta sem campo 'data'")

    # A API nao garante a ordem de retorno, mas garante o campo `index`.
    ordered = sorted(items, key=lambda item: item.get("index", 0))
    vectors = [item.get("embedding") for item in ordered]
    if any(not isinstance(vector, list) or not vector for vector in vectors):
        raise EmbeddingError("resposta sem vetores validos")
    return [[float(value) for value in vector] for vector in vectors]


async def _embed_ollama(texts: Sequence[str]) -> List[List[float]]:
    base = settings.ollama_base_url.rstrip("/")
    model = _model_for("ollama")

    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            f"{base}/api/embed",
            json={"model": model, "input": list(texts)},
        )

        # /api/embed so existe a partir do Ollama 0.3; instalacoes antigas
        # respondem 404 e precisam do endpoint singular, um texto por chamada.
        if resp.status_code == 404:
            vectors: List[List[float]] = []
            for text in texts:
                legacy = await client.post(
                    f"{base}/api/embeddings",
                    json={"model": model, "prompt": text},
                )
                data = legacy.json()
                if legacy.is_error or "embedding" not in data:
                    raise EmbeddingError(
                        f"HTTP {legacy.status_code}: {data.get('error', data)}"
                    )
                vectors.append([float(value) for value in data["embedding"]])
            return vectors

        try:
            data = resp.json()
        except Exception as exc:
            raise EmbeddingError(f"HTTP {resp.status_code}: resposta nao-JSON") from exc

    if resp.is_error:
        raise EmbeddingError(f"HTTP {resp.status_code}: {data.get('error', data)}")

    vectors = data.get("embeddings")
    if not isinstance(vectors, list) or not vectors:
        raise EmbeddingError("resposta sem campo 'embeddings'")
    return [[float(value) for value in vector] for vector in vectors]


def _load_local_model(name: str):
    """Carrega o modelo ONNX. Bloqueia: sempre chamado em thread separada."""
    from fastembed import TextEmbedding

    cache_dir = settings.embedding_cache_dir.strip()
    return TextEmbedding(
        model_name=name,
        **({"cache_dir": cache_dir} if cache_dir else {}),
    )


async def _embed_local(texts: Sequence[str]) -> List[List[float]]:
    """Embedding dentro do proprio backend, sem API e sem chave.

    O modelo e baixado uma vez (~220 MB) e fica em memoria. A primeira chamada
    depois de subir o processo paga o download; as seguintes levam milissegundos.
    """
    global _local_model

    async with _local_lock:
        if _local_model is None:
            name = _model_for("local")
            if not name:
                raise EmbeddingError("EMBEDDING_LOCAL_MODEL vazio")
            try:
                _local_model = await asyncio.to_thread(_load_local_model, name)
            except Exception as exc:
                raise EmbeddingError(f"modelo local indisponivel: {exc}") from exc
            logger.info(f"Modelo de embedding local carregado: {name}")

    model = _local_model
    try:
        vectors = await asyncio.to_thread(
            lambda: [list(vector) for vector in model.embed(list(texts))]
        )
    except Exception as exc:
        raise EmbeddingError(f"falha no modelo local: {exc}") from exc
    return [[float(value) for value in vector] for vector in vectors]


async def _embed_with(provider: str, texts: Sequence[str]) -> List[List[float]]:
    if provider == "local":
        return await _embed_local(texts)
    if provider == "ollama":
        return await _embed_ollama(texts)
    if provider == "localai":
        return await _post_openai_compatible(
            f"{settings.localai_v1_base_url}/embeddings",
            settings.embedding_api_key or settings.localai_api_key,
            _model_for("localai"),
            texts,
        )
    if provider == "openai":
        return await _post_openai_compatible(
            "https://api.openai.com/v1/embeddings",
            settings.embedding_api_key or settings.openai_api_key,
            _model_for("openai"),
            texts,
        )
    if provider == "custom":
        return await _post_openai_compatible(
            f"{_custom_base_url()}/embeddings",
            settings.embedding_api_key,
            _model_for("custom"),
            texts,
        )
    if provider == "hash":
        size = settings.embedding_dimensions or settings.qdrant_vector_size
        return [hash_embedding(text, size) for text in texts]
    raise EmbeddingError(f"provedor desconhecido: {provider}")


def _recently_failed(provider: str) -> bool:
    failed_at = _failed_providers.get(provider)
    if failed_at is None:
        return False
    if time.monotonic() - failed_at > _FAILURE_TTL_SECONDS:
        _failed_providers.pop(provider, None)
        return False
    return True


async def embed_texts(texts: Sequence[str]) -> List[List[float]]:
    """Gera embeddings, mantendo o provedor que funcionou para as proximas."""
    clean = [text.strip() or _PROBE_TEXT for text in texts]
    if not clean:
        return []

    global _resolved_provider, _resolved_dimensions

    providers = _candidate_providers()
    if _resolved_provider and _resolved_provider in providers:
        # Reordena para tentar primeiro o que ja respondeu nesta execucao.
        providers = [_resolved_provider] + [
            item for item in providers if item != _resolved_provider
        ]

    last_error: Optional[Exception] = None
    for provider in providers:
        if provider != _resolved_provider and _recently_failed(provider):
            continue
        try:
            vectors = await _embed_with(provider, clean)
        except Exception as exc:
            last_error = exc
            _failed_providers[provider] = time.monotonic()
            logger.warning(f"Embedding provider '{provider}' indisponivel: {exc}")
            if _resolved_provider == provider:
                _resolved_provider = None
                _resolved_dimensions = None
            continue

        dimensions = len(vectors[0])
        if _resolved_provider != provider or _resolved_dimensions != dimensions:
            logger.info(
                f"Embeddings via '{provider}' "
                f"(modelo={_model_for(provider) or 'hash'}, dim={dimensions})"
            )
        _resolved_provider = provider
        _resolved_dimensions = dimensions
        _failed_providers.pop(provider, None)
        return vectors

    raise EmbeddingError(f"nenhum provedor de embedding disponivel: {last_error}")


async def embed_text(text: str) -> List[float]:
    """Gera o vetor de um texto.

    Raises:
        EmbeddingError: quando nenhum provedor da cadeia respondeu.
    """
    vectors = await embed_texts([text])
    return vectors[0]


def active_signature() -> str:
    """Quem gerou os vetores agora, no formato `provedor:modelo`.

    Fica gravado junto de cada trecho indexado: e o que permite descobrir,
    depois, que um vetor foi feito por outro modelo e precisa ser refeito.
    """
    provider = _resolved_provider
    if not provider:
        return ""
    # Cortado no tamanho da coluna que a guarda em `lesson_segments`.
    return f"{provider}:{_model_for(provider) or 'hash'}"[:120]


def is_semantic(signature: str = "") -> bool:
    """Diz se a assinatura veio de um modelo de verdade, e nao do hash."""
    value = signature or active_signature()
    return bool(value) and not value.startswith("hash:")


async def resolve_dimensions() -> int:
    """Descobre o tamanho do vetor do provedor ativo, com cache por processo.

    A colecao do Qdrant precisa ser criada com o tamanho exato, e cada modelo
    tem o seu (nomic-embed-text=768, text-embedding-3-small=1536), por isso
    perguntamos ao provedor em vez de fixar um numero na configuracao.
    """
    configured = settings.embedding_dimensions
    if configured:
        return configured

    async with _lock:
        if _resolved_dimensions:
            return _resolved_dimensions
        vector = await embed_text(_PROBE_TEXT)
        return len(vector)


async def describe() -> Dict[str, object]:
    """Estado do provedor para diagnostico na interface e no /health."""
    try:
        dimensions = await resolve_dimensions()
    except Exception as exc:
        return {
            "ok": False,
            "provider": settings.embedding_provider,
            "error": str(exc),
        }
    provider = _resolved_provider or settings.embedding_provider
    return {
        "ok": True,
        "provider": provider,
        "model": _model_for(provider) or "hash",
        "dimensions": dimensions,
        "semantic": provider != "hash",
    }


def reset_cache() -> None:
    """Usado pelos testes e por mudancas de configuracao em runtime."""
    global _resolved_provider, _resolved_dimensions, _local_model
    _resolved_provider = None
    _resolved_dimensions = None
    _local_model = None
    _failed_providers.clear()
