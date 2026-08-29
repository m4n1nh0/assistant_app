"""Persistencia e retomada do grafo.

O fluxo do chat ja tinha retomada - a interface reenviava a conversa inteira e o
backend recomecava do zero. Isso funciona ate a execucao ter custado uma busca
vetorial, tres chamadas de modelo e uma ferramenta: refazer tudo e pagar de
novo pelo que ja tinha dado certo.

Com checkpointer, o LangGraph grava o estado a cada passo e sabe retomar do
ponto de parada. O `thread_id` e a sessao de conversa, o que da idempotencia
natural: reenviar a mesma execucao encontra o checkpoint em vez de gerar outra.

O padrao e memoria, e nao um banco: o backend roda na maquina do usuario, e
exigir mais uma dependencia para uma retomada que quase sempre acontece dentro
da mesma sessao seria custo sem retorno. Quem precisa sobreviver a restart liga
`CHECKPOINT_BACKEND=sqlite`.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from loguru import logger


class BoundedMemorySaver(InMemorySaver):
    """`InMemorySaver` com teto de conversas retidas.

    O checkpointer em memoria do LangGraph guarda tudo e **nunca descarta nada** -
    a propria documentacao dele diz que serve para depuracao e teste. Num backend
    que roda por dias, cada mensagem deixa um punhado de checkpoints com uma copia
    do estado (historico, prompt, respostas), e a memoria so cresce.

    Aqui as conversas entram numa fila de uso: gravar ou ler renova a posicao, e
    ao passar do teto a mais antiga e descartada inteira. Isso preserva o que a
    retomada realmente usa - as conversas recentes - e joga fora o que ninguem
    vai retomar.
    """

    def __init__(self, *, max_threads: int = 200, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._max_threads = max(1, max_threads)
        self._recent: OrderedDict[str, None] = OrderedDict()

    # --- controle de retencao ---------------------------------------------

    @staticmethod
    def _thread_of(config: Any) -> str:
        try:
            return str((config or {}).get("configurable", {}).get("thread_id") or "")
        except AttributeError:
            return ""

    def _touch(self, config: Any) -> None:
        thread_id = self._thread_of(config)
        if not thread_id:
            return
        self._recent.pop(thread_id, None)
        self._recent[thread_id] = None
        while len(self._recent) > self._max_threads:
            oldest, _ = self._recent.popitem(last=False)
            self._evict(oldest)

    def _evict(self, thread_id: str) -> None:
        """Descarta os tres armazenamentos daquela conversa.

        `storage` e indexado pelo id direto; `writes` e `blobs` por tupla que
        comeca com ele. Limpar so o primeiro deixaria os outros dois crescendo.
        """
        self.storage.pop(thread_id, None)
        for store in (self.writes, self.blobs):
            for key in [k for k in store if isinstance(k, tuple) and k and k[0] == thread_id]:
                store.pop(key, None)

    @property
    def retained_threads(self) -> int:
        """Quantas conversas estao retidas neste momento."""
        return len(self._recent)

    # --- pontos de entrada do checkpointer --------------------------------

    def put(self, config, checkpoint, metadata, new_versions):
        """Grava um checkpoint e renova a posicao da conversa na fila."""
        result = super().put(config, checkpoint, metadata, new_versions)
        self._touch(config)
        return result

    async def aput(self, config, checkpoint, metadata, new_versions):
        """Versao assincrona de `put`."""
        result = await super().aput(config, checkpoint, metadata, new_versions)
        self._touch(config)
        return result

    def get_tuple(self, config):
        """Le um checkpoint e renova a posicao da conversa na fila."""
        self._touch(config)
        return super().get_tuple(config)

    async def aget_tuple(self, config):
        """Versao assincrona de `get_tuple`."""
        self._touch(config)
        return await super().aget_tuple(config)


def build_checkpointer(
    backend: str,
    *,
    sqlite_path: str = "",
    max_threads: int = 200,
) -> Any | None:
    """Monta o checkpointer configurado.

    Args:
        backend: `memory`, `sqlite` ou `none`.
        sqlite_path: arquivo usado pelo backend `sqlite`.
        max_threads: teto de conversas retidas pelo backend em memoria.

    Returns:
        O checkpointer, ou `None` quando a persistencia esta desligada. Backend
        indisponivel cai para memoria com aviso, nunca impede o boot.
    """
    choice = (backend or "memory").strip().lower()
    if choice in ("none", "off", "disabled"):
        return None

    if choice == "sqlite":
        saver = _sqlite_saver(sqlite_path)
        if saver is not None:
            return saver
        logger.warning(
            "CHECKPOINT_BACKEND=sqlite indisponivel; usando memoria limitada. "
            "Instale langgraph-checkpoint-sqlite e aponte "
            "CHECKPOINT_SQLITE_PATH para um volume persistente."
        )

    return BoundedMemorySaver(max_threads=max_threads)


def _sqlite_saver(sqlite_path: str) -> Any | None:
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    except ImportError:
        return None

    try:
        path = Path(sqlite_path or "data/checkpoints.sqlite")
        path.parent.mkdir(parents=True, exist_ok=True)
        import aiosqlite

        connection = aiosqlite.connect(str(path))
        return AsyncSqliteSaver(connection)
    except Exception as exc:
        logger.warning(f"Checkpoint sqlite indisponivel: {exc}")
        return None


def thread_config(
    *,
    conversation_id: str,
    tenant_id: str = "",
    execution_id: str = "",
) -> dict[str, Any]:
    """Monta o `config` que identifica a linha de execucao no checkpointer.

    O dono dos dados entra **dentro do `thread_id`**, e nao em `checkpoint_ns`:
    esse campo e reservado pelo LangGraph para o namespace de subgrafos, e
    usa-lo como namespace de conta faz a leitura do estado procurar um subgrafo
    que nao existe. Compondo a chave, duas contas com o mesmo identificador de
    sessao continuam separadas sem desviar o significado do campo.

    Args:
        conversation_id: sessao de chat.
        tenant_id: perfil dono da conversa.
        execution_id: identificador desta passagem, propagado para o trace.

    Returns:
        O dicionario de configuracao aceito por `ainvoke`.
    """
    thread = conversation_id or "sem-sessao"
    return {
        "configurable": {
            "thread_id": f"{tenant_id}:{thread}" if tenant_id else thread,
            "execution_id": execution_id,
        }
    }
