"""MCP Gateway remoto: o mcp-service cuida dos servidores externos.

Este e o modo em que a extracao rende de verdade. Servidor MCP `stdio` sobe
subprocesso na maquina; isolar isso em outro processo significa que um servidor
que trava, vaza memoria ou morre nao leva o backend junto, e pode ser
reiniciado sozinho.

O contrato e igual ao do gateway local. O que muda e o transporte - e os
identificadores de correlacao viajam em cabecalho para o trace continuar do
outro lado.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from loguru import logger

from ...core.observability import current_context, span
from ...ports.mcp import MCPServerHealth, MCPToolRef, MCPUnavailable


class RemoteMCPGateway:
    """Implementa `MCPGateway` falando HTTP com o mcp-service."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        retry_backoff: float = 0.5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._backoff = max(0.0, retry_backoff)
        self._client = client
        self._configured: bool | None = None

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
        last: Exception = MCPUnavailable("sem tentativa")

        for attempt in range(self._max_retries + 1):
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
                if exc.response.status_code < 500:
                    raise MCPUnavailable(
                        f"mcp-service recusou: {exc.response.status_code}",
                        retryable=False,
                    ) from exc
                last = MCPUnavailable(str(exc))
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = MCPUnavailable(f"mcp-service inalcancavel: {exc}")
        raise last

    def configured(self) -> bool:
        """Diz se o mcp-service reportou servidores na ultima consulta.

        Sincrono por contrato, entao usa o que a ultima chamada assincrona
        descobriu. Antes da primeira consulta assumimos que sim: o custo de
        perguntar e uma chamada, e o custo de assumir que nao seria esconder
        capacidades que existem.
        """
        return True if self._configured is None else self._configured

    async def list_tools(self, *, force: bool = False) -> list[MCPToolRef]:
        """Ferramentas anunciadas, consultadas no mcp-service."""
        async with span("mcp_service.list_tools", "mcp") as observed:
            try:
                payload = await self._request(
                    "GET", "/mcp/tools?force=true" if force else "/mcp/tools"
                )
            except Exception as exc:
                observed.fail(exc)
                logger.warning(f"mcp-service indisponivel: {exc}")
                self._configured = False
                return []
        tools = payload.get("tools", [])
        self._configured = bool(payload.get("configured", bool(tools)))
        return [
            MCPToolRef(
                name=str(item.get("name") or ""),
                server=str(item.get("server") or ""),
                description=str(item.get("description") or ""),
                args_schema=item.get("args_schema") or {},
            )
            for item in tools
        ]

    async def invoke(
        self,
        name: str,
        args: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        """Executa uma ferramenta MCP atraves do mcp-service."""
        async with span("mcp_service.invoke", "mcp", tool=name) as observed:
            try:
                payload = await self._request(
                    "POST",
                    f"/mcp/tools/{name}/invoke",
                    json={"args": args, "timeout_seconds": timeout_seconds},
                    timeout=(timeout_seconds or self._timeout) + 5,
                )
            except Exception as exc:
                observed.fail(exc)
                raise
        if not payload.get("ok", False):
            raise MCPUnavailable(str(payload.get("error") or "falha no mcp-service"))
        return payload.get("output")

    async def health(self) -> list[MCPServerHealth]:
        """Estado dos servidores, como o mcp-service enxerga."""
        try:
            payload = await self._request("GET", "/mcp/servers", timeout=5)
        except Exception as exc:
            self._configured = False
            return [
                MCPServerHealth(
                    name="mcp-service", reachable=False, error=str(exc)
                )
            ]
        servers = payload.get("servers", [])
        self._configured = bool(servers)
        return [
            MCPServerHealth(
                name=str(item.get("name") or ""),
                transport=str(item.get("transport") or ""),
                reachable=bool(item.get("reachable", False)),
                tools=int(item.get("tools") or 0),
                error=str(item.get("error") or ""),
                circuit_open=bool(item.get("circuit_open", False)),
            )
            for item in servers
        ]
