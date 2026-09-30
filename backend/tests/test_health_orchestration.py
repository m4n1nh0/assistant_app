"""Public API health reflects the configured chat execution mode."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from app.adapters.orchestration.local import LocalOrchestrationGateway
from app.adapters.orchestration.remote import RemoteOrchestrationGateway
from app.routers import routes
from app.services import system_health_service as health_service


def config(remote=False):
    return SimpleNamespace(
        uses_remote_orchestrator=remote, uses_remote_tools=False,
        uses_remote_mcp=False, mcp_servers="", brevo_api_key="", health_alerts_enabled=False,
        database_url="sqlite:///test.db", redis_url="redis://test", qdrant_url="http://test",
    )


@pytest.fixture
def health_app(monkeypatch):
    monkeypatch.setattr(health_service, "_cache", None)
    monkeypatch.setattr(health_service, "_lock", asyncio.Lock())
    for probe in ("_database", "_redis", "_qdrant", "_tools"):
        monkeypatch.setattr(health_service, probe, AsyncMock(return_value=True))
    monkeypatch.setattr(routes, "get_llm_statuses", AsyncMock(return_value={}))
    monkeypatch.setattr(routes, "qdrant_status", lambda: {"ok": True})
    monkeypatch.setattr(routes, "_gs3", lambda: SimpleNamespace(
        active_llms=[], llm_labels={}, database_url="sqlite:///test.db",
    ))
    app = FastAPI()
    app.include_router(routes.router_health)
    return app


def test_monolith_health_does_not_require_remote_service(health_app, monkeypatch):
    monkeypatch.setattr(health_service, "get_settings", config)
    monkeypatch.setattr(health_service, "get_orchestration_gateway", LocalOrchestrationGateway)

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=health_app), base_url="http://test",
        ) as client:
            response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["orchestration"]["transport"] == "local"
        assert response.json()["orchestration"]["ok"] is True

    asyncio.run(check())


def test_dependency_failure_is_degraded_and_snapshot_is_cached(health_app, monkeypatch):
    monkeypatch.setattr(health_service, "get_settings", config)
    monkeypatch.setattr(health_service, "get_orchestration_gateway", LocalOrchestrationGateway)
    probe = AsyncMock(return_value=False)
    monkeypatch.setattr(health_service, "_redis", probe)
    disabled_probe = AsyncMock(side_effect=AssertionError("MCP should not be contacted"))
    monkeypatch.setattr(health_service, "_mcp", disabled_probe)

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=health_app), base_url="http://test",
        ) as client:
            first, second = await asyncio.gather(client.get("/health"), client.get("/health"))
        for response in (first, second):
            assert response.json()["status"] == "degraded"
            assert response.json()["services"]["redis"]["ok"] is False
            assert response.json()["services"]["mcp"]["status"] == "disabled"
        assert probe.await_count == 1
        disabled_probe.assert_not_awaited()

    asyncio.run(check())


@pytest.mark.parametrize("outcome", ["ready", "not_ready", "offline", "timeout"])
def test_remote_health_and_liveness(health_app, monkeypatch, outcome):
    monkeypatch.setattr(health_service, "get_settings", lambda: config(remote=True))
    requests = []

    def handler(request):
        requests.append(request.url.path)
        if outcome == "offline":
            raise httpx.ConnectError("private-service:8001", request=request)
        if outcome == "timeout":
            raise httpx.ReadTimeout("private-service:8001", request=request)
        return httpx.Response(200, json={"ok": outcome == "ready"})

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as remote:
            gateway = RemoteOrchestrationGateway(
                "http://private-service:8001", token="test-token", client=remote,
                max_retries=0,
            )
            monkeypatch.setattr(health_service, "get_orchestration_gateway", lambda: gateway)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=health_app), base_url="http://test",
            ) as client:
                live = await client.get("/health/live")
                assert live.json()["status"] == "ok"
                assert requests == []
                response = await client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == ("ok" if outcome == "ready" else "degraded")
        assert body["orchestration"]["transport"] == "remote"
        assert body["orchestration"]["ok"] is (outcome == "ready")
        assert requests == ["/health/ready"]
        assert "private-service" not in response.text
        assert "test-token" not in response.text

    asyncio.run(check())
