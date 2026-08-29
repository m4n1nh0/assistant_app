"""Execucao governada de ferramentas: autorizacao, timeout, retry e auditoria.

Este e o unico caminho por onde uma ferramenta roda. O agente monta a
`ToolInvocation` e para por ai; quem valida escopo, aplica teto de tempo,
decide se vale tentar de novo e normaliza a falha e este modulo.

Duas decisoes explicam o formato:

- **Falha vira resultado, nao excecao.** Uma ferramenta quebrada precisa virar
  texto que o modelo le e contorna. Excecao subindo mataria a resposta inteira.
- **Retry so no que e transitorio.** Argumento invalido ou ferramenta
  inexistente nao melhora tentando de novo; timeout e falha de transporte
  podem melhorar. Repetir o que nao e transitorio so multiplica latencia.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger

from ..core.observability import span
from ..ports.tools import (
    ToolDescriptor,
    ToolError,
    ToolInvocation,
    ToolNotAllowed,
    ToolNotFound,
    ToolResult,
    ToolTimeout,
)
from .registry import ToolRegistry


class ToolExecutor:
    """Aplica as regras de execucao sobre o catalogo."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        default_timeout: float = 20.0,
        max_retries: int = 1,
        retry_backoff: float = 0.5,
    ) -> None:
        self._registry = registry
        self._default_timeout = default_timeout
        self._max_retries = max(0, max_retries)
        self._retry_backoff = max(0.0, retry_backoff)

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        """Executa uma ferramenta e devolve o resultado normalizado.

        Args:
            invocation: o pedido, ja atribuido a um agente.

        Returns:
            `ToolResult` com `ok=True` e a saida, ou `ok=False` e o motivo. Nunca
            levanta excecao.
        """
        started = time.perf_counter()
        registered = self._registry.get(invocation.name)
        if registered is None:
            return self._failure(
                invocation,
                ToolNotFound(f"ferramenta desconhecida: {invocation.name}"),
                started,
            )

        descriptor = registered.descriptor
        if invocation.agent_id and not descriptor.allowed_for(invocation.agent_id):
            return self._failure(
                invocation,
                ToolNotAllowed(
                    f"{invocation.name} nao esta liberada para "
                    f"{invocation.agent_id}"
                ),
                started,
                descriptor=descriptor,
            )

        invalid = _validate_args(descriptor, invocation.args)
        if invalid:
            return self._failure(
                invocation, ToolError(invalid), started, descriptor=descriptor
            )

        timeout = (
            invocation.timeout_seconds
            or descriptor.timeout_seconds
            or self._default_timeout
        )
        return await self._run_with_retries(
            invocation, descriptor, registered.runner, timeout, started
        )

    async def _run_with_retries(
        self,
        invocation: ToolInvocation,
        descriptor: ToolDescriptor,
        runner,
        timeout: float,
        started: float,
    ) -> ToolResult:
        last_error: Exception = ToolError("falha desconhecida")
        attempts = self._max_retries + 1

        async with span(
            f"tool.{invocation.name}",
            "tool",
            tool=invocation.name,
            source=descriptor.source,
            server=descriptor.server or None,
            agent=invocation.agent_id or None,
        ) as observed:
            for attempt in range(attempts):
                if attempt:
                    observed.retry()
                    await asyncio.sleep(self._retry_backoff * attempt)
                try:
                    output = await asyncio.wait_for(
                        runner(dict(invocation.args)), timeout=timeout
                    )
                    return ToolResult(
                        name=invocation.name,
                        ok=True,
                        output=output,
                        duration_ms=_elapsed_ms(started),
                        source=descriptor.source,
                        retries=attempt,
                        call_id=invocation.call_id,
                    )
                except asyncio.TimeoutError:
                    last_error = ToolTimeout(
                        f"{invocation.name} excedeu {timeout:.0f}s"
                    )
                except asyncio.CancelledError:
                    # Cancelamento e propagado: quando o usuario desiste da
                    # requisicao, insistir na ferramenta so gasta recurso.
                    observed.fail("cancelada")
                    raise
                except Exception as exc:
                    last_error = exc
                if not _retryable(last_error):
                    break

            observed.fail(last_error)
            logger.warning(f"Ferramenta {invocation.name} falhou: {last_error}")
            return ToolResult(
                name=invocation.name,
                ok=False,
                error=f"erro ao executar: {last_error}",
                duration_ms=_elapsed_ms(started),
                source=descriptor.source,
                retries=observed.retries,
                call_id=invocation.call_id,
            )

    def _failure(
        self,
        invocation: ToolInvocation,
        error: Exception,
        started: float,
        *,
        descriptor: ToolDescriptor | None = None,
    ) -> ToolResult:
        logger.warning(f"Ferramenta {invocation.name} recusada: {error}")
        return ToolResult(
            name=invocation.name,
            ok=False,
            error=str(error),
            duration_ms=_elapsed_ms(started),
            source=descriptor.source if descriptor else "local",
            call_id=invocation.call_id,
        )


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _retryable(error: Exception) -> bool:
    if isinstance(error, ToolError):
        return error.retryable
    # Falha de transporte e transitoria por natureza; erro de dominio nao.
    return isinstance(error, (ConnectionError, OSError))


def _validate_args(descriptor: ToolDescriptor, args: dict[str, Any]) -> str:
    """Confere o basico antes de gastar uma chamada.

    A validacao profunda continua sendo do proprio schema pydantic da ferramenta
    - repeti-la aqui duplicaria regra. O que se ganha e recusar cedo o que o
    modelo alucina com mais frequencia: campo obrigatorio ausente e argumento
    que nao e objeto.

    Returns:
        A mensagem de erro, ou string vazia quando esta valido.
    """
    if not isinstance(args, dict):
        return f"{descriptor.name} espera um objeto de argumentos"

    schema = descriptor.args_schema or {}
    required = schema.get("required")
    if not isinstance(required, list):
        return ""

    missing = [
        str(field)
        for field in required
        if str(field) not in args or args.get(str(field)) in (None, "")
    ]
    if missing:
        return (
            f"{descriptor.name} exige {', '.join(sorted(missing))} "
            "e o argumento nao veio"
        )
    return ""
