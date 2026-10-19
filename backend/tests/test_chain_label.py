"""O titulo "Resposta em etapas:" e enfeite de exibicao: nao pode voltar ao modelo nem sair duplicado."""

import asyncio

import pytest

from app.models.schemas import LLMResponse, Message
from app.services import langchain_agent_service as agent
from app.services import llm_service


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "text",
    [
        "**Resposta em etapas:**\n\nEntendo melhor agora.",
        "Resposta em etapas:\n\nEntendo melhor agora.",
        "**Resposta em etapas**:\n\nEntendo melhor agora.",
        "  resposta EM etapas:  \nEntendo melhor agora.",
        "**Resposta em etapas:**\n\nResposta em etapas:\n\nEntendo melhor agora.",
    ],
)
def test_strip_removes_the_label_in_every_form_and_however_many_times(text):
    assert llm_service.strip_chain_label(text) == "Entendo melhor agora."


def test_strip_leaves_other_text_alone():
    text = "A resposta em etapas que voce pediu esta abaixo."
    assert llm_service.strip_chain_label(text) == text
    assert llm_service.strip_chain_label("") == ""
    assert llm_service.strip_chain_label("Resposta em etapas: no meio do texto") == "no meio do texto"


def test_history_sent_to_the_model_has_no_label_on_assistant_turns_only():
    history = [
        Message(role="user", content="Resposta em etapas: e o que eu quero testar"),
        Message(role="assistant", content="**Resposta em etapas:**\n\nPrimeira resposta"),
        Message(role="system", content="ignorado"),
    ]

    sent = llm_service._format_history(history)

    assert sent == [
        {"role": "user", "content": "Resposta em etapas: e o que eu quero testar"},
        {"role": "assistant", "content": "Primeira resposta"},
    ]


def test_chain_does_not_duplicate_the_label_when_the_model_echoes_it(monkeypatch):
    async def echoing(provider, message, history, system_prompt, tools=(), trace_sink=None):
        return LLMResponse(llm=provider, content="Resposta em etapas:\n\nEntendo melhor agora.")

    monkeypatch.setattr(agent, "dispatch_single", echoing)

    result = run(agent.dispatch_chain(["together"], "oi", [], "sis"))

    assert result.content == "**Resposta em etapas:**\n\nEntendo melhor agora."


def test_the_direct_chain_does_not_duplicate_the_label_either(monkeypatch):
    async def echoing(llm, message, history, system_prompt, **kwargs):
        return LLMResponse(llm=llm, content="**Resposta em etapas:**\nEntendo melhor agora.")

    monkeypatch.setattr(llm_service, "dispatch_single", echoing)

    result = run(llm_service.dispatch_chain(["together"], "oi", [], "sis"))

    assert result.content == "**Resposta em etapas:**\n\nEntendo melhor agora."


def test_the_model_never_sees_the_label_from_earlier_answers(monkeypatch):
    seen = {}

    async def spy(llm, message, history, system_prompt, **kwargs):
        seen["history"] = llm_service._format_history(history)
        return LLMResponse(llm=llm, content="ok")

    monkeypatch.setattr(llm_service, "dispatch_single", spy)

    run(llm_service.dispatch_chain(
        ["together"], "oi",
        [Message(role="assistant", content="**Resposta em etapas:**\n\nantes")], "sis"))

    assert seen["history"] == [{"role": "assistant", "content": "antes"}]
