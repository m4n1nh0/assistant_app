"""Execucao de capacidade na maquina do usuario, por chamada e resposta.

O agente monta a chamada como monta qualquer outra; o que muda e que o executor
desta ferramenta nao roda codigo no servidor: ele empurra a chamada pelo canal
da sessao, guarda o `call_id` e espera a maquina responder. Quando a resposta
chega pelo WebSocket, o `future` daquele id e resolvido e a ferramenta "retorna"
como se tivesse rodado aqui.

O transporte entra por injecao (`send`), entao todo o comportamento - timeout,
queda de conexao, resposta atrasada, resposta duplicada - e testavel sem abrir
socket nenhum.

Uma regra que nao e detalhe: **capacidade que altera a maquina nao pode ser
repetida automaticamente**. O executor tenta de novo o que e transitorio, e um
timeout normalmente e; mas aqui o script pode estar rodando ainda do outro lado,
e a segunda tentativa executaria duas vezes. Por isso o timeout de uma
capacidade `read_only=False` sobe como erro nao repetivel.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from loguru import logger

from ..ports.tools import ToolError, ToolTimeout
from ..toolkit.registry import ToolRunner

#: Envia `payload` para a maquina `device_id`. E o unico ponto de transporte.
SendToDevice = Callable[[str, dict[str, Any]], Awaitable[None]]

#: Teto de uma chamada remota. Curto o bastante para nao segurar a conversa e
#: longo o bastante para um diagnostico com ping e confirmacao do usuario.
DEFAULT_TIMEOUT_SECONDS = 90.0


class RemoteCapabilityError(ToolError):
    """A maquina do usuario recusou, falhou ou sumiu no meio da chamada."""


@dataclass
class _PendingCall:
    device_id: str
    tool_name: str
    future: asyncio.Future


class RemoteCapabilityGateway:
    """Leva chamadas de ferramenta ate a maquina que declarou a capacidade."""

    def __init__(
        self,
        send: SendToDevice,
        *,
        default_timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._send = send
        self._default_timeout = default_timeout
        self._pending: dict[str, _PendingCall] = {}

    @property
    def pending_calls(self) -> int:
        """Quantas chamadas estao esperando resposta agora."""
        return len(self._pending)

    def runner_factory(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> Callable[[Any, Any], ToolRunner]:
        """Fabrica de executores, no formato que o catalogo de cliente espera."""

        def factory(manifest: Any, capability: Any) -> ToolRunner:
            async def _run(args: dict[str, Any]) -> Any:
                return await self.call(
                    device_id=manifest.device_id,
                    tool_name=capability.tool_name,
                    capability_id=capability.id,
                    args=args,
                    timeout=timeout_seconds,
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
        timeout: float | None = None,
        repeatable: bool = True,
    ) -> str:
        """Pede a execucao e espera o resultado da maquina.

        Args:
            device_id: maquina que declarou a capacidade.
            tool_name: nome no catalogo, usado em log e trace.
            capability_id: id que a interface conhece.
            args: argumentos ja validados pelo executor.
            timeout: teto desta chamada.
            repeatable: `True` so quando repetir a chamada e inofensivo. Um
                timeout de capacidade nao repetivel sobe como erro definitivo.

        Returns:
            O texto que volta para o modelo analisar.
        """
        call_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        pending = _PendingCall(device_id, tool_name, loop.create_future())
        self._pending[call_id] = pending

        try:
            await self._send(
                device_id,
                {
                    "type": "tool_call",
                    "payload": {
                        "call_id": call_id,
                        "tool_name": tool_name,
                        "capability_id": capability_id,
                        "arguments": args,
                    },
                },
            )
        except Exception as exc:
            self._pending.pop(call_id, None)
            raise RemoteCapabilityError(
                f"nao consegui falar com a maquina do usuario: {exc}"
            ) from exc

        try:
            payload = await asyncio.wait_for(
                pending.future, timeout or self._default_timeout
            )
        except asyncio.TimeoutError as exc:
            limit = timeout or self._default_timeout
            message = (
                f"{tool_name}: a maquina do usuario nao respondeu em "
                f"{limit:.0f}s"
            )
            if repeatable:
                raise ToolTimeout(message) from exc
            # Pode estar rodando ainda do outro lado: repetir executaria duas
            # vezes o que altera a maquina.
            raise RemoteCapabilityError(
                f"{message} (nao vou repetir uma acao que altera a maquina)"
            ) from exc
        finally:
            self._pending.pop(call_id, None)

        return _output_of(tool_name, payload)

    def resolve(self, call_id: str, payload: dict[str, Any]) -> bool:
        """Entrega a resposta que chegou da maquina a chamada que a espera.

        Returns:
            `False` quando ninguem esperava por este `call_id` - resposta
            atrasada depois do timeout, ou repetida. Ignorar e o certo: o
            resultado ja foi dado como perdido.
        """
        pending = self._pending.get(call_id)
        if pending is None or pending.future.done():
            logger.debug(f"Resultado remoto sem chamada aberta: {call_id}")
            return False
        pending.future.set_result(payload)
        return True

    def cancel_device(self, device_id: str, reason: str = "conexao encerrada") -> int:
        """Derruba as chamadas pendentes de uma maquina que saiu.

        Sem isto, cada desconexao deixaria uma conversa presa ate o timeout.

        Returns:
            Quantas chamadas foram encerradas.
        """
        doomed = [
            call_id
            for call_id, pending in self._pending.items()
            if pending.device_id == device_id
        ]
        for call_id in doomed:
            pending = self._pending.pop(call_id)
            if not pending.future.done():
                pending.future.set_exception(
                    RemoteCapabilityError(
                        f"{pending.tool_name}: {reason} antes da resposta"
                    )
                )
        return len(doomed)


def _output_of(tool_name: str, payload: Any) -> str:
    """Traduz a resposta da maquina no texto que o modelo le."""
    if not isinstance(payload, dict):
        return str(payload)
    if payload.get("ok") is False:
        raise RemoteCapabilityError(
            f"{tool_name} falhou na maquina do usuario: "
            f"{payload.get('error') or 'sem detalhe'}"
        )
    for key in ("prompt_text", "summary", "output"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return "Capacidade executada, sem saida."
