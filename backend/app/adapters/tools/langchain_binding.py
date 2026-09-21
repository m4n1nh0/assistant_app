"""Traducao do catalogo para o formato que o LangChain e o LangGraph consomem.

O `ToolNode` do LangGraph executa `BaseTool`. O catalogo, por outro lado, fala
`ToolDescriptor`/`ToolInvocation` justamente para nao amarrar o dominio ao SDK.
Este modulo e a costura entre os dois: monta `BaseTool` cuja corrotina apenas
delega ao gateway.

O efeito e o que a arquitetura pede: o `ToolNode` faz a mecanica do LangChain
(mensagens de resultado, chamadas em paralelo), enquanto autorizacao, timeout,
retry e auditoria continuam dentro do Tool Service. Nenhum dos dois duplica o
trabalho do outro, e a mesma funcao serve tanto para o gateway local quanto
para o remoto.
"""

from __future__ import annotations

from typing import Any, Sequence

from langchain_core.tools import BaseTool, StructuredTool

from shared.ports.tools import (
    ToolDescriptor,
    ToolGateway,
    ToolInvocation,
    ToolPrincipal,
)


def to_langchain_tool(
    gateway: ToolGateway,
    descriptor: ToolDescriptor,
    *,
    agent_id: str = "",
    principal: ToolPrincipal | None = None,
) -> BaseTool:
    """Embrulha uma ferramenta do catalogo como `BaseTool`.

    Args:
        gateway: por onde a execucao passa.
        descriptor: contrato publico da ferramenta.
        agent_id: agente que vai dispara-la, usado na autorizacao e no trace.
        principal: dono dos dados desta requisicao. Fica preso na tool no
            momento em que ela e montada - uma tool por requisicao - em vez de
            sair de `kwargs`: `kwargs` e o que o modelo escreve, e de la nao
            pode sair a resposta de "dados de quem".

    Returns:
        Uma tool sincronizavel pelo LangChain, cuja execucao real acontece no
        gateway.
    """
    owner = principal or ToolPrincipal()

    async def _run(**kwargs: Any) -> tuple[str, Any]:
        result = await gateway.invoke(
            ToolInvocation(
                name=descriptor.name,
                args=dict(kwargs),
                agent_id=agent_id,
                principal=owner,
            )
        )
        # Dois destinos, um resultado: o texto alimenta o modelo e a leitura
        # estruturada viaja pelo `artifact` da ToolMessage ate a interface. Sem
        # esse segundo canal, mostrar a tabela na tela exigiria pedir ao modelo
        # que reescrevesse os dados - e o modelo erra numero.
        return result.as_text(), result.data()

    def _blocking(**kwargs: Any) -> str:
        # O caminho sincrono existe so porque `StructuredTool` exige um `func`.
        # A arquitetura e async-first: quem chamar por aqui esta contornando o
        # gateway e merece o erro explicito em vez de um `asyncio.run` escondido
        # que travaria o event loop.
        raise NotImplementedError(
            f"{descriptor.name} so executa pelo caminho assincrono do gateway"
        )

    return StructuredTool(
        name=descriptor.name,
        description=descriptor.description,
        args_schema=descriptor.args_schema or {"type": "object", "properties": {}},
        func=_blocking,
        coroutine=_run,
        response_format="content_and_artifact",
        metadata={
            "source": descriptor.source,
            "server": descriptor.server,
            "read_only": descriptor.read_only,
        },
    )


def to_langchain_tools(
    gateway: ToolGateway,
    descriptors: Sequence[ToolDescriptor],
    *,
    agent_id: str = "",
    principal: ToolPrincipal | None = None,
) -> list[BaseTool]:
    """Embrulha um conjunto de ferramentas do catalogo."""
    return [
        to_langchain_tool(
            gateway, descriptor, agent_id=agent_id, principal=principal
        )
        for descriptor in descriptors
    ]
