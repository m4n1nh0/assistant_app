"""Regras do quiz ao vivo que o painel do professor e a tela do aluno dividem.

Tres coisas moram aqui porque tres lugares precisam concordar nelas: o ranking
(painel, WebSocket e tela do aluno), o prazo da pergunta (quem fecha a pergunta
quando o tempo acaba) e a pontuacao por velocidade (que depende do prazo).
Duplicar isso em cada router foi o que deixou o ranking da rodada mostrando so
os pontos da pergunta, sem o acumulado que a turma acompanha.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Sequence

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import QuizModel, StudentAnswerModel

#: Sem prazo definido pelo professor, a velocidade vale numa janela de 30s, que
#: e a escala em que o quiz sempre pontuou.
DEFAULT_SPEED_WINDOW_SECONDS = 30

#: Faixa aceita para o prazo. Menos de 5s nao da tempo de ler no celular; mais
#: de 10min deixa de ser uma pergunta de quiz ao vivo.
MIN_TIME_LIMIT_SECONDS = 5
MAX_TIME_LIMIT_SECONDS = 600

#: Folga depois de o relogio chegar a zero. A resposta enviada no ultimo segundo
#: ainda cruza a rede e chega depois do prazo; sem a folga, quem clicou a tempo
#: perdia a resposta so por ter o wifi mais lento. O ranking aparece esse tempo
#: depois do zero, e a pontuacao ja e minima nesse ponto.
ANSWER_GRACE = timedelta(seconds=2)


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Datetime do banco (sem fuso) tratado como UTC, que e como e gravado."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_time_limit(value: Optional[int]) -> int:
    """Prazo por pergunta em segundos; 0 significa "o professor encerra".

    Valor entre 1 e 4 sobe para o minimo em vez de virar manual: quem digitou um
    numero pequeno queria um prazo curto, nao desligar o relogio.
    """
    try:
        seconds = int(value or 0)
    except (TypeError, ValueError):
        return 0
    if seconds <= 0:
        return 0
    return min(max(seconds, MIN_TIME_LIMIT_SECONDS), MAX_TIME_LIMIT_SECONDS)


def question_deadline(
    started_at: datetime,
    time_limit_seconds: Optional[int],
) -> Optional[datetime]:
    """Quando a pergunta recem-aberta se encerra, ou `None` no modo manual."""
    limit = normalize_time_limit(time_limit_seconds)
    if not limit:
        return None
    return as_utc(started_at) + timedelta(seconds=limit)


def seconds_remaining(
    quiz: QuizModel,
    now: Optional[datetime] = None,
) -> Optional[int]:
    """Segundos que faltam para a pergunta aberta, ou `None` sem relogio."""
    if (quiz.live_phase or "lobby") != "question":
        return None
    ends_at = as_utc(getattr(quiz, "question_ends_at", None))
    if ends_at is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0, math.ceil((ends_at - now).total_seconds()))


async def expire_question_if_due(db: AsyncSession, quiz: QuizModel) -> bool:
    """Encerra a pergunta cujo prazo passou, mostrando o ranking da rodada.

    Nao ha tarefa em segundo plano: quem le o quiz (a tela do aluno, o monitor
    do professor a cada 2s) confere o prazo e fecha. Isso sobrevive a reinicio do
    servidor e a varios workers sem coordenacao.

    O UPDATE e condicional na pergunta e na fase lidas. Sem isso, um leitor com
    o quiz velho em maos fecharia a pergunta nova que o professor acabou de abrir.
    """
    ends_at = as_utc(getattr(quiz, "question_ends_at", None))
    if (
        (quiz.live_phase or "lobby") != "question"
        or not quiz.current_question_id
        or ends_at is None
        or datetime.now(timezone.utc) < ends_at + ANSWER_GRACE
    ):
        return False

    result = await db.execute(
        update(QuizModel)
        .where(
            QuizModel.id == quiz.id,
            QuizModel.live_phase == "question",
            QuizModel.current_question_id == quiz.current_question_id,
            QuizModel.status == "open",
        )
        .values(live_phase="results")
    )
    await db.commit()
    if (result.rowcount or 0) > 0:
        # Mesmo objeto que o chamador ja tem: ele passa a ver a fase nova.
        await db.refresh(quiz)
        return True
    await db.refresh(quiz)
    return False


def score_answer(
    *,
    correta: Optional[bool],
    elapsed_ms: Optional[int],
    time_limit_seconds: Optional[int] = None,
) -> int:
    """Pontos de uma resposta: acertar vale 100 a 1000, conforme a rapidez.

    A janela e o prazo da pergunta quando o professor definiu um; responder no
    ultimo segundo de 60s rende o mesmo que no ultimo de 15s.
    """
    if correta is not True:
        return 0
    window = normalize_time_limit(time_limit_seconds) or DEFAULT_SPEED_WINDOW_SECONDS
    elapsed_seconds = (elapsed_ms or 0) / 1000
    speed_factor = max(0.0, 1.0 - min(elapsed_seconds, window) / window)
    return max(100, int(round(1000 * speed_factor)))


def ranking_rows(
    answers: Iterable[StudentAnswerModel],
    current_question_id: Optional[str] = None,
) -> list[dict]:
    """Ranking por pontos acumulados, com o que cada aluno fez na pergunta atual.

    `score` e o total do quiz inteiro e e ele que ordena. `round_score` e o que
    o aluno somou na pergunta `current_question_id` - e o que explica a posicao
    ("+820 nesta pergunta"), sem trocar a classificacao pelo placar da rodada.
    """
    grouped: dict[str, dict] = {}
    for answer in answers:
        student_id = answer.student_id or "anon"
        row = grouped.setdefault(
            student_id,
            {
                "student_id": student_id,
                "student_name": answer.student_name or "Aluno",
                "score": 0,
                "round_score": 0,
                "round_correct": None,
                "correct": 0,
                "answers": 0,
            },
        )
        row["student_name"] = answer.student_name or row["student_name"]
        points = int(answer.pontuacao or 0)
        row["score"] += points
        row["correct"] += 1 if answer.correta is True else 0
        row["answers"] += 1
        if current_question_id and answer.question_id == current_question_id:
            row["round_score"] += points
            row["round_correct"] = answer.correta

    rows = list(grouped.values())
    rows.sort(key=lambda item: (-item["score"], -item["correct"], item["student_name"]))
    for index, row in enumerate(rows, start=1):
        row["position"] = index
    return rows


def public_options(options: Sequence[dict]) -> list[dict]:
    """Alternativas como a turma ve, sem entregar o gabarito."""
    return [
        {"label": str(item.get("label", "")), "texto": str(item.get("texto", ""))}
        for item in options
        if isinstance(item, dict)
    ]
