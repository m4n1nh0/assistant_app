"""Composicao das dependencias: onde a configuracao vira implementacao.

Este e o unico modulo que sabe, ao mesmo tempo, qual e a configuracao e quais
implementacoes existem. Agente, no de grafo e servico de dominio pedem o
gateway aqui e recebem uma abstracao - por isso trocar in-process por remoto e
mudar `TOOL_TRANSPORT`, `MCP_TRANSPORT` ou `ORCHESTRATOR_TRANSPORT`, sem tocar
em regra de negocio.

As instancias sao preguicosas e memorizadas por processo: montar o catalogo lê
o modulo de ferramentas, e fazer isso em tempo de import criaria dependencia
circular com os servicos que as ferramentas usam.
"""

from __future__ import annotations

from loguru import logger

from ..core.config import get_settings
from shared.ports.mcp import MCPGateway
from ..ports.orchestration import OrchestrationGateway
from ..ports.retrieval import RetrievalGateway
from shared.ports.tools import ToolGateway

_mcp_gateway: MCPGateway | None = None
_tool_gateway: ToolGateway | None = None
_retrieval_gateway: RetrievalGateway | None = None
_orchestration_gateway: OrchestrationGateway | None = None


def get_mcp_gateway() -> MCPGateway:
    """A porta de acesso ao MCP deste processo."""
    global _mcp_gateway
    if _mcp_gateway is None:
        _mcp_gateway = _build_mcp_gateway()
    return _mcp_gateway


def get_tool_gateway() -> ToolGateway:
    """A porta de acesso ao catalogo de ferramentas deste processo."""
    global _tool_gateway
    if _tool_gateway is None:
        _tool_gateway = _build_tool_gateway()
    return _tool_gateway


def get_retrieval_gateway() -> RetrievalGateway:
    """A porta de acesso a busca semantica deste processo."""
    global _retrieval_gateway
    if _retrieval_gateway is None:
        from .retrieval.lesson_retriever import LessonRetrievalGateway

        _retrieval_gateway = LessonRetrievalGateway()
    return _retrieval_gateway


def get_orchestration_gateway() -> OrchestrationGateway:
    """A porta pela qual a API entrega um turno ao grafo do chat."""
    global _orchestration_gateway
    if _orchestration_gateway is None:
        _orchestration_gateway = _build_orchestration_gateway()
    return _orchestration_gateway


def override(
    *,
    mcp: MCPGateway | None = None,
    tools: ToolGateway | None = None,
    retrieval: RetrievalGateway | None = None,
    orchestration: OrchestrationGateway | None = None,
) -> None:
    """Substitui implementacoes, para teste e para o modo de desenvolvimento.

    Passar `None` num campo mantem o que ja estava; use `reset()` para voltar
    tudo ao que a configuracao manda.
    """
    global _mcp_gateway, _tool_gateway, _retrieval_gateway, _orchestration_gateway
    if mcp is not None:
        _mcp_gateway = mcp
    if tools is not None:
        _tool_gateway = tools
    if retrieval is not None:
        _retrieval_gateway = retrieval
    if orchestration is not None:
        _orchestration_gateway = orchestration


def reset() -> None:
    """Descarta as instancias, forcando releitura da configuracao."""
    global _mcp_gateway, _tool_gateway, _retrieval_gateway, _orchestration_gateway
    _mcp_gateway = None
    _tool_gateway = None
    _retrieval_gateway = None
    _orchestration_gateway = None


def build_mcp_client():
    """Cria o `MCPClient` deste processo com a configuracao da API.

    A construcao mora em `shared.mcp.factory`, a mesma que o mcp-service usa,
    para os dois terem exatamente o mesmo timeout, retry e disjuntor.
    """
    from shared.mcp.factory import build_mcp_client as build

    return build(get_settings())


def build_local_tool_gateway(
    *,
    mcp: MCPGateway | None = None,
    product_tools: bool = False,
) -> ToolGateway:
    """Monta o gateway local completo: registry, executor e MCP acoplado.

    O tool-service usa a mesma funcao, e e isso que garante que rodar o catalogo
    fora do processo nao muda a regra de execucao.

    Args:
        mcp: porta de acesso ao MCP; `None` usa a do processo.
        product_tools: inclui as ferramentas de leitura do produto, que falam
            com o banco. Fica desligado por padrao porque o tool-service chama
            esta mesma funcao e a imagem dele nao tem banco nem SQLAlchemy -
            ligar por engano la quebraria o servico no boot. Quem atende o chat
            liga explicitamente.
    """
    from ..toolkit.catalog import build_local_registry, build_product_registry
    from shared.toolkit.executor import ToolExecutor
    from .tools.local import LocalToolGateway

    settings = get_settings()
    registry = build_product_registry() if product_tools else build_local_registry()
    executor = ToolExecutor(
        registry,
        default_timeout=settings.tool_timeout_seconds,
        max_retries=settings.tool_max_retries,
        retry_backoff=settings.tool_retry_backoff_seconds,
    )
    return LocalToolGateway(
        registry,
        executor,
        mcp=mcp if mcp is not None else get_mcp_gateway(),
        mcp_timeout_seconds=settings.mcp_timeout_seconds,
    )


def _build_mcp_gateway() -> MCPGateway:
    settings = get_settings()
    if settings.uses_remote_mcp:
        from .mcp.remote import RemoteMCPGateway

        logger.info(f"MCP remoto em {settings.mcp_service_base_url}")
        return RemoteMCPGateway(
            settings.mcp_service_base_url,
            timeout_seconds=settings.mcp_timeout_seconds,
            max_retries=settings.mcp_max_retries,
            retry_backoff=settings.mcp_retry_backoff_seconds,
        )

    from .mcp.local import LocalMCPGateway

    return LocalMCPGateway(build_mcp_client())


def _build_tool_gateway() -> ToolGateway:
    settings = get_settings()
    if settings.uses_remote_tools:
        from .tools.remote import RemoteToolGateway

        logger.info(f"Tool service remoto em {settings.tool_service_base_url}")
        return RemoteToolGateway(
            settings.tool_service_base_url,
            timeout_seconds=settings.tool_timeout_seconds,
            max_retries=settings.tool_max_retries,
            retry_backoff=settings.tool_retry_backoff_seconds,
            # As ferramentas que leem o banco ficam neste processo mesmo com o
            # catalogo remoto, pelo mesmo motivo das capacidades da maquina do
            # usuario: elas nao existem do outro lado. Sem isso, ligar
            # TOOL_TRANSPORT=remote tirava do agente o acesso ao cadastro sem
            # erro nenhum - ele so voltaria a dizer que nao tem acesso.
            local=build_local_tool_gateway(product_tools=True),
        )

    return build_local_tool_gateway(product_tools=True)


def _build_orchestration_gateway() -> OrchestrationGateway:
    settings = get_settings()
    if settings.uses_remote_orchestrator:
        from .orchestration.remote import RemoteOrchestrationGateway

        if not settings.internal_service_token.strip():
            # O orquestrador recusa turno sem token; avisar aqui poupa o
            # diagnostico de "chat sempre responde erro" sem mensagem util.
            logger.error(
                "ORCHESTRATOR_TRANSPORT=remote sem INTERNAL_SERVICE_TOKEN: "
                "o agent-orchestrator vai recusar os turnos"
            )
        logger.info(f"Orquestrador remoto em {settings.orchestrator_base_url}")
        return RemoteOrchestrationGateway(
            settings.orchestrator_base_url,
            token=settings.internal_service_token,
            timeout_seconds=settings.orchestrator_timeout_seconds,
            max_retries=settings.orchestrator_max_retries,
        )

    from .orchestration.local import LocalOrchestrationGateway

    return LocalOrchestrationGateway()
