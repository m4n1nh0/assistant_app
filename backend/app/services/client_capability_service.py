"""Catalogo publicado pela maquina do usuario.

Quem tem a maquina e a interface; quem sabe o que aquela maquina consegue fazer
tambem. Ate aqui o backend guardava essa lista escrita em Python - e por isso
uma capacidade nova exigia deploy do servidor, e o Windows de um usuario e o Mac
de outro eram tratados como se fossem a mesma coisa.

Neste modulo a interface publica um manifesto e cada entrada vira uma
`ToolDescriptor` de origem `remote`, com o `server` sendo o dispositivo. Dai em
diante e uma ferramenta como qualquer outra: o mesmo executor aplica escopo,
timeout, retry e auditoria, e o agente nao sabe - nem precisa saber - que a
execucao acontece do outro lado do WebSocket.

O manifesto vem de fora, entao ele e validado, nao acreditado: id fora do
padrao, descricao vazia ou schema quebrado sao descartados, e uma capacidade que
altera a maquina passa a exigir confirmacao mesmo que o cliente diga que nao
precisa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from ..orchestration.agents import mcp_scopes
from ..ports.tools import ToolDescriptor
from ..toolkit.registry import ToolRegistry, ToolRunner

#: Prefixo do nome no catalogo. Deixa obvio no trace e no prompt que a execucao
#: sai do servidor, e evita colisao com ferramentas locais do backend.
CAPABILITY_PREFIX = "local_"

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,48}$")
_RISK_LEVELS = ("low", "medium", "high")
_MAX_CAPABILITIES = 64
_MAX_DESCRIPTION = 600


class ClientManifestError(ValueError):
    """Manifesto malformado a ponto de nao dar para aproveitar nada."""


@dataclass(frozen=True)
class ClientCapability:
    """Uma capacidade que a maquina do usuario declarou saber executar."""

    id: str
    name: str
    description: str
    args_schema: dict[str, Any] = field(default_factory=dict)
    risk_level: str = "low"
    requires_confirmation: bool = False
    read_only: bool = True
    platforms: tuple[str, ...] = ()

    @property
    def tool_name(self) -> str:
        """Nome desta capacidade dentro do catalogo de ferramentas."""
        return f"{CAPABILITY_PREFIX}{self.id}"


@dataclass(frozen=True)
class ClientManifest:
    """O catalogo de uma maquina, ja validado."""

    device_id: str
    platform: str
    capabilities: tuple[ClientCapability, ...] = ()
    rejected: tuple[str, ...] = ()


def parse_manifest(payload: Any, *, device_id: str) -> ClientManifest:
    """Le e valida o manifesto publicado pela interface.

    Entrada quebrada em uma capacidade nao derruba as outras: a entrada ruim vai
    para `rejected` com o motivo, e o resto do catalogo continua valendo.

    Raises:
        ClientManifestError: quando nem o envelope do manifesto e aproveitavel.
    """
    if not isinstance(payload, dict):
        raise ClientManifestError("Manifesto precisa ser um objeto.")
    if not device_id.strip():
        raise ClientManifestError("Manifesto sem dispositivo de origem.")

    platform = str(payload.get("platform") or "").strip().lower()
    raw_items = payload.get("capabilities")
    if not isinstance(raw_items, list):
        raise ClientManifestError("Manifesto sem lista de capacidades.")

    capabilities: list[ClientCapability] = []
    rejected: list[str] = []
    seen: set[str] = set()

    for index, raw in enumerate(raw_items[:_MAX_CAPABILITIES]):
        try:
            capability = _parse_capability(raw)
        except ValueError as exc:
            rejected.append(f"#{index}: {exc}")
            continue
        if capability.id in seen:
            rejected.append(f"{capability.id}: declarada duas vezes")
            continue
        seen.add(capability.id)
        capabilities.append(capability)

    if len(raw_items) > _MAX_CAPABILITIES:
        rejected.append(
            f"acima do limite de {_MAX_CAPABILITIES} capacidades por maquina"
        )
    if rejected:
        logger.warning(
            f"Manifesto de {device_id} com entradas descartadas: {rejected}"
        )

    return ClientManifest(
        device_id=device_id.strip(),
        platform=platform,
        capabilities=tuple(capabilities),
        rejected=tuple(rejected),
    )


def register_client_capabilities(
    registry: ToolRegistry,
    manifest: ClientManifest,
    runner_factory: Any,
    *,
    timeout_seconds: float | None = None,
) -> int:
    """Publica as capacidades de uma maquina no catalogo.

    Args:
        registry: catalogo de destino.
        manifest: catalogo ja validado da maquina.
        runner_factory: recebe `(manifest, capability)` e devolve o executor que
            leva a chamada ate aquela maquina. E o ponto onde o transporte entra
            - hoje o WebSocket da sessao, num teste um dublê.
        timeout_seconds: teto proprio destas ferramentas.

    Returns:
        Quantas capacidades ficaram publicadas para esta maquina.
    """
    # Trocar o catalogo inteiro de uma maquina de uma vez: a interface publica o
    # que ela sabe fazer agora, e o que sumiu do manifesto tem que sumir daqui.
    unregister_client_capabilities(registry, manifest.device_id)

    scopes = mcp_scopes()
    for capability in manifest.capabilities:
        registry.register(
            ToolDescriptor(
                name=capability.tool_name,
                description=_describe(capability, manifest),
                args_schema=capability.args_schema,
                source="remote",
                server=manifest.device_id,
                scopes=scopes,
                timeout_seconds=timeout_seconds,
                read_only=capability.read_only,
            ),
            _runner_for(runner_factory, manifest, capability),
        )
    return len(manifest.capabilities)


def unregister_client_capabilities(
    registry: ToolRegistry,
    device_id: str,
) -> int:
    """Tira do catalogo tudo que veio de uma maquina, ao desconectar."""
    return registry.unregister_source("remote", server=device_id)


def client_descriptors(
    registry: ToolRegistry,
    *,
    device_id: str = "",
) -> list[ToolDescriptor]:
    """As ferramentas publicadas por maquina de usuario, para inspecao."""
    items = registry.descriptors(source="remote")
    if device_id:
        items = [item for item in items if item.server == device_id]
    return items


def _parse_capability(raw: Any) -> ClientCapability:
    if not isinstance(raw, dict):
        raise ValueError("capacidade precisa ser um objeto")

    capability_id = str(raw.get("id") or "").strip().lower()
    if not _ID_PATTERN.match(capability_id):
        raise ValueError(f"id invalido: {capability_id or '(vazio)'}")

    description = str(raw.get("description") or "").strip()
    if not description:
        # A descricao e o unico texto que o modelo le para decidir se a
        # capacidade serve. Sem ela, a ferramenta existe e nunca e escolhida.
        raise ValueError("sem descricao")

    schema = raw.get("args_schema")
    if schema is None:
        schema = {"type": "object", "properties": {}}
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ValueError("args_schema precisa ser um JSON Schema de objeto")

    risk = str(raw.get("risk_level") or "low").strip().lower()
    if risk not in _RISK_LEVELS:
        raise ValueError(f"risco invalido: {risk}")

    read_only = bool(raw.get("read_only", True))
    requires_confirmation = bool(raw.get("requires_confirmation", False))
    if not read_only and not requires_confirmation:
        # Cliente velho ou adulterado nao ganha execucao silenciosa do que
        # altera a maquina: aqui a confirmacao volta a ser obrigatoria.
        logger.warning(
            f"Capacidade {capability_id} altera a maquina sem pedir "
            "confirmacao; exigindo confirmacao no servidor."
        )
        requires_confirmation = True

    platforms = raw.get("platforms") or ()
    if not isinstance(platforms, (list, tuple)):
        raise ValueError("platforms precisa ser lista")

    return ClientCapability(
        id=capability_id,
        name=str(raw.get("name") or capability_id).strip(),
        description=description[:_MAX_DESCRIPTION],
        args_schema=schema,
        risk_level=risk,
        requires_confirmation=requires_confirmation,
        read_only=read_only,
        platforms=tuple(str(item).strip().lower() for item in platforms),
    )


def _describe(capability: ClientCapability, manifest: ClientManifest) -> str:
    """Descricao que vai para o modelo, com a origem explicita.

    O modelo precisa saber que isso roda na maquina do usuario: e o que o leva a
    escolher esta ferramenta em vez de responder "rode este comando ai".
    """
    where = f"Executa na maquina do usuario ({manifest.platform or 'desktop'})."
    confirm = (
        " O usuario confirma antes de executar."
        if capability.requires_confirmation
        else ""
    )
    return f"{capability.description} {where}{confirm}".strip()


def _runner_for(
    runner_factory: Any,
    manifest: ClientManifest,
    capability: ClientCapability,
) -> ToolRunner:
    runner = runner_factory(manifest, capability)
    if runner is None:
        raise ClientManifestError(
            f"Sem transporte para executar {capability.tool_name}."
        )
    return runner
