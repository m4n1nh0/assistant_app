import asyncio

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
