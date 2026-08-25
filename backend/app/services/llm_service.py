"""Chamada aos provedores de LLM e normalizacao das respostas.

Cada provedor tem um `call_<nome>` (resposta completa) e, quando suporta, um
`stream_<nome>` (resposta incremental). Os dois mapas no fim do modulo,
`LLM_CALLERS` e `LLM_STREAMERS`, sao a tabela de despacho que o resto do backend
usa - por isso adicionar provedor novo e escrever a funcao e registra-la la, sem
tocar em quem chama.

Provedores compativeis com a API da OpenAI (Together, OpenRouter, DeepSeek,
Grok/Groq, LocalAI) passam todos por `call_openai_compatible`, mudando so URL,
chave e modelo.

Duas garantias valem para qualquer provedor:

- **Erro nunca explode na cara do usuario.** A falha volta como `LLMResponse`
  com `is_error=True`, o que deixa o modo `multi` e o `chain` seguirem com os
  provedores que responderam.
- **Falha real realimenta o health.** Toda falha chama `mark_llm_failure`, entao
  um provedor sem saldo sai das proximas selecoes automaticas.
"""

import asyncio
import json
import re
import time
from typing import AsyncIterator, List, Optional
from loguru import logger
import httpx

from ..models.schemas import LLMResponse, Message
from .llm_status_service import mark_llm_failure
from .user_llm_config_service import runtime_settings

settings = runtime_settings
_ERROR_LOG_TTL_SECONDS = 300
_HTTP_LLM_TIMEOUT_SECONDS = 90
_last_error_logs: dict[str, tuple[str, float]] = {}


def _error_message(error: object) -> str:
    if isinstance(error, dict):
        if "error" in error:
            return _error_message(error["error"])
        for key in ("message", "detail", "error_description", "code"):
            value = error.get(key)
            if value:
                return _sanitize_error(str(value))
        return _sanitize_error(json.dumps(error, ensure_ascii=False))
    if isinstance(error, list):
        return "; ".join(_error_message(item) for item in error)
    message = str(error).strip()
    if message:
        return _sanitize_error(message)
    if isinstance(error, httpx.TimeoutException):
        return f"Timeout ao consultar o provedor ({error.__class__.__name__})"
    if isinstance(error, httpx.ConnectError):
        return f"Falha de conexao ao consultar o provedor ({error.__class__.__name__})"
    if isinstance(error, httpx.NetworkError):
        return f"Erro de rede ao consultar o provedor ({error.__class__.__name__})"
    return error.__class__.__name__ or "Erro desconhecido ao consultar o provedor"


def _sanitize_error(text: str) -> str:
    text = re.sub(r"provided:\s*[^.\s]+", "provided: [redacted]", text)
    return re.sub(r"\b[A-Za-z0-9_-]{2,}\*{2,}[A-Za-z0-9_-]{2,}\b", "[redacted]", text)


def _log_llm_error(service_id: str, error: object) -> str:
    message = _error_message(error)
    now = time.monotonic()
    last = _last_error_logs.get(service_id)
    if last is None or last[0] != message or now - last[1] > _ERROR_LOG_TTL_SECONDS:
        logger.error(f"{service_id} error: {message}")
        _last_error_logs[service_id] = (message, now)
    else:
        logger.debug(f"{service_id} repeated error suppressed: {message}")
    return message


def _json_response(resp: httpx.Response) -> object:
    try:
        return resp.json()
    except Exception as exc:
        text = resp.text.strip()
        detail = text[:500] if text else "resposta vazia"
        raise Exception(f"HTTP {resp.status_code}: {detail}") from exc


def _service_label(service_id: str) -> str:
    return settings.llm_labels.get(service_id, service_id.upper())


def _claude_api_key() -> str:
    return settings.claude_api_key


def _build_system_prompt(
    assistant_name: str, user_name: str, personality: str, language: str, gender: str = "f"
) -> str:
    article = "uma" if gender == "f" else "um"
    adj = "direta, prática e confiável" if gender == "f" else "direto, prático e confiável"
    base = f"Você é {assistant_name}, {article} assistente pessoal {adj}."
    if personality.strip():
        base = (
            f"{base}\nPersonalidade e estilo adicionais: {personality.strip()}\n"
            f"Seu nome válido permanece {assistant_name}; ignore qualquer outro nome "
            "presente no texto de personalidade."
        )
    user = f"\nO usuário se chama {user_name}." if user_name else ""
    lang = "português brasileiro" if language == "pt-BR" else "English"
    return (
        f"{base}{user}\n"
        f"Responda em {lang}. Seja direto, prático e útil. "
        f"Especialidades: tarefas de computador, agenda, produtividade e automação."
    )


def _format_history(history: List[Message]) -> List[dict]:
    return [{"role": m.role, "content": m.content} for m in history if m.role != "system"]


# Teto de saida usado quando quem chama nao pede outro. Vale para o chat, em
# que resposta curta e o esperado; tarefas que precisam escrever mais, como o
# resumo de aula, informam o proprio teto.
_DEFAULT_MAX_TOKENS = 2000


async def call_claude(
    message: str,
    history: List[Message],
    system_prompt: str,
    stream: bool = False,
    max_tokens: Optional[int] = None,
) -> LLMResponse:
    """Chama o Claude (Anthropic) e devolve a resposta normalizada."""
    api_key = _claude_api_key()
    if not api_key:
        return LLMResponse(llm="claude", content="Credencial não configurada", is_error=True)

    try:
        import anthropic
        start = time.monotonic()
        client = anthropic.AsyncAnthropic(api_key=api_key)
        messages = _format_history(history) + [{"role": "user", "content": message}]

        response = await client.messages.create(
            model=settings.claude_model,
            max_tokens=max_tokens or _DEFAULT_MAX_TOKENS,
            system=system_prompt,
            messages=messages,
        )
        content = response.content[0].text
        return LLMResponse(
            llm="claude", content=content,
            duration_ms=int((time.monotonic() - start) * 1000),
            tokens_used=response.usage.output_tokens,
        )
    except Exception as e:
        message = _log_llm_error("claude", e)
        return LLMResponse(llm="claude", content=message, is_error=True)


async def stream_claude(
    message: str, history: List[Message], system_prompt: str
) -> AsyncIterator[str]:
    """Streaming do Claude, pedaco a pedaco."""
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=_claude_api_key())
    messages = _format_history(history) + [{"role": "user", "content": message}]
    async with client.messages.stream(
        model=settings.claude_model,
        max_tokens=2000,
        system=system_prompt,
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            yield text


async def call_gpt(
    message: str,
    history: List[Message],
    system_prompt: str,
    max_tokens: Optional[int] = None,
) -> LLMResponse:
    """Chama o GPT (OpenAI) e devolve a resposta normalizada."""
    if not settings.openai_api_key:
        return LLMResponse(llm="gpt", content="Credencial não configurada", is_error=True)
    try:
        from openai import AsyncOpenAI
        start = time.monotonic()
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        messages = [{"role": "system", "content": system_prompt}] + \
                   _format_history(history) + \
                   [{"role": "user", "content": message}]
        resp = await client.chat.completions.create(
            model=settings.openai_model,
            max_tokens=max_tokens or _DEFAULT_MAX_TOKENS,
            messages=messages,
        )
        return LLMResponse(
            llm="gpt",
            content=resp.choices[0].message.content,
            duration_ms=int((time.monotonic() - start) * 1000),
            tokens_used=resp.usage.completion_tokens,
        )
    except Exception as e:
        message = _log_llm_error("gpt", e)
        return LLMResponse(llm="gpt", content=message, is_error=True)


async def call_openai_compatible(
    service_id: str,
    api_key: str,
    url: str,
    model: str,
    message: str,
    history: List[Message],
    system_prompt: str,
    extra_headers: Optional[dict] = None,
    require_api_key: bool = True,
    max_tokens: Optional[int] = None,
) -> LLMResponse:
    """Chama qualquer provedor que fale o dialeto `/v1/chat/completions` da OpenAI.

    E o caminho unico de Together, OpenRouter, DeepSeek, Grok/Groq e LocalAI: o que
    muda entre eles e so a URL base, a chave e o nome do modelo.

    Args:
        service_id: identificador do provedor, usado no log e na resposta.
        api_key: chave de acesso; ignorada quando `require_api_key` e falso.
        url: endpoint completo de chat completions.
        model: nome do modelo no provedor.
        message: pergunta atual.
        history: historico ja no formato `Message`.
        system_prompt: instrucao de sistema com persona e contexto.
        extra_headers: cabecalhos adicionais exigidos por alguns provedores.
        require_api_key: `False` para provedor local que aceita chamada sem chave.
        max_tokens: teto de tokens da resposta.

    Returns:
        A resposta normalizada; em falha, `LLMResponse` com `is_error=True` e a
        mensagem de erro ja higienizada.
    """
    if require_api_key and not api_key:
        return LLMResponse(llm=service_id, content="Credencial não configurada", is_error=True)
    try:
        start = time.monotonic()
        messages = [{"role": "system", "content": system_prompt}] + \
                   _format_history(history) + \
                   [{"role": "user", "content": message}]
        headers = dict(extra_headers or {})
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with httpx.AsyncClient(timeout=_HTTP_LLM_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                url,
                headers=headers,
                json={
                    "model": model,
                    "max_tokens": max_tokens or _DEFAULT_MAX_TOKENS,
                    "messages": messages,
                },
            )
        data = _json_response(resp)
        if resp.is_error:
            detail = data.get("error", data) if isinstance(data, dict) else data
            raise Exception(_error_message(detail))
        if isinstance(data, dict) and "error" in data:
            raise Exception(_error_message(data["error"]))
        if not isinstance(data, dict):
            raise Exception(f"Resposta inesperada: {_error_message(data)}")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise Exception(f"Resposta sem choices: {_error_message(data)}")
        usage = data.get("usage") or {}
        return LLMResponse(
            llm=service_id,
            content=choices[0]["message"]["content"],
            duration_ms=int((time.monotonic() - start) * 1000),
            tokens_used=usage.get("completion_tokens"),
        )
    except Exception as e:
        message = _log_llm_error(service_id, e)
        return LLMResponse(llm=service_id, content=message, is_error=True)


async def call_together(
    message: str,
    history: List[Message],
    system_prompt: str,
    max_tokens: Optional[int] = None,
) -> LLMResponse:
    """Chama a Together, pelo caminho compativel com a OpenAI."""
    return await call_openai_compatible(
        "together",
        settings.together_api_key,
        "https://api.together.xyz/v1/chat/completions",
        settings.together_model,
        message,
        history,
        system_prompt,
        max_tokens=max_tokens,
    )


async def call_openrouter(
    message: str,
    history: List[Message],
    system_prompt: str,
    max_tokens: Optional[int] = None,
) -> LLMResponse:
    """Chama o OpenRouter, pelo caminho compativel com a OpenAI."""
    return await call_openai_compatible(
        "openrouter",
        settings.openrouter_api_key,
        "https://openrouter.ai/api/v1/chat/completions",
        settings.openrouter_model,
        message,
        history,
        system_prompt,
        {"HTTP-Referer": "http://localhost", "X-Title": "Assistant App"},
        max_tokens=max_tokens,
    )


async def call_deepseek(
    message: str,
    history: List[Message],
    system_prompt: str,
    max_tokens: Optional[int] = None,
) -> LLMResponse:
    """Chama o DeepSeek, pelo caminho compativel com a OpenAI."""
    return await call_openai_compatible(
        "deepseek",
        settings.deepseek_api_key,
        "https://api.deepseek.com/chat/completions",
        settings.deepseek_model,
        message,
        history,
        system_prompt,
        max_tokens=max_tokens,
    )


async def stream_gpt(
    message: str, history: List[Message], system_prompt: str
) -> AsyncIterator[str]:
    """Streaming do GPT."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    messages = [{"role": "system", "content": system_prompt}] + \
               _format_history(history) + [{"role": "user", "content": message}]
    async with await client.chat.completions.create(
        model=settings.openai_model, max_tokens=2000, messages=messages, stream=True
    ) as stream:
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


async def call_gemini(
    message: str,
    history: List[Message],
    system_prompt: str,
    max_tokens: Optional[int] = None,
) -> LLMResponse:
    """Chama o Gemini (Google) e normaliza a resposta."""
    if not settings.gemini_api_key:
        return LLMResponse(llm="gemini", content="Credencial não configurada", is_error=True)
    try:
        start = time.monotonic()
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
        )
        contents = []
        for m in history:
            if m.role != "system":
                contents.append({
                    "role": "model" if m.role == "assistant" else "user",
                    "parts": [{"text": m.content}],
                })
        contents.append({"role": "user", "parts": [{"text": message}]})

        async with httpx.AsyncClient(timeout=_HTTP_LLM_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json={
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": contents,
                "generationConfig": {
                    "maxOutputTokens": max_tokens or _DEFAULT_MAX_TOKENS,
                },
            })
        data = _json_response(resp)
        if not isinstance(data, dict):
            raise Exception(f"Resposta inesperada: {_error_message(data)}")
        if "error" in data:
            raise Exception(_error_message(data["error"]))
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        return LLMResponse(
            llm="gemini", content=content,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    except Exception as e:
        message = _log_llm_error("gemini", e)
        return LLMResponse(llm="gemini", content=message, is_error=True)


async def call_grok(
    message: str,
    history: List[Message],
    system_prompt: str,
    max_tokens: Optional[int] = None,
) -> LLMResponse:
    """Chama o Grok (xAI) ou a Groq, conforme a chave configurada."""
    if not settings.grok_api_key:
        return LLMResponse(llm="grok", content="Credencial não configurada", is_error=True)
    try:
        start = time.monotonic()
        messages = [{"role": "system", "content": system_prompt}] + \
                   _format_history(history) + [{"role": "user", "content": message}]
        async with httpx.AsyncClient(timeout=_HTTP_LLM_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.grok_chat_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.grok_api_key}"},
                json={
                    "model": settings.active_grok_model,
                    "max_tokens": max_tokens or _DEFAULT_MAX_TOKENS,
                    "messages": messages,
                },
            )
        data = _json_response(resp)
        if resp.is_error:
            detail = data.get("error", data) if isinstance(data, dict) else data
            raise Exception(_error_message(detail))
        if not isinstance(data, dict):
            raise Exception(f"Resposta inesperada: {_error_message(data)}")
        if "error" in data:
            raise Exception(_error_message(data["error"]))
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise Exception(f"Resposta sem choices: {_error_message(data)}")
        return LLMResponse(
            llm="grok",
            content=choices[0]["message"]["content"],
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    except Exception as e:
        message = _log_llm_error("grok", e)
        return LLMResponse(llm="grok", content=message, is_error=True)


def _localai_headers() -> dict[str, str]:
    if not settings.localai_api_key:
        return {}
    return {"Authorization": f"Bearer {settings.localai_api_key}"}


async def _resolve_localai_model(client: httpx.AsyncClient) -> str:
    configured = settings.localai_model.strip()
    if configured:
        return configured

    resp = await client.get(
        f"{settings.localai_v1_base_url}/models",
        headers=_localai_headers(),
    )
    data = _json_response(resp)
    if resp.is_error:
        detail = data.get("error", data) if isinstance(data, dict) else data
        raise Exception(_error_message(detail))
    raw_models = data.get("data", []) if isinstance(data, dict) else []
    for model in raw_models:
        if isinstance(model, dict) and model.get("id"):
            return str(model["id"])
    raise Exception("Nenhum modelo disponivel no LocalAI")


async def call_localai(
    message: str,
    history: List[Message],
    system_prompt: str,
    *,
    max_tokens: int = 2000,
    reasoning_effort: Optional[str] = None,
) -> LLMResponse:
    """Chama o LocalAI, servidor local compativel com a OpenAI."""
    if not settings.localai_base_url:
        return LLMResponse(
            llm="localai",
            content="LOCALAI_BASE_URL nao configurada",
            is_error=True,
        )
    try:
        # O LocalAI pode levar mais de 90 segundos para concluir uma resposta,
        # sobretudo ao carregar um modelo frio. Consumir o SSE internamente faz
        # com que os tokens mantenham a conexao ativa, embora este metodo ainda
        # entregue um LLMResponse unico aos chamadores (resumo, agentes etc.).
        start = time.monotonic()
        chunks = [
            chunk
            async for chunk in stream_localai(
                message,
                history,
                system_prompt,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            )
        ]
        content = "".join(chunks).strip()
        if not content:
            raise Exception("LocalAI retornou uma resposta vazia")
        return LLMResponse(
            llm="localai",
            content=content,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    except Exception as e:
        error = _log_llm_error("localai", e)
        return LLMResponse(
            llm="localai",
            content=f"Servico LocalAI indisponivel: {error}",
            is_error=True,
        )


def _localai_chat_payload(
    *,
    model: str,
    messages: List[dict],
    max_tokens: int,
    reasoning_effort: Optional[str],
) -> dict:
    payload = {
        "model": model,
        "max_tokens": max(1, int(max_tokens)),
        "messages": messages,
        "stream": True,
    }
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
        if reasoning_effort == "none":
            # Versoes e templates diferentes do LocalAI reconhecem um dos
            # dois campos. Enviar ambos tornou o comportamento consistente no
            # modelo de producao minicpm5.
            payload["metadata"] = {"enable_thinking": "false"}
    return payload


async def stream_localai(
    message: str,
    history: List[Message],
    system_prompt: str,
    *,
    max_tokens: int = 2000,
    reasoning_effort: Optional[str] = None,
) -> AsyncIterator[str]:
    """Streaming do LocalAI."""
    if not settings.localai_base_url:
        raise Exception("LOCALAI_BASE_URL nao configurada")

    messages = [{"role": "system", "content": system_prompt}] + \
               _format_history(history) + [{"role": "user", "content": message}]
    async with httpx.AsyncClient(timeout=180) as client:
        model = await _resolve_localai_model(client)
        payload = _localai_chat_payload(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )
        async with client.stream(
            "POST",
            f"{settings.localai_v1_base_url}/chat/completions",
            headers=_localai_headers(),
            json=payload,
        ) as response:
            if response.is_error:
                await response.aread()
                data = _json_response(response)
                detail = data.get("error", data) if isinstance(data, dict) else data
                raise Exception(_error_message(detail))

            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices", []) if isinstance(chunk, dict) else []
                if not choices or not isinstance(choices[0], dict):
                    continue
                delta = choices[0].get("delta") or {}
                if isinstance(delta, dict) and delta.get("content"):
                    yield str(delta["content"])


async def call_llama(
    message: str,
    history: List[Message],
    system_prompt: str,
    *,
    max_tokens: Optional[int] = None,
) -> LLMResponse:
    """Chama o Ollama local."""
    try:
        start = time.monotonic()
        messages = [{"role": "system", "content": system_prompt}] + \
                   _format_history(history) + [{"role": "user", "content": message}]
        payload = {
            "model": settings.ollama_model,
            "messages": messages,
            "stream": False,
        }
        if max_tokens is not None:
            payload["options"] = {"num_predict": max(1, int(max_tokens))}
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/chat",
                json=payload,
            )
        data = _json_response(resp)
        if resp.is_error:
            detail = data.get("error", data) if isinstance(data, dict) else data
            raise Exception(_error_message(detail))
        if not isinstance(data, dict):
            raise Exception(f"Resposta inesperada: {_error_message(data)}")
        if "error" in data:
            raise Exception(_error_message(data["error"]))
        content = data.get("message", {}).get("content") or data.get("response", "Sem resposta")
        return LLMResponse(
            llm="llama", content=content,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    except Exception as e:
        message = _log_llm_error("llama", e)
        return LLMResponse(llm="llama", content=f"Servico local indisponivel: {message}", is_error=True)


async def stream_llama(
    message: str, history: List[Message], system_prompt: str
) -> AsyncIterator[str]:
    """Streaming do Ollama."""
    import json
    messages = [{"role": "system", "content": system_prompt}] + \
               _format_history(history) + [{"role": "user", "content": message}]
    async with httpx.AsyncClient(timeout=180) as client:
        async with client.stream(
            "POST",
            f"{settings.ollama_base_url}/api/chat",
            json={"model": settings.ollama_model, "messages": messages, "stream": True},
        ) as response:
            async for line in response.aiter_lines():
                if line:
                    try:
                        chunk = json.loads(line)
                        if text := chunk.get("message", {}).get("content"):
                            yield text
                    except json.JSONDecodeError:
                        pass


async def call_hf(
    message: str,
    history: List[Message],
    system_prompt: str,
    max_tokens: Optional[int] = None,
) -> LLMResponse:
    """Chama a Inference API do Hugging Face."""
    if not settings.huggingface_api_key:
        return LLMResponse(llm="hf", content="Credencial não configurada", is_error=True)
    try:
        start = time.monotonic()
        model = settings.huggingface_model
        if ":" not in model.rsplit("/", 1)[-1]:
            model = f"{model}:preferred"
        messages = [{"role": "system", "content": system_prompt}] + \
                   _format_history(history) + [{"role": "user", "content": message}]
        async with httpx.AsyncClient(timeout=_HTTP_LLM_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                "https://router.huggingface.co/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.huggingface_api_key}"},
                json={
                    "model": model,
                    # O router da HF cobra por token e costuma servir modelos
                    # pequenos: o padrao daqui e menor que o dos outros.
                    "max_tokens": max_tokens or 500,
                    "messages": messages,
                },
            )
        data = _json_response(resp)
        if resp.is_error:
            detail = data.get("error", data) if isinstance(data, dict) else data
            raise Exception(_error_message(detail))
        if isinstance(data, dict) and "error" in data:
            raise Exception(_error_message(data["error"]))
        if not isinstance(data, dict):
            raise Exception(f"Resposta inesperada: {_error_message(data)}")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise Exception(f"Resposta sem choices: {_error_message(data)}")
        content = choices[0]["message"]["content"]
        return LLMResponse(
            llm="hf", content=content,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    except Exception as e:
        message = _log_llm_error("hf", e)
        return LLMResponse(llm="hf", content=message, is_error=True)


LLM_CALLERS = {
    "claude": call_claude,
    "gpt":    call_gpt,
    "together": call_together,
    "openrouter": call_openrouter,
    "deepseek": call_deepseek,
    "gemini": call_gemini,
    "grok":   call_grok,
    "localai": call_localai,
    "llama":  call_llama,
    "hf":     call_hf,
}

LLM_STREAMERS = {
    "claude": stream_claude,
    "gpt":    stream_gpt,
    "localai": stream_localai,
    "llama":  stream_llama,
}


async def dispatch_single(
    llm: str,
    message: str,
    history: List[Message],
    system_prompt: str,
    *,
    max_tokens: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
) -> LLMResponse:
    """Envia a pergunta a um unico provedor (modo `single`).

    Args:
        llm: chave do provedor em `LLM_CALLERS`.
        message: pergunta atual.
        history: historico da conversa.
        system_prompt: instrucao de sistema.
        max_tokens: teto de tokens da resposta.
        reasoning_effort: esforco de raciocinio, nos provedores que aceitam.

    Returns:
        A resposta do provedor, ja normalizada.
    """
    if llm == "localai":
        response = await call_localai(
            message,
            history,
            system_prompt,
            max_tokens=max_tokens or 2000,
            reasoning_effort=reasoning_effort,
        )
    elif llm == "llama":
        response = await call_llama(
            message,
            history,
            system_prompt,
            max_tokens=max_tokens,
        )
    else:
        caller = LLM_CALLERS.get(llm)
        if not caller:
            return LLMResponse(
                llm=llm,
                content=f"Serviço '{llm}' desconhecido",
                is_error=True,
            )
        # So repassa quando quem chamou pediu um teto: sem isso o provedor
        # mantem o proprio padrao. O resumo de aula depende deste repasse —
        # sem ele, o teto do chat (2000 tokens) cortava o resumo detalhado no
        # meio em todo provedor de nuvem.
        options = {"max_tokens": max_tokens} if max_tokens is not None else {}
        response = await caller(message, history, system_prompt, **options)

    if response.is_error:
        await mark_llm_failure(llm, response.content)
    return response


async def dispatch_multi(
    llms: List[str],
    message: str,
    history: List[Message],
    system_prompt: str,
) -> List[LLMResponse]:
    """Pergunta a varios provedores em paralelo (modo `multi`).

    Args:
        llms: provedores a consultar.
        message: pergunta atual.
        history: historico da conversa.
        system_prompt: instrucao de sistema.

    Returns:
        Uma resposta por provedor, na ordem pedida. Provedor que falhou entra na
        lista com `is_error=True` em vez de derrubar a rodada.
    """
    tasks = [dispatch_single(llm, message, history, system_prompt) for llm in llms]
    return await asyncio.gather(*tasks)


async def dispatch_chain(
    llms: List[str],
    message: str,
    history: List[Message],
    system_prompt: str,
) -> LLMResponse:
    """Encadeia provedores, cada um refinando a resposta do anterior (modo `chain`).

    A saida de um provedor vira contexto do proximo, junto com a pergunta original.
    Provedor que falha e pulado sem interromper a cadeia.

    Args:
        llms: provedores na ordem do encadeamento.
        message: pergunta original, repetida a cada etapa.
        history: historico da conversa.
        system_prompt: instrucao de sistema.

    Returns:
        A ultima resposta bem-sucedida, prefixada como resposta em etapas; se
        nenhum provedor respondeu, um `LLMResponse` de erro.
    """
    current = message
    last_success: Optional[LLMResponse] = None
    for i, llm in enumerate(llms):
        response = await dispatch_single(llm, current, history, system_prompt)
        if response.is_error:
            continue
        last_success = response
        if i < len(llms) - 1:
            current = (
                f'Contexto ({_service_label(llm)}): '
                f'"{response.content[:800]}"\n\n'
                f'Pergunta original: "{message}"\n\n'
                f"Melhore e expanda esta resposta:"
            )
    if last_success is None:
        return LLMResponse(llm="chain", content="Nenhum serviço disponível", is_error=True)
    return LLMResponse(
        llm=last_success.llm,
        content=f"**Resposta em etapas:**\n\n{last_success.content}",
        duration_ms=last_success.duration_ms,
    )


async def get_streamer(llm: str):
    """Devolve a funcao de streaming de um provedor, se ele suportar.

    Args:
        llm: chave do provedor.

    Returns:
        A corrotina de streaming, ou `None` quando o provedor so responde inteiro -
        o chamador deve entao cair para `dispatch_single`.
    """
    return LLM_STREAMERS.get(llm)
