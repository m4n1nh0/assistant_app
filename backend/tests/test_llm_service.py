import asyncio
from types import SimpleNamespace

import httpx

from app.models.schemas import ChatRequest
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
