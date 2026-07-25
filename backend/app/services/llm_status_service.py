import asyncio
import re
import time
from typing import Any

import httpx

from ..core.config import get_settings
from ..models.schemas import LLMStatus

settings = get_settings()

_CACHE_TTL_SECONDS = 300
_FAILED_CACHE_TTL_SECONDS = 30
_cache: dict[str, LLMStatus] | None = None
_cache_at = 0.0
_refresh_task: asyncio.Task | None = None

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
    global _cache, _cache_at

    now = time.monotonic()
    if not force and _cache is not None and _is_cache_fresh(_cache, now):
        return _cache

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

    _cache = {status.id: status for status in results}
    _cache_at = time.monotonic()
    return _cache


async def get_available_llms(force: bool = False) -> list[str]:
    statuses = await get_llm_statuses(force=force)
    return [
        provider
        for provider in _PROVIDER_ORDER
        if statuses.get(provider) is not None and statuses[provider].available
    ]


async def get_statuses_fast() -> dict[str, LLMStatus]:
    """Return cached statuses instantly; if cache is cold, return key-based statuses and
    kick off a background refresh so the next call will have real data."""
    global _cache, _cache_at, _refresh_task

    now = time.monotonic()
    if _cache is not None and _is_cache_fresh(_cache, now):
        return _cache

    # Cache is cold — build a quick "key configured" status for each active LLM
    fast: dict[str, LLMStatus] = {}
    for provider in _PROVIDER_ORDER:
        key_present = bool(_provider_key(provider))
        fast[provider] = _checking(provider) if key_present else _missing(provider)

    # Trigger a real check in the background so the 5-min cache warms up
    if _refresh_task is None or _refresh_task.done():
        try:
            loop = asyncio.get_running_loop()
            _refresh_task = loop.create_task(get_llm_statuses())
        except RuntimeError:
            pass

    return fast


def _is_cache_fresh(cache: dict[str, LLMStatus], now: float) -> bool:
    ttl = (
        _CACHE_TTL_SECONDS
        if any(status.available for status in cache.values())
        else _FAILED_CACHE_TTL_SECONDS
    )
    return now - _cache_at < ttl


def _provider_key(provider: str) -> str:
    return {
        "claude": settings.claude_api_key,
        "gpt": settings.openai_api_key,
        "together": settings.together_api_key,
        "openrouter": settings.openrouter_api_key,
        "deepseek": settings.deepseek_api_key,
        "gemini": settings.gemini_api_key,
        "grok": settings.grok_api_key,
        "hf": settings.huggingface_api_key,
        "localai": settings.localai_base_url,
        "llama": "local",  # always "configured" (local Ollama)
    }.get(provider, "")


def _label(provider: str) -> str:
    return settings.llm_labels.get(provider, provider.upper())


def _missing(provider: str) -> LLMStatus:
    error = (
        "LOCALAI_BASE_URL nao configurada"
        if provider == "localai"
        else "Credencial nao configurada"
    )
    return LLMStatus(
        id=provider,
        label=_label(provider),
        configured=False,
        status="missing_key",
        error=error,
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
    )


async def _check_json_endpoint(
    client: httpx.AsyncClient,
    provider: str,
    url: str,
    *,
    key: str,
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
        return _status(provider, configured=True, online=True)
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
    return await _check_json_endpoint(
        client,
        "grok",
        f"{settings.grok_chat_base_url}/models",
        key=settings.grok_api_key,
        headers={"Authorization": f"Bearer {settings.grok_api_key}"},
    )


async def _check_hf(client: httpx.AsyncClient) -> LLMStatus:
    return await _check_json_endpoint(
        client,
        "hf",
        "https://router.huggingface.co/v1/models",
        key=settings.huggingface_api_key,
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
            return _status(
                "localai",
                configured=True,
                online=False,
                error=f"Modelo local '{wanted}' nao encontrado no LocalAI",
            )
        if not wanted and not model_ids:
            return _status(
                "localai",
                configured=True,
                online=False,
                error="Nenhum modelo disponivel no LocalAI",
            )
        return _status("localai", configured=True, online=True)
    except Exception as exc:
        return _status(
            "localai",
            configured=True,
            online=False,
            error=_exception_error(exc),
        )


async def _check_llama(client: httpx.AsyncClient) -> LLMStatus:
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
            )
        return _status(
            "llama",
            configured=True,
            online=True,
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
    text = re.sub(r"provided:\s*[^.\s]+", "provided: [redacted]", text)
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
