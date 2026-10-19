"""Mapa de servicos: o destino leva o nome do servico, nao o nome gerado pela plataforma.

No Railway o host de um servico e o nome dele, e um nome gerado ("serene-creation") nao diz o
papel. A aplicacao sabe qual URL e de qual servico, entao rotula a chamada ao sair.
"""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from shared.observability import otel
from shared.observability.middleware import peer_names


def run(coro):
    return asyncio.run(coro)


def test_peer_names_maps_each_configured_url_host_to_its_service():
    settings = SimpleNamespace(
        tool_service_url="http://serene-creation.railway.internal:8003",
        orchestrator_url="supportive-elegance.railway.internal:8001",
        mcp_service_url="",
        assistant_api_url="https://API.Example.com/",
    )

    assert peer_names(settings) == {
        "serene-creation.railway.internal": "tool-service",
        "supportive-elegance.railway.internal": "agent-orchestrator",
        "api.example.com": "assistant-api",
    }


def test_peer_names_ignores_settings_a_process_does_not_have():
    assert peer_names(SimpleNamespace()) == {}


def test_the_hook_labels_only_known_hosts_and_never_breaks_the_call():
    attrs = {}

    class Span:
        def set_attribute(self, key, value):
            attrs[key] = value

    hook, _ = otel.peer_service_hooks({"serene-creation.railway.internal": "tool-service"})

    hook(Span(), SimpleNamespace(url=SimpleNamespace(host="Serene-Creation.railway.internal")))
    assert attrs == {"peer.service": "tool-service"}

    attrs.clear()
    hook(Span(), SimpleNamespace(url=SimpleNamespace(host="api.openai.com")))
    assert attrs == {}

    hook(Span(), object())  # requisicao estranha: o gancho nao levanta


@pytest.fixture
def traced(monkeypatch):
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(otel, "_enabled", True)
    HTTPXClientInstrumentor().uninstrument()
    yield provider, exporter
    HTTPXClientInstrumentor().uninstrument()


def test_calls_to_our_services_carry_the_service_name_through_the_real_http_client(traced):
    provider, exporter = traced

    async def scenario():
        async def handle(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handle, "0.0.0.0", 0)
        port = server.sockets[0].getsockname()[1]
        # 127.0.0.1 faz o papel do host gerado do tool-service; 127.0.0.2 e um destino qualquer.
        otel.instrument_clients(tracer_provider=provider, peers={"127.0.0.1": "tool-service"})
        async with httpx.AsyncClient() as client:
            await client.get(f"http://127.0.0.1:{port}/health/ready")
            await client.get(f"http://127.0.0.2:{port}/qualquer")
        server.close()
        await server.wait_closed()

    run(scenario())

    spans = {s.attributes.get("http.url") or s.attributes.get("url.full"): s for s in exporter.get_finished_spans()}
    ours = next(s for url, s in spans.items() if "127.0.0.1" in url)
    other = next(s for url, s in spans.items() if "127.0.0.2" in url)
    assert ours.attributes["peer.service"] == "tool-service"
    assert "peer.service" not in other.attributes


# --- checagem de e-mail com cache proprio ------------------------------------------------------


@pytest.fixture
def brevo(monkeypatch):
    from app.core.config import get_settings
    from app.services import registration_invite_service, system_health_service as health

    calls = {"n": 0, "success": True}

    async def diagnostic():
        calls["n"] += 1
        return {"success": calls["success"]}

    monkeypatch.setattr(get_settings(), "brevo_api_key", "chave")
    monkeypatch.setattr(registration_invite_service, "brevo_api_diagnostic", diagnostic)
    monkeypatch.setattr(health, "_email_cache", None)
    return health, calls


def test_a_healthy_email_check_is_not_repeated_every_round(brevo):
    health, calls = brevo

    results = [run(health._email()) for _ in range(5)]

    assert results == [True] * 5
    assert calls["n"] == 1


def test_a_healthy_email_check_is_renewed_after_its_ttl(brevo, monkeypatch):
    health, calls = brevo
    run(health._email())
    ok, checked_at = health._email_cache
    monkeypatch.setattr(health, "_email_cache", (checked_at - health._EMAIL_OK_TTL_SECONDS - 1, ok))

    run(health._email())

    assert calls["n"] == 2


def test_a_failing_email_check_is_retried_on_every_round(brevo):
    health, calls = brevo
    calls["success"] = False

    first = run(health._email())
    second = run(health._email())

    assert first is False and second is False
    assert calls["n"] == 2
    calls["success"] = True
    assert run(health._email()) is True
