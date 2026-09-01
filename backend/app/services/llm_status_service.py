"""Saude dos provedores de LLM: quem esta configurado, online e utilizavel.

Consultar todos os provedores a cada requisicao seria lento e caro, entao o
resultado e cacheado em duas camadas: memoria do processo (por escopo de
usuario) e Redis compartilhado, com TTL curto para falha e longo para sucesso.

O modulo separa deliberadamente tres estados que costumam ser tratados como um
so: **configurado** (existe chave), **online** (a API respondeu) e **disponivel**
(da para mandar uma geracao agora). Provedor com chave valida mas sem saldo e
configurado e online, e mesmo assim indisponivel.
"""

import asyncio
import json
import re
import time
from typing import Any, Iterable
from urllib.parse import quote

import httpx
from loguru import logger

from ..core.redis_client import get_client as get_redis_client
from ..models.schemas import LLMStatus
from .user_llm_config_service import runtime_scope, runtime_settings

settings = runtime_settings

_CACHE_TTL_SECONDS = 300
_FAILED_CACHE_TTL_SECONDS = 30
_caches: dict[str, tuple[dict[str, LLMStatus], float]] = {}
_refresh_tasks: dict[str, asyncio.Task] = {}
# Backward-compatible local-scope cache names; a few operational tests and
# extensions inspect these directly.
_cache: dict[str, LLMStatus] | None = None
_cache_at = 0.0
_refresh_task: asyncio.Task | None = None

# Sufixo versionado impede que um deploy novo reutilize por cinco minutos um
# snapshot criado antes da validacao de modelo/capacidade de chat.
_REDIS_KEY = "assistant:llm_status:v3"

_PROVIDER_ORDER = [
    "claude",
    "gpt",
    "together",
    "openrouter",
    "deepseek",
    "gemini",
    "grok",
    "hf",
    "localai",
    "llama",
]


async def get_llm_statuses(force: bool = False) -> dict[str, LLMStatus]:
    """Devolve o status de cada provedor, usando cache quando ainda esta fresco.

    Args:
        force: ignora o cache e reconsulta todos os provedores.

    Returns:
        Mapa de provedor para `LLMStatus`.
    """
    global _cache, _cache_at
    scope = runtime_scope()
    now = time.monotonic()
    cached = (_cache, _cache_at) if scope == "local" and _cache is not None else _caches.get(scope)
    if not force and cached is not None and _is_cache_fresh(cached[0], cached[1], now):
        return cached[0]

    if not force:
        shared = await _read_shared_cache()
        if shared is not None:
            _caches[scope] = (shared, now)
            if scope == "local":
                _cache, _cache_at = shared, now
            return shared

    timeout = httpx.Timeout(8.0, connect=4.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        results = await asyncio.gather(
            _check_claude(client),
            _check_gpt(client),
            _check_together(client),
            _check_openrouter(client),
            _check_deepseek(client),
            _check_gemini(client),
            _check_grok(client),
            _check_hf(client),
            _check_localai(client),
            _check_llama(client),
        )

    cache = {status.id: status for status in results}
    _caches[scope] = (cache, time.monotonic())
    if scope == "local":
        _cache, _cache_at = _caches[scope]
    await _write_shared_cache(cache)
    return cache


async def _read_shared_cache() -> dict[str, LLMStatus] | None:
    client = get_redis_client()
    if client is None:
        return None
    try:
        raw = await client.get(f"{_REDIS_KEY}:{runtime_scope()}")
        if not raw:
            return None
        return {
            provider: LLMStatus.model_validate(data)
            for provider, data in json.loads(raw).items()
        }
    except Exception as e:
        logger.debug(f"LLM status Redis read skipped: {e}")
        return None


async def _write_shared_cache(cache: dict[str, LLMStatus]) -> None:
    client = get_redis_client()
    if client is None:
        return
    ttl = (
        _CACHE_TTL_SECONDS
        if any(status.available for status in cache.values())
        else _FAILED_CACHE_TTL_SECONDS
    )
    try:
        payload = json.dumps(
            {provider: status.model_dump(mode="json") for provider, status in cache.items()}
        )
        await client.set(f"{_REDIS_KEY}:{runtime_scope()}", payload, ex=ttl)
    except Exception as e:
        logger.debug(f"LLM status Redis write skipped: {e}")


async def get_available_llms(force: bool = False) -> list[str]:
    """Lista os provedores utilizaveis agora, na ordem de preferencia do projeto.

    Args:
        force: forca a reconsulta antes de filtrar.

    Returns:
        Chaves dos provedores com `available` verdadeiro.
    """
    statuses = await get_llm_statuses(force=force)
    return [
        provider
        for provider in _PROVIDER_ORDER
        if statuses.get(provider) is not None and statuses[provider].available
    ]


async def get_ready_llms() -> list[str]:
    """Configured llms (settings.active_llms order) that are actually available right now."""
    available = set(await get_available_llms())
    return [llm for llm in settings.active_llms if llm in available]


def _runtime_failure_status(provider: str, error: str) -> LLMStatus:
    clean_error = _sanitize_error(error)[:500]
    lowered = clean_error.lower()
    credit_failure = any(
        marker in lowered
        for marker in (
            "credit balance",
            "insufficient credit",
            "insufficient_quota",
            "billing",
            "saldo",
            "sem credito",
        )
    )
    model_failure = any(
        marker in lowered
        for marker in (
            "model does not exist",
            "model `",
            "not a chat model",
            "modelo de chat",
            "model not found",
            "modelo nao encontrado",
            "do not have access",
            "nao tem acesso",
        )
    )
    auth_failure = any(
        marker in lowered
        for marker in (
            "invalid api key",
            "incorrect api key",
            "unauthorized",
            "authentication",
        )
    )

    if credit_failure:
        status = "limited"
        online = True
        balance_ok: bool | None = False
    elif model_failure:
        status = "model_unavailable"
        online = True
        balance_ok = None
    elif auth_failure:
        status = "invalid_credentials"
        online = True
        balance_ok = None
    else:
        status = "offline"
        online = False
        balance_ok = None

    return LLMStatus(
        id=provider,
        label=_label(provider),
        configured=bool(_provider_key(provider)),
        online=online,
        available=False,
        has_balance_check=credit_failure,
        balance_ok=balance_ok,
        status=status,
        error=clean_error or "Falha ao usar o provedor",
    )


async def mark_llm_failure(provider: str, error: str) -> None:
    """Realimenta o health cache quando uma geracao real falha.

    Listar modelos prova que o endpoint e a chave respondem, mas nao prova
    saldo, permissao de projeto ou compatibilidade de chat. A chamada real e
    o sinal mais forte e precisa retirar o provedor das proximas selecoes.
    """

    global _cache, _cache_at
    if provider not in _PROVIDER_ORDER:
        return
    scope = runtime_scope()
    current = (_cache, _cache_at) if scope == "local" and _cache is not None else _caches.get(scope)
    updated = dict((current or ({}, 0.0))[0])
    updated[provider] = _runtime_failure_status(provider, error)
    _caches[scope] = (updated, time.monotonic())
    if scope == "local":
        _cache, _cache_at = _caches[scope]
    await _write_shared_cache(updated)


async def get_statuses_fast() -> dict[str, LLMStatus]:
    """Return cached statuses instantly; if cache is cold, return key-based statuses and
    kick off a background refresh so the next call will have real data."""
    global _refresh_task
    scope = runtime_scope()
    now = time.monotonic()
    cached = (_cache, _cache_at) if scope == "local" and _cache is not None else _caches.get(scope)
    if cached is not None and _is_cache_fresh(cached[0], cached[1], now):
        return cached[0]

    # Cache is cold — build a quick "key configured" status for each active LLM
    fast: dict[str, LLMStatus] = {}
    for provider in _PROVIDER_ORDER:
        key_present = bool(_provider_key(provider))
        fast[provider] = _checking(provider) if key_present else _missing(provider)

    # Trigger a real check in the background so the 5-min cache warms up
    refresh_task = _refresh_task if scope == "local" else _refresh_tasks.get(scope)
    if refresh_task is None or refresh_task.done():
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(get_llm_statuses())
            _refresh_tasks[scope] = task
            if scope == "local":
                _refresh_task = task
        except RuntimeError:
            pass

    return fast


def _is_cache_fresh(
    cache: dict[str, LLMStatus],
    cached_at_or_now: float,
    now: float | None = None,
) -> bool:
    cached_at = _cache_at if now is None else cached_at_or_now
    now = cached_at_or_now if now is None else now
    ttl = (
        _CACHE_TTL_SECONDS
        if any(status.available for status in cache.values())
        else _FAILED_CACHE_TTL_SECONDS
    )
    return now - cached_at < ttl


def _provider_key(provider: str) -> str:
    return {
        "claude": getattr(settings, "claude_api_key", ""),
        "gpt": getattr(settings, "openai_api_key", ""),
        "together": getattr(settings, "together_api_key", ""),
        "openrouter": getattr(settings, "openrouter_api_key", ""),
        "deepseek": getattr(settings, "deepseek_api_key", ""),
        "gemini": getattr(settings, "gemini_api_key", ""),
        "grok": getattr(settings, "grok_api_key", ""),
        "hf": getattr(settings, "huggingface_api_key", ""),
        "localai": getattr(settings, "localai_base_url", ""),
        "llama": "local",  # always "configured" (local Ollama)
    }.get(provider, "")


def _label(provider: str) -> str:
    return settings.llm_labels.get(provider, provider.upper())


# O que falta configurar em cada provedor. Ollama e LocalAI nao tem credencial:
# o que os liga e um endereco. Dizer "credencial nao configurada" para eles
# manda procurar uma chave que nao existe - e foi o que a guarda nova do
# `_check_llama` passou a fazer ao reusar a mensagem padrao.
_MISSING_REASON = {
    "localai": "LOCALAI_BASE_URL nao configurada",
    "llama": "OLLAMA_BASE_URL nao configurada",
}


def _missing(provider: str) -> LLMStatus:
    return LLMStatus(
        id=provider,
        label=_label(provider),
        configured=False,
        status="missing_key",
        error=_MISSING_REASON.get(provider, "Credencial nao configurada"),
    )


def _checking(provider: str) -> LLMStatus:
    return LLMStatus(
        id=provider,
        label=_label(provider),
        configured=True,
        online=False,
        available=False,
        status="checking",
        error="Checando disponibilidade do provedor",
    )


# Modelo que nao serve para conversar. O catalogo de um provedor mistura chat,
# embedding, transcricao, moderacao e imagem; oferecer tudo numa lista de
# escolha faria o usuario configurar um `whisper` como agente de chat.
_NOT_CHAT_MARKERS = (
    "embed", "whisper", "tts", "audio", "speech", "voice", "orpheus",
    "guard", "moderation", "safety", "rerank", "reranker",
    "stable-diffusion", "flux", "dall-e", "image", "vision-encoder",
)

# Preferencia por provedor, em ordem, casada por trecho do id contra o catalogo
# que o provedor devolveu. E deliberadamente por padrao, e nao por id fixo: id
# fixo e exatamente o que quebrou aqui quando a Mistral saiu do router do HF e
# quando o `llama-3.3-70b-versatile` virou tier Enterprise na Groq. Casando por
# trecho, sumindo o preferido a sugestao cai sozinha para o proximo.
_MODEL_PREFERENCE: dict[str, tuple[str, ...]] = {
    "claude": ("sonnet", "opus", "haiku"),
    "gpt": ("gpt-4o", "gpt-4.1", "gpt-4", "o4-", "gpt-3.5"),
    "gemini": ("flash", "pro"),
    "together": ("llama-3.3-70b", "llama-3.1-70b", "qwen", "llama-3"),
    "openrouter": ("auto", ":free", "llama-3.3"),
    "deepseek": ("deepseek-chat", "deepseek"),
    "grok": ("grok-", "gpt-oss-120b", "llama-3.3-70b", "llama-3.1-8b-instant"),
    "hf": (
        "llama-3.3-70b-instruct", "qwen2.5-72b", "llama-3.1-8b-instruct",
        "gemma-3-27b", "instruct",
    ),
}


def _is_chat_model(model_id: str) -> bool:
    lowered = model_id.lower()
    return not any(marker in lowered for marker in _NOT_CHAT_MARKERS)


def _sorted_models(models: Iterable[str] | None) -> list[str]:
    """Catalogo limpo e estavel: so modelo de chat, sem repeticao, ordenado."""
    if not models:
        return []
    return sorted({str(item) for item in models if item and _is_chat_model(str(item))})


def recommended_model(provider: str, models: Iterable[str] | None) -> str:
    """Sugere o modelo mais adequado entre os que a conta realmente tem.

    Devolve string vazia quando nao ha catalogo - sugerir um id que a conta nao
    pode usar seria repetir o problema que esta funcao existe para evitar.

    Args:
        provider: chave do provedor.
        models: catalogo devolvido pelo provedor nesta checagem.

    Returns:
        O id sugerido, ou "" quando nao da para sugerir.
    """
    catalog = _sorted_models(models)
    if not catalog:
        return ""
    for pattern in _MODEL_PREFERENCE.get(provider, ()):
        for model_id in catalog:
            if pattern in model_id.lower():
                return model_id
    return catalog[0]


def _status(
    provider: str,
    *,
    configured: bool,
    online: bool,
    has_balance_check: bool = False,
    balance_ok: bool | None = None,
    balance: str | None = None,
    currency: str | None = None,
    error: str | None = None,
    models: Iterable[str] | None = None,
) -> LLMStatus:
    available = configured and online and balance_ok is not False
    if not configured:
        status = "missing_key"
    elif not online:
        status = "offline"
    elif balance_ok is False:
        status = "limited"
    else:
        status = "online"

    catalog = _sorted_models(models)
    return LLMStatus(
        id=provider,
        label=_label(provider),
        configured=configured,
        online=online,
        available=available,
        has_balance_check=has_balance_check,
        balance_ok=balance_ok,
        balance=balance,
        currency=currency,
        status=status,
        error=error,
        available_models=catalog,
        recommended_model=recommended_model(provider, catalog),
    )


def _model_unavailable(
    provider: str, model: str, models: Iterable[str] | None = None
) -> LLMStatus:
    """Modelo configurado que o provedor nao oferece a esta conta.

    A lista de modelos entra no resultado porque a checagem **ja a baixou** para
    descobrir a ausencia. Descarta-la deixava o usuario com um beco sem saida:
    o erro dizia que o modelo nao servia, mas nao qual serviria.
    """
    catalog = _sorted_models(models)
    suggestion = recommended_model(provider, catalog)
    error = f"Modelo de chat '{model}' indisponivel ou sem acesso"
    if suggestion:
        error += f". Disponivel nesta conta, por exemplo: {suggestion}"
    return LLMStatus(
        id=provider,
        label=_label(provider),
        configured=True,
        online=True,
        available=False,
        status="model_unavailable",
        error=error,
        available_models=catalog,
        recommended_model=suggestion,
    )


def _model_id_without_policy(model: str) -> str:
    """Remove apenas o sufixo de roteamento HF, preservando org/model."""

    head, separator, tail = model.rpartition("/")
    if ":" in tail:
        tail = tail.split(":", 1)[0]
    return f"{head}{separator}{tail}" if separator else tail


def _listed_model_ids(data: Any) -> set[str]:
    """Ids de modelo de uma listagem, nos tres formatos que os provedores usam.

    OpenAI, Anthropic e Groq devolvem `{"data": [{"id": ...}]}`; a Together
    devolve a lista crua; o Gemini devolve `{"models": [{"name": "models/x"}]}`.
    Um parser so evita tres funcoes de checagem quase iguais.
    """
    if isinstance(data, dict):
        raw_models = data.get("data") or data.get("models") or []
    elif isinstance(data, list):
        raw_models = data
    else:
        raw_models = []

    ids: set[str] = set()
    for model in raw_models:
        if not isinstance(model, dict):
            continue
        identifier = model.get("id") or model.get("name") or ""
        identifier = str(identifier).strip()
        if not identifier:
            continue
        # O Gemini prefixa com `models/`; a chave usada na chamada nao tem o
        # prefixo, entao guardar com ele faria a comparacao falhar sempre.
        if identifier.startswith("models/"):
            identifier = identifier[len("models/"):]
        ids.add(identifier)
    return ids


async def _check_chat_model_endpoint(
    client: httpx.AsyncClient,
    provider: str,
    url: str,
    *,
    key: str,
    model: str,
    headers: dict[str, str] | None = None,
) -> LLMStatus:
    if not key:
        return _missing(provider)
    try:
        resp = await client.get(url, headers=headers)
        if resp.is_error:
            return _status(
                provider,
                configured=True,
                online=False,
                error=_response_error(resp),
            )
        model_ids = _listed_model_ids(_safe_json(resp))
        wanted = _model_id_without_policy(model.strip())
        if not wanted or wanted not in model_ids:
            return _model_unavailable(provider, wanted or model, model_ids)
        return _status(provider, configured=True, online=True, models=model_ids)
    except Exception as exc:
        return _status(
            provider,
            configured=True,
            online=False,
            error=_exception_error(exc),
        )


async def _catalog(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str] | None = None,
) -> set[str]:
    """Catalogo de modelos por fora da checagem de saude, sem influenciar nela.

    Serve o provedor cuja checagem consulta saldo, e nao modelos: sem isto,
    OpenRouter e DeepSeek ficariam com campo de texto livre na interface
    enquanto todos os outros ganham lista de escolha - e digitar o id na mao e
    o que faz a configuracao apontar para modelo aposentado.

    Falha aqui devolve conjunto vazio de proposito. Catalogo e conveniencia de
    formulario; deixar uma listagem indisponivel marcar o provedor como offline
    seria transformar enfeite em incidente. O custo e uma requisicao a mais por
    checagem, amortizada pelo cache de status.
    """
    try:
        resp = await client.get(url, headers=headers)
        if resp.is_error:
            return set()
        return _listed_model_ids(_safe_json(resp))
    except Exception as exc:
        logger.debug(f"Catalogo de modelos indisponivel em {url}: {exc}")
        return set()


async def _check_json_endpoint(
    client: httpx.AsyncClient,
    provider: str,
    url: str,
    *,
    key: str,
    headers: dict[str, str] | None = None,
) -> LLMStatus:
    """Confirma que o provedor responde, e aproveita o catalogo que ele mandou.

    Estes provedores ja eram checados contra o endpoint de modelos - o corpo da
    resposta so era descartado. Ler os ids aqui nao custa nenhuma requisicao a
    mais e e o que permite a interface oferecer uma lista de escolha em vez de
    um campo de texto livre.
    """
    if not key:
        return _missing(provider)
    try:
        resp = await client.get(url, headers=headers)
        if resp.is_error:
            return _status(
                provider,
                configured=True,
                online=False,
                error=_response_error(resp),
            )
        return _status(
            provider,
            configured=True,
            online=True,
            models=_listed_model_ids(_safe_json(resp)),
        )
    except Exception as exc:
        return _status(provider, configured=True, online=False, error=_exception_error(exc))


async def _check_claude(client: httpx.AsyncClient) -> LLMStatus:
    return await _check_json_endpoint(
        client,
        "claude",
        "https://api.anthropic.com/v1/models",
        key=settings.claude_api_key,
        headers={
            "x-api-key": settings.claude_api_key,
            "anthropic-version": "2023-06-01",
        },
    )


async def _check_gpt(client: httpx.AsyncClient) -> LLMStatus:
    return await _check_json_endpoint(
        client,
        "gpt",
        "https://api.openai.com/v1/models",
        key=settings.openai_api_key,
        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
    )


async def _check_together(client: httpx.AsyncClient) -> LLMStatus:
    return await _check_json_endpoint(
        client,
        "together",
        "https://api.together.xyz/v1/models",
        key=settings.together_api_key,
        headers={"Authorization": f"Bearer {settings.together_api_key}"},
    )


async def _check_openrouter(client: httpx.AsyncClient) -> LLMStatus:
    if not settings.openrouter_api_key:
        return _missing("openrouter")

    try:
        resp = await client.get(
            "https://openrouter.ai/api/v1/credits",
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
        )
        if resp.is_error:
            return _status(
                "openrouter",
                configured=True,
                online=False,
                has_balance_check=True,
                error=_response_error(resp),
            )

        data = _safe_json(resp)
        credits = data.get("data", data) if isinstance(data, dict) else {}
        total = _as_float(credits.get("total_credits"))
        usage = _as_float(credits.get("total_usage"))
        remaining = None if total is None or usage is None else total - usage
        balance = _money(remaining, "USD") if remaining is not None else None
        return _status(
            "openrouter",
            configured=True,
            online=True,
            has_balance_check=True,
            balance_ok=None if remaining is None else remaining > 0,
            balance=balance,
            currency="USD" if remaining is not None else None,
            models=await _catalog(
                client,
                "https://openrouter.ai/api/v1/models",
                {"Authorization": f"Bearer {settings.openrouter_api_key}"},
            ),
        )
    except Exception as exc:
        return _status(
            "openrouter",
            configured=True,
            online=False,
            has_balance_check=True,
            error=_exception_error(exc),
        )


async def _check_deepseek(client: httpx.AsyncClient) -> LLMStatus:
    if not settings.deepseek_api_key:
        return _missing("deepseek")

    try:
        resp = await client.get(
            "https://api.deepseek.com/user/balance",
            headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
        )
        if resp.is_error:
            return _status(
                "deepseek",
                configured=True,
                online=False,
                has_balance_check=True,
                error=_response_error(resp),
            )

        data = _safe_json(resp)
        infos = data.get("balance_infos", []) if isinstance(data, dict) else []
        info = _pick_balance_info(infos)
        amount = _as_float(info.get("total_balance")) if info else None
        currency = info.get("currency") if info else None
        is_available = bool(data.get("is_available")) if isinstance(data, dict) else False
        return _status(
            "deepseek",
            configured=True,
            online=True,
            has_balance_check=True,
            balance_ok=is_available,
            balance=_money(amount, currency) if amount is not None else None,
            currency=currency,
            models=await _catalog(
                client,
                "https://api.deepseek.com/models",
                {"Authorization": f"Bearer {settings.deepseek_api_key}"},
            ),
        )
    except Exception as exc:
        return _status(
            "deepseek",
            configured=True,
            online=False,
            has_balance_check=True,
            error=_exception_error(exc),
        )


async def _check_gemini(client: httpx.AsyncClient) -> LLMStatus:
    return await _check_json_endpoint(
        client,
        "gemini",
        f"https://generativelanguage.googleapis.com/v1beta/models?key={settings.gemini_api_key}",
        key=settings.gemini_api_key,
    )


async def _check_grok(client: httpx.AsyncClient) -> LLMStatus:
    return await _check_chat_model_endpoint(
        client,
        "grok",
        f"{settings.grok_chat_base_url}/models",
        key=settings.grok_api_key,
        model=settings.active_grok_model,
        headers={"Authorization": f"Bearer {settings.grok_api_key}"},
    )


async def _check_hf(client: httpx.AsyncClient) -> LLMStatus:
    return await _check_chat_model_endpoint(
        client,
        "hf",
        "https://router.huggingface.co/v1/models",
        key=settings.huggingface_api_key,
        model=settings.huggingface_model,
        headers={"Authorization": f"Bearer {settings.huggingface_api_key}"},
    )


async def _check_localai(client: httpx.AsyncClient) -> LLMStatus:
    if not settings.localai_base_url:
        return _missing("localai")

    headers = (
        {"Authorization": f"Bearer {settings.localai_api_key}"}
        if settings.localai_api_key
        else None
    )
    try:
        resp = await client.get(
            f"{settings.localai_v1_base_url}/models",
            headers=headers,
        )
        if resp.is_error:
            return _status(
                "localai",
                configured=True,
                online=False,
                error=_response_error(resp),
            )

        data = _safe_json(resp)
        raw_models = data.get("data", []) if isinstance(data, dict) else []
        model_ids = [
            str(model.get("id", ""))
            for model in raw_models
            if isinstance(model, dict) and model.get("id")
        ]
        wanted = settings.localai_model.strip()
        if wanted and wanted not in model_ids:
            root_url = settings.localai_base_url.rstrip("/")
            if root_url.endswith("/v1"):
                root_url = root_url[:-3]
            config_resp = await client.get(
                f"{root_url}/api/models/config-json/{quote(wanted, safe='')}",
                headers=headers,
            )
            config_data = _safe_json(config_resp) if not config_resp.is_error else {}
            if (
                isinstance(config_data, dict)
                and str(config_data.get("name", "")) == wanted
            ):
                return _status(
                    "localai", configured=True, online=True, models=model_ids
                )
            return _status(
                "localai",
                configured=True,
                online=False,
                error=f"Modelo local '{wanted}' nao encontrado no LocalAI",
                models=model_ids,
            )
        if not wanted and not model_ids:
            return _status(
                "localai",
                configured=True,
                online=False,
                error="Nenhum modelo disponivel no LocalAI",
            )
        return _status("localai", configured=True, online=True, models=model_ids)
    except Exception as exc:
        return _status(
            "localai",
            configured=True,
            online=False,
            error=_exception_error(exc),
        )


async def _check_llama(client: httpx.AsyncClient) -> LLMStatus:
    # Endereco vazio nao e falha de rede: e configuracao ausente, e precisa
    # dizer isso. Sem esta guarda a URL vira o caminho relativo `/api/tags`, e o
    # httpx responde "missing an 'http://' or 'https://' protocol" - uma
    # mensagem que manda procurar defeito no Ollama quando o defeito esta em
    # `OLLAMA_BASE_URL`. O `_check_localai` ja fazia essa distincao.
    if not settings.ollama_base_url:
        return _missing("llama")
    try:
        resp = await client.get(f"{settings.ollama_base_url}/api/tags")
        if resp.is_error:
            return _status("llama", configured=True, online=False, error=_response_error(resp))

        data = _safe_json(resp)
        models = data.get("models", []) if isinstance(data, dict) else []
        names = [
            str(model.get("name", ""))
            for model in models
            if isinstance(model, dict)
        ]
        wanted = settings.ollama_model
        has_model = any(name == wanted or name.startswith(f"{wanted}:") for name in names)
        if not has_model:
            return _status(
                "llama",
                configured=True,
                online=False,
                error=f"Modelo local '{wanted}' nao encontrado no Ollama",
                models=names,
            )
        return _status(
            "llama",
            configured=True,
            online=True,
            models=names,
        )
    except Exception as exc:
        return _status("llama", configured=True, online=False, error=_exception_error(exc))


def _response_error(resp: httpx.Response) -> str:
    data = _safe_json(resp)
    if isinstance(data, dict):
        error = data.get("error") or data.get("detail") or data.get("message")
        if isinstance(error, dict):
            return _sanitize_error(str(error.get("message") or error.get("code") or error))
        if error:
            return _sanitize_error(str(error))
    text = resp.text.strip()
    return _sanitize_error(text[:300]) if text else f"HTTP {resp.status_code}"


def _exception_error(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return _sanitize_error(message)
    if isinstance(exc, httpx.TimeoutException):
        return f"Timeout ao consultar o provedor ({exc.__class__.__name__})"
    if isinstance(exc, httpx.ConnectError):
        return f"Falha de conexao ao consultar o provedor ({exc.__class__.__name__})"
    if isinstance(exc, httpx.NetworkError):
        return f"Erro de rede ao consultar o provedor ({exc.__class__.__name__})"
    return exc.__class__.__name__ or "Erro desconhecido ao consultar o provedor"


def _sanitize_error(text: str) -> str:
    """Remove credencial da mensagem antes de ela virar resposta, log ou tela.

    A mensagem de erro do provedor vai inteira para `/llm/config`, para a
    interface e para o log. Provedor que ecoa a chave no proprio erro - e o
    httpx, ao recusar um header malformado - transformaria o diagnostico em
    vazamento. Por isso a redacao e por forma da credencial, e nao por
    provedor: chave nova aparece o tempo todo, e um padrao esquecido aqui e um
    segredo publicado.
    """
    # "Incorrect API key provided: sk-..." (OpenAI)
    text = re.sub(r"provided:\s*[^.\s]+", "provided: [redacted]", text)
    # "Illegal header value b'Bearer sk-or-v1-...'" (httpx recusando o header).
    # `Bearer` e sempre seguido do token; os outros rotulos so contam com o
    # separador explicito, senao a regra come prosa - "API key provided" viraria
    # "API [redacted]".
    text = re.sub(r"(?i)\b(bearer)\s+[\"']?[A-Za-z0-9_\-.]{8,}", r"\1 [redacted]", text)
    text = re.sub(
        r"(?i)\b(authorization|api[-_ ]?key)\s*[:=]\s*[\"']?[A-Za-z0-9_\-.]{8,}",
        r"\1: [redacted]",
        text,
    )
    # Prefixos conhecidos soltos no meio da mensagem, sem rotulo antes.
    text = re.sub(
        r"\b(sk|sk-or|sk-ant|gsk|hf|xai|AIza|pplx|nvapi)[-_][A-Za-z0-9_\-]{6,}",
        "[redacted]",
        text,
    )
    # Chave ja mascarada pelo proprio provedor (`sk-ab****cd`).
    return re.sub(r"\b[A-Za-z0-9_-]{2,}\*{2,}[A-Za-z0-9_-]{2,}\b", "[redacted]", text)


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {}


def _pick_balance_info(infos: Any) -> dict[str, Any]:
    if not isinstance(infos, list):
        return {}
    for item in infos:
        if isinstance(item, dict) and item.get("currency") == "USD":
            return item
    for item in infos:
        if isinstance(item, dict):
            return item
    return {}


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _money(value: float | None, currency: str | None) -> str | None:
    if value is None:
        return None
    suffix = currency or ""
    if suffix:
        return f"{value:.4f} {suffix}"
    return f"{value:.4f}"
