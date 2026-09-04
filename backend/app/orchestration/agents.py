"""Registro dos especialistas: dado puro, sem dependencia de framework.

Este modulo descreve **quem** atende e **o que** cada um pode usar. Ele nao
importa LangChain, LangGraph, MCP nem cliente HTTP de proposito: e o nucleo que
o grafo, o catalogo de ferramentas e os testes consultam, e todos os tres
quebrariam junto se ele carregasse um SDK.

A separacao tambem resolve um ciclo real: o catalogo de ferramentas precisa
saber quais agentes podem usar cada ferramenta, e o agente precisa saber quais
ferramentas existem. Com a declaracao isolada aqui, os dois leem a mesma fonte
sem se importarem mutuamente.
"""

from __future__ import annotations

from dataclasses import dataclass

HANDOFF_TOOL_NAME = "transfer_to_agent"
DEFAULT_SPECIALIST = "general"


@dataclass(frozen=True)
class Specialist:
    """Um agente especialista: papel, instrucoes proprias e ferramentas permitidas.

    Attributes:
        id: identificador usado em roteamento, handoff e trace.
        label: nome de exibicao na interface.
        description: usada no catalogo de destinos de transferencia.
        instructions: instrucao de sistema especifica deste papel.
        routing_task: tarefa que este especialista atende, para escolher provedor.
        tool_names: ferramentas locais liberadas para ele.
        use_mcp: se ele tambem recebe as capacidades expostas por MCP.
    """

    id: str
    label: str
    description: str
    instructions: str
    routing_task: str
    tool_names: tuple[str, ...] = ()
    use_mcp: bool = False


SPECIALISTS: dict[str, Specialist] = {
    "general": Specialist(
        id="general",
        label="Generalista",
        description="conversa geral, duvidas amplas e pedidos que nao se "
                    "encaixam nas outras especialidades",
        instructions=(
            "Voce e o agente generalista. Responda de forma direta e pratica. "
            "Se o pedido for claramente de codigo, de aulas gravadas ou de "
            "agenda, transfira para o agente correspondente em vez de "
            "responder por conta propria."
        ),
        routing_task="general",
        use_mcp=True,
    ),
    "code": Specialist(
        id="code",
        label="Codigo",
        description="programacao, leitura de workspace, scripts, erros e "
                    "revisao de codigo",
        instructions=(
            "Voce e o agente de codigo. Trabalhe com o contexto real do "
            "workspace quando ele estiver na mensagem e proponha passos "
            "pequenos e verificaveis. Nao execute nada: proponha e deixe a "
            "interface confirmar."
        ),
        routing_task="code",
        # `propose_coding_action` e `propose_computer_action` sairam daqui: a
        # capacidade real chega pelo catalogo que a maquina publica
        # (`local_inspect_workspace`, `local_network_diagnostics`, ...), e essa
        # sim executa. As `propose_*` apenas montam a proposta, e proposta
        # criada dentro do loop do agente nao chega na interface - o `action`
        # da resposta so e escrito por `detect_action`. Deixa-las visiveis para
        # o modelo era oferecer um caminho que termina em nada.
        tool_names=("propose_project_action",),
        use_mcp=True,
    ),
    "study": Specialist(
        id="study",
        label="Estudos",
        description="aulas gravadas, materias, resumos e conteudo de estudo",
        instructions=(
            "Voce e o agente de estudos. Responda com base nos trechos de aula "
            "fornecidos no contexto, citando disciplina e data. Se os trechos "
            "nao cobrirem a pergunta, diga o que falta em vez de supor."
        ),
        routing_task="study",
    ),
    "calendar": Specialist(
        id="calendar",
        label="Agenda",
        description="compromissos, reunioes, eventos e disponibilidade",
        instructions=(
            "Voce e o agente de agenda. Trate datas e horarios com precisao e "
            "confirme o que ficou entendido antes de propor um evento."
        ),
        routing_task="calendar",
        tool_names=("propose_calendar_event",),
    ),
}

_TASK_TO_SPECIALIST = {
    "code": "code",
    "study": "study",
    "calendar": "calendar",
    "general": "general",
}


def select_specialist(task: str) -> Specialist:
    """Escolhe o especialista que atende a tarefa.

    Args:
        task: tipo de tarefa detectado na mensagem.

    Returns:
        O especialista escolhido, com instrucoes e ferramentas dele.
    """
    return SPECIALISTS[_TASK_TO_SPECIALIST.get(task, DEFAULT_SPECIALIST)]


def scopes_for_tool(tool_name: str) -> tuple[str, ...]:
    """Quais especialistas podem usar uma ferramenta local.

    E daqui que o catalogo tira a autorizacao, entao liberar uma ferramenta para
    um agente novo e so declara-la no `tool_names` dele.
    """
    return tuple(
        specialist.id
        for specialist in SPECIALISTS.values()
        if tool_name in specialist.tool_names
    )


def mcp_scopes() -> tuple[str, ...]:
    """Especialistas autorizados a usar capacidades vindas de MCP."""
    return tuple(
        specialist.id for specialist in SPECIALISTS.values() if specialist.use_mcp
    )


def handoff_targets(current: str) -> list[Specialist]:
    """Destinos validos de transferencia a partir de um especialista."""
    return [item for item in SPECIALISTS.values() if item.id != current]
