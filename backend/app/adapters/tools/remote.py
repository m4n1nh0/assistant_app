"""Tool Gateway remoto: o catalogo vive no tool-service.

Mesmo contrato do gateway local, outro transporte. O dominio nao sabe qual dos
dois esta ligado - e isso que permite mover o catalogo para fora do processo
sem tocar em agente ou no de grafo.

Toda chamada carrega os identificadores de correlacao em cabecalho, entao um
trace comecado na API continua no tool-service em vez de virar dois traces
soltos.

As capacidades da maquina do usuario **nao** vivem no tool-service: elas sao
publicadas pelo WebSocket da sessao, no processo que atende o chat. Por isso
este gateway soma o catalogo de dispositivos local ao remoto, como o gateway
in-process faz - sem isso, ligar `TOOL_TRANSPORT=remote` tirava do agente toda
capacidade da maquina, sem erro nenhum.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from loguru import logger

from shared.observability import current_context, span
from shared.ports.tools import ToolDescriptor, ToolInvocation, ToolResult


class RemoteToolGateway:
    """Implementa `ToolGateway` falando HTTP com o tool-service."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 20.0,
        max_retries: int = 1,
        retry_backoff: float = 0.5,
        client: httpx.AsyncClient | None = None,
        devices: Any = None,
        local: Any = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._backoff = max(0.0, retry_backoff)
        self._client = client
        self._devices = devices
        #: Ferramentas que so existem neste processo - as que leem o banco do
        #: produto. Somam-se ao catalogo remoto e executam aqui.
        self._local = local

    def _device_catalog(self):
        if self._devices is None:
            from ...services.device_catalog_service import get_device_catalog

            return get_device_catalog()
        return self._devices

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        headers = current_context().headers()
        attempts = self._max_retries + 1
        last: Exception = RuntimeError("sem tentativa")

        for attempt in range(attempts):
            if attempt:
                await asyncio.sleep(self._backoff * attempt)
            try:
                if self._client is not None:
                    response = await self._client.request(
                        method, url, json=json, headers=headers,
                        timeout=timeout or self._timeout,
                    )
                else:
                    async with httpx.AsyncClient(
                        timeout=timeout or self._timeout
                    ) as client:
                        response = await client.request(
                            method, url, json=json, headers=headers
                        )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                # 4xx e decisao do servico, nao falha de rede: repetir so
                # transformaria uma recusa em varias.
                if exc.response.status_code < 500:
                    raise
                last = exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
        raise last

    async def _local_tools(self, agent_id: str) -> list[ToolDescriptor]:
        """As ferramentas deste processo, que o tool-service nao publica."""
        if self._local is None:
            return []
        try:
            return await self._local.list_tools(agent_id=agent_id)
        except Exception as exc:
            logger.warning(f"Catalogo local nao consultado: {exc}")
            return []

    async def list_tools(self, *, agent_id: str = "") -> list[ToolDescriptor]:
        """Catalogo do tool-service, mais o deste processo e a maquina da sessao."""
        devices = self._device_catalog().descriptors(agent_id=agent_id)
        locais = await self._local_tools(agent_id)
        # Nome repetido fica com a versao remota: o tool-service e a fonte do
        # catalogo compartilhado, e o local complementa em vez de sobrescrever.
        async with span("tool_service.list", "tool", agent=agent_id or None):
            try:
                payload = await self._request(
                    "GET", f"/tools?agent_id={agent_id}" if agent_id else "/tools"
                )
            except Exception as exc:
                # Catalogo indisponivel nao pode derrubar a conversa: o agente
                # responde sem ferramenta, como ja faz quando o MCP cai. A
                # maquina do usuario e o catalogo local nao dependem do
                # tool-service e continuam.
                logger.warning(f"tool-service indisponivel: {exc}")
                return locais + devices
        remotas = [_descriptor(item) for item in payload.get("tools", [])]
        vistos = {item.name for item in remotas}
        return (
            remotas
            + [item for item in locais if item.name not in vistos]
            + devices
        )

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        """Executa uma ferramenta no tool-service, ou na maquina da sessao."""
        devices = self._device_catalog()
        device_executor = devices.executor()
        if device_executor is not None and devices.find(invocation.name):
            return await device_executor.invoke(invocation)
        if self._local is not None and await self._knows_locally(invocation.name):
            return await self._local.invoke(invocation)
        async with span(
            f"tool.{invocation.name}",
            "tool",
            tool=invocation.name,
            transport="remote",
            agent=invocation.agent_id or None,
        ) as observed:
            try:
                payload = await self._request(
                    "POST",
                    f"/tools/{invocation.name}/invoke",
                    json={
                        "args": invocation.args,
                        "agent_id": invocation.agent_id,
                        "call_id": invocation.call_id,
                        "timeout_seconds": invocation.timeout_seconds,
                        # Fora de `args` tambem no fio: do outro lado o
                        # executor publica isso como identidade da execucao, e
                        # misturar com os argumentos do modelo apagaria a
                        # distincao entre o que o usuario e e o que ele pediu.
                        "principal": {
                            "tutor_id": invocation.principal.tutor_id,
                            "user_id": invocation.principal.user_id,
                        },
                    },
                    timeout=(invocation.timeout_seconds or self._timeout) + 5,
                )
            except Exception as exc:
                observed.fail(exc)
                return ToolResult(
                    name=invocation.name,
                    ok=False,
                    error=f"tool-service indisponivel: {exc}",
                    source="remote",
                    call_id=invocation.call_id,
                )
        return _result(invocation, payload)

    async def _knows_locally(self, name: str) -> bool:
        registry = getattr(self._local, "registry", None)
        if registry is None:
            return False
        return name in registry.names()

    async def health(self) -> dict[str, Any]:
        """Health do tool-service, ou o motivo de nao responder."""
        try:
            payload = await self._request("GET", "/health/ready", timeout=5)
        except Exception as exc:
            return {"ok": False, "transport": "remote", "error": str(exc)}
        return {"ok": True, "transport": "remote", **payload}


def _descriptor(item: dict[str, Any]) -> ToolDescriptor:
    return ToolDescriptor(
        name=str(item.get("name") or ""),
        description=str(item.get("description") or ""),
        args_schema=item.get("args_schema") or {},
        source=item.get("source") or "remote",
        server=str(item.get("server") or ""),
        scopes=tuple(item.get("scopes") or ()),
        timeout_seconds=item.get("timeout_seconds"),
        read_only=bool(item.get("read_only", True)),
    )


def _result(invocation: ToolInvocation, payload: dict[str, Any]) -> ToolResult:
    return ToolResult(
        name=invocation.name,
        ok=bool(payload.get("ok", False)),
        output=payload.get("output"),
        error=str(payload.get("error") or ""),
        duration_ms=float(payload.get("duration_ms") or 0.0),
        source=payload.get("source") or "remote",
        retries=int(payload.get("retries") or 0),
        call_id=invocation.call_id,
    )
