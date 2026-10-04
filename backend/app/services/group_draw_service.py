"""Regra do sorteio de apresentacao por grupo.

O sorteio precisa ser justo e, mais que isso, poder ser provado justo: aluno
desconfia de sorteio feito dentro de uma tela. Por isso nao ha gerador aleatorio
escondido - cada passo sai de um hash (SHA-256) da semente guardada com o sorteio,
do numero do passo e do grupo. Quem tiver a semente e a lista de grupos refaz a
conta e chega na mesma ordem, em qualquer linguagem, sem depender de versao de
biblioteca.

A semente nasce no servidor, no momento do sorteio, e o professor nao a escolhe:
senao daria para testar sementes ate sair a ordem que se queria.

Os dois modos usam a mesma regra. Na fila completa todos os passos saem de uma vez;
no sorteio avulso um passo por clique. A ordem final de um e do outro, com a mesma
semente e os mesmos grupos, e a mesma - so muda quando ela e revelada.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Iterable, Optional, Sequence

#: Identifica a regra gravada com o sorteio. Mudar a conta cria `sha256-v2`, e o que
#: ja foi sorteado continua verificavel pela regra com que nasceu.
ALGORITHM = "sha256-v1"

MODE_QUEUE = "fila"
MODE_ONE_BY_ONE = "avulso"
MODES = (MODE_QUEUE, MODE_ONE_BY_ONE)


def new_seed() -> str:
    """Semente de 128 bits, em hexadecimal."""
    return secrets.token_hex(16)


def _score(*parts: object) -> str:
    texto = ":".join(str(part) for part in parts)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def pick_step(seed: str, step: int, remaining: Iterable[str]) -> str:
    """Grupo sorteado no passo `step` entre os que ainda nao sairam.

    Vence o de menor hash de `semente:passo:grupo`. O passo entra na conta para a
    escolha de cada rodada ser independente das outras, e nao uma fatia de um
    embaralhamento unico.
    """
    candidatos = list(remaining)
    if not candidatos:
        raise ValueError("Nao ha grupos para sortear")
    return min(candidatos, key=lambda group_id: (_score(seed, step, group_id), group_id))


def draw_order(seed: str, group_ids: Sequence[str], *, start: int = 0) -> list[str]:
    """Ordem completa dos grupos, passo a passo.

    `start` permite continuar um sorteio avulso de onde parou: recebe so os grupos
    que restam e o numero do proximo passo.
    """
    restantes = list(dict.fromkeys(group_ids))
    ordem: list[str] = []
    passo = start
    while restantes:
        escolhido = pick_step(seed, passo, restantes)
        ordem.append(escolhido)
        restantes.remove(escolhido)
        passo += 1
    return ordem


def day_of(position: int, per_day: Optional[int]) -> int:
    """Dia (1, 2, ...) de uma posicao quando se apresenta `per_day` grupos por dia."""
    if not per_day or per_day < 1:
        return 1
    return (position - 1) // per_day + 1


def pick_representative(
    seed: str, group_id: str, member_ids: Sequence[str], *, round_: int = 0
) -> str:
    """Integrante sorteado para representar o grupo.

    `round_` sobe a cada novo sorteio do mesmo grupo (o escolhido faltou, por
    exemplo): muda o resultado sem perder a prova, porque o numero da rodada fica
    gravado.
    """
    if not member_ids:
        raise ValueError("O grupo nao tem integrantes para sortear")
    return min(
        member_ids,
        key=lambda member_id: (_score(seed, "rep", group_id, round_, member_id), member_id),
    )


def verify_order(seed: str, group_ids: Sequence[str], drawn: Sequence[str]) -> bool:
    """Confere se a ordem sorteada ate agora e a que a semente produz."""
    esperado = draw_order(seed, group_ids)
    return list(drawn) == esperado[: len(drawn)]
