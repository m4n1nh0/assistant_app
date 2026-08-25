"""Accessor for the shared Redis connection created in main.py's lifespan.

Other modules (e.g. llm_status_service) read from here instead of opening
their own connection. Stays None if Redis was never configured/reachable —
callers must treat that as "no cache available", not an error.
"""

_client = None


def set_client(client) -> None:
    """Guarda a conexao Redis criada no `lifespan` da aplicacao.

    Args:
        client: conexao pronta, ou `None` para limpar no shutdown.
    """
    global _client
    _client = client


def get_client():
    """Devolve a conexao Redis compartilhada.

    Returns:
        A conexao, ou `None` quando o Redis nao foi configurado ou nao respondeu -
        quem chama deve tratar isso como "sem cache", nunca como erro.
    """
    return _client
