"""Fronteiras de import entre nucleo, dominio e servicos.

Separar servico em Dockerfile e porta nao basta: um import novo e o servico
volta a carregar o produto inteiro, e ninguem percebe ate a imagem enxuta quebrar
em runtime. Estes testes transformam as fronteiras em regra verificavel.

Dois tipos de verificacao:

- **estatica**: le o codigo com `ast`, sem importar. Serve para regras de
  pacote ("nada em shared importa app").
- **fecho real**: importa o entrypoint num interpretador limpo e lista os
  modulos carregados. E o que o container vai carregar de verdade, incluindo
  import transitivo.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

BACKEND = Path(__file__).resolve().parent.parent


def _module_of(path: Path) -> tuple[str, bool]:
    parts = list(path.relative_to(BACKEND).with_suffix("").parts)
    is_pkg = parts[-1] == "__init__"
    if is_pkg:
        parts = parts[:-1]
    return ".".join(parts), is_pkg


def _imports(path: Path) -> set[str]:
    """Modulos importados por um arquivo, com relativos ja resolvidos."""
    module, is_pkg = _module_of(path)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module.split(".")
                if not is_pkg:
                    base = base[:-1]
                base = base[: len(base) - (node.level - 1)]
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            found.add(target)
    return found


def _violations(package: str, forbidden: tuple[str, ...]) -> list[str]:
    bad = []
    for path in sorted((BACKEND / package.replace(".", "/")).rglob("*.py")):
        for target in _imports(path):
            if any(target == f or target.startswith(f + ".") for f in forbidden):
                bad.append(f"{path.relative_to(BACKEND)} -> {target}")
    return bad


def _loaded_by(entrypoint: str) -> set[str]:
    """Modulos carregados ao importar um entrypoint, num processo limpo."""
    script = (
        "import json, sys\n"
        "from loguru import logger\n"
        "logger.remove()\n"
        f"import {entrypoint}\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return set(json.loads(result.stdout.strip().splitlines()[-1]))


# --- regras de pacote --------------------------------------------------------


def test_shared_never_imports_the_product():
    """O nucleo serve a qualquer servico; importar `app` o amarraria ao produto."""
    assert _violations("shared", ("app", "services")) == []


def test_core_does_not_depend_on_domain_or_delivery():
    """`app.core` e infraestrutura do produto: nao conhece regra nem rota."""
    forbidden = ("app.services", "app.routers", "app.orchestration", "app.adapters")
    assert _violations("app.core", forbidden) == []


def test_ports_do_not_depend_on_implementations():
    forbidden = ("app.adapters", "app.services", "app.routers", "app.core")
    assert _violations("shared.ports", forbidden) == []
    assert _violations("app.ports", forbidden) == []


# --- fecho real dos servicos -------------------------------------------------


def test_mcp_service_loads_nothing_from_the_product():
    """A imagem do mcp-service nao copia `app/`: um import dele quebraria o boot."""
    loaded = _loaded_by("services.mcp_service.main")

    assert sorted(m for m in loaded if m == "app" or m.startswith("app.")) == []


#: O que o tool-service carrega de `app` hoje. E divida conhecida, nao desenho:
#: `assistant_tools` puxa `launcher_service`, que traz banco e credenciais sem
#: usa-los (docs/arquitetura/configuracao-por-servico.md). A lista existe para
#: a divida so poder diminuir - modulo novo aqui reprova o teste.
TOOL_SERVICE_KNOWN_DEBT = {
    "app.core.database",
    "app.core.security",
    "app.services.credential_storage_service",
    "app.services.user_llm_config_service",
    "app.services.launcher_service",
}


def test_tool_service_does_not_grow_its_dependency_on_the_product():
    loaded = _loaded_by("services.tool_service.main")

    domain = {
        m
        for m in loaded
        if m.startswith(("app.core.database", "app.core.security", "app.services."))
    }
    assert domain - TOOL_SERVICE_KNOWN_DEBT - {
        # Montam proposta de acao: e o catalogo do servico.
        "app.services.assistant_tools",
        "app.services.calendar_action_service",
        "app.services.coding_action_service",
        "app.services.computer_action_service",
        "app.services.client_capability_service",
        "app.services.device_catalog_service",
        "app.services.local_message_markers",
    } == set()
    assert not any(m.startswith("app.routers") for m in loaded)


def test_orchestrator_never_loads_the_http_delivery_layer():
    """Rotas e WebSocket sao da API; o orquestrador recebe o turno pronto."""
    loaded = _loaded_by("services.orchestrator.main")

    assert sorted(m for m in loaded if m.startswith("app.routers")) == []
