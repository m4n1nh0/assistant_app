"""Portal do aluno: o que cada aluno vê com a matrícula.

Junta, para o aluno, o que já existe espalhado pelo app: resumos das aulas das turmas dele,
resultado dos quizzes em grupo, pontos extras, materiais das disciplinas e, nas mentorias,
as atividades com a situação de cada entrega. Nada é copiado nem publicado à parte: o
portal lê o dado vivo, então o que o professor gera aparece sozinho.

O acesso é só pela matrícula, por decisão do professor. Por isso o portal mostra apenas o que
é do próprio aluno ou coletivo da turma (nunca a lista de colegas) e o router limita as
tentativas por IP.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    ClassGroupModel,
    LessonClassGroupModel,
    LessonModel,
    LessonPointModel,
    MaterialImprovementModel,
    MaterialModel,
    MentorshipActivityModel,
    MentorshipDeliveryModel,
    MentorshipFormModel,
    MentorshipSignupModel,
    ProjectGroupMemberModel,
    QuestionModel,
    QuizGroupConfigModel,
    QuizModel,
    StudentAnswerModel,
    StudentModel,
    StudentPortalModel,
)
from . import availability_service as availability
from . import mentorship_service as mentorship
from . import quiz_group_service as groups

MAX_LESSONS = 80
MAX_POINTS = 200


def normalize_enrollment(value: Optional[str]) -> str:
    return re.sub(r"[^0-9a-z]", "", (value or "").casefold())


def new_token() -> str:
    return secrets.token_urlsafe(12)


async def get_or_create_portal(db: AsyncSession, tutor_id: str) -> StudentPortalModel:
    portal = (await db.execute(select(StudentPortalModel).where(
        StudentPortalModel.tutor_id == tutor_id))).scalar_one_or_none()
    if portal is None:
        portal = StudentPortalModel(tutor_id=tutor_id, token=new_token(), active=True)
        db.add(portal)
        await db.commit()
        await db.refresh(portal)
    return portal


async def get_portal_by_token(db: AsyncSession, token: str) -> Optional[StudentPortalModel]:
    token = (token or "").strip()
    if not token:
        return None
    return (await db.execute(select(StudentPortalModel).where(
        StudentPortalModel.token == token))).scalar_one_or_none()


async def find_students(db: AsyncSession, tutor_id: str, enrollment: str) -> list[StudentModel]:
    """Registros ativos com essa matrícula (um por turma em que o aluno está)."""
    key = normalize_enrollment(enrollment)
    if not key:
        return []
    rows = (await db.execute(select(StudentModel).where(
        StudentModel.tutor_id == tutor_id, StudentModel.active.is_(True)))).scalars().all()
    return [s for s in rows if normalize_enrollment(s.external_id) == key]


def _class_label(item: ClassGroupModel) -> str:
    parts = [(item.code or "").strip(), (item.name or "").strip()]
    return " ".join(p for p in parts if p) or (item.discipline or "turma")


def _iso(value: Optional[datetime]) -> str:
    return value.isoformat() if value else ""


async def _classes(db: AsyncSession, students: list[StudentModel]) -> list[ClassGroupModel]:
    ids = {s.class_id for s in students if s.class_id}
    if not ids:
        return []
    return list((await db.execute(select(ClassGroupModel).where(
        ClassGroupModel.id.in_(ids)).order_by(ClassGroupModel.semester.desc(),
                                              ClassGroupModel.code))).scalars().all())


async def _lessons(db: AsyncSession, classes: list[ClassGroupModel],
                   mentorship_class_ids: set[str]) -> list[dict]:
    if not classes:
        return []
    by_class = {c.id: c for c in classes}
    links = (await db.execute(select(LessonClassGroupModel).where(
        LessonClassGroupModel.class_group_id.in_(by_class)))).scalars().all()
    lesson_class: dict[str, str] = {}
    for link in links:
        lesson_class.setdefault(link.lesson_id, link.class_group_id)
    if not lesson_class:
        return []
    lessons = (await db.execute(select(LessonModel).where(
        LessonModel.id.in_(lesson_class),
        LessonModel.summary.is_not(None),
    ).order_by(LessonModel.started_at.desc()).limit(MAX_LESSONS * 2))).scalars().all()
    out = []
    for lesson in lessons:
        if not (lesson.summary or "").strip():
            continue
        cls = by_class[lesson_class[lesson.id]]
        out.append({
            "id": lesson.id, "title": lesson.title or lesson.discipline,
            "discipline": lesson.discipline, "date": _iso(lesson.started_at),
            "class_label": _class_label(cls), "summary": lesson.summary.strip(),
            "mentorship": cls.id in mentorship_class_ids,
        })
        if len(out) >= MAX_LESSONS:
            break
    return out


async def _quizzes(db: AsyncSession, tutor_id: str, students: list[StudentModel],
                   discipline_ids: set[str]) -> list[dict]:
    """Resultado dos quizzes em grupo em que o aluno respondeu, pelo mesmo cálculo do ranking."""
    if not discipline_ids:
        return []
    student_ids = {s.id for s in students}
    my_members = {m.id for m in (await db.execute(select(ProjectGroupMemberModel).where(
        ProjectGroupMemberModel.student_id.in_(student_ids)))).scalars().all()}
    if not my_members:
        return []
    configs = (await db.execute(select(QuizGroupConfigModel).where(
        QuizGroupConfigModel.tutor_id == tutor_id,
        QuizGroupConfigModel.discipline_id.in_(discipline_ids)))).scalars().all()
    out = []
    for config in configs:
        quiz = await db.get(QuizModel, config.quiz_id)
        if quiz is None:
            continue
        question_ids = list((await db.execute(select(QuestionModel.id).where(
            QuestionModel.quiz_id == quiz.id))).scalars())
        if not question_ids:
            continue
        answers = list((await db.execute(select(StudentAnswerModel).where(
            StudentAnswerModel.question_id.in_(question_ids)))).scalars())
        ctx = await groups.load_context(db, config)
        mine = [row for row in groups.member_rows(answers, None, ctx)
                if row["member_id"] in my_members and row["answers"] > 0]
        if not mine:
            continue
        me = mine[0]
        ranking = groups.group_ranking_rows(answers, None, ctx)
        group_row = next((r for r in ranking if r["student_id"] == me["group_id"]), None)
        out.append({
            "quiz_id": quiz.id, "title": quiz.titulo, "date": _iso(quiz.created_at),
            "finished": quiz.status == "closed",
            "group_name": me["group_name"],
            "group_score": group_row["score"] if group_row else None,
            "position": group_row["position"] if group_row else None,
            "groups_total": len(ranking), "questions": len(question_ids),
            "my_score": me["score"], "my_correct": me["correct"], "my_answers": me["answers"],
            "mode": config.mode,
        })
    out.sort(key=lambda item: item["date"], reverse=True)
    return out


async def _points(db: AsyncSession, tutor_id: str, students: list[StudentModel]) -> dict:
    ids = {s.id for s in students}
    rows = (await db.execute(select(LessonPointModel).where(
        LessonPointModel.tutor_id == tutor_id, LessonPointModel.student_id.in_(ids)
    ).order_by(LessonPointModel.lesson_date.desc()))).scalars().all()
    total = sum(float(r.points or 0) for r in rows)
    return {
        "total": round(total, 2),
        "items": [{"date": _iso(r.lesson_date), "discipline": r.discipline,
                   "points": float(r.points or 0), "reason": (r.reason or "").strip()}
                  for r in rows[:MAX_POINTS]],
    }


async def _materials(db: AsyncSession, tutor_id: str, discipline_ids: set[str]) -> list[dict]:
    if not discipline_ids:
        return []
    rows = (await db.execute(select(MaterialModel).where(
        MaterialModel.tutor_id == tutor_id,
        MaterialModel.discipline_id.in_(discipline_ids),
        MaterialModel.group_id.is_(None),
    ).order_by(MaterialModel.created_at.desc()))).scalars().all()
    return [{"id": m.id, "title": m.title or m.filename, "filename": m.filename,
             "discipline": m.discipline, "pages": m.page_count or 0,
             "type": m.source_type, "date": _iso(m.created_at)} for m in rows]


async def _mentorships(db: AsyncSession, tutor_id: str, class_ids: set[str],
                       enrollment_key: str) -> list[dict]:
    if not class_ids:
        return []
    forms = (await db.execute(select(MentorshipFormModel).where(
        MentorshipFormModel.tutor_id == tutor_id,
        MentorshipFormModel.class_id.in_(class_ids)))).scalars().all()
    out = []
    for form in forms:
        signup = (await db.execute(select(MentorshipSignupModel).where(
            MentorshipSignupModel.form_id == form.id,
            MentorshipSignupModel.enrollment_key == enrollment_key,
            MentorshipSignupModel.status == "accepted"))).scalar_one_or_none()
        if signup is None:
            continue
        activities = await mentorship.list_activities(db, form.id)
        mine = {d.activity_id: d for d in (await db.execute(
            select(MentorshipDeliveryModel).where(
                MentorshipDeliveryModel.form_id == form.id,
                MentorshipDeliveryModel.signup_id == signup.id))).scalars().all()}
        out.append({
            "title": form.title, "class_id": form.class_id,
            "deliver_path": f"/education/mentorship-deliver/{form.token}",
            "activities": [{
                "title": a.title, "instructions": a.instructions, "due_at": _iso(a.due_at),
                "status": mentorship.delivery_status(a, mine.get(a.id)),
            } for a in activities],
        })
    return out


async def _availability(db: AsyncSession, tutor_id: str, classes: list[ClassGroupModel],
                        mentorship_ids: set[str]) -> dict:
    """A agenda de atendimento, só com as faixas que valem para este aluno."""
    wanted = {"todos"}
    if any(c.id not in mentorship_ids for c in classes):
        wanted.add("graduacao")
    if any(c.id in mentorship_ids for c in classes):
        wanted.add("mentoria")
    upcoming = await availability.occurrences(db, tutor_id, days=28, wanted=wanted)
    weekly = [
        {"weekday": s.weekday, "weekday_name": availability.WEEKDAY_NAMES[s.weekday],
         "start_time": s.start_time, "end_time": s.end_time, "mode": s.mode,
         "location": s.location, "audience": s.audience, "note": s.note}
        for s in await availability.list_slots(db, tutor_id, only_active=True)
        if s.audience in wanted
    ]
    return {"weekly": weekly, "upcoming": upcoming}


async def build_portal(db: AsyncSession, tutor_id: str, students: list[StudentModel],
                       enrollment: str) -> dict[str, Any]:
    """Tudo que o portal mostra para esse aluno."""
    classes = await _classes(db, students)
    class_ids = {c.id for c in classes}
    discipline_ids = {c.discipline_id for c in classes if c.discipline_id}
    mentorship_ids = {f.class_id for f in (await db.execute(select(MentorshipFormModel).where(
        MentorshipFormModel.tutor_id == tutor_id,
        MentorshipFormModel.class_id.in_(class_ids or {""})))).scalars().all() if f.class_id}
    return {
        "student": {"name": students[0].name},
        "classes": [{"id": c.id, "label": _class_label(c), "discipline": c.discipline,
                     "semester": c.semester, "mentorship": c.id in mentorship_ids}
                    for c in classes],
        "lessons": await _lessons(db, classes, mentorship_ids),
        "quizzes": await _quizzes(db, tutor_id, students, discipline_ids),
        "points": await _points(db, tutor_id, students),
        "materials": await _materials(db, tutor_id, discipline_ids),
        "mentorships": await _mentorships(
            db, tutor_id, class_ids & mentorship_ids, normalize_enrollment(enrollment)),
        "availability": await _availability(db, tutor_id, classes, mentorship_ids),
    }


async def material_text(db: AsyncSession, tutor_id: str, students: list[StudentModel],
                        material_id: str) -> Optional[MaterialModel]:
    """O material, só se for de uma disciplina das turmas do aluno."""
    material = await db.get(MaterialModel, material_id)
    if material is None or material.tutor_id != tutor_id or material.group_id:
        return None
    allowed = {c.discipline_id for c in await _classes(db, students) if c.discipline_id}
    return material if material.discipline_id in allowed else None


async def material_body(db: AsyncSession, material: MaterialModel) -> tuple[str, str]:
    """Texto que o aluno lê e o formato dele: a versão melhorada por IA (Markdown), se houver."""
    improved = await db.get(MaterialImprovementModel, material.id)
    if improved is not None and (improved.content or "").strip():
        return improved.content, "markdown"
    return material.content, "text"
