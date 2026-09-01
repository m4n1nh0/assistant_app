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


# --- Saneamento da chave: recusar no formulario em vez de vazar no health ---


def test_clean_api_key_removes_whitespace_from_a_wrapped_paste():
    """Colagem quebrada por largura de campo poe `\n` no meio da chave.

    `.strip()` nao alcanca o meio da string: a chave era salva e so falhava
    depois, no health check, com `Illegal header value` - carregando a chave
    inteira na mensagem.
    """
    assert service.clean_api_key("sk-or-v1-abc\n  def\t123") == "sk-or-v1-abcdef123"
    assert service.clean_api_key("  sk-limpa  ") == "sk-limpa"
    assert service.clean_api_key("") == ""
    assert service.clean_api_key(None) == ""


def test_clean_api_key_refuses_characters_that_cannot_go_in_a_header():
    """Aspas curvas e espaco nao-quebravel sao invisiveis no campo."""
    import pytest

    with pytest.raises(ValueError) as excinfo:
        service.clean_api_key("sk-“abcdef”")

    assert "cabeçalho" in str(excinfo.value)

    with pytest.raises(ValueError):
        service.clean_api_key("sk-abc​def")


def test_clean_api_key_drops_a_dirty_environment_value_instead_of_raising():
    """Variavel de ambiente suja nao pode derrubar o login do usuario."""
    assert service.clean_api_key("sk-“abc”", strict=False) == ""
    assert service.clean_api_key("sk-valida", strict=False) == "sk-valida"


def test_provider_list_carries_the_catalog_so_the_ui_needs_no_extra_route(monkeypatch):
    """A lista de modelos nasce no health check e e consumida pelo formulario.

    Juntar os dois no payload que a tela ja recebe evita uma rota nova e evita
    a interface cruzar duas listas por conta propria.
    """
    async def no_migration(_user):
        return None

    async def load(_tutor_id):
        return service.UserLLMRuntime(scope="tutor:one", providers={})

    async def safe_list(_tutor_id):
        return [
            {"id": "gpt", "label": "OpenAI", "kind": "external",
             "enabled": True, "configured": True, "model": "gpt-4o"},
            {"id": "openrouter", "label": "OpenRouter", "kind": "external",
             "enabled": True, "configured": True, "model": "openrouter/auto"},
        ]

    async def statuses(force=False):
        return {
            "gpt": LLMStatus(
                id="gpt", label="OpenAI", configured=True, online=True,
                available=True, status="online",
                available_models=["gpt-4", "gpt-4o"],
                recommended_model="gpt-4o",
            ),
            # Provedor cuja checagem e de saldo, e portanto nao lista modelos.
            "openrouter": LLMStatus(
                id="openrouter", label="OpenRouter", configured=True,
                online=True, available=False, status="limited",
            ),
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
        SimpleNamespace(active_llms=["gpt"], llm_labels={"gpt": "OpenAI"}),
    )

    response = run(router._response({"uid": "one", "tutor_id": "one"}))
    por_id = {item["id"]: item for item in response["providers"]}

    assert por_id["gpt"]["available_models"] == ["gpt-4", "gpt-4o"]
    assert por_id["gpt"]["recommended_model"] == "gpt-4o"
    # O estado resumido viaja junto para a lista de agentes sinalizar sem
    # cruzar duas colecoes do lado do cliente.
    assert por_id["gpt"]["status"] == "online"
    assert por_id["openrouter"]["status"] == "limited"
    # Sem catalogo o campo vem vazio, e a interface cai no campo de texto livre
    # em vez de mostrar uma lista de escolha vazia.
    assert por_id["openrouter"]["available_models"] == []
    assert por_id["openrouter"]["recommended_model"] == ""
