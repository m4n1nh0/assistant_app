"""Contrato da orquestracao: quem roda o grafo do chat para um turno.

A assistant-api recebe a mensagem, autentica, monta persona e historico - e
entrega o resto a este contrato. Se o grafo roda no mesmo processo ou no
agent-orchestrator e decisao de `ORCHESTRATOR_TRANSPORT`, como ja acontece com
ferramentas e MCP.

O turno carrega apenas o que e **dado**: texto, historico, provedores
disponiveis, identificadores. O que e **segredo** (chave de provedor) fica de
fora de proposito - cada lado a obtem do banco pelo `tutor_id`, e nenhuma chave
decifrada atravessa a rede.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..models.schemas import Message, ResponseModeEnum


@dataclass(frozen=True)
class ChatTurn:
    """Uma mensagem pronta para passar pelo grafo.

    Attributes:
        message: pergunta do usuario.
        history: historico da conversa.
        mode: `single`, `multi` ou `chain`.
        requested_llm: provedor pedido; `None` deixa o roteamento decidir.
        active_llms: provedores disponiveis, avaliados pela API.
        system_prompt: persona e contexto ja montados.
        tutor_id: perfil de dados dono da conversa e das credenciais.
        user_id: conta autenticada.
        timezone: fuso do usuario.
        conversation_id: sessao; e o `thread_id` do checkpoint.
        execution_id: identificador desta passagem; gerado quando vazio.
        device_id: maquina amarrada a sessao, cujas capacidades o agente pode
            usar. Vazio quando a interface nao esta conectada.
    """

    message: str
    history: list[Message] = field(default_factory=list)
    mode: ResponseModeEnum = ResponseModeEnum.single
    requested_llm: str | None = None
    active_llms: tuple[str, ...] = ()
    system_prompt: str = ""
    tutor_id: str = ""
    user_id: str = ""
    timezone: str = "America/Sao_Paulo"
    conversation_id: str = ""
    execution_id: str = ""
    device_id: str = ""

    def graph_kwargs(self) -> dict[str, Any]:
        """Argumentos de `run_chat_graph`, sem o que e so de transporte."""
        return {
            "message": self.message,
            "history": list(self.history),
            "mode": self.mode,
            "requested_llm": self.requested_llm,
            "active_llms": list(self.active_llms),
            "system_prompt": self.system_prompt,
            "tutor_id": self.tutor_id,
            "user_id": self.user_id,
            "timezone": self.timezone,
            "conversation_id": self.conversation_id,
            "execution_id": self.execution_id,
        }


@runtime_checkable
class OrchestrationGateway(Protocol):
    """Como a API entrega um turno ao grafo, in-process ou pelo orquestrador."""

    async def run_chat(self, turn: ChatTurn) -> dict[str, Any]:
        """Roda o grafo e devolve o estado final.

        Falha de transporte nao sobe como excecao: vira resposta com
        `is_error`, igual a falha do proprio grafo, para a rota responder ao
        usuario em vez de devolver 500.
        """
        ...

    async def health(self) -> dict[str, Any]:
        """Estado de quem roda o grafo, para diagnostico."""
        ...
