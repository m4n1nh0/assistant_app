"""Calendario letivo: em que dias cada turma tem aula de fato.

O horario semanal (`class_schedules`) diz "segunda, 18:30" e repete para sempre. Esta camada o
cruza com o periodo do semestre (inicio e fim) e com as datas sem aula (feriado, recesso, aula
cancelada) para responder **"a turma X tem aula no dia D?"**. E a regra unica: a pergunta "que
aula e hoje?" do assistente, a projecao das proximas semanas e a tela de presenca devem sair
daqui, para nao divergirem.

Um semestre sem periodo cadastrado nao bloqueia nada: o horario semanal vale como sempre. O que se
perde e a certeza sobre inicio e fim, e quem responde ao usuario deve dizer isso.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Optional

from sqlalchemy import select

from ..core import database
from ..core.database import (
    ClassBreakModel,
    ClassGroupModel,
    ClassScheduleModel,
    DisciplineModel,
    SemesterPeriodModel,
)

#: Estados de um dia de aula.
CLASS = "class"          # tem aula
BREAK = "break"          # data sem aula cadastrada (feriado, recesso, cancelada)
BEFORE = "before"        # antes do inicio do semestre
AFTER = "after"          # depois do fim do semestre


@dataclass(frozen=True)
class Period:
    """Periodo das aulas de um semestre; `None` em uma ponta significa "nao informado"."""

    start: Optional[date] = None
    end: Optional[date] = None

    @property
    def known(self) -> bool:
        return self.start is not None or self.end is not None


@dataclass(frozen=True)
class Break:
    """Data, ou intervalo, sem aula. `class_group_id` `None` vale para todas as turmas."""

    id: str
    date_from: date
    date_to: date
    class_group_id: Optional[str] = None
    reason: str = ""

    def covers(self, day: date, class_group_id: str) -> bool:
        if not self.date_from <= day <= self.date_to:
            return False
        return self.class_group_id in (None, "", class_group_id)


@dataclass(frozen=True)
class DayStatus:
    """Se a turma tem aula num dia e, quando nao tem, por que."""

    state: str
    reason: str = ""

    @property
    def has_class(self) -> bool:
        return self.state == CLASS


@dataclass(frozen=True)
class ClassOccurrence:
    """Uma aula de uma turma num dia, com o estado dela."""

    day: date
    group_id: str
    group_label: str
    discipline_label: str
    semester: str
    start_time: str
    end_time: str
    status: DayStatus


def parse_day(raw: object) -> Optional[date]:
    """`AAAA-MM-DD` em data; qualquer outra coisa (vazio, lixo) vira `None`."""
    try:
        return date.fromisoformat(str(raw).strip()) if raw else None
    except ValueError:
        return None


def day_status(
    day: date,
    class_group_id: str,
    period: Period,
    breaks: Iterable[Break] = (),
) -> DayStatus:
    """A turma tem aula neste dia? Considera o periodo do semestre e as datas sem aula.

    Nao olha o dia da semana: quem chama ja filtrou pelo horario semanal.
    """
    if period.start is not None and day < period.start:
        return DayStatus(BEFORE, f"o semestre comeca em {period.start:%d/%m/%Y}")
    if period.end is not None and day > period.end:
        return DayStatus(AFTER, f"o semestre terminou em {period.end:%d/%m/%Y}")
    for item in breaks:
        if item.covers(day, class_group_id):
            return DayStatus(BREAK, item.reason or "sem aula")
    return DayStatus(CLASS)


@dataclass(frozen=True)
class CalendarData:
    """O que se sabe do calendario letivo de um professor."""

    periods: dict[str, Period]
    breaks: dict[str, list[Break]]

    def period_of(self, semester: str) -> Period:
        return self.periods.get(semester, Period())

    def breaks_of(self, semester: str) -> list[Break]:
        return self.breaks.get(semester, [])


async def load_calendar(db, tutor_id: str) -> CalendarData:
    """Periodos e datas sem aula de um professor, por semestre."""
    periods = {
        row.code: Period(parse_day(row.start_date), parse_day(row.end_date))
        for row in (
            await db.execute(
                select(SemesterPeriodModel).where(SemesterPeriodModel.tutor_id == tutor_id)
            )
        ).scalars()
    }
    breaks: dict[str, list[Break]] = {}
    for row in (
        await db.execute(select(ClassBreakModel).where(ClassBreakModel.tutor_id == tutor_id))
    ).scalars():
        start, end = parse_day(row.date_from), parse_day(row.date_to)
        if start is None or end is None:
            continue
        breaks.setdefault(row.semester, []).append(
            Break(row.id, start, max(start, end), row.class_group_id or None, row.reason or "")
        )
    return CalendarData(periods, breaks)


async def occurrences(
    tutor_id: str,
    start: date,
    end: date,
    *,
    include_skipped: bool = False,
) -> list[ClassOccurrence]:
    """As aulas de todas as turmas ativas do professor entre duas datas, em ordem.

    Args:
        tutor_id: dono das turmas.
        start: primeiro dia, inclusive.
        end: ultimo dia, inclusive.
        include_skipped: inclui tambem os dias em que o horario cairia mas nao ha aula
            (feriado, fora do semestre), com o motivo no `status`.
    """
    async with database.AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(ClassGroupModel, ClassScheduleModel, DisciplineModel)
                .join(ClassScheduleModel, ClassScheduleModel.class_group_id == ClassGroupModel.id)
                .outerjoin(DisciplineModel, DisciplineModel.id == ClassGroupModel.discipline_id)
                .where(ClassGroupModel.tutor_id == tutor_id, ClassGroupModel.active.is_(True))
                .order_by(ClassGroupModel.code, ClassScheduleModel.weekday)
            )
        ).all()
        calendar = await load_calendar(db, tutor_id)

    found: list[ClassOccurrence] = []
    for group, schedule, discipline in rows:
        if not 0 <= schedule.weekday <= 6:
            continue
        label = " ".join(
            part
            for part in (
                (discipline.code if discipline and discipline.tutor_id == tutor_id else "") or "",
                (discipline.name if discipline and discipline.tutor_id == tutor_id else group.discipline) or "",
            )
            if part
        ).strip() or "Disciplina sem nome"
        group_label = " ".join(part for part in (group.code, group.name) if part).strip()
        period = calendar.period_of(group.semester)
        breaks = calendar.breaks_of(group.semester)

        day = start + timedelta(days=(schedule.weekday - start.weekday()) % 7)
        while day <= end:
            status = day_status(day, group.id, period, breaks)
            if status.has_class or include_skipped:
                found.append(
                    ClassOccurrence(
                        day=day,
                        group_id=group.id,
                        group_label=group_label,
                        discipline_label=label,
                        semester=group.semester,
                        start_time=schedule.start_time,
                        end_time=schedule.end_time,
                        status=status,
                    )
                )
            day += timedelta(days=7)
    found.sort(key=lambda item: (item.day, item.start_time, item.group_label))
    return found
