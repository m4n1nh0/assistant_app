"""Atividade real de uso: ha alguem usando o app agora?

Serve para tarefas de fundo que so fazem sentido com gente por perto (o monitor de saude), e para
nao manter acordado, a cada minuto, um servico que o Railway deixaria dormir. Todo trafego pela
rede privada conta como atividade para o Railway, entao um ping periodico impede o sono e, num
servico dormindo, uma checagem com timeout curto vira falha e alerta falso.

O que conta como atividade: uma requisicao autenticada (fora health e rotas internas) e uma
conexao WebSocket aberta, que e a interface ligada. Chamada de monitor externo, healthcheck do
container e requisicao entre servicos nao contam.
"""

from __future__ import annotations

import time

_last_request: float | None = None


def touch() -> None:
    """Registra uma requisicao de uso real."""
    global _last_request
    _last_request = time.monotonic()


def reset() -> None:
    """Esquece a atividade registrada (testes)."""
    global _last_request
    _last_request = None


def idle_seconds() -> float | None:
    """Ha quanto tempo nao ha requisicao de uso, ou `None` se nunca houve neste processo."""
    return None if _last_request is None else time.monotonic() - _last_request


def is_active(window_seconds: float, *, connections: int = 0) -> bool:
    """Ha uso recente?

    Args:
        window_seconds: quanto tempo depois da ultima requisicao ainda conta como uso.
        connections: conexoes WebSocket abertas; com alguma, a interface esta ligada.
    """
    if connections > 0:
        return True
    idle = idle_seconds()
    return idle is not None and idle <= window_seconds


def counts_as_activity(path: str, has_credentials: bool) -> bool:
    """Esta requisicao e uso real? Autenticada, e fora de health e das rotas entre servicos."""
    if not has_credentials:
        return False
    return not path.startswith(("/health", "/internal"))
