"""Agenda de atendimento: quando o professor atende e o que o aluno enxerga.

O professor cadastra faixas **semanais** (quinta das 19h às 21h) e **exceções por data**
(bloquear um dia, abrir um horário extra), cada uma com modalidade (presencial, online ou
ambos), local ou link e **para quem vale** (todos, graduação ou mentoria). Daí saem as
ocorrências datadas dos próximos dias, que o aluno vê no portal.

Os horários são de parede (o relógio de quem atende), sem fuso: "19:00" é 19:00 onde o
professor está. Só o "hoje" depende de fuso, e vem de `AGENDA_TIMEZONE`.

O mesmo cadastro alimenta o plano de encontros da mentoria: cruza as faixas com os
horários livres que cada inscrito informou, para sugerir o melhor dia.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional

import pytz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    AvailabilityExceptionModel,
    AvailabilitySlotModel,
    MentorshipFormModel,
    MentorshipSignupModel,
)

AGENDA_TIMEZONE = "America/Sao_Paulo"
MODES = ("presencial", "online", "ambos")
AUDIENCES = ("todos", "graduacao", "mentoria")
KINDS = ("blocked", "extra")
WEEKDAYS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")
WEEKDAY_NAMES = ("Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo")
#: Turnos do formulario de inscricao, em minutos desde a meia-noite.
SHIFTS = {"manha": (6 * 60, 12 * 60), "tarde": (12 * 60, 18 * 60), "noite": (18 * 60, 24 * 60)}
#: Uma faixa cobre um turno quando se sobrepoem por pelo menos isto.
MIN_OVERLAP_MINUTES = 30
MAX_DAYS = 120

_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AvailabilityError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def today() -> date:
    return datetime.now(pytz.timezone(AGENDA_TIMEZONE)).date()


def minutes(value: str) -> int:
    hours, mins = value.split(":")
    return int(hours) * 60 + int(mins)


# --- validacao ------------------------------------------------------------------------------


def _choice(value: Any, allowed: tuple, label: str, default: str) -> str:
    text = str(value or default).strip().lower()
    if text not in allowed:
        raise AvailabilityError(label, f"{label.capitalize()} inválido.")
    return text


def _times(start: Any, end: Any) -> tuple[str, str]:
    start, end = str(start or "").strip(), str(end or "").strip()
    if not _TIME.match(start) or not _TIME.match(end):
        raise AvailabilityError("time", "Use horários no formato HH:MM, como 19:00.")
    if minutes(end) <= minutes(start):
        raise AvailabilityError("time", "O fim precisa ser depois do início.")
    return start, end


def _common(data: dict) -> dict:
    return {
        "mode": _choice(data.get("mode"), MODES, "modalidade", "ambos"),
        "audience": _choice(data.get("audience"), AUDIENCES, "público", "todos"),
        "location": " ".join(str(data.get("location") or "").split())[:255],
        "note": " ".join(str(data.get("note") or "").split())[:255],
    }


def validate_slot(data: dict) -> dict:
    try:
        weekday = int(data.get("weekday"))
    except (TypeError, ValueError):
        raise AvailabilityError("weekday", "Escolha o dia da semana.") from None
    if not 0 <= weekday <= 6:
        raise AvailabilityError("weekday", "Dia da semana inválido.")
    start, end = _times(data.get("start_time"), data.get("end_time"))
    return {"weekday": weekday, "start_time": start, "end_time": end, **_common(data)}


def validate_exception(data: dict) -> dict:
    day = str(data.get("day") or "").strip()
    try:
        date.fromisoformat(day)
    except ValueError:
        raise AvailabilityError("day", "Informe a data.") from None
    if not _DAY.match(day):
        raise AvailabilityError("day", "Informe a data.")
    kind = _choice(data.get("kind"), KINDS, "tipo", "blocked")
    if kind == "extra":
        start, end = _times(data.get("start_time"), data.get("end_time"))
    else:
        start = end = ""
    return {"day": day, "kind": kind, "start_time": start, "end_time": end, **_common(data)}


# --- ocorrencias ----------------------------------------------------------------------------


async def list_slots(db: AsyncSession, tutor_id: str, *, only_active: bool = False):
    query = select(AvailabilitySlotModel).where(AvailabilitySlotModel.tutor_id == tutor_id)
    if only_active:
        query = query.where(AvailabilitySlotModel.active.is_(True))
    return list((await db.execute(query.order_by(
        AvailabilitySlotModel.weekday, AvailabilitySlotModel.start_time))).scalars().all())


async def list_exceptions(db: AsyncSession, tutor_id: str, *, from_day: Optional[str] = None):
    query = select(AvailabilityExceptionModel).where(
        AvailabilityExceptionModel.tutor_id == tutor_id)
    if from_day:
        query = query.where(AvailabilityExceptionModel.day >= from_day)
    return list((await db.execute(query.order_by(
        AvailabilityExceptionModel.day, AvailabilityExceptionModel.start_time))).scalars().all())


def _applies(audience: str, wanted: Optional[set[str]]) -> bool:
    return wanted is None or audience == "todos" or audience in wanted


def expand(
    slots: Iterable[AvailabilitySlotModel],
    exceptions: Iterable[AvailabilityExceptionModel],
    start: date,
    days: int,
    wanted: Optional[set[str]] = None,
) -> list[dict]:
    """Ocorrências datadas: a semana repetida, sem os dias bloqueados, mais os extras.

    `wanted` filtra pelo público (o aluno de graduação não vê faixa só de mentoria); `None`
    traz tudo, que é a visão do professor.
    """
    days = max(1, min(days, MAX_DAYS))
    exceptions = list(exceptions)
    blocked = {e.day: e for e in exceptions if e.kind == "blocked"}
    extras: dict[str, list] = {}
    for item in exceptions:
        if item.kind == "extra":
            extras.setdefault(item.day, []).append(item)

    out: list[dict] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        key = day.isoformat()
        if key in blocked:
            out.append({
                "date": key, "weekday": day.weekday(), "blocked": True,
                "note": blocked[key].note, "start_time": "", "end_time": "",
                "mode": "", "location": "", "audience": "", "source": "blocked",
            })
            continue
        for slot in slots:
            if slot.active and slot.weekday == day.weekday() and _applies(slot.audience, wanted):
                out.append(_occurrence(key, day, slot, "weekly"))
        for extra in extras.get(key, []):
            if _applies(extra.audience, wanted):
                out.append(_occurrence(key, day, extra, "extra"))
    out.sort(key=lambda o: (o["date"], o["start_time"]))
    return out


def _occurrence(key: str, day: date, item: Any, source: str) -> dict:
    return {
        "date": key, "weekday": day.weekday(), "blocked": False, "note": item.note,
        "start_time": item.start_time, "end_time": item.end_time, "mode": item.mode,
        "location": item.location, "audience": item.audience, "source": source,
    }


async def occurrences(
    db: AsyncSession, tutor_id: str, *, start: Optional[date] = None, days: int = 28,
    wanted: Optional[set[str]] = None,
) -> list[dict]:
    start = start or today()
    slots = await list_slots(db, tutor_id, only_active=True)
    exceptions = await list_exceptions(db, tutor_id, from_day=start.isoformat())
    return expand(slots, exceptions, start, days, wanted)


# --- plano de encontros da mentoria -------------------------------------------------------------


def shifts_covered(start_time: str, end_time: str) -> list[str]:
    """Turnos do formulário (manhã, tarde, noite) que a faixa cobre de verdade."""
    a, b = minutes(start_time), minutes(end_time)
    return [name for name, (lo, hi) in SHIFTS.items()
            if min(b, hi) - max(a, lo) >= MIN_OVERLAP_MINUTES]


def _availability_field(form: MentorshipFormModel) -> Optional[str]:
    for field in form.fields or []:
        if isinstance(field, dict) and field.get("type") == "availability":
            return str(field.get("id") or "")
    return None


async def meeting_plan(db: AsyncSession, form: MentorshipFormModel) -> dict:
    """Quais faixas do professor servem melhor aos aceitos, pelos horários livres deles.

    Cada faixa semanal que vale para mentoria é cruzada com o turno que cada aceito marcou
    (`sab-manha`, `qui-noite`...). Ordena por quantos conseguem; empate vai para o dia e
    a hora mais cedo. Quem não consegue nenhuma faixa aparece à parte.
    """
    from . import mentorship_service as mentorship

    people = await mentorship.accepted_signups(db, form.id)
    field_id = _availability_field(form)
    free: dict[str, set[str]] = {}
    for person in people:
        marked = (person.answers or {}).get(field_id) if field_id else None
        free[person.id] = {str(v) for v in (marked or [])}

    slots = [s for s in await list_slots(db, form.tutor_id, only_active=True)
             if s.audience in ("todos", "mentoria")]
    ranked = []
    covered: set[str] = set()
    for slot in slots:
        day = WEEKDAYS[slot.weekday]
        shifts = shifts_covered(slot.start_time, slot.end_time)
        can = [p for p in people if any(f"{day}-{shift}" in free[p.id] for shift in shifts)]
        covered.update(p.id for p in can)
        ranked.append({
            "slot_id": slot.id, "weekday": slot.weekday, "weekday_name": WEEKDAY_NAMES[slot.weekday],
            "start_time": slot.start_time, "end_time": slot.end_time, "mode": slot.mode,
            "location": slot.location, "audience": slot.audience, "shifts": shifts,
            "count": len(can), "names": [p.name for p in can],
        })
    ranked.sort(key=lambda r: (-r["count"], r["weekday"], r["start_time"]))
    return {
        "accepted": len(people),
        "with_availability": sum(1 for p in people if free[p.id]),
        "options": ranked,
        "uncovered": [p.name for p in people if p.id not in covered],
        "has_slots": bool(slots),
    }
