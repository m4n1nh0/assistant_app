"""Cliente MCP com ciclo de vida, cache e protecao contra falha.

Servidor MCP e processo externo: pode nao existir na maquina, demorar para
subir, travar ou morrer no meio de uma chamada. Nada disso pode derrubar o chat
- na falha, o assistente responde sem aquelas capacidades.

Tres mecanismos sustentam essa promessa:

- **Cache com TTL** evita reconectar a cada mensagem.
- **Retry com backoff** cobre a oscilacao curta, com teto: repetir para sempre
  transforma um servidor morto em requisicao pendurada.
- **Disjuntor** para de tentar depois de N falhas seguidas e so volta a tentar
  passado o tempo de recuperacao. Sem ele, cada mensagem paga o timeout inteiro
  de um servidor que ja se sabe fora do ar.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger

from ..core.observability import span
from ..ports.mcp import MCPError, MCPServerHealth, MCPToolRef, MCPUnavailable
from .config import MCPServerConfig, as_client_config, parse_servers


class CircuitBreaker:
    """Disjuntor simples por contagem de falhas consecutivas."""

    def __init__(self, *, failure_threshold: int = 3, reset_seconds: float = 60.0):
        self._threshold = max(1, failure_threshold)
        # Zero e uma forma legitima de desligar o disjuntor: toda tentativa
        # passa. O piso existe so para nao aceitar janela negativa.
        self._reset_seconds = max(0.0, reset_seconds)
        self._failures = 0
        self._opened_at = 0.0

    @property
    def is_open(self) -> bool:
        """Diz se o disjuntor esta cortando as tentativas neste momento."""
        if self._failures < self._threshold:
            return False
        if time.monotonic() - self._opened_at >= self._reset_seconds:
            # Meia-abertura: deixa uma tentativa passar para descobrir se o
            # servidor voltou, sem liberar o caminho inteiro de uma vez.
            self._failures = self._threshold - 1
            return False
        return True

    def record_success(self) -> None:
        """Zera o contador apos uma chamada bem-sucedida."""
        self._failures = 0
        self._opened_at = 0.0

    def record_failure(self) -> None:
        """Conta mais uma falha e abre o disjuntor ao atingir o limite."""
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = time.monotonic()

    def reset(self) -> None:
        """Fecha o disjuntor. Usado no reset de cache e nos testes."""
        self._failures = 0
        self._opened_at = 0.0


class MCPClient:
    """Fala com os servidores MCP configurados, com cache e resiliencia.

    Ele nao conhece o conceito de agente nem de catalogo de ferramentas: devolve
    referencias e executa por nome. Quem transforma isso em ferramenta do
    assistente e o Tool Service.
    """

    def __init__(
        self,
        raw_servers: str,
        *,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        retry_backoff: float = 0.5,
        cache_ttl_seconds: float = 300.0,
        failure_threshold: int = 3,
        circuit_reset_seconds: float = 60.0,
    ) -> None:
        self._servers: dict[str, MCPServerConfig] = parse_servers(raw_servers)
        self._timeout = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._backoff = max(0.0, retry_backoff)
        self._cache_ttl = max(0.0, cache_ttl_seconds)
        self._breaker = CircuitBreaker(
            failure_threshold=failure_threshold,
            reset_seconds=circuit_reset_seconds,
        )
        self._cache: tuple[float, list[Any]] | None = None
        self._last_error = ""
        self._lock = asyncio.Lock()

    # --- configuracao ------------------------------------------------------

    def configured(self) -> bool:
        """Diz se ha ao menos um servidor MCP declarado."""
        return bool(self._servers)

    def server_names(self) -> list[str]:
        """Nomes dos servidores configurados, em ordem."""
        return sorted(self._servers)

    def reset(self) -> None:
        """Descarta o cache e fecha o disjuntor, forcando nova conexao."""
        self._cache = None
        self._last_error = ""
        self._breaker.reset()

    # --- ferramentas -------------------------------------------------------

    async def _load_tools(self) -> list[Any]:
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
        except ImportError as exc:
            raise MCPUnavailable(
                f"langchain-mcp-adapters ausente: {exc}", retryable=False
            ) from exc

        client = MultiServerMCPClient(as_client_config(self._servers))
        return await asyncio.wait_for(client.get_tools(), timeout=self._timeout)

    async def _fetch_with_retries(self) -> list[Any]:
        last: Exception = MCPUnavailable("sem tentativa")
        async with span(
            "mcp.list_tools", "mcp", servers=len(self._servers)
        ) as observed:
            for attempt in range(self._max_retries + 1):
                if attempt:
                    observed.retry()
                    await asyncio.sleep(self._backoff * attempt)
                try:
                    tools = await self._load_tools()
                    self._breaker.record_success()
                    self._last_error = ""
                    observed.set(tools=len(tools))
                    return tools
                except asyncio.TimeoutError:
                    last = MCPUnavailable(
                        f"servidores MCP nao responderam em {self._timeout:.0f}s"
                    )
                except MCPError as exc:
                    last = exc
                    if not exc.retryable:
                        break
                except Exception as exc:
                    last = MCPUnavailable(str(exc))
            self._breaker.record_failure()
            self._last_error = str(last)
            observed.fail(last)
        raise last

    async def langchain_tools(self, *, force: bool = False) -> list[Any]:
        """As tools cruas do adaptador MCP, com cache.

        Devolve o tipo do `langchain-mcp-adapters` de proposito: o Tool Service
        precisa do schema e do executor originais para publicar a capacidade no
        catalogo sem reimplementar o protocolo.
        """
        if not self._servers:
            return []

        now = time.monotonic()
        if not force and self._cache is not None and now - self._cache[0] < self._cache_ttl:
            return list(self._cache[1])

        if self._breaker.is_open:
            logger.debug("MCP em disjuntor aberto; usando cache atual")
            return list(self._cache[1]) if self._cache else []

        async with self._lock:
            # Outra corrotina pode ter preenchido o cache enquanto esperavamos.
            if not force and self._cache is not None:
                if time.monotonic() - self._cache[0] < self._cache_ttl:
                    return list(self._cache[1])
            try:
                tools = await self._fetch_with_retries()
            except Exception as exc:
                logger.warning(f"Servidores MCP indisponiveis: {exc}")
                # Cacheia a falha para nao repetir o custo a cada mensagem.
                self._cache = (time.monotonic(), [])
                return []
            self._cache = (time.monotonic(), list(tools))
            logger.info(
                f"MCP conectado: {len(tools)} ferramentas de "
                f"{len(self._servers)} servidor(es)"
            )
            return list(tools)

    async def list_tools(self, *, force: bool = False) -> list[MCPToolRef]:
        """Referencias das ferramentas anunciadas, no contrato do dominio."""
        tools = await self.langchain_tools(force=force)
        return [
            MCPToolRef(
                name=tool.name,
                server=_server_of(tool),
                description=getattr(tool, "description", "") or "",
                args_schema=_schema_of(tool),
            )
            for tool in tools
        ]

    async def invoke(
        self,
        name: str,
        args: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        """Executa uma ferramenta MCP pelo nome.

        Args:
            name: nome anunciado pelo servidor.
            args: argumentos ja validados pelo Tool Service.
            timeout_seconds: teto desta chamada.

        Returns:
            A saida crua do servidor.

        Raises:
            MCPUnavailable: quando a ferramenta nao existe ou o servidor falhou.
        """
        tools = await self.langchain_tools()
        target = next((tool for tool in tools if tool.name == name), None)
        if target is None:
            raise MCPUnavailable(
                f"ferramenta MCP desconhecida: {name}", retryable=False
            )

        async with span("mcp.invoke", "mcp", tool=name, server=_server_of(target)):
            try:
                return await asyncio.wait_for(
                    target.ainvoke(args), timeout=timeout_seconds or self._timeout
                )
            except asyncio.TimeoutError as exc:
                self._breaker.record_failure()
                raise MCPUnavailable(f"{name} excedeu o tempo limite") from exc
            except Exception as exc:
                self._breaker.record_failure()
                raise MCPUnavailable(str(exc)) from exc

    async def health(self) -> list[MCPServerHealth]:
        """Estado de cada servidor configurado.

        A contagem por servidor sai do proprio anuncio das ferramentas, quando o
        adaptador informa a origem; quando nao informa, o total fica no primeiro
        servidor e os demais aparecem sem contagem - preferimos numero honesto a
        numero inventado.
        """
        if not self._servers:
            return []

        tools = await self.langchain_tools()
        per_server: dict[str, int] = {}
        for tool in tools:
            origin = _server_of(tool)
            per_server[origin] = per_server.get(origin, 0) + 1

        reachable = bool(tools)
        return [
            MCPServerHealth(
                name=config.name,
                transport=config.transport,
                reachable=reachable,
                tools=per_server.get(config.name, 0),
                error="" if reachable else self._last_error,
                circuit_open=self._breaker.is_open,
            )
            for config in self._servers.values()
        ]

    @property
    def last_error(self) -> str:
        """Motivo da ultima falha de conexao."""
        return self._last_error


def _server_of(tool: Any) -> str:
    metadata = getattr(tool, "metadata", None) or {}
    if isinstance(metadata, dict):
        for key in ("server_name", "server", "mcp_server"):
            value = metadata.get(key)
            if value:
                return str(value)
    return ""


def _schema_of(tool: Any) -> dict[str, Any]:
    try:
        schema = getattr(tool, "args_schema", None)
        if isinstance(schema, dict):
            return dict(schema)
        if schema is not None:
            return schema.model_json_schema()
        return {"type": "object", "properties": getattr(tool, "args", {}) or {}}
    except Exception:
        return {"type": "object", "properties": {}}
