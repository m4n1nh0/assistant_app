import asyncio
import json
from types import SimpleNamespace

from app.models.schemas import LLMStatus
from app.routers import llm_config as router
from app.services import user_llm_config_service as service


def run(coro):
    return asyncio.run(coro)


def _base_settings():
    return SimpleNamespace(
        claude_api_key="global-must-not-leak",
        openai_api_key="global-must-not-leak",
        localai_base_url="http://localai:8080",
        localai_model="local-model",
        ollama_model="llama3",
        llm_labels={
            "localai": "LocalAI (local-model)",
            "llama": "Ollama (llama3)",
        },
    )


def test_cloud_credentials_are_scoped_while_local_agents_are_fixed(monkeypatch):
    monkeypatch.setattr(service, "get_settings", _base_settings)

    assert service.runtime_settings.claude_api_key == ""
    assert service.runtime_settings.active_llms == ["localai", "llama"]

    first = service.UserLLMRuntime(
        scope="tutor:first",
        providers={
            "claude": {
                "api_key": "first-secret",
                "model": "claude-user-model",
                "enabled": True,
            }
        },
    )
    token = service.activate_user_llms(first)
    try:
        assert service.runtime_settings.claude_api_key == "first-secret"
        assert service.runtime_settings.claude_model == "claude-user-model"
        assert service.runtime_settings.active_llms == [
            "claude",
            "localai",
            "llama",
        ]
    finally:
        service.reset_user_llms(token)

    assert service.runtime_settings.claude_api_key == ""


def test_public_user_config_never_serializes_api_key(monkeypatch):
    secret = "provider-secret-that-must-stay-in-backend"
    runtime = service.UserLLMRuntime(
        scope="tutor:one",
        providers={
            "gpt": {"api_key": secret, "model": "gpt-4o", "enabled": True}
        },
    )

    async def no_migration(_user):
        return None

    async def load(_tutor_id):
        return runtime

    async def safe_list(_tutor_id):
        return [{
            "id": "gpt",
            "label": "OpenAI",
            "kind": "external",
            "enabled": True,
            "configured": True,
            "model": "gpt-4o",
        }]

    async def statuses(force=False):
        return {
            "gpt": LLMStatus(
                id="gpt",
                label="OpenAI (gpt-4o)",
                configured=True,
                online=True,
                available=True,
                status="online",
            )
        }

    async def available(force=False):
        return ["gpt"]

    monkeypatch.setattr(router, "migrate_legacy_environment_for_user", no_migration)
    monkeypatch.setattr(router, "load_user_llm_runtime", load)
    monkeypatch.setattr(router, "list_provider_config", safe_list)
    monkeypatch.setattr(router, "get_llm_statuses", statuses)
    monkeypatch.setattr(router, "get_available_llms", available)
    monkeypatch.setattr(
        router,
        "runtime_settings",
        SimpleNamespace(
            active_llms=["gpt", "localai", "llama"],
            llm_labels={"gpt": "OpenAI (gpt-4o)"},
        ),
    )

    response = run(router._response({"uid": "one", "tutor_id": "one"}))

    assert response["providers"][0]["configured"] is True
    assert secret not in json.dumps(response)
