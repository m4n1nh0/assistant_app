import asyncio
from types import SimpleNamespace

from app.models.schemas import LLMStatus
from app.routers import chat as chat_router


def run(coro):
    return asyncio.run(coro)


def test_unavailable_response_includes_provider_label_and_error(monkeypatch):
    fake_settings = SimpleNamespace(
        active_llms=[],
        llm_labels={"gemini": "Gemini 1.5 Flash"},
    )

    async def fake_statuses():
        return {
            "gemini": LLMStatus(
                id="gemini",
                label="Gemini 1.5 Flash",
                configured=True,
                online=False,
                available=False,
                status="offline",
                error="API key not valid",
            )
        }

    monkeypatch.setattr(chat_router, "settings", fake_settings)
    monkeypatch.setattr(chat_router, "get_llm_statuses", fake_statuses)

    response = run(chat_router._llm_unavailable_response("gemini"))

    assert response.llm == "gemini"
    assert response.is_error is True
    assert "Gemini 1.5 Flash" in response.content
    assert "API key not valid" in response.content
