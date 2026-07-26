import asyncio
from types import SimpleNamespace

from app.models.schemas import LLMStatus
from app.routers import routes


def run(coro):
    return asyncio.run(coro)


def test_health_reports_configured_and_available_llms_separately(monkeypatch):
    fake_settings = SimpleNamespace(
        active_llms=["gpt", "gemini"],
        llm_labels={
            "gpt": "GPT-4o",
            "gemini": "Gemini 1.5 Flash",
        },
        database_url="mysql+aiomysql://user:pass@localhost:3306/assistant",
        telegram_bot_token="telegram-token",
        telegram_chat_id="chat-id",
        wa_number="5511999999999",
    )

    async def fake_get_llm_statuses():
        return {
            "gpt": LLMStatus(
                id="gpt",
                label="GPT-4o",
                configured=True,
                online=True,
                available=True,
                status="online",
            ),
            "gemini": LLMStatus(
                id="gemini",
                label="Gemini 1.5 Flash",
                configured=True,
                online=False,
                available=False,
                status="offline",
                error="API key not valid",
            ),
        }

    monkeypatch.setattr(routes, "_gs3", lambda: fake_settings)
    monkeypatch.setattr(routes, "get_llm_statuses", fake_get_llm_statuses)
    monkeypatch.setattr(routes, "qdrant_status", lambda: {"ok": True})

    response = run(routes.health())

    assert response.active_llms == ["gpt", "gemini"]
    assert response.available_llms == ["gpt"]
    assert response.llm_labels == {
        "gpt": "GPT-4o",
        "gemini": "Gemini 1.5 Flash",
    }
    assert response.llm_status["gemini"].error == "API key not valid"
    assert response.calendar_sources == []
    assert response.notifications == {
        "telegram": True,
        "whatsapp": True,
    }
    assert response.storage["database"]["url"] == "localhost:3306/assistant"
