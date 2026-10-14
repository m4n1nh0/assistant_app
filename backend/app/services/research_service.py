"""Pesquisas cientificas: projetos, participantes, etapas e o plano montado pela IA.

O professor cadastra a pesquisa (tema, area, periodo), liga os participantes - aluno da
casa ou pessoa de fora - e acompanha as etapas do plano com prazo e situacao. A IA propoe
o plano a partir do tema; o professor ajusta antes de gravar, como nos campos da mentoria.

A matricula do participante nao e validada (o app nao tem como): ela so *marca* quem ja e
aluno cadastrado, para o professor reconhecer quem e de fora.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    ResearchParticipantModel,
    ResearchProjectModel,
    ResearchStageModel,
    StudentModel,
)

PROJECT_STATUSES = ("planning", "active", "paused", "done")
STAGE_STATUSES = ("todo", "doing", "done")
ROLES = ("orientando", "coorientador", "colaborador")
MAX_STAGES = 20


class ResearchError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def naive(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def normalize_enrollment(value: Optional[str]) -> str:
    return re.sub(r"[^0-9a-z]", "", (value or "").casefold())


# --- plano --------------------------------------------------------------------------------


def default_stages() -> list[dict]:
    """Etapas de sempre, usadas quando a IA nao responde. Sem prazo: o professor define."""
    titles = [
        ("Revisão bibliográfica", "Levantar e ler os trabalhos relacionados ao tema."),
        ("Definição da metodologia", "Escolher o método, os instrumentos e os critérios."),
        ("Coleta de dados ou desenvolvimento", "Executar a parte prática da pesquisa."),
        ("Análise dos resultados", "Tratar os dados e interpretar o que foi obtido."),
        ("Redação do texto", "Escrever o relatório ou artigo com os resultados."),
        ("Revisão e submissão", "Revisar o texto e enviar ao evento ou periódico."),
    ]
    return [{"title": t, "description": d, "week": None} for t, d in titles]


def sanitize_stages(raw: Any) -> list[dict]:
    """Aceita o que a IA ou o app mandou e devolve so etapas validas. Nunca levanta."""
    if not isinstance(raw, list):
        return []
    stages: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = " ".join(str(item.get("title") or "").split())[:255]
        if not title:
            continue
        week = item.get("week")
        try:
            week = max(0, min(520, int(week))) if week is not None else None
        except (TypeError, ValueError):
            week = None
        stages.append({
            "title": title,
            "description": str(item.get("description") or "").strip()[:2000],
            "week": week,
        })
        if len(stages) >= MAX_STAGES:
            break
    return stages


_SYSTEM = (
    "Voce ajuda a planejar pesquisas cientificas academicas. Responda somente com JSON "
    "valido, sem texto antes ou depois."
)


def _prompt(title: str, description: str, weeks: int) -> str:
    return (
        "Monte o plano de etapas de uma pesquisa cientifica.\n"
        f"Titulo: {title.strip()[:300]}\n"
        f'Descricao: """{description.strip()[:2000]}"""\n'
        f"Duracao total: cerca de {weeks} semanas.\n\n"
        "De 5 a 10 etapas, na ordem de execucao, realistas para essa duracao.\n"
        'Formato: {"stages": [{"title": "...", "description": "o que fazer", '
        '"week": numero da semana (a partir de 1) em que a etapa deve terminar}]}'
    )


def parse_plan(text: str) -> list[dict]:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return []
    return sanitize_stages(data.get("stages") if isinstance(data, dict) else None)


async def _ask_llm(prompt: str) -> str:
    """Pergunta ao primeiro provedor que responder. Separado para os testes trocarem."""
    from . import education_service as edu
    from .llm_service import dispatch_single

    for provider in await edu._summary_provider_candidates(None):
        response = await dispatch_single(provider, prompt, [], _SYSTEM, max_tokens=1800)
        if not response.is_error and response.content.strip():
            return response.content
        logger.warning(f"Plano de pesquisa: {provider} nao respondeu")
    return ""


def schedule(stages: list[dict], start: Optional[datetime]) -> list[dict]:
    """Converte a semana de cada etapa em data (a partir de `start`; sem semana, sem data)."""
    base = naive(start) or _now()
    return [{**s, "due_at": (base + timedelta(weeks=s["week"])
                             if s.get("week") is not None else None)} for s in stages]


async def generate_plan(
    title: str, description: str, *, weeks: int = 24, start: Optional[datetime] = None,
) -> tuple[list[dict], bool]:
    """Etapas propostas pela IA, ja com data, e se vieram dela (False = padrao de reserva)."""
    weeks = max(2, min(260, weeks))
    try:
        stages = parse_plan(await _ask_llm(_prompt(title, description, weeks)))
    except Exception as exc:  # provedor fora do ar nao pode derrubar a criacao
        logger.warning(f"Plano de pesquisa: falha ao chamar a IA: {exc}")
        stages = []
    if len(stages) >= 3:
        return schedule(stages, start), True
    return schedule(default_stages(), start), False


# --- participantes ------------------------------------------------------------------------


async def known_student(db: AsyncSession, tutor_id: str, enrollment: str) -> Optional[StudentModel]:
    key = normalize_enrollment(enrollment)
    if not key:
        return None
    rows = (await db.execute(select(StudentModel).where(
        StudentModel.tutor_id == tutor_id, StudentModel.active.is_(True)))).scalars().all()
    for student in rows:
        if normalize_enrollment(student.external_id) == key:
            return student
    return None


async def add_participant(
    db: AsyncSession, project: ResearchProjectModel, data: dict,
) -> ResearchParticipantModel:
    name = " ".join(str(data.get("name") or "").split())[:180]
    if not name:
        raise ResearchError("name", "Informe o nome do participante.")
    role = str(data.get("role") or "orientando").strip().lower()
    if role not in ROLES:
        raise ResearchError("role", "Papel inválido.")
    email = str(data.get("email") or "").strip().lower()[:255]
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$", email):
        raise ResearchError("email", "E-mail inválido.")
    enrollment = " ".join(str(data.get("enrollment") or "").split())[:80]
    key = normalize_enrollment(enrollment)
    if key:
        duplicate = (await db.execute(select(ResearchParticipantModel).where(
            ResearchParticipantModel.project_id == project.id,
            ResearchParticipantModel.active.is_(True)))).scalars().all()
        if any(normalize_enrollment(p.enrollment) == key for p in duplicate):
            raise ResearchError("duplicate", "Esta matrícula já participa da pesquisa.", 409)
    student = await known_student(db, project.tutor_id, enrollment)
    participant = ResearchParticipantModel(
        project_id=project.id, tutor_id=project.tutor_id, name=name, email=email,
        phone=" ".join(str(data.get("phone") or "").split())[:40], enrollment=enrollment,
        institution=" ".join(str(data.get("institution") or "").split())[:180], role=role,
        student_id=student.id if student else None, known_student=student is not None)
    db.add(participant)
    await db.commit()
    await db.refresh(participant)
    return participant


# --- etapas -------------------------------------------------------------------------------


def apply_stage_status(stage: ResearchStageModel, status: str) -> None:
    if status not in STAGE_STATUSES:
        raise ResearchError("status", "Situação inválida.")
    stage.done_at = _now() if status == "done" and stage.status != "done" else (
        stage.done_at if status == "done" else None)
    stage.status = status


def stage_state(stage: ResearchStageModel, now: Optional[datetime] = None) -> str:
    """`done`, `doing`, `overdue` (prazo passou e nao acabou) ou `todo`."""
    if stage.status == "done":
        return "done"
    deadline = naive(stage.due_at)
    if deadline is not None and deadline <= (naive(now) or _now()):
        return "overdue"
    return stage.status


async def stages_of(db: AsyncSession, project_id: str) -> list[ResearchStageModel]:
    return list((await db.execute(select(ResearchStageModel).where(
        ResearchStageModel.project_id == project_id
    ).order_by(ResearchStageModel.position, ResearchStageModel.created_at))).scalars().all())


async def participants_of(db: AsyncSession, project_id: str) -> list[ResearchParticipantModel]:
    return list((await db.execute(select(ResearchParticipantModel).where(
        ResearchParticipantModel.project_id == project_id,
        ResearchParticipantModel.active.is_(True)
    ).order_by(ResearchParticipantModel.role, ResearchParticipantModel.name))).scalars().all())


async def summary(db: AsyncSession, project: ResearchProjectModel) -> dict:
    """O que a lista mostra de cada pesquisa: progresso, atraso e proximo prazo."""
    stages = await stages_of(db, project.id)
    now = _now()
    done = sum(1 for s in stages if s.status == "done")
    overdue = sum(1 for s in stages if stage_state(s, now) == "overdue")
    upcoming = sorted((s for s in stages if s.status != "done" and naive(s.due_at)
                       and naive(s.due_at) > now), key=lambda s: naive(s.due_at))
    return {
        "stages": len(stages), "done": done, "overdue": overdue,
        "progress": round(done * 100 / len(stages)) if stages else 0,
        "next_due": upcoming[0].due_at if upcoming else None,
        "next_title": upcoming[0].title if upcoming else "",
        "participants": len(await participants_of(db, project.id)),
    }
