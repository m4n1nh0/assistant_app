"""A identidade do dono dos dados, da requisicao ate dentro da ferramenta.

Ferramenta que le o banco precisa saber de quem ler. A resposta **nao** pode
sair dos argumentos: argumento e o que o modelo escreve a partir da conversa, e
quem escrevesse "liste as questoes do tutor X" faria o modelo preencher o campo.
Por isso o `ToolPrincipal` viaja fora de `args`, preso na ferramenta no momento
em que ela e montada para aquela requisicao.

Estes testes guardam os dois lados desse caminho: que a identidade chega, e que
sem ela a leitura e recusada em vez de virar leitura de todo mundo.
"""

from __future__ import annotations

import asyncio

import pytest

from app.adapters.tools.langchain_binding import to_langchain_tool
from app.orchestration.agent_graph import AgentRuntimeContext
from app.services import agent_service as service
from shared.ports.tools import (
    ToolDescriptor,
    ToolError,
    ToolInvocation,
    ToolPrincipal,
    ToolResult,
)
from shared.toolkit.executor import ToolExecutor
from shared.toolkit.principal import current_principal, require_principal
from shared.toolkit.registry import ToolRegistry

pytestmark = pytest.mark.integration


def run(coro):
    return asyncio.run(coro)


class GatewayEspiao:
    """Guarda a invocacao que recebeu, para o teste olhar o que viajou."""

    def __init__(self, output=None) -> None:
        self.recebida: ToolInvocation | None = None
        self._output = output

    async def list_tools(self, *, agent_id: str = ""):
        return []

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        self.recebida = invocation
        return ToolResult(name=invocation.name, ok=True, output=self._output)

    async def health(self):
        return {"ok": True}


DESCRITOR = ToolDescriptor(
    name="education_search_question_bank",
    description="le o banco de questoes",
    args_schema={"type": "object", "properties": {"search": {"type": "string"}}},
    scopes=("study",),
)


def test_identidade_viaja_fora_dos_argumentos():
    gateway = GatewayEspiao()
    ferramenta = to_langchain_tool(
        gateway,
        DESCRITOR,
        agent_id="study",
        principal=ToolPrincipal(tutor_id="tutor-1", user_id="u1"),
    )

    run(ferramenta.ainvoke({"search": "normalizacao"}))

    assert gateway.recebida is not None
    assert gateway.recebida.principal.tutor_id == "tutor-1"
    # O ponto do desenho: o dono dos dados nao esta entre os argumentos, entao
    # nao ha campo para o modelo preencher.
    assert "tutor_id" not in gateway.recebida.args
    assert gateway.recebida.args == {"search": "normalizacao"}


def test_leitura_estruturada_volta_pela_artifact():
    """O texto alimenta o modelo; a leitura vai inteira para a interface."""
    gateway = GatewayEspiao(
        output={
            "kind": "question_bank",
            "text": "2 questoes encontradas",
            "items": [{"enunciado": "a"}, {"enunciado": "b"}],
            "total": 2,
        }
    )
    ferramenta = to_langchain_tool(gateway, DESCRITOR, agent_id="study")

    mensagem = run(ferramenta.ainvoke({
        "name": DESCRITOR.name,
        "args": {"search": ""},
        "id": "call_1",
        "type": "tool_call",
    }))

    assert mensagem.content == "2 questoes encontradas"
    assert mensagem.artifact["kind"] == "question_bank"
    assert len(mensagem.artifact["items"]) == 2


def test_executor_publica_a_identidade_para_a_ferramenta():
    """E o executor que torna `require_principal()` utilizavel la dentro."""
    vistos: list[str] = []

    async def runner(args):
        vistos.append(require_principal().tutor_id)
        return "ok"

    registry = ToolRegistry()
    registry.register(DESCRITOR, runner)
    executor = ToolExecutor(registry)

    resultado = run(executor.invoke(ToolInvocation(
        name=DESCRITOR.name,
        args={"search": ""},
        agent_id="study",
        principal=ToolPrincipal(tutor_id="tutor-9"),
    )))

    assert resultado.ok
    assert vistos == ["tutor-9"]
    # Terminada a execucao, a identidade nao fica pendurada no processo.
    assert current_principal().tutor_id == ""


def test_sem_identidade_a_falha_vira_resultado_e_nao_excecao():
    """O modelo precisa poder explicar a recusa, e nao ver a resposta morrer."""

    async def runner(args):
        require_principal()
        return "nao deveria chegar aqui"

    registry = ToolRegistry()
    registry.register(DESCRITOR, runner)
    executor = ToolExecutor(registry)

    resultado = run(executor.invoke(ToolInvocation(
        name=DESCRITOR.name, args={"search": ""}, agent_id="study"
    )))

    assert not resultado.ok
    assert "identidade" in resultado.error


def test_erro_de_identidade_nao_e_tentado_de_novo():
    """Repetir nao conserta: a identidade nao vai aparecer na segunda tentativa."""
    tentativas: list[int] = []

    async def runner(args):
        tentativas.append(1)
        raise ToolError("sem identidade", retryable=False)

    registry = ToolRegistry()
    registry.register(DESCRITOR, runner)
    executor = ToolExecutor(registry, max_retries=2)

    run(executor.invoke(ToolInvocation(name=DESCRITOR.name, args={"search": ""})))

    assert len(tentativas) == 1


def test_contexto_do_agente_carrega_o_tutor_da_requisicao(monkeypatch):
    """O `_tools_for` do grafo monta o principal a partir do contexto."""
    gateway = GatewayEspiao()

    async def lista(*, agent_id=""):
        return [DESCRITOR]

    gateway.list_tools = lista  # type: ignore[assignment]
    monkeypatch.setattr(service, "get_tool_gateway", lambda: gateway)

    tools = run(service._tools_for(
        service.SPECIALISTS["study"],
        False,
        AgentRuntimeContext(tutor_id="tutor-do-chat", user_id="u7"),
    ))
    run(tools[0].ainvoke({"search": ""}))

    assert gateway.recebida is not None
    assert gateway.recebida.principal.tutor_id == "tutor-do-chat"
    assert gateway.recebida.principal.user_id == "u7"
