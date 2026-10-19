"""Consulta de leitura dos horarios de aula registrados no banco interno."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import academic_calendar_service as calendar


def _plain(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.lower())
                   if not unicodedata.combining(c))


#: Pedido sobre o que aconteceu DENTRO de uma aula. "aula do dia 10/09" casa as
#: palavras de agenda, mas "resumo", "sobre" ou "o que foi visto" dizem que a
#: pessoa quer o conteudo - e quem responde isso e o contexto das aulas gravadas,
#: nao a projecao de horarios.
_LESSON_CONTENT = re.compile(
    r"\b(resum\w*|conteudo\w*|materia\w*|assunto\w*|topico\w*|transcri\w*"
    r"|explica\w*|revis\w*|detalh\w*"
    r"|o que (?:foi|a gente|nos|eu|voce|vimos|vi|falamos|falei|estudamos|aprendemos|dei|passei|passou|teve))\b"
)
#: "sobre" sozinho e ambiguo: "buscar sobre a aula do dia 10/09" quer conteudo,
#: "horarios das aulas sobre banco de dados" quer agenda. So vale como pedido de
#: conteudo quando nenhuma palavra forte de agenda aparece junto.
_ABOUT = re.compile(r"\bsobre\b")
#: Pedido para PLANEJAR a aula ("o que posso abordar na proxima aula", "pensei em seguir este
#: slide"): "proxima aula" aparece, mas a pessoa quer ideias de conteudo, nao a lista de datas.
#: So uma palavra de agenda explicita (quando, horario, agenda, calendario) mantem a rota de horarios.
_PLANNING = re.compile(
    r"\b(abord\w*|ensin\w*|lecion\w*|planej\w*|prepar\w*|pensei|pensando|falar|conversar|slides?|sugest\w*|ideias?|roteiro|pauta"
    r"|o que (?:posso|devo|vou|podemos|poderia|seguir|dar|falar|passar))\b"
)
_EXPLICIT_SCHEDULE = re.compile(r"\b(quando|horario\w*|agenda\w*|calendario\w*)\b")
_STRONG_SCHEDULE =re.compile(r"\b(quando|horario\w*|agenda\w*|calendario\w*|proxim\w*)\b")


def is_academic_schedule_query(
    message: str,
    *,
    timezone_name: str = "America/Sao_Paulo",
    now: datetime | None = None,
) -> bool:
    """Diz se a pergunta e sobre a agenda de aulas, e nao sobre uma aula dada.

    A resposta desta rota projeta as proximas semanas a partir dos horarios
    semanais. Por isso ela nao serve a duas perguntas que tambem falam de "aula"
    e "dia": o conteudo de uma aula ("resumo da aula do dia 10/09") e uma data
    que ja passou ("tive aula dia 10/09?") - nas duas, a lista de aulas futuras
    ignoraria a data pedida.
    """
    text = _plain(message)
    if not (re.search(r"\b(aula|aulas|turma|turmas|disciplina|disciplinas)\b", text)
            and re.search(r"\b(quando|data|datas|dia|dias|horario|horarios|agenda|calendario|proxim|listar|trazer|tracar)\w*\b", text)):
        return False
    if _LESSON_CONTENT.search(text):
        return False
    if _PLANNING.search(text) and not _EXPLICIT_SCHEDULE.search(text):
        return False
    if _ABOUT.search(text) and not _STRONG_SCHEDULE.search(text):
        return False

    from .lesson_context_service import parse_day

    day, _ = parse_day(message, timezone_name=timezone_name, now=now)
    if day is not None:
        today = (now.astimezone(ZoneInfo(timezone_name)) if now else datetime.now(ZoneInfo(timezone_name))).date()
        if day < today:
            return False
    return True


async def academic_schedule_response(tutor_id: str, timezone_name: str) -> str:
    """Lista as proximas quatro semanas; o tutor vem da sessao autenticada.

    Usa o calendario letivo: respeita o inicio e o fim do semestre e as datas sem aula
    cadastradas. Quando o semestre nao tem periodo, diz isso em vez de afirmar o que nao sabe.
    """
    today = datetime.now(ZoneInfo(timezone_name)).date()
    found = await calendar.occurrences(
        tutor_id, today, today + timedelta(days=27), include_skipped=True
    )
    if not found:
        return "Não encontrei horários de aula cadastrados para suas turmas no banco interno."

    classes = [item for item in found if item.status.has_class]
    skipped = [item for item in found if not item.status.has_class]
    lines = [
        f"- {item.day:%d/%m/%Y}: {item.discipline_label} — turma {item.group_label} — "
        + (
            f"{item.start_time}–{item.end_time}" if item.start_time and item.end_time
            else item.start_time or "horário não informado"
        )
        for item in classes[:80]
    ]
    text = (
        "Próximas aulas conforme os horários semanais cadastrados:\n" + "\n".join(lines)
        if lines
        else "Não há aulas previstas nos próximos 28 dias."
    )
    if skipped:
        text += "\nSem aula nesse período (o horário semanal cairia nesses dias):\n" + "\n".join(
            f"- {item.day:%d/%m/%Y}: {item.discipline_label} — turma {item.group_label}: "
            f"{item.status.reason}"
            for item in skipped[:20]
        )

    data = None
    notes = []
    for semester in sorted({item.semester for item in found if item.semester}):
        if data is None:
            data = await _calendar(tutor_id)
        period = data.period_of(semester)
        if period.end is not None:
            notes.append(f"O semestre {semester} termina em {period.end:%d/%m/%Y}.")
        else:
            notes.append(f"O fim do semestre {semester} não está cadastrado.")
    if not data or not any(data.period_of(item.semester).known for item in found):
        notes.append("Feriados e cancelamentos só aparecem se cadastrados em Disciplinas > período do semestre.")
    return text + ("\n" + " ".join(notes) if notes else "")


async def _calendar(tutor_id: str):
    from ..core import database

    async with database.AsyncSessionLocal() as db:
        return await calendar.load_calendar(db, tutor_id)
