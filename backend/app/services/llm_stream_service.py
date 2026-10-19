"""Streaming dos provedores de IA, com a mesma contabilidade da chamada inteira.

`stream_single` e o par incremental de `llm_service.dispatch_single`: devolve a resposta aos
pedacos (`StreamDelta`) e termina com um `StreamDone` que traz o `LLMResponse` completo, igual ao
que a chamada inteira devolveria. Consumo, custo e falha entram na telemetria e no health da mesma
forma, para o streaming nao deixar buraco no relatorio.

Quem tem streaming de verdade: Claude, GPT, Together, OpenRouter, DeepSeek, Grok/Groq (todos pelo
dialeto `/chat/completions`, exceto o Claude), LocalAI e Ollama. Gemini e Hugging Face respondem
inteiros: o resultado sai como um unico pedaco, e o chamador nao precisa saber a diferenca.

Erro nunca sobe como excecao: vira `StreamDone` com `is_error`, como em `dispatch_single`, para o
grafo seguir o mesmo caminho de falha de sempre.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import AsyncIterator, Callable, List, Optional, Union

import httpx

from ..models.schemas import LLMResponse, Message
from . import llm_service
from .llm_status_service import mark_llm_failure
from .user_llm_config_service import runtime_settings

settings = runtime_settings


@dataclass(frozen=True)
class StreamDelta:
    """Um pedaco de texto da resposta."""

    text: str


@dataclass(frozen=True)
class StreamDone:
    """Fim da resposta: o `LLMResponse` completo, com o texto inteiro e o consumo."""

    response: LLMResponse


StreamEvent = Union[StreamDelta, StreamDone]

_OPENROUTER_HEADERS = {"HTTP-Referer": "http://localhost", "X-Title": "Assistant App"}


def _messages(message: str, history: List[Message], system_prompt: str) -> list[dict]:
    return (
        [{"role": "system", "content": system_prompt}]
        + llm_service._format_history(history)
        + [{"role": "user", "content": message}]
    )


async def stream_openai_compatible(
    service_id: str,
    api_key: str,
    url: str,
    model: str,
    message: str,
    history: List[Message],
    system_prompt: str,
    *,
    headers: Optional[dict] = None,
    require_api_key: bool = True,
    max_tokens: Optional[int] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> AsyncIterator[StreamEvent]:
    """Streaming de qualquer provedor que fale `/v1/chat/completions` (SSE).

    Pede `stream_options.include_usage` para o consumo vir no ultimo pedaco; provedor que nao
    manda fica com `None` (nao informado), nunca zero.
    """
    if require_api_key and not api_key:
        yield StreamDone(LLMResponse(llm=service_id, content="Credencial não configurada", is_error=True))
        return

    start = time.monotonic()
    parts: list[str] = []
    usage: dict = {}
    resolved_model = model
    try:
        request_headers = dict(headers or {})
        if api_key:
            request_headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": model,
            "max_tokens": max_tokens or llm_service._DEFAULT_MAX_TOKENS,
            "messages": _messages(message, history, system_prompt),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        async with httpx.AsyncClient(
            timeout=llm_service._HTTP_LLM_TIMEOUT_SECONDS, transport=transport
        ) as client:
            async with client.stream("POST", url, headers=request_headers, json=payload) as response:
                if response.is_error:
                    await response.aread()
                    data = llm_service._json_response(response)
                    detail = data.get("error", data) if isinstance(data, dict) else data
                    raise Exception(llm_service._error_message(detail))

                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(chunk, dict):
                        continue
                    if chunk.get("error"):
                        raise Exception(llm_service._error_message(chunk["error"]))
                    if isinstance(chunk.get("usage"), dict):
                        usage = chunk["usage"]
                    if chunk.get("model"):
                        resolved_model = str(chunk["model"])
                    choices = chunk.get("choices") or []
                    first = choices[0] if choices and isinstance(choices[0], dict) else {}
                    delta = first.get("delta") or {}
                    text = delta.get("content") if isinstance(delta, dict) else None
                    if text:
                        parts.append(str(text))
                        yield StreamDelta(str(text))
    except Exception as exc:
        yield StreamDone(
            LLMResponse(llm=service_id, content=llm_service._log_llm_error(service_id, exc), is_error=True)
        )
        return

    details = usage.get("prompt_tokens_details") or {}
    yield StreamDone(
        LLMResponse(
            llm=service_id,
            content="".join(parts),
            duration_ms=int((time.monotonic() - start) * 1000),
            tokens_used=usage.get("completion_tokens"),
            model=resolved_model,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            cached_tokens=details.get("cached_tokens") if isinstance(details, dict) else None,
        )
    )


async def _stream_claude(
    message: str,
    history: List[Message],
    system_prompt: str,
    max_tokens: Optional[int],
) -> AsyncIterator[StreamEvent]:
    api_key = llm_service._claude_api_key()
    if not api_key:
        yield StreamDone(LLMResponse(llm="claude", content="Credencial não configurada", is_error=True))
        return

    start = time.monotonic()
    parts: list[str] = []
    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=api_key)
        messages = llm_service._format_history(history) + [{"role": "user", "content": message}]
        async with client.messages.stream(
            model=settings.claude_model,
            max_tokens=max_tokens or llm_service._DEFAULT_MAX_TOKENS,
            system=system_prompt,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                parts.append(text)
                yield StreamDelta(text)
            final = await stream.get_final_message()
    except Exception as exc:
        yield StreamDone(LLMResponse(llm="claude", content=llm_service._log_llm_error("claude", exc), is_error=True))
        return

    usage = final.usage
    yield StreamDone(
        LLMResponse(
            llm="claude",
            content="".join(parts),
            duration_ms=int((time.monotonic() - start) * 1000),
            tokens_used=usage.output_tokens,
            model=settings.claude_model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_tokens=getattr(usage, "cache_read_input_tokens", None),
        )
    )


async def _stream_plain(
    service_id: str,
    streamer: Callable[..., AsyncIterator[str]],
    model: str,
    message: str,
    history: List[Message],
    system_prompt: str,
    max_tokens: Optional[int],
) -> AsyncIterator[StreamEvent]:
    """Provedor local cujo streamer so devolve texto (LocalAI, Ollama): sem consumo informado."""
    start = time.monotonic()
    parts: list[str] = []
    try:
        options = {"max_tokens": max_tokens} if max_tokens is not None and service_id == "localai" else {}
        async for text in streamer(message, history, system_prompt, **options):
            parts.append(text)
            yield StreamDelta(text)
    except Exception as exc:
        yield StreamDone(LLMResponse(llm=service_id, content=llm_service._log_llm_error(service_id, exc), is_error=True))
        return
    yield StreamDone(
        LLMResponse(
            llm=service_id,
            content="".join(parts),
            duration_ms=int((time.monotonic() - start) * 1000),
            model=model,
        )
    )


def _streamer_for(llm: str):
    """Funcao de streaming do provedor, ou `None` quando ele so responde inteiro."""
    if llm == "claude":
        return lambda m, h, s, mt: _stream_claude(m, h, s, mt)
    if llm == "gpt":
        return lambda m, h, s, mt: stream_openai_compatible(
            "gpt", settings.openai_api_key, "https://api.openai.com/v1/chat/completions",
            settings.openai_model, m, h, s, max_tokens=mt,
        )
    if llm == "together":
        return lambda m, h, s, mt: stream_openai_compatible(
            "together", settings.together_api_key, "https://api.together.xyz/v1/chat/completions",
            settings.together_model, m, h, s, max_tokens=mt,
        )
    if llm == "openrouter":
        return lambda m, h, s, mt: stream_openai_compatible(
            "openrouter", settings.openrouter_api_key, "https://openrouter.ai/api/v1/chat/completions",
            settings.openrouter_model, m, h, s, headers=_OPENROUTER_HEADERS, max_tokens=mt,
        )
    if llm == "deepseek":
        return lambda m, h, s, mt: stream_openai_compatible(
            "deepseek", settings.deepseek_api_key, "https://api.deepseek.com/chat/completions",
            settings.deepseek_model, m, h, s, max_tokens=mt,
        )
    if llm == "grok":
        return lambda m, h, s, mt: stream_openai_compatible(
            "grok", settings.grok_api_key, f"{settings.grok_chat_base_url}/chat/completions",
            settings.active_grok_model, m, h, s, max_tokens=mt,
        )
    if llm == "localai":
        return lambda m, h, s, mt: _stream_plain(
            "localai", llm_service.stream_localai, "localai", m, h, s, mt
        )
    if llm == "llama":
        return lambda m, h, s, mt: _stream_plain(
            "llama", llm_service.stream_llama, settings.ollama_model, m, h, s, mt
        )
    return None


async def stream_single(
    llm: str,
    message: str,
    history: List[Message],
    system_prompt: str,
    *,
    max_tokens: Optional[int] = None,
) -> AsyncIterator[StreamEvent]:
    """Resposta de um unico provedor, aos pedacos; o ultimo evento e sempre um `StreamDone`.

    Args:
        llm: chave do provedor.
        message: pergunta atual.
        history: historico da conversa.
        system_prompt: instrucao de sistema.
        max_tokens: teto de tokens da resposta.
    """
    streamer = _streamer_for(llm)
    if streamer is None:
        # Sem streaming: a chamada inteira ja contabiliza, entao so repassa o resultado.
        response = await llm_service.dispatch_single(
            llm, message, history, system_prompt, max_tokens=max_tokens
        )
        if not response.is_error and response.content:
            yield StreamDelta(response.content)
        yield StreamDone(response)
        return

    async for event in streamer(message, history, system_prompt, max_tokens):
        if isinstance(event, StreamDone):
            # O mesmo registro de `dispatch_single`: consumo, custo e falha que realimenta o health.
            llm_service._record_call_usage(event.response)
            if event.response.is_error:
                await mark_llm_failure(llm, event.response.content)
        yield event
