"""De quem sao os dados que a ferramenta em execucao pode ler.

O executor publica aqui o `ToolPrincipal` da invocacao, e a ferramenta le com
`current_principal()`. E um `ContextVar` pelo mesmo motivo que os
identificadores de correlacao sao: a identidade precisa alcancar o fundo da
pilha sem virar parametro de toda funcao no caminho, e sem entrar em `args` --
onde o modelo escreve.

Nao reaproveitamos o `tenant_id` que ja existe no contexto de observabilidade.
Aquele contexto existe para *observar*, e e montado por middleware de trace;
transformar o campo de um log em fronteira de autorizacao faria a seguranca
depender de a instrumentacao estar ligada e correta. Sao dois planos, e so um
deles pode negar leitura.

`require_principal()` levanta quando nao ha dono definido. A escolha e
deliberada: ferramenta de dado sem identidade nao deve cair para "le tudo" nem
para "le nada em silencio" -- deve falhar alto, e o executor transforma isso em
`ToolResult(ok=False)` que o modelo consegue explicar ao usuario.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from shared.ports.tools import ToolError, ToolPrincipal

_PRINCIPAL: ContextVar[ToolPrincipal] = ContextVar(
    "tool_principal", default=ToolPrincipal()
)


def current_principal() -> ToolPrincipal:
    """O dono dos dados desta execucao; vazio fora de uma invocacao."""
    return _PRINCIPAL.get()


def require_principal() -> ToolPrincipal:
    """O dono dos dados, exigindo que exista.

    Raises:
        ToolError: quando a execucao chegou sem identidade, o que significa que
            alguem chamou a ferramenta por um caminho que nao passa pelo grafo
            autenticado.
    """
    principal = _PRINCIPAL.get()
    if not principal.identified():
        raise ToolError(
            "esta ferramenta le dados de uma conta e a execucao chegou sem "
            "identidade; ela so roda pelo chat autenticado",
            retryable=False,
        )
    return principal


@contextmanager
def use_principal(principal: ToolPrincipal) -> Iterator[ToolPrincipal]:
    """Publica o dono dos dados enquanto a ferramenta roda."""
    token = _PRINCIPAL.set(principal)
    try:
        yield principal
    finally:
        _PRINCIPAL.reset(token)
