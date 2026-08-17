import asyncio

from app.models.schemas import LLMResponse, Message
from app.services import langchain_agent_service


def run(coro):
    return asyncio.run(coro)


def test_langchain_model_adapter_preserves_request_and_structured_response(
    monkeypatch,
):
    async def raw_dispatch(provider, message, history, system_prompt):
        assert provider == "gpt"
        assert message == "Pergunta atual"
        assert history == [
            Message(role="user", content="Pergunta anterior"),
            Message(role="assistant", content="Resposta anterior"),
        ]
        assert system_prompt == "Instrucao do sistema"
        return LLMResponse(
            llm="gpt",
            content="Resposta estruturada",
            duration_ms=42,
            tokens_used=17,
        )

    monkeypatch.setattr(
        langchain_agent_service.llm_service,
        "dispatch_single",
        raw_dispatch,
    )

    response = run(
        langchain_agent_service.dispatch_single(
            "gpt",
            "Pergunta atual",
            [
                Message(role="user", content="Pergunta anterior"),
                Message(role="assistant", content="Resposta anterior"),
            ],
            "Instrucao do sistema",
        )
    )

    assert response == LLMResponse(
        llm="gpt",
        content="Resposta estruturada",
        duration_ms=42,
        tokens_used=17,
    )


def test_langchain_model_adapter_preserves_provider_errors(monkeypatch):
    async def raw_dispatch(provider, message, history, system_prompt):
        return LLMResponse(
            llm=provider,
            content="Credencial nao configurada",
            is_error=True,
        )

    monkeypatch.setattr(
        langchain_agent_service.llm_service,
        "dispatch_single",
        raw_dispatch,
    )

    response = run(
        langchain_agent_service.dispatch_single(
            "claude",
            "Ola",
            [],
            "system",
        )
    )

    assert response.llm == "claude"
    assert response.is_error is True
    assert response.content == "Credencial nao configurada"


def test_langchain_multi_dispatch_uses_model_adapter(monkeypatch):
    called: list[str] = []

    async def single(provider, message, history, system_prompt):
        called.append(provider)
        return LLMResponse(llm=provider, content=provider.upper())

    monkeypatch.setattr(langchain_agent_service, "dispatch_single", single)

    responses = run(
        langchain_agent_service.dispatch_multi(
            ["gpt", "claude"],
            "Ola",
            [],
            "system",
        )
    )

    assert called == ["gpt", "claude"]
    assert [item.content for item in responses] == ["GPT", "CLAUDE"]


def test_langchain_chain_passes_previous_structured_content(monkeypatch):
    requests: list[tuple[str, str]] = []

    async def single(provider, message, history, system_prompt):
        requests.append((provider, message))
        return LLMResponse(llm=provider, content=f"Resposta de {provider}")

    monkeypatch.setattr(langchain_agent_service, "dispatch_single", single)

    response = run(
        langchain_agent_service.dispatch_chain(
            ["claude", "gpt"],
            "Pergunta original",
            [],
            "system",
        )
    )

    assert requests[0] == ("claude", "Pergunta original")
    assert requests[1][0] == "gpt"
    assert "Resposta de claude" in requests[1][1]
    assert response.llm == "gpt"
    assert response.content.endswith("Resposta de gpt")


def test_langchain_chain_keeps_local_answer_when_cloud_refinement_fails(
    monkeypatch,
):
    async def single(provider, message, history, system_prompt):
        if provider == "localai":
            return LLMResponse(llm=provider, content="Resposta local valida")
        return LLMResponse(
            llm=provider,
            content="saldo insuficiente",
            is_error=True,
        )

    monkeypatch.setattr(langchain_agent_service, "dispatch_single", single)

    response = run(
        langchain_agent_service.dispatch_chain(
            ["localai", "claude"],
            "Pergunta original",
            [],
            "system",
        )
    )

    assert response.llm == "localai"
    assert response.is_error is False
    assert response.content.endswith("Resposta local valida")
