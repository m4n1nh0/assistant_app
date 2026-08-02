from __future__ import annotations

import asyncio
import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
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
        history.append(Message(role=role, content=_text_content(item)))

    return (
        "\n".join(system_parts),
        history,
        _text_content(current_message),
    )


class ProviderChatModel(BaseChatModel):
    """LangChain chat-model adapter over the existing provider gateway."""

    provider: str

    @property
    def _llm_type(self) -> str:
        return "assistant-provider-gateway"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"provider": self.provider}

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
        response = await llm_service.dispatch_single(
            self.provider,
            message,
            history,
            system_prompt,
        )
        ai_message = AIMessage(
            content=response.content,
            response_metadata={
                "provider": response.llm,
                "is_error": response.is_error,
                "duration_ms": response.duration_ms,
                "tokens_used": response.tokens_used,
            },
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
