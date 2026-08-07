from __future__ import annotations

import asyncio
import json
import re
import uuid
from typing import Any, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import BaseTool
from loguru import logger
from pydantic import BaseModel

from ..core.config import get_settings
from ..models.schemas import LLMResponse, Message
from . import llm_service


settings = get_settings()


class StructuredModelResponse(BaseModel):
    provider: str
    content: str
    is_error: bool = False
    duration_ms: int = 0
    tokens_used: int | None = None

    def to_llm_response(self) -> LLMResponse:
        return LLMResponse(
            llm=self.provider,
            content=self.content,
            is_error=self.is_error,
            duration_ms=self.duration_ms,
            tokens_used=self.tokens_used,
        )


def _text_content(message: BaseMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return json.dumps(message.content, ensure_ascii=False, default=str)


def _provider_request(
    messages: list[BaseMessage],
) -> tuple[str, list[Message], str]:
    system_parts: list[str] = []
    conversation: list[BaseMessage] = []

    for message in messages:
        if isinstance(message, SystemMessage):
            system_parts.append(_text_content(message))
        else:
            conversation.append(message)

    if not conversation:
        return "\n".join(system_parts), [], ""

    current_message = conversation[-1]
    history_messages = conversation[:-1]
    history: list[Message] = []
    for item in history_messages:
        role = "assistant" if isinstance(item, AIMessage) else "user"
        history.append(Message(role=role, content=_render(item)))

    return (
        "\n".join(system_parts),
        history,
        _render(current_message),
    )


def _render(message: BaseMessage) -> str:
    """Texto legivel para o provedor, que so aceita user/assistant/system.

    Um AIMessage que so tem tool_calls chega com content vazio; mandar string
    vazia ao provedor perde o passo do raciocinio e alguns modelos recusam a
    mensagem. Por isso a chamada e o resultado viram texto explicito.
    """
    if isinstance(message, ToolMessage):
        return f"Resultado da ferramenta: {_text_content(message)}"
    if isinstance(message, AIMessage) and message.tool_calls:
        calls = ", ".join(
            f"{call['name']}({json.dumps(call.get('args', {}), ensure_ascii=False)})"
            for call in message.tool_calls
        )
        body = _text_content(message).strip()
        return f"{body}\nChamei a ferramenta: {calls}".strip()
    return _text_content(message)


_TOOL_PROTOCOL = (
    "\n\nVoce pode usar ferramentas. Quando uma ferramenta resolver o pedido, "
    "responda SOMENTE com este JSON, sem markdown e sem texto em volta:\n"
    '{"tool": "nome_da_ferramenta", "args": {...}}\n'
    "Quando nenhuma ferramenta for necessaria, responda normalmente em texto, "
    "sem JSON. Nunca invente nomes de ferramenta fora da lista.\n\n"
    "Ferramentas disponiveis:\n"
)


def _tool_catalog(tools: Sequence[BaseTool]) -> str:
    entries = []
    for tool in tools:
        try:
            args = json.dumps(tool.args, ensure_ascii=False)
        except Exception:
            args = "{}"
        entries.append(f"- {tool.name}: {tool.description}\n  argumentos: {args}")
    return _TOOL_PROTOCOL + "\n".join(entries)


def _parse_tool_call(content: str, names: set[str]) -> dict[str, Any] | None:
    """Le a escolha de ferramenta do texto devolvido pelo provedor.

    O gateway fala com dez provedores por HTTP proprio, e varios (Ollama,
    LocalAI, HF) nao expoem tool-calling nativo. Um protocolo textual unico
    funciona em todos sem reescrever as dez integracoes; a validacao contra a
    lista de nomes e o que impede alucinacao virar chamada de ferramenta.
    """
    text = (content or "").strip()
    if not text:
        return None

    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None

    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    name = payload.get("tool")
    if not isinstance(name, str) or name not in names:
        return None
    args = payload.get("args")
    return {"name": name, "args": args if isinstance(args, dict) else {}}


class ProviderChatModel(BaseChatModel):
    """LangChain chat-model adapter over the existing provider gateway."""

    provider: str
    bound_tools: list[Any] = []

    @property
    def _llm_type(self) -> str:
        return "assistant-provider-gateway"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"provider": self.provider}

    def bind_tools(
        self,
        tools: Sequence[Any],
        **kwargs: Any,
    ) -> "ProviderChatModel":
        return self.model_copy(update={"bound_tools": list(tools)})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs: Any,
    ) -> ChatResult:
        return asyncio.run(
            self._agenerate(
                messages,
                stop=stop,
                run_manager=None,
                **kwargs,
            )
        )

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs: Any,
    ) -> ChatResult:
        system_prompt, history, message = _provider_request(messages)
        if self.bound_tools:
            system_prompt += _tool_catalog(self.bound_tools)

        response = await llm_service.dispatch_single(
            self.provider,
            message,
            history,
            system_prompt,
        )

        metadata = {
            "provider": response.llm,
            "is_error": response.is_error,
            "duration_ms": response.duration_ms,
            "tokens_used": response.tokens_used,
        }

        tool_calls = []
        if self.bound_tools and not response.is_error:
            names = {tool.name for tool in self.bound_tools}
            parsed = _parse_tool_call(response.content, names)
            if parsed:
                tool_calls = [{
                    "name": parsed["name"],
                    "args": parsed["args"],
                    "id": f"call_{uuid.uuid4().hex[:12]}",
                }]

        ai_message = AIMessage(
            content="" if tool_calls else response.content,
            tool_calls=tool_calls,
            response_metadata=metadata,
        )
        return ChatResult(
            generations=[ChatGeneration(message=ai_message)],
            llm_output={"provider": response.llm},
        )


def _structured_response(message: AIMessage) -> StructuredModelResponse:
    metadata = message.response_metadata
    return StructuredModelResponse(
        provider=str(metadata.get("provider") or "unknown"),
        content=_text_content(message),
        is_error=bool(metadata.get("is_error", False)),
        duration_ms=int(metadata.get("duration_ms") or 0),
        tokens_used=metadata.get("tokens_used"),
    )


def _langchain_messages(
    message: str,
    history: list[Message],
    system_prompt: str,
) -> list[BaseMessage]:
    messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]
    for item in history:
        if item.role == "assistant":
            messages.append(AIMessage(content=item.content))
        elif item.role == "user":
            messages.append(HumanMessage(content=item.content))
    messages.append(HumanMessage(content=message))
    return messages


async def dispatch_single(
    provider: str,
    message: str,
    history: list[Message],
    system_prompt: str,
) -> LLMResponse:
    model = ProviderChatModel(provider=provider)
    chain = model | RunnableLambda(_structured_response)
    structured = await chain.ainvoke(
        _langchain_messages(message, history, system_prompt)
    )
    return structured.to_llm_response()


async def run_with_tools(
    provider: str,
    message: str,
    history: list[Message],
    system_prompt: str,
    tools: Sequence[BaseTool],
    max_iterations: int = 3,
    stop_tools: set[str] | None = None,
) -> tuple[LLMResponse, list[dict[str, Any]]]:
    """Ciclo modelo -> ferramenta -> modelo, com teto de iteracoes.

    Devolve a resposta final e o rastro de ferramentas usadas, que o grafo
    repassa para a interface poder mostrar o que foi executado.

    `stop_tools` interrompe o ciclo assim que uma dessas ferramentas e chamada,
    sem executa-la. E o que permite a transferencia entre agentes: quem decide
    o repasse e o orquestrador, nao a ferramenta.
    """
    stop_tools = stop_tools or set()
    if not tools:
        return await dispatch_single(provider, message, history, system_prompt), []

    model = ProviderChatModel(provider=provider).bind_tools(tools)
    by_name = {tool.name: tool for tool in tools}
    messages = _langchain_messages(message, history, system_prompt)
    trace: list[dict[str, Any]] = []

    for _ in range(max_iterations):
        result = await model.ainvoke(messages)
        if not isinstance(result, AIMessage):
            break
        if not result.tool_calls:
            return _structured_response(result).to_llm_response(), trace

        handoff = next(
            (call for call in result.tool_calls if call["name"] in stop_tools),
            None,
        )
        if handoff is not None:
            trace.append({
                "tool": handoff["name"],
                "args": handoff.get("args") or {},
                "output": "",
                "stopped": True,
            })
            return _structured_response(result).to_llm_response(), trace

        messages.append(result)
        for call in result.tool_calls:
            tool = by_name.get(call["name"])
            if tool is None:
                output: Any = f"ferramenta desconhecida: {call['name']}"
            else:
                try:
                    output = await tool.ainvoke(call.get("args") or {})
                except Exception as e:
                    logger.warning(f"Ferramenta {call['name']} falhou: {e}")
                    output = f"erro ao executar: {e}"
            trace.append({
                "tool": call["name"],
                "args": call.get("args") or {},
                "output": str(output)[:2000],
            })
            messages.append(
                ToolMessage(content=str(output), tool_call_id=call["id"])
            )

    # Estourou o teto: pede a resposta final sem ferramentas para nao devolver
    # um JSON de tool-call cru ao usuario.
    system_prompt, plain_history, plain_message = _provider_request(messages)
    final = await llm_service.dispatch_single(
        provider,
        plain_message
        or "Responda ao pedido original usando os resultados acima.",
        plain_history,
        system_prompt,
    )
    return final, trace


async def dispatch_multi(
    providers: list[str],
    message: str,
    history: list[Message],
    system_prompt: str,
) -> list[LLMResponse]:
    tasks = [
        dispatch_single(provider, message, history, system_prompt)
        for provider in providers
    ]
    return await asyncio.gather(*tasks)


async def dispatch_chain(
    providers: list[str],
    message: str,
    history: list[Message],
    system_prompt: str,
) -> LLMResponse:
    current = message
    last: LLMResponse | None = None
    for index, provider in enumerate(providers):
        last = await dispatch_single(
            provider,
            current,
            history,
            system_prompt,
        )
        if last.is_error:
            continue
        if index < len(providers) - 1:
            label = settings.llm_labels.get(provider, provider.upper())
            current = (
                f'Contexto ({label}): "{last.content[:800]}"\n\n'
                f'Pergunta original: "{message}"\n\n'
                "Melhore e expanda esta resposta:"
            )

    if last is None:
        return LLMResponse(
            llm="chain",
            content="Nenhum servico disponivel",
            is_error=True,
        )
    return LLMResponse(
        llm=providers[-1],
        content=f"**Resposta em etapas:**\n\n{last.content}",
        duration_ms=last.duration_ms,
        tokens_used=last.tokens_used,
        is_error=last.is_error,
    )
