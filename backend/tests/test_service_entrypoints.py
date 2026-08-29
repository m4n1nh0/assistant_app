"""Entrypoints dos servicos extraidos: porta, health e contrato minimo.

O que se verifica aqui e o que decide se um deploy sobe ou reprova no
healthcheck - e nao a logica de negocio, que ja tem teste proprio.
"""

import pytest

from services.common import resolve_port

pytestmark = pytest.mark.unit


# --- Resolucao de porta ------------------------------------------------------


def test_configured_port_is_used_without_platform_port(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)

    assert resolve_port(8002) == 8002


def test_platform_port_wins(monkeypatch):
    """Railway injeta PORT e roteia para ela; ignorar isso reprova o deploy."""
    monkeypatch.setenv("PORT", "7431")

    assert resolve_port(8002) == 7431


def test_malformed_platform_port_falls_back(monkeypatch):
    monkeypatch.setenv("PORT", "nao-e-numero")

    assert resolve_port(8002) == 8002


def test_empty_platform_port_falls_back(monkeypatch):
    monkeypatch.setenv("PORT", "  ")

    assert resolve_port(8003) == 8003


# --- Health ------------------------------------------------------------------


@pytest.mark.parametrize(
    "module,name",
    [
        ("services.mcp_service.main", "mcp-service"),
        ("services.tool_service.main", "tool-service"),
        ("services.orchestrator.main", "agent-orchestrator"),
    ],
)
def test_every_service_separates_live_from_ready(module, name):
    """`live` diz que o processo esta de pe; `ready`, que ele atende."""
    import importlib

    app = importlib.import_module(module).app
    paths = {route.path for route in app.routes if hasattr(route, "path")}

    assert "/health/live" in paths
    assert "/health/ready" in paths
