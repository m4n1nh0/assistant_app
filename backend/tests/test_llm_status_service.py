import asyncio
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
