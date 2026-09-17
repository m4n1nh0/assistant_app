"""Capacidade da maquina do usuario disparada fora da assistant-api.

A maquina so e alcancavel pelo WebSocket da sessao, e esse socket vive na API.
Quando o grafo roda no agent-orchestrator, o agente continua enxergando as
capacidades - o manifesto chega junto com o turno -, mas a execucao precisa
voltar a API para seguir pelo socket.

Este modulo e o executor dessas ferramentas no orquestrador. Ele mantem as duas
regras do executor original (`remote_capability_gateway`):

- timeout de capacidade repetivel sobe como `ToolTimeout`, que o executor pode
  tentar de novo;
- falha de uma capacidade que altera a maquina **nao** e repetivel. Aqui isso
  vale tambem para queda de rede no meio da chamada: a API pode ter entregue o
  pedido a maquina antes de a resposta se perder.
"""

from __future__ import annotations

from typing import Any, Callable

import httpx

from ...core.internal_auth import INTERNAL_TOKEN_HEADER
from shared.observability import current_context
from shared.ports.tools import ToolTimeout
from ...services.remote_capability_gateway import (
    DEFAULT_TIMEOUT_SECONDS,
    RemoteCapabilityError,
)
from shared.toolkit.registry import ToolRunner

#: Folga sobre o teto da maquina: a API espera a maquina ate o teto dela, e so
#: depois responde. Sem folga, o orquestrador desistiria antes da resposta.
_TRANSPORT_MARGIN_SECONDS = 15.0


class DeviceCapabilityCallback:
    """Leva uma chamada de capacidade de volta a assistant-api."""

    def __init__(
        self,
        api_base_url: str,
        *,
        token: str = "",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = api_base_url.rstrip("/")
        self._token = token.strip()
        self._timeout = timeout_seconds
        self._client = client

    def runner_factory(self) -> Callable[[Any, Any], ToolRunner]:
        """Fabrica de executores, no formato de `register_client_capabilities`."""

        def factory(manifest: Any, capability: Any) -> ToolRunner:
            async def _run(args: dict[str, Any]) -> Any:
                return await self.call(
                    device_id=manifest.device_id,
                    tool_name=capability.tool_name,
                    capability_id=capability.id,
                    args=args,
                    repeatable=capability.read_only,
                )

            return _run

        return factory

    async def call(
        self,
        *,
        device_id: str,
        tool_name: str,
        capability_id: str,
        args: dict[str, Any],
        repeatable: bool = True,
    ) -> str:
        """Pede a execucao a API e devolve o texto que a maquina respondeu."""
        headers = current_context().headers()
        if self._token:
            headers[INTERNAL_TOKEN_HEADER] = self._token
        body = {
            "device_id": device_id,
            "tool_name": tool_name,
            "capability_id": capability_id,
            "arguments": args,
            "timeout_seconds": self._timeout,
            "repeatable": repeatable,
        }
        url = f"{self._base_url}/internal/devices/invoke"
        timeout = self._timeout + _TRANSPORT_MARGIN_SECONDS

        try:
            if self._client is not None:
                response = await self._client.post(
                    url, json=body, headers=headers, timeout=timeout
                )
            else:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise RemoteCapabilityError(
                f"{tool_name}: assistant-api recusou a chamada "
                f"(HTTP {exc.response.status_code})"
            ) from exc
        except httpx.HTTPError as exc:
            raise RemoteCapabilityError(
                f"{tool_name}: nao consegui falar com a assistant-api: {exc}"
            ) from exc

        if payload.get("ok"):
            return str(payload.get("output") or "Capacidade executada, sem saida.")
        error = str(payload.get("error") or f"{tool_name} falhou sem detalhe")
        if payload.get("retryable") and repeatable:
            raise ToolTimeout(error)
        raise RemoteCapabilityError(error)
