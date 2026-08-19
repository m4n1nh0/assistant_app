import asyncio
from types import SimpleNamespace

import httpx

from app.models.schemas import ChatRequest, LLMResponse
from app.services import llm_service


def run(coro):
    return asyncio.run(coro)


def test_error_message_extracts_nested_provider_message_and_redacts_secret():
    error = {
        "error": {
            "message": "Incorrect API key provided: sk-test-secret.",
        }
    }

    message = llm_service._error_message(error)

    assert message == "Incorrect API key provided: [redacted]."


def test_error_message_keeps_empty_timeouts_readable():
    message = llm_service._error_message(httpx.ReadTimeout(""))

    assert "Timeout" in message
    assert "ReadTimeout" in message


def test_localai_summary_payload_disables_thinking():
    payload = llm_service._localai_chat_payload(
        model="minicpm5",
        messages=[{"role": "user", "content": "resuma"}],
        max_tokens=192,
        reasoning_effort="none",
    )

    assert payload["max_tokens"] == 192
    assert payload["reasoning_effort"] == "none"
    assert payload["metadata"] == {"enable_thinking": "false"}
    assert payload["stream"] is True


def test_call_localai_collects_stream_without_changing_response_contract(monkeypatch):
    async def _stream(message, history, system_prompt, **options):
        assert options == {"max_tokens": 2000, "reasoning_effort": None}
        yield "Resumo "
        yield "gerado."

    monkeypatch.setattr(
        llm_service,
        "settings",
        SimpleNamespace(localai_base_url="http://localai:8080"),
    )
    monkeypatch.setattr(llm_service, "stream_localai", _stream)

    response = run(llm_service.call_localai("aula", [], "resuma"))

    assert response.is_error is False
    assert response.llm == "localai"
    assert response.content == "Resumo gerado."


def test_call_localai_reports_empty_stream_as_error(monkeypatch):
    async def _stream(message, history, system_prompt, **options):
        if False:
            yield ""

    monkeypatch.setattr(
        llm_service,
        "settings",
        SimpleNamespace(localai_base_url="http://localai:8080"),
    )
    monkeypatch.setattr(llm_service, "stream_localai", _stream)

    response = run(llm_service.call_localai("aula", [], "resuma"))

    assert response.is_error is True
    assert "resposta vazia" in response.content


def test_dispatch_real_failure_updates_provider_availability(monkeypatch):
    recorded = []

    async def fail(_message, _history, _system_prompt):
        return LLMResponse(
            llm="claude",
            content="Your credit balance is too low",
            is_error=True,
        )

    async def mark(provider, error):
        recorded.append((provider, error))

    monkeypatch.setitem(llm_service.LLM_CALLERS, "claude", fail)
    monkeypatch.setattr(llm_service, "mark_llm_failure", mark)

    response = run(llm_service.dispatch_single("claude", "ola", [], "system"))

    assert response.is_error is True
    assert recorded == [("claude", "Your credit balance is too low")]


def test_dispatch_forwards_max_tokens_to_a_cloud_provider(monkeypatch):
    # Sem este repasse, o teto pedido por quem chama era descartado e todo
    # provedor de nuvem usava o teto do chat: o resumo detalhado de aula saia
    # cortado no mesmo tamanho do comum.
    recebido = {}

    async def caller(_message, _history, _system_prompt, max_tokens=None):
        recebido["max_tokens"] = max_tokens
        return LLMResponse(llm="together", content="resumo longo")

    monkeypatch.setitem(llm_service.LLM_CALLERS, "together", caller)

    response = run(
        llm_service.dispatch_single(
            "together", "resuma", [], "system", max_tokens=4000
        )
    )

    assert response.is_error is False
    assert recebido["max_tokens"] == 4000


def test_dispatch_keeps_the_provider_default_when_no_ceiling_is_asked(monkeypatch):
    async def caller(_message, _history, _system_prompt):
        return LLMResponse(llm="together", content="resposta curta")

    monkeypatch.setitem(llm_service.LLM_CALLERS, "together", caller)

    response = run(llm_service.dispatch_single("together", "ola", [], "system"))

    assert response.content == "resposta curta"


def test_dispatch_chain_preserves_last_success_after_refiner_error(monkeypatch):
    async def dispatch(provider, message, history, system_prompt, **options):
        if provider == "localai":
            return LLMResponse(llm=provider, content="Resposta local")
        return LLMResponse(llm=provider, content="sem credito", is_error=True)

    monkeypatch.setattr(llm_service, "dispatch_single", dispatch)

    response = run(
        llm_service.dispatch_chain(
            ["localai", "claude"],
            "pergunta",
            [],
            "system",
        )
    )

    assert response.llm == "localai"
    assert response.is_error is False
    assert response.content.endswith("Resposta local")


def test_dispatch_single_unknown_service_returns_error_response():
    response = run(
        llm_service.dispatch_single(
            "unknown",
            "ola",
            [],
            "responda em portugues",
        )
    )

    assert response.llm == "unknown"
    assert response.is_error is True
    assert "desconhecido" in response.content


def test_chat_request_accepts_localai_provider():
    request = ChatRequest(message="ola", llm="localai")

    assert request.llm.value == "localai"


def test_resolve_localai_model_uses_first_available_model(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://localai:8080/v1/models"
        return httpx.Response(
            200,
            json={"data": [{"id": "first-model"}, {"id": "second-model"}]},
        )

    monkeypatch.setattr(
        llm_service,
        "settings",
        SimpleNamespace(
            localai_model="",
            localai_api_key="",
            localai_v1_base_url="http://localai:8080/v1",
        ),
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        model = run(llm_service._resolve_localai_model(client))
    finally:
        run(client.aclose())

    assert model == "first-model"
