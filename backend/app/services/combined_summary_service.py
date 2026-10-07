"""Resumo conjunto de várias gravações do histórico.

Serve, sobretudo, ao dia de apresentações de grupo: o professor marca as gravações no
histórico e recebe um resumo só, com uma seção por grupo e a comparação entre elas. Vale
também para aulas, palestras e reuniões (e para uma mistura delas).

Cada gravação entra com o resumo que já tem; a que ainda não foi resumida é resumida na
hora (sem gravar o resultado na aula) e, se isso falhar, entra pela transcrição cortada.
O resumo conjunto parte desses textos, cada um sob o título da sua gravação, para não
misturar o que foi dito numa com o que foi dito em outra. O resultado não fica guardado:
é gerado sob demanda e sai no PDF.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    LessonModel,
    LessonSegmentModel,
    ProjectGroupModel,
)
from . import education_service

MIN_LESSONS = 2
MAX_LESSONS = 30

#: Teto do espaço reservado às fontes no pedido final, dividido entre as gravações. O
#: que vale é o da janela do modelo (veja `build_combined_summary`): passar dela faria o
#: resumo ser condensado em blocos, e a condensação perde o título de cada gravação.
SOURCES_CHAR_BUDGET = 50_000
#: Fatia da janela que as fontes podem ocupar; o resto é folga para o prompt.
WINDOW_SHARE = 0.85
MIN_BLOCK_CHARS = 400


class CombinedSummaryError(Exception):
    """O resumo conjunto não pode ser pedido; `message` é para o professor."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message = message
        self.status = status


def _date(value: Optional[datetime]) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


def _date_time(value: Optional[datetime]) -> str:
    return value.strftime("%d/%m %H:%M") if value else ""


def lesson_label(lesson: LessonModel, group_name: str = "") -> str:
    """Como a gravação se chama dentro do resumo conjunto."""
    when = _date_time(lesson.started_at)
    suffix = f" ({when})" if when else ""
    title = (lesson.title or "").strip()
    if lesson.kind == "apresentacao":
        name = group_name or title or "Apresentação de grupo"
        return f"{name}{suffix}"
    if lesson.kind == "palestra":
        return f"Palestra: {title or 'sem título'}{suffix}"
    if lesson.kind == "reuniao":
        return f"Reunião: {title or 'sem título'}{suffix}"
    base = (lesson.discipline or "").strip() or "Aula"
    return f"{base}{' — ' + title if title else ''}{suffix}"


def selection_kind(lessons: Sequence[LessonModel]) -> str:
    """Todas apresentações: resumo por grupo. Qualquer outra mistura: por gravação."""
    if lessons and all(item.kind == "apresentacao" for item in lessons):
        return education_service.SELECTION_PRESENTATIONS_KIND
    return education_service.SELECTION_KIND


def common_discipline(lessons: Sequence[LessonModel]) -> str:
    """A disciplina, quando todas as gravações são da mesma; senão, vazio."""
    found = {(item.discipline or "").strip() for item in lessons} - {""}
    return found.pop() if len(found) == 1 else ""


def selection_title(lessons: Sequence[LessonModel]) -> tuple[str, str]:
    """Título e subtítulo do documento: o que é, de que disciplina, de quando."""
    kinds = {item.kind for item in lessons}
    if kinds == {"apresentacao"}:
        title = "Apresentações dos grupos"
    elif kinds == {"aula"}:
        title = "Aulas selecionadas"
    elif kinds == {"palestra"}:
        title = "Palestras selecionadas"
    elif kinds == {"reuniao"}:
        title = "Reuniões selecionadas"
    else:
        title = "Gravações selecionadas"
    discipline = common_discipline(lessons)

    dates = sorted(item.started_at for item in lessons if item.started_at)
    if dates:
        first, last = _date(dates[0]), _date(dates[-1])
        period = first if first == last else f"{first} a {last}"
    else:
        period = ""
    subtitle = "  -  ".join(part for part in (
        discipline, period, f"{len(lessons)} gravações") if part)
    return title, subtitle


def _cut(text: str, limit: int) -> str:
    """Corta no fim de um parágrafo ou de uma frase, avisando que cortou."""
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    for mark in ("\n\n", "\n", ". "):
        index = head.rfind(mark)
        if index > limit * 0.6:
            head = head[: index + (1 if mark == ". " else 0)]
            break
    return f"{head.rstrip()} [...]"


async def _load(db: AsyncSession, tutor_id: str, lesson_ids: Sequence[str]):
    ids = list(dict.fromkeys(lesson_ids))
    if len(ids) < MIN_LESSONS:
        raise CombinedSummaryError(
            f"Escolha pelo menos {MIN_LESSONS} gravações para resumir juntas.")
    if len(ids) > MAX_LESSONS:
        raise CombinedSummaryError(
            f"Escolha no máximo {MAX_LESSONS} gravações por resumo.")
    lessons = list((await db.execute(select(LessonModel).where(
        LessonModel.tutor_id == tutor_id, LessonModel.id.in_(ids)))).scalars().all())
    if len(lessons) != len(ids):
        raise CombinedSummaryError("Há gravação que não foi encontrada.", 404)
    lessons.sort(key=lambda item: (item.started_at is None, item.started_at,
                                   item.title or "", item.id))
    group_ids = [item.group_id for item in lessons if item.group_id]
    groups = {}
    if group_ids:
        groups = {group.id: group.name for group in (await db.execute(
            select(ProjectGroupModel).where(
                ProjectGroupModel.tutor_id == tutor_id,
                ProjectGroupModel.id.in_(group_ids)))).scalars().all()}
    segments: dict[str, list[str]] = {item.id: [] for item in lessons}
    for row in (await db.execute(
        select(LessonSegmentModel)
        .where(LessonSegmentModel.lesson_id.in_([item.id for item in lessons]))
        .order_by(LessonSegmentModel.lesson_id, LessonSegmentModel.sequence)
    )).scalars().all():
        segments[row.lesson_id].append(row.text)
    return lessons, groups, segments


async def build_combined_summary(
    db: AsyncSession,
    tutor_id: str,
    lesson_ids: Sequence[str],
    *,
    style: str = education_service.STANDARD_SUMMARY_STYLE,
    focus: str = "",
    llm: Optional[str] = None,
) -> dict:
    """Resumo conjunto das gravações escolhidas; ver o módulo para o que entra em cada uma."""
    lessons, groups, segments = await _load(db, tutor_id, lesson_ids)
    style = education_service.normalize_summary_style(style)

    items: list[dict] = []
    skipped: list[dict] = []
    blocks: list[tuple[dict, str]] = []
    for lesson in lessons:
        group_name = groups.get(lesson.group_id or "", "")
        label = lesson_label(lesson, group_name)
        texts = segments.get(lesson.id, [])
        stored = (lesson.summary or "").strip()
        if stored:
            source, body = "resumo", stored
        elif texts:
            outcome = await education_service.generate_summary(
                discipline=lesson.discipline or "", title=lesson.title or "",
                segments=texts, llm=llm, focus=focus,
                style=education_service.STANDARD_SUMMARY_STYLE, kind=lesson.kind)
            generated = (outcome.get("summary") or "").strip()
            if generated:
                source, body = "gerado", generated
            else:
                source, body = "transcricao", "\n".join(texts)
        else:
            skipped.append(dict(id=lesson.id, label=label,
                                reason="sem resumo e sem transcrição"))
            continue
        info = dict(id=lesson.id, label=label, kind=lesson.kind,
                    group_name=group_name, source=source)
        items.append(info)
        blocks.append((info, body))

    if len(blocks) < MIN_LESSONS:
        raise CombinedSummaryError(
            "Menos de 2 gravações têm resumo ou transcrição para juntar: "
            + (", ".join(item["label"] for item in skipped) or "nenhuma") + ".")

    providers = await education_service._summary_provider_candidates(llm)
    window = education_service.summary_budget_chars(providers[0] if providers else "")
    sources_budget = min(SOURCES_CHAR_BUDGET, int(window * WINDOW_SHARE))
    per_block = max(MIN_BLOCK_CHARS, sources_budget // len(blocks))
    sources = [f"### {info['label']}\n{_cut(body, per_block)}" for info, body in blocks]

    used = [item for item in lessons if item.id in {info["id"] for info in items}]
    title, subtitle = selection_title(used)
    kind = selection_kind(used)
    outcome = await education_service.generate_summary(
        discipline=common_discipline(used), title=title, segments=sources,
        llm=llm, focus=focus, style=style, kind=kind)
    if not outcome.get("summary"):
        raise CombinedSummaryError(
            "Não foi possível gerar o resumo conjunto: "
            f"{outcome.get('error', 'sem resposta do modelo')}", 502)
    return dict(
        summary=outcome["summary"], llm=outcome.get("llm", ""), style=style,
        title=title, subtitle=subtitle, kind=kind, items=items, skipped=skipped,
        attempts=outcome.get("attempts", []),
    )
