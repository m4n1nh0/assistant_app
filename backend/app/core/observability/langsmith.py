"""Integracao opcional com o LangSmith.

O LangSmith enxerga bem o que e especifico de IA - prompt, resposta, cadeia,
passo de agente, avaliacao. Ele **complementa** a observabilidade da aplicacao,
que continua sendo a fonte de verdade para latencia de rota, falha de servico e
custo agregado.

A ativacao e por variavel de ambiente e sem chave nao acontece nada: o projeto
nao pode exigir conta em servico externo para rodar localmente.
"""

from __future__ import annotations

import os

from loguru import logger


def setup(
    *,
    enabled: bool,
    api_key: str,
    project: str,
    endpoint: str = "",
) -> bool:
    """Liga o tracing do LangChain/LangGraph para o LangSmith.

    Configura as variaveis que o proprio `langsmith` le, em vez de instanciar um
    cliente: assim qualquer componente LangChain do processo passa a exportar
    sem receber callback explicito.

    Args:
        enabled: chave mestra vinda da configuracao.
        api_key: credencial do LangSmith.
        project: projeto que recebe os traces.
        endpoint: endpoint alternativo, para instalacao propria.

    Returns:
        `True` quando ficou ativo.
    """
    if not enabled:
        os.environ["LANGSMITH_TRACING"] = "false"
        return False
    if not api_key:
        logger.warning(
            "LANGSMITH_ENABLED ligado sem LANGSMITH_API_KEY: tracing de IA "
            "segue desligado."
        )
        os.environ["LANGSMITH_TRACING"] = "false"
        return False

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = api_key
    os.environ["LANGSMITH_PROJECT"] = project or "assistant-app"
    if endpoint:
        os.environ["LANGSMITH_ENDPOINT"] = endpoint
    logger.info(f"LangSmith ativo no projeto {os.environ['LANGSMITH_PROJECT']}")
    return True


def enabled() -> bool:
    """Diz se o tracing para o LangSmith esta ligado neste processo."""
    return os.environ.get("LANGSMITH_TRACING", "").lower() == "true"
