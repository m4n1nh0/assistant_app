"""Um catalogo por maquina conectada, isolado dos demais.

As capacidades publicadas por um usuario **nao podem** aparecer para outro: os
nomes se repetem entre maquinas (`local_run_script` existe em todas), e um
catalogo unico faria a segunda conexao sobrescrever a primeira - e a conversa de
um usuario dispararia um script na maquina de outro.

Por isso cada maquina tem o proprio `ToolRegistry`. O isolamento fica estrutural:
nao existe filtro para esquecer de aplicar, porque o catalogo do vizinho nao esta
no mesmo lugar.

Qual maquina vale na requisicao atual sai de um `ContextVar`, como ja acontece
com o runtime de LLM por conta em `user_llm_config_service`: o canal WebSocket
amarra a sessao no inicio e solta no fim, e o codigo assincrono no meio nao
precisa carregar o id de maquina por parametro ate o executor.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Iterator

from loguru import logger

from ..ports.tools import ToolDescriptor
from ..toolkit.executor import ToolExecutor
from ..toolkit.registry import RegisteredTool, ToolRegistry
from .client_capability_service import (
    ClientManifest,
    register_client_capabilities,
)

_current_device: ContextVar[str] = ContextVar("current_device", default="")


def bind_device(device_id: str) -> Token:
    """Amarra a maquina desta requisicao. Devolve o token para desfazer."""
    return _current_device.set(device_id or "")


def reset_device(token: Token) -> None:
    """Desfaz o `bind_device`, restaurando o valor anterior."""
    _current_device.reset(token)


def current_device() -> str:
    """A maquina da requisicao atual, ou vazio quando nao ha nenhuma."""
    return _current_device.get()


def device_key(user_id: str, session_id: str) -> str:
    """O id de uma maquina.

    Definido num lugar so porque duas portas escrevem a mesma chave: o
    WebSocket, que registra o catalogo, e a rota HTTP do chat, que precisa
    encontrar aquele mesmo catalogo. Se as duas divergirem, a capacidade e
    publicada e nunca encontrada.
    """
    return f"{user_id}:{session_id or 'default'}"


@contextmanager
def session_device(user_id: str, session_id: str) -> Iterator[str]:
    """Amarra a maquina de uma sessao pelo tempo de uma requisicao."""
    key = device_key(user_id, session_id)
    token = bind_device(key)
    try:
        yield key
    finally:
        reset_device(token)


class DeviceCatalog:
    """Os catalogos das maquinas conectadas, um por dispositivo."""

    def __init__(self, *, default_timeout: float = 90.0) -> None:
        self._registries: dict[str, ToolRegistry] = {}
        self._executors: dict[str, ToolExecutor] = {}
        self._default_timeout = default_timeout

    def publish(
        self,
        manifest: ClientManifest,
        runner_factory: Any,
        *,
        timeout_seconds: float | None = None,
    ) -> int:
        """Substitui o catalogo daquela maquina pelo que ela acabou de declarar."""
        registry = ToolRegistry()
        published = register_client_capabilities(
            registry,
            manifest,
            runner_factory,
            timeout_seconds=timeout_seconds,
        )
        self._registries[manifest.device_id] = registry
        self._executors[manifest.device_id] = ToolExecutor(
            registry,
            default_timeout=timeout_seconds or self._default_timeout,
            # Sem repeticao automatica: a ferramenta ja atravessa a rede e o
            # usuario; o que e seguro repetir o proprio gateway remoto decide.
            max_retries=0,
        )
        logger.info(f"Maquina {manifest.device_id} publicou {published} capacidades")
        return published

    def drop(self, device_id: str) -> int:
        """Esquece a maquina que desconectou."""
        registry = self._registries.pop(device_id, None)
        self._executors.pop(device_id, None)
        return len(registry) if registry else 0

    def descriptors(
        self,
        device_id: str = "",
        *,
        agent_id: str = "",
    ) -> list[ToolDescriptor]:
        """As capacidades de uma maquina, filtradas pelo escopo do agente."""
        registry = self._registries.get(device_id or current_device())
        if registry is None:
            return []
        return registry.descriptors(agent_id=agent_id)

    def find(self, name: str, device_id: str = "") -> RegisteredTool | None:
        """Procura uma ferramenta no catalogo de uma maquina."""
        registry = self._registries.get(device_id or current_device())
        return registry.get(name) if registry else None

    def executor(self, device_id: str = "") -> ToolExecutor | None:
        """O executor daquela maquina, ja governando o catalogo dela."""
        return self._executors.get(device_id or current_device())

    def devices(self) -> list[str]:
        """As maquinas com catalogo publicado agora."""
        return sorted(self._registries)

    def __len__(self) -> int:
        return len(self._registries)


_catalog: DeviceCatalog | None = None


def get_device_catalog() -> DeviceCatalog:
    """O catalogo de maquinas deste processo."""
    global _catalog
    if _catalog is None:
        _catalog = DeviceCatalog()
    return _catalog


def reset_device_catalog() -> None:
    """Descarta os catalogos. Usado nos testes."""
    global _catalog
    _catalog = None
