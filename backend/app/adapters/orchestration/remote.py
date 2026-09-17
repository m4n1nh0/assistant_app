"""Orquestracao remota: o grafo roda no agent-orchestrator.

Tres coisas precisam atravessar a fronteira, e cada uma atravessa de um jeito:

- **Credenciais**: nao atravessam. O orquestrador decifra do banco pelo
  `tutor_id`; o que viaja e so a identificacao.
- **Maquina do usuario**: o manifesto validado vai junto com o turno. A execucao
  volta pela API (`/internal/devices/invoke`), que e quem tem o WebSocket.
- **Correlacao**: `traceparent` e os ids de conversa e execucao, em cabecalho.

Repeticao so quando a requisicao comprovadamente nao chegou (falha de conexao).
Um turno que chegou pode ter chamado modelo pago ou disparado acao na maquina;
repetir por timeout faria isso duas vezes.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from loguru import logger

from ...core.internal_auth import INTERNAL_TOKEN_HEADER
from shared.observability import current_context, span
from ...models.schemas import LLMResponse
from ...ports.orchestration import ChatTurn
from .wire import result_from_payload, turn_to_payload


class RemoteOrchestrationGateway:
    """Implementa `OrchestrationGateway` falando HTTP com o agent-orchestrator."""

    def __init__(
        self,
        base_url: str,
        *,
        token: str = "",
        timeout_seconds: float = 300.0,
        max_retries: int = 1,
        retry_backoff: float = 0.5,
        client: httpx.AsyncClient | None = None,
        devices: Any = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token.strip()
        self._timeout = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._backoff = max(0.0, retry_backoff)
        self._client = client
        self._devices = devices

    def _device_catalog(self):
        if self._devices is None:
            from ...services.device_catalog_service import get_device_catalog

            return get_device_catalog()
        return self._devices

    def _headers(self) -> dict[str, str]:
        headers = current_context().headers()
        if self._token:
            headers[INTERNAL_TOKEN_HEADER] = self._token
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        headers = self._headers()
        last: Exception = RuntimeError("sem tentativa")

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
            except httpx.ConnectError as exc:
                # Nao chegou ao orquestrador: repetir e seguro.
                last = exc
        raise last

    async def run_chat(self, turn: ChatTurn) -> dict[str, Any]:
        """Envia o turno ao orquestrador e devolve o estado final."""
        manifest = (
            self._device_catalog().manifest(turn.device_id)
            if turn.device_id
            else None
        )
        async with span(
            "orchestrator.chat",
            "graph",
            transport="remote",
            mode=turn.mode.value,
            provider=turn.requested_llm,
        ) as observed:
            try:
                payload = await self._request(
                    "POST",
                    "/orchestrate/chat",
                    json=turn_to_payload(turn, device=manifest),
                )
            except Exception as exc:
                observed.fail(exc)
                logger.error(f"agent-orchestrator indisponivel: {_describe(exc)}")
                return _unavailable(turn, exc)
            result = result_from_payload(payload)
            observed.set(action_kind=result.get("action_kind"), agent=result.get("agent_id"))
            return result

    async def health(self) -> dict[str, Any]:
        """Health do orquestrador, ou o motivo de nao responder."""
        try:
            payload = await self._request("GET", "/health/ready", timeout=5)
        except Exception as exc:
            return {"ok": False, "transport": "remote", "error": _describe(exc)}
        return {"transport": "remote", **payload}


def _describe(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 401:
            return "INTERNAL_SERVICE_TOKEN diferente entre assistant-api e orquestrador"
        if code == 503:
            return "INTERNAL_SERVICE_TOKEN nao configurado no orquestrador"
        return f"HTTP {code}"
    return str(exc) or exc.__class__.__name__


def _unavailable(turn: ChatTurn, exc: Exception) -> dict[str, Any]:
    """Resposta degradada, no mesmo formato da falha do grafo local."""
    return {
        "action_kind": "chat",
        "action": None,
        "execution_id": turn.execution_id,
        "errors": [f"agent-orchestrator indisponivel: {_describe(exc)}"],
        "responses": [
            LLMResponse(
                llm=turn.requested_llm or "backend",
                content=(
                    "Nao consegui processar sua mensagem agora. "
                    "Tente novamente em instantes."
                ),
                is_error=True,
            )
        ],
    }
