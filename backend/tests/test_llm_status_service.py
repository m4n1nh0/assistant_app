import asyncio
import json
from types import SimpleNamespace

import httpx

from app.models.schemas import LLMStatus
from app.services import llm_status_service as service


def run(coro):
    return asyncio.run(coro)


def test_status_marks_available_only_when_configured_online_and_not_limited():
    online = service._status("gpt", configured=True, online=True)
    limited = service._status(
        "deepseek",
        configured=True,
        online=True,
        has_balance_check=True,
        balance_ok=False,
    )
    missing = service._missing("gemini")

    assert online.available is True
    assert online.status == "online"

    assert limited.available is False
    assert limited.status == "limited"

    assert missing.configured is False
    assert missing.available is False
    assert missing.status == "missing_key"


def test_sanitize_error_redacts_api_key_fragments():
    text = service._sanitize_error(
        "Incorrect API key provided: sk-test-secret. token abc**xyz failed"
    )

    assert "sk-test-secret" not in text
    assert "abc**xyz" not in text
    assert "provided: [redacted]" in text
    assert "[redacted] failed" in text


def test_exception_error_keeps_empty_timeouts_readable():
    text = service._exception_error(httpx.ReadTimeout(""))

    assert "Timeout" in text
    assert "ReadTimeout" in text


def test_checking_status_is_not_available_yet():
    status = service._checking("gpt")

    assert status.configured is True
    assert status.online is False
    assert status.available is False
    assert status.status == "checking"


def test_failed_cache_expires_faster_than_available_cache(monkeypatch):
    monkeypatch.setattr(service, "_cache_at", 100.0)

    failed = {
        "gpt": LLMStatus(
            id="gpt",
            label="GPT",
            configured=True,
            online=False,
            available=False,
            status="offline",
        )
    }
    available = {
        "gpt": LLMStatus(
            id="gpt",
            label="GPT",
            configured=True,
            online=True,
            available=True,
            status="online",
        )
    }

    assert service._is_cache_fresh(failed, 125.0) is True
    assert service._is_cache_fresh(failed, 131.0) is False
    assert service._is_cache_fresh(available, 131.0) is True


def test_get_available_llms_keeps_provider_order(monkeypatch):
    async def fake_get_llm_statuses(force=False):
        return {
            "claude": LLMStatus(
                id="claude",
                label="Claude",
                configured=True,
                online=False,
                available=False,
                status="offline",
            ),
            "gpt": LLMStatus(
                id="gpt",
                label="GPT",
                configured=True,
                online=True,
                available=True,
                status="online",
            ),
            "hf": LLMStatus(
                id="hf",
                label="Hugging Face",
                configured=True,
                online=True,
                available=True,
                status="online",
            ),
        }

    monkeypatch.setattr(service, "get_llm_statuses", fake_get_llm_statuses)

    assert run(service.get_available_llms(force=True)) == ["gpt", "hf"]


class FakeRedis:
    def __init__(self, stored=None):
        self.stored = stored
        self.writes = []
        self.fail = False

    async def get(self, key):
        if self.fail:
            raise ConnectionError("redis down")
        return self.stored

    async def set(self, key, value, ex=None):
        if self.fail:
            raise ConnectionError("redis down")
        self.writes.append((key, value, ex))
        self.stored = value


def cold_memory_cache(monkeypatch):
    monkeypatch.setattr(service, "_cache", None)
    monkeypatch.setattr(service, "_cache_at", 0.0)


def block_network_checks(monkeypatch):
    """Fail loudly if any provider check runs — used to prove the cache short-circuits."""
    async def _boom(client):
        raise AssertionError("provider check should not run when shared cache is warm")

    for provider in service._PROVIDER_ORDER:
        monkeypatch.setattr(service, f"_check_{provider}", _boom)


def test_shared_cache_hit_skips_all_provider_checks(monkeypatch):
    cold_memory_cache(monkeypatch)
    block_network_checks(monkeypatch)
    stored = json.dumps(
        {
            "gpt": LLMStatus(
                id="gpt",
                label="GPT",
                configured=True,
                online=True,
                available=True,
                status="online",
            ).model_dump(mode="json")
        }
    )
    monkeypatch.setattr(service, "get_redis_client", lambda: FakeRedis(stored=stored))

    statuses = run(service.get_llm_statuses())

    assert list(statuses) == ["gpt"]
    assert statuses["gpt"].available is True


def test_refresh_writes_shared_cache_with_availability_based_ttl(monkeypatch):
    cold_memory_cache(monkeypatch)
    redis = FakeRedis()
    monkeypatch.setattr(service, "get_redis_client", lambda: redis)

    available = {"gpt": service._status("gpt", configured=True, online=True)}
    offline = {"gpt": service._status("gpt", configured=True, online=False)}

    run(service._write_shared_cache(available))
    run(service._write_shared_cache(offline))

    assert redis.writes[0][2] == service._CACHE_TTL_SECONDS
    assert redis.writes[1][2] == service._FAILED_CACHE_TTL_SECONDS


def test_redis_failure_does_not_break_status_lookup(monkeypatch):
    cold_memory_cache(monkeypatch)
    redis = FakeRedis()
    redis.fail = True
    monkeypatch.setattr(service, "get_redis_client", lambda: redis)

    assert run(service._read_shared_cache()) is None
    run(service._write_shared_cache({"gpt": service._status("gpt", configured=True, online=True)}))


def test_get_ready_llms_intersects_configured_with_available(monkeypatch):
    async def fake_get_available_llms(force=False):
        return ["llama", "gpt"]

    monkeypatch.setattr(service, "get_available_llms", fake_get_available_llms)
    monkeypatch.setattr(
        service,
        "settings",
        SimpleNamespace(active_llms=["claude", "gpt", "llama"]),
    )

    assert run(service.get_ready_llms()) == ["gpt", "llama"]


def test_check_grok_uses_configured_chat_base_url(monkeypatch):
    captured = {}

    async def fake_check_json_endpoint(client, provider, url, *, key, headers=None):
        captured["provider"] = provider
        captured["url"] = url
        captured["key"] = key
        return service._status(provider, configured=True, online=True)

    monkeypatch.setattr(
        service,
        "settings",
        SimpleNamespace(
            grok_api_key="gsk_valid_test",
            grok_chat_base_url="https://api.groq.com/openai/v1",
            llm_labels={"grok": "Groq"},
        ),
    )
    monkeypatch.setattr(service, "_check_json_endpoint", fake_check_json_endpoint)

    status = run(service._check_grok(client=None))

    assert status.available is True
    assert captured == {
        "provider": "grok",
        "url": "https://api.groq.com/openai/v1/models",
        "key": "gsk_valid_test",
    }


def test_check_localai_detects_model_without_requiring_api_key(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://localai.railway.internal:8080/v1/models"
        assert "authorization" not in request.headers
        return httpx.Response(
            200,
            json={"data": [{"id": "qwen3-4b", "object": "model"}]},
        )

    monkeypatch.setattr(
        service,
        "settings",
        SimpleNamespace(
            localai_base_url="http://localai.railway.internal:8080",
            localai_v1_base_url="http://localai.railway.internal:8080/v1",
            localai_api_key="",
            localai_model="qwen3-4b",
            llm_labels={"localai": "LocalAI (qwen3-4b)"},
        ),
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        status = run(service._check_localai(client))
    finally:
        run(client.aclose())

    assert status.available is True
    assert status.online is True


def test_check_localai_reports_configured_model_not_found(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "other-model"}]})
        assert request.url.path == "/api/models/config-json/wanted-model"
        return httpx.Response(404, json={"error": "model configuration not found"})

    monkeypatch.setattr(
        service,
        "settings",
        SimpleNamespace(
            localai_base_url="http://localai:8080",
            localai_v1_base_url="http://localai:8080/v1",
            localai_api_key="secret",
            localai_model="wanted-model",
            llm_labels={"localai": "LocalAI (wanted-model)"},
        ),
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        status = run(service._check_localai(client))
    finally:
        run(client.aclose())

    assert status.available is False
    assert status.configured is True
    assert "wanted-model" in (status.error or "")


def test_check_localai_accepts_configured_cold_model(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": []})
        assert (
            request.url.path
            == "/api/models/config-json/minicpm5-1b-claude-opus-fable5-v2-thinking"
        )
        return httpx.Response(
            200,
            json={
                "name": "minicpm5-1b-claude-opus-fable5-v2-thinking",
                "backend": "llama-cpp",
            },
        )

    monkeypatch.setattr(
        service,
        "settings",
        SimpleNamespace(
            localai_base_url="http://localai:8080",
            localai_v1_base_url="http://localai:8080/v1",
            localai_api_key="secret",
            localai_model="minicpm5-1b-claude-opus-fable5-v2-thinking",
            llm_labels={
                "localai": (
                    "LocalAI "
                    "(minicpm5-1b-claude-opus-fable5-v2-thinking)"
                )
            },
        ),
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        status = run(service._check_localai(client))
    finally:
        run(client.aclose())

    assert status.available is True
    assert status.online is True
