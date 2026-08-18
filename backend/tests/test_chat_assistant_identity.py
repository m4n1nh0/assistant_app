import asyncio
from types import SimpleNamespace

from app.routers import chat as chat_router


def test_system_prompt_uses_personalized_assistant_name():
    prompt = chat_router._system_prompt(
        {
            "assistant_name": "Hannah",
            "gender": "f",
            "user_name": "Mariano",
            "language": "pt-BR",
        }
    )

    assert "Você é Hannah" in prompt
    assert "O usuário se chama Mariano" in prompt


def test_personality_cannot_override_the_configured_name():
    prompt = chat_router._system_prompt(
        {
            "assistant_name": "Hannah",
            "gender": "f",
            "personality": "Você é Dani, uma assistente objetiva.",
            "language": "pt-BR",
        }
    )

    assert prompt.startswith("Você é Hannah")
    assert "Seu nome válido permanece Hannah" in prompt


def test_assistant_config_loads_authenticated_tutor_profile(monkeypatch):
    tutor = SimpleNamespace(display_name="Mariano", locale="pt-BR")
    profile = SimpleNamespace(
        assistant_name="Hannah",
        gender="f",
        personality="Você é Hannah, uma assistente educacional.",
        language="pt-BR",
    )

    class FakeResult:
        def scalar_one_or_none(self):
            return profile

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _model, _key):
            return tutor

        async def execute(self, _statement):
            return FakeResult()

    monkeypatch.setattr(chat_router, "AsyncSessionLocal", FakeSession)

    config = asyncio.run(
        chat_router._assistant_config(
            {"uid": "user-1", "sub": "mariano", "tutor_id": "tutor-1"}
        )
    )

    assert config["assistant_name"] == "Hannah"
    assert config["user_name"] == "Mariano"
    assert config["personality"].startswith("Você é Hannah")


def test_legacy_unnamed_profile_uses_assistant_default(monkeypatch):
    tutor = SimpleNamespace(display_name="Novo usuário", locale="pt-BR")
    profile = SimpleNamespace(
        assistant_name="Assistente",
        gender="f",
        personality="",
        language="pt-BR",
    )

    class FakeResult:
        def scalar_one_or_none(self):
            return profile

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _model, _key):
            return tutor

        async def execute(self, _statement):
            return FakeResult()

    monkeypatch.setattr(chat_router, "AsyncSessionLocal", FakeSession)
    config = asyncio.run(
        chat_router._assistant_config(
            {"uid": "user-2", "sub": "novo", "tutor_id": "tutor-2"}
        )
    )

    assert config["assistant_name"] == "Assistant"
