"""Inscricao em mentorias: formulario montado pela IA, link publico e aceite.

O professor descreve a mentoria, a IA propoe os campos e ele ajusta antes de publicar.
Matricula, nome, e-mail e telefone sao sempre pedidos e nao entram em `fields`; o resto
(idade, curso, horarios livres...) e dinamico. A matricula nao e validada - o app nao
tem como - mas a inscricao e marcada quando ela casa com um aluno ja cadastrado neste
semestre. Aceitar inscritos cria a mentoria como disciplina com uma turma, e cada
aceito entra nela como aluno: dai em diante presenca, pontos e reuniao funcionam como
em qualquer turma, e remover quem nao entrega e tirar o aluno da turma.
"""

from __future__ import annotations

import json
import re
import secrets
import unicodedata
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    ClassGroupModel,
    DisciplineModel,
    MentorshipFormModel,
    MentorshipSignupModel,
    StudentModel,
)

FIELD_TYPES = ("text", "textarea", "number", "select", "availability")
MAX_FIELDS = 15
MAX_TEXT = 1000

#: Dias e turnos do campo de horarios livres. O valor guardado e "dia-turno".
DAYS = (("seg", "Segunda"), ("ter", "Terça"), ("qua", "Quarta"), ("qui", "Quinta"),
        ("sex", "Sexta"), ("sab", "Sábado"), ("dom", "Domingo"))
SHIFTS = (("manha", "Manhã"), ("tarde", "Tarde"), ("noite", "Noite"))
AVAILABILITY_VALUES = frozenset(f"{d}-{s}" for d, _ in DAYS for s, _ in SHIFTS)

#: Estados de um formulario: `open`, `closed` (professor fechou), `expired` (prazo) ou
#: `full` (vagas acabaram).
STATUSES = ("pending", "accepted", "rejected", "removed")


class MentorshipError(Exception):
    """Erro que a pagina publica ou o app mostra como esta."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def new_token() -> str:
    return secrets.token_urlsafe(12)


def normalize_enrollment(value: Optional[str]) -> str:
    """So letras e numeros, sem caixa: "2024-0123 " e "20240123" sao a mesma matricula."""
    return re.sub(r"[^0-9a-z]", "", (value or "").casefold())


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def naive(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


# --- campos -------------------------------------------------------------------------


def default_fields() -> list[dict]:
    """Campos de sempre, usados quando a IA nao responde ou como ponto de partida."""
    return [
        {"id": "idade", "label": "Idade", "type": "number", "required": True, "options": []},
        {"id": "curso", "label": "Curso", "type": "text", "required": True, "options": []},
        {"id": "periodo", "label": "Período", "type": "text", "required": True,
         "options": []},
        {"id": "horarios_livres", "label": "Horários livres para os encontros",
         "type": "availability", "required": True, "options": []},
    ]


def _slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "_", plain.casefold()).strip("_")
    return base[:40] or "campo"


def sanitize_fields(raw: Any) -> list[dict]:
    """Aceita o que a IA ou o app mandou e devolve so campos validos e unicos.

    Descarta o que nao tem rotulo ou tem tipo desconhecido; `select` sem opcoes vira
    texto, e o `id` repetido ganha sufixo. Nunca levanta: lixo vira lista menor.
    """
    if not isinstance(raw, list):
        return []
    fields: list[dict] = []
    used: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = " ".join(str(item.get("label") or "").split())[:120]
        kind = str(item.get("type") or "text").strip().lower()
        if not label or kind not in FIELD_TYPES:
            continue
        options = [" ".join(str(o).split())[:80] for o in (item.get("options") or [])
                   if str(o).strip()] if kind == "select" else []
        if kind == "select" and len(options) < 2:
            kind, options = "text", []
        base = _slug(str(item.get("id") or label))
        field_id, n = base, 2
        while field_id in used:
            field_id, n = f"{base}_{n}", n + 1
        used.add(field_id)
        fields.append({"id": field_id, "label": label, "type": kind,
                       "required": bool(item.get("required", False)), "options": options})
        if len(fields) >= MAX_FIELDS:
            break
    return fields


_SYSTEM = (
    "Voce monta formularios de inscricao para mentorias academicas. Responda somente "
    "com JSON valido, sem texto antes ou depois."
)


def _prompt(description: str) -> str:
    return (
        "Monte os campos de um formulario de inscricao para esta mentoria:\n"
        f'"""\n{description.strip()[:2000]}\n"""\n\n'
        "Ja serao pedidos sempre: matricula, nome, e-mail e telefone. NAO os repita.\n"
        "Inclua so o que ajuda a escolher e organizar os inscritos (idade, curso, periodo, "
        "interesses, experiencia, horarios livres...). Entre 4 e 10 campos.\n"
        'Formato: {"fields": [{"label": "...", "type": "text|textarea|number|select|'
        'availability", "required": true, "options": ["so para select"]}]}\n'
        'Use o tipo "availability" (uma vez) para os horarios livres: o formulario mostra '
        "dias da semana e turnos."
    )


def parse_fields(text: str) -> list[dict]:
    """Tira os campos da resposta do modelo, que pode vir cercada de texto ou de ```."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return []
    return sanitize_fields(data.get("fields") if isinstance(data, dict) else None)


async def _ask_llm(prompt: str) -> str:
    """Pergunta ao primeiro provedor que responder. Separado para os testes trocarem."""
    from . import education_service as edu
    from .llm_service import dispatch_single

    for provider in await edu._summary_provider_candidates(None):
        response = await dispatch_single(provider, prompt, [], _SYSTEM, max_tokens=1500)
        if not response.is_error and response.content.strip():
            return response.content
        logger.warning(f"Formulario de mentoria: {provider} nao respondeu")
    return ""


async def generate_fields(description: str) -> tuple[list[dict], bool]:
    """Campos propostos pela IA e se vieram dela (False = campos padrao de reserva)."""
    try:
        fields = parse_fields(await _ask_llm(_prompt(description)))
    except Exception as exc:  # provedor fora do ar nao pode derrubar a criacao
        logger.warning(f"Formulario de mentoria: falha ao chamar a IA: {exc}")
        fields = []
    if len(fields) >= 2:
        return fields, True
    return default_fields(), False


# --- formulario ---------------------------------------------------------------------


def form_state(form: MentorshipFormModel, taken: int, now: Optional[datetime] = None) -> str:
    if not form.active:
        return "closed"
    deadline = naive(form.closes_at)
    if deadline is not None and deadline <= (naive(now) or _now()):
        return "expired"
    if form.max_slots is not None and taken >= form.max_slots:
        return "full"
    return "open"


async def get_form_by_token(db: AsyncSession, token: str) -> Optional[MentorshipFormModel]:
    token = (token or "").strip()
    if not token:
        return None
    return (await db.execute(select(MentorshipFormModel).where(
        MentorshipFormModel.token == token))).scalar_one_or_none()


async def count_signups(db: AsyncSession, form_id: str) -> int:
    """Inscricoes que ocupam vaga: so recusadas e removidas liberam a vaga."""
    return int((await db.execute(select(func.count()).select_from(MentorshipSignupModel).where(
        MentorshipSignupModel.form_id == form_id,
        MentorshipSignupModel.status.in_(("pending", "accepted"))))).scalar_one())


# --- inscricao ----------------------------------------------------------------------

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def validate_answers(fields: list[dict], answers: Any) -> dict:
    """Confere as respostas contra os campos do formulario e devolve so as validas."""
    answers = answers if isinstance(answers, dict) else {}
    clean: dict[str, Any] = {}
    for field in fields:
        raw = answers.get(field["id"])
        label = field["label"]
        kind = field["type"]
        if kind == "availability":
            picked = [v for v in (raw if isinstance(raw, list) else [])
                      if v in AVAILABILITY_VALUES]
            value: Any = sorted(set(picked))
            empty = not value
        elif kind == "number":
            text = str(raw if raw is not None else "").strip().replace(",", ".")
            try:
                number = float(text) if text else None
            except ValueError:
                raise MentorshipError("invalid", f"“{label}” precisa ser um número.")
            value = None if number is None else (int(number) if number.is_integer() else number)
            empty = value is None
        else:
            value = " ".join(str(raw if raw is not None else "").split())[:MAX_TEXT] \
                if kind != "textarea" else str(raw or "").strip()[:MAX_TEXT]
            if kind == "select" and value and value not in field["options"]:
                raise MentorshipError("invalid", f"Escolha uma opção válida em “{label}”.")
            empty = not value
        if empty:
            if field["required"]:
                raise MentorshipError("required", f"Preencha “{label}”.")
            continue
        clean[field["id"]] = value
    return clean


async def known_student(db: AsyncSession, form: MentorshipFormModel,
                        enrollment_key: str) -> Optional[StudentModel]:
    """Aluno ativo com essa matricula em alguma turma do semestre do formulario."""
    if not enrollment_key:
        return None
    query = select(StudentModel).join(
        ClassGroupModel, ClassGroupModel.id == StudentModel.class_id
    ).where(StudentModel.tutor_id == form.tutor_id, StudentModel.active.is_(True))
    if form.semester:
        query = query.where(ClassGroupModel.semester == form.semester)
    for student in (await db.execute(query)).scalars().all():
        if normalize_enrollment(student.external_id) == enrollment_key:
            return student
    return None


async def submit(db: AsyncSession, form: MentorshipFormModel, payload: dict) -> MentorshipSignupModel:
    """Registra uma inscricao vinda da pagina publica."""
    state = form_state(form, await count_signups(db, form.id))
    if state != "open":
        raise MentorshipError(state, {
            "closed": "As inscrições foram encerradas.",
            "expired": "O prazo de inscrição terminou.",
            "full": "As vagas acabaram.",
        }[state], 409)

    enrollment = " ".join(str(payload.get("enrollment") or "").split())[:80]
    key = normalize_enrollment(enrollment)
    name = " ".join(str(payload.get("name") or "").split())[:180]
    email = str(payload.get("email") or "").strip().lower()[:255]
    phone = " ".join(str(payload.get("phone") or "").split())[:40]
    if not key:
        raise MentorshipError("enrollment", "Informe a sua matrícula.")
    if not name:
        raise MentorshipError("name", "Informe o seu nome.")
    if not _EMAIL.match(email):
        raise MentorshipError("email", "Informe um e-mail válido.")
    if len(re.sub(r"\D", "", phone)) < 10:
        raise MentorshipError("phone", "Informe o telefone com DDD.")
    answers = validate_answers(sanitize_fields(form.fields), payload.get("answers"))

    exists = (await db.execute(select(MentorshipSignupModel.id).where(
        MentorshipSignupModel.form_id == form.id,
        MentorshipSignupModel.enrollment_key == key))).first()
    if exists:
        raise MentorshipError("duplicate", "Esta matrícula já está inscrita.", 409)

    student = await known_student(db, form, key)
    signup = MentorshipSignupModel(
        form_id=form.id, tutor_id=form.tutor_id, enrollment=enrollment, enrollment_key=key,
        name=name, email=email, phone=phone, answers=answers,
        known_student=student is not None, status="pending")
    db.add(signup)
    await db.commit()
    await db.refresh(signup)
    return signup


async def send_confirmation(form: MentorshipFormModel, signup: MentorshipSignupModel) -> bool:
    """Confirma o recebimento por e-mail. Falha aqui nunca desfaz a inscricao."""
    from .registration_invite_service import (
        registration_delivery_configured, send_transactional_email)

    if not registration_delivery_configured(signup.email):
        return False
    try:
        await send_transactional_email(
            signup.email,
            subject=f"Inscrição recebida: {form.title}"[:200],
            text_content=(
                f"Olá, {signup.name}!\n\n"
                f"Recebemos a sua inscrição na mentoria “{form.title}”.\n"
                "Você receberá uma resposta quando as inscrições forem analisadas.\n\n"
                "INTARQ\n"))
        return True
    except Exception as exc:
        logger.warning(f"Confirmacao de mentoria nao enviada: {exc}")
        return False


# --- aceite -------------------------------------------------------------------------


def _discipline_label(item: DisciplineModel) -> str:
    return " - ".join(p for p in ((item.code or "").strip(), (item.name or "").strip()) if p)


async def ensure_class(db: AsyncSession, form: MentorshipFormModel) -> ClassGroupModel:
    """A turma da mentoria: criada no primeiro aceite, com a disciplina dela."""
    if form.class_id:
        existing = await db.get(ClassGroupModel, form.class_id)
        if existing is not None:
            return existing
    discipline = await db.get(DisciplineModel, form.discipline_id) if form.discipline_id else None
    if discipline is None:
        discipline = DisciplineModel(
            tutor_id=form.tutor_id, code="MENTORIA", name=form.title[:180],
            semester=form.semester, active=True)
        db.add(discipline)
        await db.flush()
    group = ClassGroupModel(
        tutor_id=form.tutor_id, code="MENTORIA", name=form.title[:120],
        discipline_id=discipline.id, discipline=_discipline_label(discipline)[:120],
        semester=form.semester, active=True)
    db.add(group)
    await db.flush()
    form.discipline_id, form.class_id = discipline.id, group.id
    return group


async def set_status(db: AsyncSession, form: MentorshipFormModel,
                     signups: list[MentorshipSignupModel], status: str) -> None:
    """Muda a situacao dos inscritos e mantem a turma da mentoria em dia.

    Aceitar cria o aluno na turma (ou reativa o que ja existia); recusar ou remover quem
    estava aceito tira o aluno da turma, sem apagar o historico dele.
    """
    if status not in STATUSES:
        raise MentorshipError("status", "Situação inválida.")
    group = await ensure_class(db, form) if status == "accepted" else None
    for signup in signups:
        if status == "accepted":
            student = await db.get(StudentModel, signup.student_id) if signup.student_id else None
            if student is None:
                student = StudentModel(
                    tutor_id=form.tutor_id, name=signup.name, class_id=group.id,
                    class_group=f"{group.code} {group.name}".strip()[:120],
                    discipline=group.discipline, external_id=signup.enrollment,
                    aliases=[], active=True)
                db.add(student)
                await db.flush()
                signup.student_id = student.id
            student.active = True
        elif signup.student_id:
            student = await db.get(StudentModel, signup.student_id)
            if student is not None:
                student.active = False
        signup.status = status
    await db.commit()
