"""Contrato de Tool Calling: catalogo e execucao governada de ferramentas.

Tool Calling e o **mecanismo** pelo qual um agente escolhe e dispara uma
capacidade. Nao e o protocolo de transporte dessa capacidade: uma ferramenta
pode ser uma funcao local ou pode falar MCP por baixo, e o agente nao precisa
saber a diferenca. Por isso `ToolDescriptor.source` existe - para *registrar* a
origem em auditoria e trace - e nao para o agente ramificar por ela.

O agente nunca executa codigo de ferramenta: ele monta uma `ToolInvocation` e
entrega ao gateway, que valida, autoriza, aplica timeout, tenta de novo quando
cabe e devolve `ToolResult` normalizado.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

ToolSource = Literal["local", "mcp", "remote"]


@dataclass(frozen=True)
class ToolDescriptor:
    """Uma ferramenta publicada no catalogo.

    Attributes:
        name: identificador unico no registry.
        description: o que ela faz, em texto que vai para o modelo.
        args_schema: JSON Schema dos argumentos aceitos.
        source: de onde a capacidade vem (local, mcp ou remote).
        server: servidor MCP de origem, quando a origem e mcp.
        scopes: quais agentes podem disparar. Vazio significa **nenhum**:
            a ferramenta existe no catalogo e pode ser chamada pelo grafo
            sem agente atribuido, mas nao entra na lista que vai para o
            modelo. Negar por omissao evita que uma ferramenta nova
            apareca para todos os agentes so por ter sido registrada.
        timeout_seconds: teto proprio, quando difere do teto global.
        read_only: True quando a ferramenta so monta proposta, sem efeito.
    """

    name: str
    description: str = ""
    args_schema: dict[str, Any] = field(default_factory=dict)
    source: ToolSource = "local"
    server: str = ""
    scopes: tuple[str, ...] = ()
    timeout_seconds: float | None = None
    read_only: bool = True

    def allowed_for(self, agent_id: str) -> bool:
        """Diz se um agente pode disparar esta ferramenta.

        Chamada sem agente (`agent_id` vazio) e uso interno do grafo, que
        invoca o construtor de acao diretamente sem passar pelo modelo; nesse
        caso o escopo nao se aplica.
        """
        if not agent_id:
            return True
        return agent_id in self.scopes


@dataclass(frozen=True)
class ToolPrincipal:
    """De quem sao os dados que esta execucao pode alcancar.

    Existe por uma razao de seguranca, nao de conveniencia: ferramenta que le o
    banco precisa saber de qual tutor ler, e esse dado **nao pode** chegar como
    argumento do modelo. Argumento e conteudo gerado a partir da conversa; quem
    conseguisse escrever "liste as questoes do tutor X" faria o modelo preencher
    o campo e leria dado alheio. O principal e preenchido pelo grafo com a
    identidade autenticada da requisicao e viaja fora de `args`.

    Attributes:
        tutor_id: perfil de dados dono da conversa.
        user_id: conta autenticada que fez o pedido.
    """

    tutor_id: str = ""
    user_id: str = ""

    def identified(self) -> bool:
        """Diz se ha um dono de dados definido para esta execucao."""
        return bool(self.tutor_id)


@dataclass(frozen=True)
class ToolInvocation:
    """Um pedido de execucao, ja atribuido a um agente."""

    name: str
    args: dict[str, Any] = field(default_factory=dict)
    agent_id: str = ""
    timeout_seconds: float | None = None
    call_id: str = ""
    #: Identidade dona dos dados, preenchida pelo grafo - nunca pelo modelo.
    principal: ToolPrincipal = field(default_factory=ToolPrincipal)


@dataclass(frozen=True)
class ToolResult:
    """O resultado normalizado de uma execucao.

    Falha vira `ok=False` com `error` preenchido, e nao excecao. O agente
    precisa poder mostrar ao modelo que a ferramenta falhou e seguir a conversa;
    excecao subindo mataria a resposta inteira por causa de uma ferramenta.
    """

    name: str
    ok: bool
    output: Any = None
    error: str = ""
    duration_ms: float = 0.0
    source: ToolSource = "local"
    retries: int = 0
    call_id: str = ""

    def as_text(self, *, limit: int = 4000) -> str:
        """Texto que volta para o modelo como resultado da ferramenta.

        Ferramenta que le dados devolve um envelope com `text` ja redigido: o
        modelo recebe a leitura em portugues em vez do `repr` de um dicionario,
        que ele costuma copiar cru para a resposta.
        """
        if not self.ok:
            return str(self.error)[:limit]
        body = self.output
        if isinstance(body, Mapping) and isinstance(body.get("text"), str):
            return body["text"][:limit]
        return str(body)[:limit]

    def data(self) -> dict[str, Any] | None:
        """A leitura estruturada, quando a ferramenta devolveu uma.

        E o que a interface desenha como resultado para o usuario decidir. O
        `kind` e o que distingue um envelope de dados de uma saida qualquer:
        sem ele, nao ha card a montar e so o texto segue para o modelo.
        """
        body = self.output
        if not self.ok or not isinstance(body, Mapping):
            return None
        if not body.get("kind"):
            return None
        return dict(body)


class ToolError(Exception):
    """Falha de execucao de ferramenta ja classificada."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class ToolNotFound(ToolError):
    """A ferramenta pedida nao existe no catalogo."""


class ToolNotAllowed(ToolError):
    """A ferramenta existe, mas nao esta no escopo do agente."""


class ToolTimeout(ToolError):
    """A ferramenta estourou o tempo maximo de execucao."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


@runtime_checkable
class ToolGateway(Protocol):
    """Como o dominio fala com o Tool Service, local ou remoto."""

    async def list_tools(self, *, agent_id: str = "") -> list[ToolDescriptor]:
        """Ferramentas visiveis para um agente."""
        ...

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        """Executa uma ferramenta e devolve o resultado normalizado."""
        ...

    async def health(self) -> dict[str, Any]:
        """Estado do servico de ferramentas, para diagnostico."""
        ...
