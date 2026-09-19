"""Modo educacao: grava a aula em blocos, indexa e resume sob demanda."""

from collections import defaultdict
import asyncio
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
import json
import hashlib
import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from loguru import logger
from sqlalchemy import delete as sql_delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.database import (
    ClassGroupModel,
    ClassScheduleModel,
    LessonClassGroupModel,
    LessonModel,
    LessonPointModel,
    LessonSegmentModel,
    MaterialModel,
    QuizSourceModel,
    StudentModel,
    StudyTimeModel,
    ProjectGroupModel,
    ProjectGroupNameResolutionModel,
    ProjectGroupMemberModel,
    DisciplineModel,
    QuizModel,
    QuestionModel,
    StudentAnswerModel,
    AsyncSessionLocal,
    current_semester_code,
    get_db,
)
from ..core.security import get_current_user
from ..models.schemas import (
    BankQuestionBulkDelete,
    ClassGroupCreate,
    ClassGroupResponse,
    ClassGroupUpdate,
    ClassScheduleItem,
    EmbeddingStatusResponse,
    LessonCreate,
    LessonDetailResponse,
    LessonIndexStatusResponse,
    LessonPointCreate,
    LessonPointResponse,
    LessonReindexRequest,
    LessonReindexResponse,
    LessonResponse,
    LessonSearchResult,
    LessonSegmentIngestRequest,
    LessonSegmentIngestResponse,
    LessonSegmentResponse,
    LessonSegmentUpdate,
    SemesterResponse,
    SemesterUpdate,
    ExternalLessonSummaryRequest,
    LessonSummaryPromptResponse,
    LessonSummaryRequest,
    LessonSummaryResponse,
    LessonUpdate,
    LessonStatusUpdate,
    PointsReportEntry,
    PointsReportResponse,
    StudentBulkDeleteRequest,
    StudentBulkDeleteResponse,
    StudentCreate,
    StudentImportRequest,
    StudentImportResponse,
    StudentResponse,
    StudentUpdate,
    ProjectGroupTextRequest,
    ProjectGroupCommitRequest,
    ProjectGroupUpdate,
    ProjectGroupMemberLink,
    ProjectGroupSuggestedLinksCommit,
    DisciplineCreate,
    DisciplineResponse,
    DisciplineUpdate,
    QuestionOption,
    QuestionResponse,
    MaterialResponse,
    QuizCreateRequest,
    QuizFromQuestionsRequest,
    QuizJobSeenRequest,
    QuizResponse,
    QuizGenerateResponse,
    QuestionUpdate,
    StudentAnswerRequest,
    StudentAnswerResponse,
)
from ..services import (
    education_service,
    embedding_service,
    lesson_index_service,
    qdrant_service,
)
from ..services.voice_service import transcribe_audio, trim_transcript_overlap
from ..services.user_llm_config_service import (
    activate_user_llms,
    load_user_llm_runtime,
    reset_user_llms,
    user_llm_context,
)
from ..services import material_service, quiz_generator_service, quiz_job_service
from ..services.notification_service import send_notification
from ..services.runtime_config_service import load_notif_config

settings = get_settings()
router = APIRouter(
    prefix="/education",
    tags=["Education"],
    dependencies=[Depends(get_current_user)],
)


async def _owned_project_discipline(discipline_id: str, tutor_id: str,
                                    db: AsyncSession) -> DisciplineModel:
    item = await db.get(DisciplineModel, discipline_id)
    if item is None or item.tutor_id != tutor_id:
        raise HTTPException(404, "Disciplina não encontrada")
    return item


async def _owned_project_group(group_id: str, tutor_id: str,
                               db: AsyncSession) -> ProjectGroupModel:
    item = await db.get(ProjectGroupModel, group_id)
    if item is None or item.tutor_id != tutor_id:
        raise HTTPException(404, "Grupo não encontrado")
    return item


@router.post("/project-groups/preview")
async def preview_project_group_text(
    body: ProjectGroupTextRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from ..services.project_group_service import (
        parse_project_group_text, preview_project_groups, source_sha256,
    )

    discipline = await _owned_project_discipline(
        body.discipline_id, user["tutor_id"], db)
    try:
        parsed, context = parse_project_group_text(body.text)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    summary = await preview_project_groups(
        db, user["tutor_id"], discipline.id, parsed)
    return {**summary, "preview_sha256": source_sha256(body.text),
            "discipline_code": discipline.code,
            "discipline_name": discipline.name,
            "semester": discipline.semester,
            "list_context": context}


@router.post("/project-groups/import")
async def import_project_group_text(
    body: ProjectGroupCommitRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from ..services.project_group_service import (
        import_project_groups, parse_project_group_text, source_sha256,
    )

    if source_sha256(body.text) != body.preview_sha256:
        raise HTTPException(409, "A lista mudou depois da prévia; confira novamente")
    discipline = await _owned_project_discipline(
        body.discipline_id, user["tutor_id"], db)
    try:
        parsed, context = parse_project_group_text(body.text)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        return await import_project_groups(db, user["tutor_id"],
            discipline, parsed, context, body.member_links)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/project-groups")
async def list_project_groups(
    discipline_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(ProjectGroupModel).where(
        ProjectGroupModel.tutor_id == user["tutor_id"])
    if discipline_id:
        await _owned_project_discipline(discipline_id, user["tutor_id"], db)
        query = query.where(ProjectGroupModel.discipline_id == discipline_id)
    groups = (await db.execute(query.order_by(
        ProjectGroupModel.semester.desc(), ProjectGroupModel.name
    ))).scalars().all()
    if not groups:
        return []
    members = (await db.execute(select(ProjectGroupMemberModel).where(
        ProjectGroupMemberModel.group_id.in_([group.id for group in groups])
    ))).scalars().all()
    student_ids = [member.student_id for member in members if member.student_id]
    students = (await db.execute(select(StudentModel).where(
        StudentModel.tutor_id == user["tutor_id"],
        StudentModel.id.in_(student_ids or [""]),
    ))).scalars().all()
    by_student_id = {student.id: student.name for student in students}
    by_group_id: dict[str, list] = {}
    for member in members:
        by_group_id.setdefault(member.group_id, []).append(dict(
            id=member.id, name=member.name,
            student_id=member.student_id if member.student_id in by_student_id else None,
            student_name=by_student_id.get(member.student_id),
            source_note=member.source_note, position=member.position))
    # A disciplina vem pelo nome, e nao so pelo id: nome de grupo se repete
    # entre disciplinas ("Grupo 4" existe em todas), e a tela precisa dizer de
    # qual delas e o grupo.
    disciplinas = {
        item.id: _discipline_label(item)
        for item in (await db.execute(select(DisciplineModel).where(
            DisciplineModel.tutor_id == user["tutor_id"],
            DisciplineModel.id.in_({group.discipline_id for group in groups}),
        ))).scalars().all()
    }
    return [dict(id=group.id, discipline_id=group.discipline_id,
                 discipline=disciplinas.get(group.discipline_id, ""),
                 semester=group.semester, name=group.name,
                 project_title=group.project_title,
                 project_description=group.project_description,
                 review_notes=group.review_notes, score=group.score,
                 penalty_points=group.penalty_points,
                 source_note=group.source_note,
                 members=sorted(by_group_id.get(group.id, []),
                                key=lambda member: member["position"]))
            for group in groups]


@router.patch("/project-groups/{group_id}")
async def update_project_group(
    group_id: str,
    body: ProjectGroupUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    group = await _owned_project_group(group_id, user["tutor_id"], db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    await db.commit()
    return {"success": True}


@router.get("/project-groups/link-suggestions")
async def project_group_link_suggestions(
    discipline_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from ..services.project_group_service import (
        NameSimilarityIndex, learned_name_resolutions, roster_for_discipline,
        suggested_student_matches, unique_student_match,
    )
    await _owned_project_discipline(discipline_id, user["tutor_id"], db)
    roster = await roster_for_discipline(db, user["tutor_id"], discipline_id)
    learned = await learned_name_resolutions(db, user["tutor_id"], discipline_id, roster)
    index = NameSimilarityIndex(roster)
    groups = (await db.execute(select(ProjectGroupModel).where(
        ProjectGroupModel.tutor_id == user["tutor_id"],
        ProjectGroupModel.discipline_id == discipline_id,
    ))).scalars().all()
    members = (await db.execute(select(ProjectGroupMemberModel).where(
        ProjectGroupMemberModel.group_id.in_([group.id for group in groups] or [""]),
        ProjectGroupMemberModel.student_id.is_(None),
    ))).scalars().all()
    by_group = {group.id: group.name for group in groups}
    result = []
    for member in members:
        automatic = unique_student_match(member.name, roster, learned)
        result.append(dict(member_id=member.id, member_name=member.name,
                           group_name=by_group[member.group_id],
                           automatic_match=(dict(student_id=automatic.id,
                               student_name=automatic.name,
                               enrollment=automatic.external_id or "")
                               if automatic else None),
                           candidates=suggested_student_matches(member.name, roster, index)))
    return result


@router.post("/project-groups/link-suggestions/confirm")
async def confirm_project_group_link_suggestions(
    body: ProjectGroupSuggestedLinksCommit,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from ..services.project_group_service import (
        remember_name_resolution, roster_for_discipline,
    )
    await _owned_project_discipline(body.discipline_id, user["tutor_id"], db)
    roster = await roster_for_discipline(db, user["tutor_id"], body.discipline_id)
    valid_students = {student.id: student for student in roster}
    if len({link.member_id for link in body.links}) != len(body.links):
        raise HTTPException(422, "Integrante repetido na confirmação")
    groups = (await db.execute(select(ProjectGroupModel).where(
        ProjectGroupModel.tutor_id == user["tutor_id"],
        ProjectGroupModel.discipline_id == body.discipline_id,
    ))).scalars().all()
    group_ids = {group.id for group in groups}
    member_ids = [link.member_id for link in body.links]
    members = (await db.execute(select(ProjectGroupMemberModel).where(
        ProjectGroupMemberModel.id.in_(member_ids or [""]),
    ))).scalars().all()
    by_id = {member.id: member for member in members}
    for link in body.links:
        member = by_id.get(link.member_id)
        if (member is None or member.group_id not in group_ids
                or member.student_id is not None or link.student_id not in valid_students):
            raise HTTPException(409, "Sugestão desatualizada ou fora da disciplina; confira novamente")
    for link in body.links:
        member = by_id[link.member_id]
        member.student_id = link.student_id
        await remember_name_resolution(db, user["tutor_id"], body.discipline_id,
                                       member.name, valid_students[link.student_id])
    await db.commit()
    return {"linked": len(body.links)}


@router.patch("/project-groups/{group_id}/members/{member_id}")
async def link_project_group_member(
    group_id: str,
    member_id: str,
    body: ProjectGroupMemberLink,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from ..services.project_group_service import (
        remember_name_resolution, roster_for_discipline,
    )

    group = await _owned_project_group(group_id, user["tutor_id"], db)
    member = await db.get(ProjectGroupMemberModel, member_id)
    if member is None or member.group_id != group.id:
        raise HTTPException(404, "Integrante não encontrado")
    roster = await roster_for_discipline(db, user["tutor_id"], group.discipline_id)
    valid_students = {student.id: student for student in roster}
    if body.student_id:
        if body.student_id not in valid_students:
            raise HTTPException(422, "Aluno não pertence às turmas desta disciplina")
    member.student_id = body.student_id
    await remember_name_resolution(db, user["tutor_id"], group.discipline_id,
                                   member.name, valid_students.get(body.student_id))
    await db.commit()
    return {"success": True}


@router.delete("/project-groups/all")
async def delete_all_project_groups(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove todos os grupos deste professor, inclusive seus integrantes."""
    groups = (await db.execute(select(ProjectGroupModel.id).where(
        ProjectGroupModel.tutor_id == user["tutor_id"],
    ))).scalars().all()
    if groups:
        await db.execute(sql_delete(ProjectGroupMemberModel).where(
            ProjectGroupMemberModel.group_id.in_(groups)))
        await db.execute(sql_delete(ProjectGroupModel).where(
            ProjectGroupModel.id.in_(groups),
            ProjectGroupModel.tutor_id == user["tutor_id"]))
    await db.execute(sql_delete(ProjectGroupNameResolutionModel).where(
        ProjectGroupNameResolutionModel.tutor_id == user["tutor_id"]))
    await db.commit()
    return {"deleted": len(groups)}


@router.delete("/project-groups/{group_id}")
async def delete_project_group(
    group_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    group = await _owned_project_group(group_id, user["tutor_id"], db)
    members = (await db.execute(select(ProjectGroupMemberModel).where(
        ProjectGroupMemberModel.group_id == group.id
    ))).scalars().all()
    for member in members:
        await db.delete(member)
    await db.delete(group)
    await db.commit()
    return {"success": True}


@router.post("/study-times/import")
async def import_study_time_file(
    file: UploadFile = File(...),
    preview_sha256: str = Form(...),
    include_without_student: bool = Form(False),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reimportar a mesma chave substitui os minutos e corrige o registro."""
    from ..services.study_time_service import (
        belongs_to_scope, import_study_times, owned_discipline_scope,
        parse_study_time_xlsx,
    )

    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(422, "Selecione uma planilha .xlsx")
    content = await file.read()
    if len(content) > 10_000_000:
        raise HTTPException(413, "Planilha maior que 10 MB")
    if hashlib.sha256(content).hexdigest() != preview_sha256:
        raise HTTPException(409, "A planilha mudou depois da prévia; visualize novamente")
    try:
        rows, blank_rows = parse_study_time_xlsx(content)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
    scope = await owned_discipline_scope(db, user["tutor_id"])
    if not scope:
        raise HTTPException(422, "Cadastre suas disciplinas com codigo antes de importar")
    accepted = [row for row in rows if belongs_to_scope(
        row["discipline_code"], scope)]
    skipped_blank_minutes = sum(belongs_to_scope(
        row["discipline_code"], scope) for row in blank_rows)
    skipped_other_disciplines = len(rows) - len(accepted) + len(blank_rows) - skipped_blank_minutes
    from ..services.study_time_service import (
        student_enrollment_index, match_study_student, remove_unmatched_existing,
    )
    by_enrollment = await student_enrollment_index(db, user["tutor_id"])
    without_student = sum(match_study_student(row, by_enrollment) is None
                          for row in accepted)
    chosen = (accepted if include_without_student else
              [row for row in accepted if match_study_student(row, by_enrollment)])
    removed_without_student = 0
    if not include_without_student:
        unmatched_rows = [row for row in accepted
                          if match_study_student(row, by_enrollment) is None]
        removed_without_student = await remove_unmatched_existing(
            db, user["tutor_id"], unmatched_rows)
    if not chosen:
        await db.commit()
        return dict(created=0, updated=0, linked=0, pending=0,
                    skipped_blank_minutes=skipped_blank_minutes,
                    skipped_other_disciplines=skipped_other_disciplines,
                    without_student_not_imported=without_student if not include_without_student else 0,
                    removed_without_student=removed_without_student)
    result = await import_study_times(db, user["tutor_id"], chosen)
    return {**result, "skipped_blank_minutes": skipped_blank_minutes,
            "skipped_other_disciplines": skipped_other_disciplines,
            "without_student_not_imported": without_student if not include_without_student else 0,
            "removed_without_student": removed_without_student}


@router.post("/study-times/preview")
async def preview_study_time_file(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lê o arquivo e mostra o destino das linhas sem gravar nada."""
    from ..services.study_time_service import (
        belongs_to_scope, owned_discipline_scope, parse_study_time_xlsx,
        preview_study_times,
    )

    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(422, "Selecione uma planilha .xlsx")
    content = await file.read()
    if len(content) > 10_000_000:
        raise HTTPException(413, "Planilha maior que 10 MB")
    try:
        rows, blank_rows = parse_study_time_xlsx(content)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
    scope = await owned_discipline_scope(db, user["tutor_id"])
    if not scope:
        raise HTTPException(422, "Cadastre suas disciplinas com código antes de importar")
    accepted = [row for row in rows if belongs_to_scope(row["discipline_code"], scope)]
    blank_mine = sum(belongs_to_scope(row["discipline_code"], scope)
                     for row in blank_rows)
    summary = await preview_study_times(db, user["tutor_id"], accepted)
    registered = (await db.execute(select(DisciplineModel).where(
        DisciplineModel.tutor_id == user["tutor_id"]
    ))).scalars().all()
    registered_periods = {code: sorted({item.semester for item in registered
                          if item.code.strip().upper() == code and item.semester})
                          for code in summary["by_discipline"]}
    return {**summary, "preview_sha256": hashlib.sha256(content).hexdigest(),
            "registered_periods": registered_periods,
            "accepted_with_minutes": len(accepted),
            "blank_minutes_in_my_disciplines": blank_mine,
            "outside_my_disciplines": len(rows) - len(accepted)
              + len(blank_rows) - blank_mine}


@router.post("/study-times/reconcile")
async def reconcile_study_times(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from ..services.study_time_service import owned_discipline_scope, purge_outside_scope

    scope = await owned_discipline_scope(db, user["tutor_id"])
    removed = await purge_outside_scope(db, user["tutor_id"], scope)
    return {"removed_outside_scope": removed}


@router.get("/study-times")
async def list_study_times(
    discipline: Optional[str] = None,
    group: Optional[str] = None,
    course: Optional[str] = None,
    pending_only: bool = False,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from ..services.study_time_service import belongs_to_scope, owned_discipline_scope

    scope = await owned_discipline_scope(db, user["tutor_id"])
    # A turma da planilha ("15034853") e a sequencia da instituicao, que nao e o
    # codigo que o professor usa em sala ("3001"). As duas viajam juntas: a
    # importada para conferir a origem, a do cadastro para agrupar e filtrar.
    query = select(
        StudyTimeModel, StudentModel.name,
        ClassGroupModel.id, ClassGroupModel.code, ClassGroupModel.name,
    ).outerjoin(
        StudentModel, (StudentModel.id == StudyTimeModel.student_id)
        & (StudentModel.tutor_id == user["tutor_id"])
    ).outerjoin(
        ClassGroupModel, (ClassGroupModel.id == StudentModel.class_id)
        & (ClassGroupModel.tutor_id == user["tutor_id"])
    ).where(StudyTimeModel.tutor_id == user["tutor_id"])
    if discipline:
        query = query.where(StudyTimeModel.discipline_code == discipline)
    if group:
        query = query.where(StudyTimeModel.group_sequence == group)
    if course:
        query = query.where(StudyTimeModel.course == course)
    if pending_only:
        query = query.where(StudyTimeModel.student_id.is_(None))
    records = (await db.execute(query.order_by(
        StudyTimeModel.discipline_code, StudyTimeModel.group_sequence,
        StudyTimeModel.enrollment
    ))).all()
    return [dict(id=item.id, enrollment=item.enrollment, student_id=item.student_id,
                 student_name=name, discipline_code=item.discipline_code,
                 group_sequence=item.group_sequence, course=item.course,
                 semester=item.semester, minutes=item.minutes,
                 class_id=class_id,
                 class_code=class_code or "",
                 class_label=" ".join(
                     part for part in (class_code or "", class_name or "") if part
                 ))
            for item, name, class_id, class_code, class_name in records
            if belongs_to_scope(item.discipline_code, scope)]


@router.delete("/study-times/all")
async def delete_all_study_times(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove todas as linhas de tempo importadas deste professor."""
    result = await db.execute(sql_delete(StudyTimeModel).where(
        StudyTimeModel.tutor_id == user["tutor_id"]))
    await db.commit()
    return {"deleted": max(0, result.rowcount or 0)}


@router.delete("/study-times/bulk")
async def delete_study_times_for_period(
    discipline_code: str,
    semester: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permite retirar uma importação de teste de uma disciplina e período."""
    from ..services.study_time_service import belongs_to_scope, owned_discipline_scope

    scope = await owned_discipline_scope(db, user["tutor_id"])
    if not belongs_to_scope(discipline_code, scope):
        raise HTTPException(422, "Disciplina não cadastrada para este professor")
    items = (await db.execute(select(StudyTimeModel).where(
        StudyTimeModel.tutor_id == user["tutor_id"],
        StudyTimeModel.discipline_code == discipline_code.strip().upper(),
        StudyTimeModel.semester == semester.strip(),
    ))).scalars().all()
    for item in items:
        await db.delete(item)
    await db.commit()
    return {"deleted": len(items)}


@router.delete("/study-times/{record_id}")
async def delete_study_time(
    record_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = (await db.execute(select(StudyTimeModel).where(
        StudyTimeModel.id == record_id,
        StudyTimeModel.tutor_id == user["tutor_id"]
    ))).scalar_one_or_none()
    if item is None:
        raise HTTPException(404, "Registro nao encontrado")
    await db.delete(item)
    await db.commit()
    return {"success": True}

# --- Mapeadores ------------------------------------------------------------


_WEEKDAYS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")
_PRESENTATION_STUDENTS = (
    ("DEMO001", "2026001", "Ana Souza (Demo)"),
    ("DEMO002", "2026002", "Bruno Lima (Demo)"),
    ("DEMO003", "2026003", "Carla Mendes (Demo)"),
)


def _presentation_id(tutor_id: str, semester: str, kind: str) -> str:
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"assistant-app:presentation:{tutor_id}:{semester}:{kind}",
    ))


def _discipline_label(item: DisciplineModel) -> str:
    parts = [(item.code or "").strip(), (item.name or "").strip()]
    label = " - ".join(part for part in parts if part)
    return label or "disciplina"


def _discipline_response(
    item: DisciplineModel,
    class_count: int = 0,
) -> DisciplineResponse:
    return DisciplineResponse(
        id=item.id,
        code=item.code or "",
        name=item.name or "",
        label=_discipline_label(item),
        semester=getattr(item, "semester", "") or current_semester_code(),
        active=bool(item.active),
        class_count=class_count,
    )


def _class_label(item: ClassGroupModel) -> str:
    parts = [(item.code or "").strip(), (item.name or "").strip()]
    label = " ".join(part for part in parts if part)
    return label or (item.discipline or "").strip() or "turma"


def _schedule_label(schedules: Sequence[ClassScheduleModel]) -> str:
    parts = []
    for item in sorted(schedules, key=lambda row: (row.weekday, row.start_time)):
        day = _WEEKDAYS[item.weekday] if 0 <= item.weekday < 7 else "?"
        parts.append(f"{day} {item.start_time}".strip())
    return ", ".join(parts)


@router.post("/demo/presentation")
async def create_presentation_demo(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Creates an idempotent, clearly identified classroom demonstration."""
    tutor_id = user["tutor_id"]
    semester = current_semester_code()
    local_now = datetime.now(ZoneInfo("America/Sao_Paulo"))

    discipline_id = _presentation_id(tutor_id, semester, "discipline")
    discipline = await db.get(DisciplineModel, discipline_id)
    discipline_created = discipline is None
    if discipline is None:
        discipline = DisciplineModel(
            id=discipline_id,
            tutor_id=tutor_id,
            code="DEMO-IA",
            name="Inteligencia Artificial Aplicada",
            semester=semester,
            active=True,
        )
        db.add(discipline)

    class_id = _presentation_id(tutor_id, semester, "class")
    group = await db.get(ClassGroupModel, class_id)
    class_created = group is None
    if group is None:
        group = ClassGroupModel(
            id=class_id,
            tutor_id=tutor_id,
            code=f"DEMO-{semester}",
            name="Turma de apresentacao",
            discipline_id=discipline_id,
            discipline="DEMO-IA - Inteligencia Artificial Aplicada",
            semester=semester,
            active=True,
        )
        db.add(group)

    schedule_id = _presentation_id(
        tutor_id, semester, f"schedule-{local_now.weekday()}"
    )
    if await db.get(ClassScheduleModel, schedule_id) is None:
        db.add(ClassScheduleModel(
            id=schedule_id,
            class_group_id=class_id,
            weekday=local_now.weekday(),
            start_time="19:00",
            end_time="21:00",
        ))

    students_created = 0
    students_updated = 0
    for legacy_key, enrollment, name in _PRESENTATION_STUDENTS:
        # A chave legada preserva o ID dos exemplos ja criados. Assim, executar
        # novamente a demonstracao converte DEMO001..003 em matriculas numericas
        # sem duplicar os alunos existentes.
        student_id = _presentation_id(tutor_id, semester, f"student-{legacy_key}")
        existing_student = await db.get(StudentModel, student_id)
        if existing_student is not None:
            if existing_student.external_id != enrollment:
                existing_student.external_id = enrollment
                students_updated += 1
            continue
        db.add(StudentModel(
            id=student_id,
            tutor_id=tutor_id,
            name=name,
            class_id=class_id,
            class_group=f"DEMO-{semester} Turma de apresentacao",
            discipline="DEMO-IA - Inteligencia Artificial Aplicada",
            external_id=enrollment,
            aliases=[],
            notes="Dado ficticio criado para demonstracao.",
            active=True,
        ))
        students_created += 1

    await db.commit()
    return {
        "discipline_id": discipline_id,
        "class_id": class_id,
        "semester": semester,
        "discipline_created": discipline_created,
        "class_created": class_created,
        "students_created": students_created,
        "students_updated": students_updated,
        "message": (
            f"Demonstracao pronta: DEMO-IA, turma DEMO-{semester}, "
            "com 3 alunos ficticios e horario no dia de hoje."
        ),
    }


def _class_response(
    item: ClassGroupModel,
    student_count: int = 0,
    schedules: Sequence[ClassScheduleModel] = (),
) -> ClassGroupResponse:
    ordered = sorted(schedules, key=lambda row: (row.weekday, row.start_time))
    return ClassGroupResponse(
        id=item.id,
        code=item.code or "",
        name=item.name or "",
        discipline_id=item.discipline_id,
        discipline=item.discipline or "",
        semester=getattr(item, "semester", "") or "",
        label=_class_label(item),
        active=bool(item.active),
        student_count=student_count,
        schedules=[
            ClassScheduleItem(
                weekday=row.weekday,
                start_time=row.start_time or "",
                end_time=row.end_time or "",
            )
            for row in ordered
        ],
        schedule_label=_schedule_label(ordered),
    )


def _student_response(item: StudentModel) -> StudentResponse:
    return StudentResponse(
        id=item.id,
        tutor_id=item.tutor_id,
        name=item.name,
        class_id=item.class_id,
        class_group=item.class_group or "",
        discipline=item.discipline or "",
        external_id=item.external_id,
        aliases=list(item.aliases or []),
        notes=item.notes,
        active=bool(item.active),
        created_at=item.created_at,
    )


def _lesson_response(
    item: LessonModel,
    classes: Sequence[ClassGroupModel] = (),
    group_name: str = "",
) -> LessonResponse:
    return LessonResponse(
        id=item.id,
        tutor_id=item.tutor_id,
        kind=getattr(item, "kind", "aula") or "aula",
        group_id=getattr(item, "group_id", None),
        group_name=group_name,
        discipline=item.discipline,
        semester=getattr(item, "semester", "") or "",
        title=item.title or "",
        class_group=item.class_group or "",
        class_ids=[group.id for group in classes],
        class_labels=[_class_label(group) for group in classes],
        teacher=item.teacher,
        status=item.status,
        started_at=item.started_at,
        ended_at=item.ended_at,
        summary=item.summary,
        summary_llm=item.summary_llm,
        summary_at=item.summary_at,
        summary_style=getattr(item, "summary_style", None),
        segment_count=item.segment_count or 0,
        transcript_chars=item.transcript_chars or 0,
        metadata=item.metadata_ or {},
    )


def _segment_response(item: LessonSegmentModel) -> LessonSegmentResponse:
    return LessonSegmentResponse(
        id=item.id,
        lesson_id=item.lesson_id,
        sequence=item.sequence,
        text=item.text,
        confidence=item.confidence,
        duration_ms=item.duration_ms,
        indexed=bool(item.indexed),
        created_at=item.created_at,
    )


def _point_response(item: LessonPointModel) -> LessonPointResponse:
    return LessonPointResponse(
        id=item.id,
        lesson_id=item.lesson_id,
        student_id=item.student_id,
        student_name=item.student_name,
        points=item.points,
        reason=item.reason,
        discipline=item.discipline or "",
        lesson_date=item.lesson_date,
        source=item.source,
        confidence=item.confidence,
        quote=item.quote,
        created_at=item.created_at,
    )


# --- Helpers ---------------------------------------------------------------


def _semester_code(value: str, *, default_current: bool = True) -> str:
    code = (value or "").strip()
    if not code and default_current:
        return current_semester_code()
    parts = code.split(".")
    if len(parts) != 2 or not parts[0].isdigit() or parts[1] not in {"1", "2"}:
        raise HTTPException(422, "Semestre invalido. Use o formato 2026.1 ou 2026.2")
    if len(parts[0]) != 4:
        raise HTTPException(422, "Semestre invalido. Use o formato 2026.1 ou 2026.2")
    return code


async def _get_lesson(lesson_id: str, tutor_id: str, db: AsyncSession) -> LessonModel:
    lesson = await db.get(LessonModel, lesson_id)
    if lesson is None or lesson.tutor_id != tutor_id:
        raise HTTPException(404, "Aula nao encontrada")
    return lesson


async def _classes_of(
    lesson_ids: Sequence[str],
    db: AsyncSession,
) -> Dict[str, List[ClassGroupModel]]:
    """Turmas de cada aula, numa consulta so."""
    if not lesson_ids:
        return {}
    result = await db.execute(
        select(LessonClassGroupModel.lesson_id, ClassGroupModel)
        .join(
            ClassGroupModel,
            ClassGroupModel.id == LessonClassGroupModel.class_group_id,
        )
        .where(LessonClassGroupModel.lesson_id.in_(list(lesson_ids)))
    )
    grouped: Dict[str, List[ClassGroupModel]] = defaultdict(list)
    for lesson_id, group in result.all():
        grouped[lesson_id].append(group)
    for items in grouped.values():
        items.sort(key=_class_label)
    return grouped


async def _schedules_of(
    class_ids: Sequence[str],
    db: AsyncSession,
) -> Dict[str, List[ClassScheduleModel]]:
    if not class_ids:
        return {}
    result = await db.execute(
        select(ClassScheduleModel).where(
            ClassScheduleModel.class_group_id.in_(list(class_ids))
        )
    )
    grouped: Dict[str, List[ClassScheduleModel]] = defaultdict(list)
    for row in result.scalars().all():
        grouped[row.class_group_id].append(row)
    return grouped


async def _set_schedules(
    group: ClassGroupModel,
    items: Sequence[ClassScheduleItem],
    db: AsyncSession,
) -> List[ClassScheduleModel]:
    """Refaz os dias da turma. Lista vazia = turma sem dia definido."""
    await db.execute(
        sql_delete(ClassScheduleModel).where(
            ClassScheduleModel.class_group_id == group.id
        )
    )
    rows = [
        ClassScheduleModel(
            class_group_id=group.id,
            weekday=item.weekday,
            start_time=(item.start_time or "").strip(),
            end_time=(item.end_time or "").strip(),
        )
        for item in items
    ]
    for row in rows:
        db.add(row)
    return rows


async def _resolve_discipline(
    discipline_id: Optional[str],
    tutor_id: str,
    db: AsyncSession,
) -> Optional[DisciplineModel]:
    if not discipline_id:
        return None
    discipline = await db.get(DisciplineModel, discipline_id)
    if discipline is None or discipline.tutor_id != tutor_id:
        raise HTTPException(404, "Disciplina nao encontrada")
    if not getattr(discipline, "active", True):
        raise HTTPException(409, "A disciplina pertence a um semestre encerrado")
    return discipline


async def _resolve_classes(
    class_ids: Sequence[str],
    tutor_id: str,
    db: AsyncSession,
) -> List[ClassGroupModel]:
    """Valida que as turmas informadas existem e sao do proprio usuario."""
    wanted = [item.strip() for item in class_ids if item and item.strip()]
    if not wanted:
        return []
    result = await db.execute(
        select(ClassGroupModel).where(
            ClassGroupModel.tutor_id == tutor_id,
            ClassGroupModel.id.in_(wanted),
        )
    )
    found = list(result.scalars().all())
    if len(found) != len(set(wanted)):
        raise HTTPException(404, "Turma nao encontrada")
    return found


async def _link_classes(
    lesson: LessonModel,
    classes: Sequence[ClassGroupModel],
    db: AsyncSession,
) -> None:
    """Refaz o vinculo da aula e reescreve os campos de texto derivados.

    `class_group` e `discipline` na aula viram rotulo: uma turma escreve o nome
    dela, varias deixam a turma vazia — que continua sendo como o resto do
    codigo le "vale para todas".
    """
    await db.execute(
        sql_delete(LessonClassGroupModel).where(
            LessonClassGroupModel.lesson_id == lesson.id
        )
    )
    for group in classes:
        db.add(
            LessonClassGroupModel(lesson_id=lesson.id, class_group_id=group.id)
        )
    if len(classes) == 1:
        lesson.class_group = _class_label(classes[0])
        lesson.semester = classes[0].semester or lesson.semester
        if classes[0].discipline:
            lesson.discipline = classes[0].discipline
    elif classes:
        lesson.class_group = ""
        disciplines = {group.discipline for group in classes if group.discipline}
        if len(disciplines) == 1:
            lesson.discipline = disciplines.pop()
        semesters = {group.semester for group in classes if group.semester}
        if len(semesters) == 1:
            lesson.semester = semesters.pop()


async def _roster(lesson: LessonModel, db: AsyncSession) -> List[Dict[str, Any]]:
    """Alunos que podem ser citados nesta aula.

    Com turmas vinculadas, sao os alunos delas — varias turmas numa aula
    reunida entram juntas. Aluno sem turma nenhuma no cadastro segue valendo
    para qualquer aula, e aula antiga sem vinculo cai na comparacao por texto.
    """
    result = await db.execute(
        select(StudentModel).where(
            StudentModel.tutor_id == lesson.tutor_id,
            StudentModel.active.is_(True),
        )
    )
    students = list(result.scalars().all())
    linked = {group.id for group in (await _classes_of([lesson.id], db)).get(lesson.id, [])}
    lesson_group = (lesson.class_group or "").strip()
    lesson_discipline = (lesson.discipline or "").strip()
    roster = []
    for student in students:
        group = (student.class_group or "").strip()
        discipline = (student.discipline or "").strip()
        if linked:
            if student.class_id and student.class_id not in linked:
                continue
            if not student.class_id and (group or discipline):
                continue
        else:
            if group and lesson_group and group != lesson_group:
                continue
            if discipline and lesson_discipline and discipline != lesson_discipline:
                continue
        roster.append({
            "id": student.id,
            "name": student.name,
            "aliases": list(student.aliases or []),
        })
    return roster


async def _existing_points(lesson_id: str, db: AsyncSession) -> List[Dict[str, Any]]:
    result = await db.execute(
        select(LessonPointModel).where(LessonPointModel.lesson_id == lesson_id)
    )
    return [
        {
            "student_name": item.student_name,
            "points": item.points,
            "reason": item.reason,
            "quote": item.quote,
        }
        for item in result.scalars().all()
    ]


def _parse_date(value: Optional[str], *, end_of_day: bool = False) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, f"Data invalida: {value}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if end_of_day and parsed.time() == time.min:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    return parsed


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _ingest_segment(
    *,
    lesson: LessonModel,
    text: str,
    confidence: float,
    duration_ms: int,
    extract_points: bool,
    db: AsyncSession,
) -> LessonSegmentIngestResponse:
    clean = " ".join((text or "").split())
    previous = await db.scalar(
        select(LessonSegmentModel)
        .where(LessonSegmentModel.lesson_id == lesson.id)
        .order_by(LessonSegmentModel.sequence.desc())
        .limit(1)
    )
    if previous is not None:
        clean = trim_transcript_overlap(previous.text, clean)
    if len(clean) < settings.education_min_segment_chars:
        # Bloco de silencio ou ruido: nao vale gastar embedding nem LLM.
        return LessonSegmentIngestResponse(
            lesson=_lesson_response(lesson),
            skipped_reason="trecho curto demais para indexar",
        )

    sequence = (lesson.segment_count or 0) + 1
    segment = LessonSegmentModel(
        lesson_id=lesson.id,
        tutor_id=lesson.tutor_id,
        sequence=sequence,
        text=clean,
        confidence=confidence,
        duration_ms=duration_ms,
    )
    db.add(segment)
    lesson.segment_count = sequence
    lesson.transcript_chars = (lesson.transcript_chars or 0) + len(clean)
    await db.commit()
    await db.refresh(segment)
    await db.refresh(lesson)

    started = _as_utc(lesson.started_at)
    indexed = False
    try:
        written = await qdrant_service.index_lesson_segments(
            tutor_id=lesson.tutor_id,
            lesson_id=lesson.id,
            discipline=lesson.discipline,
            segments=[{
                "id": segment.id,
                "text": clean,
                "sequence": sequence,
                "class_group": lesson.class_group or "",
                "lesson_date": started.date().isoformat(),
                "lesson_ts": int(started.timestamp()),
            }],
        )
        indexed = written > 0
    except Exception as e:
        # A transcricao ja esta no banco; a indexacao pode ser refeita depois
        # sem perder a aula, entao nao derrubamos a gravacao por isso.
        logger.warning(f"Falha ao indexar trecho {segment.id}: {e}")

    if indexed:
        segment.indexed = True
        segment.qdrant_point_id = segment.id
        segment.embedding_model = embedding_service.active_signature()
        await db.commit()
        await db.refresh(segment)

    created_points: List[LessonPointModel] = []
    if extract_points:
        try:
            roster = await _roster(lesson, db)
            entries = await education_service.extract_points(text=clean, roster=roster)
            existing = await _existing_points(lesson.id, db)
            for entry in entries:
                if education_service.is_duplicate_point(entry, existing):
                    continue
                point = LessonPointModel(
                    tutor_id=lesson.tutor_id,
                    lesson_id=lesson.id,
                    segment_id=segment.id,
                    student_id=entry["student_id"],
                    student_name=entry["student_name"],
                    points=entry["points"],
                    reason=entry["reason"],
                    discipline=lesson.discipline,
                    lesson_date=started,
                    source="extracted",
                    confidence=entry["confidence"],
                    quote=entry["quote"],
                )
                db.add(point)
                created_points.append(point)
                existing.append(entry)
            if created_points:
                await db.commit()
                for point in created_points:
                    await db.refresh(point)
        except Exception as e:
            logger.warning(f"Falha ao extrair pontuacoes do trecho {segment.id}: {e}")

    return LessonSegmentIngestResponse(
        segment=_segment_response(segment),
        indexed=indexed,
        points=[_point_response(item) for item in created_points],
        lesson=_lesson_response(lesson),
    )


# --- Disciplinas -----------------------------------------------------------


@router.get("/disciplines", response_model=List[DisciplineResponse])
async def list_disciplines(
    active_only: bool = True,
    semester: Optional[str] = None,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lista as disciplinas do usuario."""
    query = select(DisciplineModel).where(DisciplineModel.tutor_id == user["tutor_id"])
    if active_only:
        query = query.where(DisciplineModel.active.is_(True))
    if semester:
        query = query.where(DisciplineModel.semester == _semester_code(semester))
    result = await db.execute(
        query.order_by(
            DisciplineModel.semester.desc(),
            DisciplineModel.code,
            DisciplineModel.name,
        )
    )
    disciplines = list(result.scalars().all())

    counts = dict(
        (
            await db.execute(
                select(ClassGroupModel.discipline_id, func.count(ClassGroupModel.id))
                .where(ClassGroupModel.tutor_id == user["tutor_id"])
                .group_by(ClassGroupModel.discipline_id)
            )
        ).all()
    )
    return [_discipline_response(item, counts.get(item.id, 0)) for item in disciplines]


@router.post("/disciplines", response_model=DisciplineResponse)
async def create_discipline(
    body: DisciplineCreate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cadastra uma disciplina."""
    code = body.code.strip()
    name = body.name.strip()
    semester = _semester_code(body.semester)
    if not code and not name:
        raise HTTPException(422, "Informe o codigo ou o nome da disciplina")

    duplicate = (
        await db.execute(
            select(DisciplineModel).where(
                DisciplineModel.tutor_id == user["tutor_id"],
                DisciplineModel.code == code,
                DisciplineModel.name == name,
                DisciplineModel.semester == semester,
            )
        )
    ).scalars().first()
    if duplicate is not None:
        raise HTTPException(409, "Disciplina ja cadastrada")

    discipline = DisciplineModel(
        tutor_id=user["tutor_id"],
        code=code,
        name=name,
        semester=semester,
    )
    db.add(discipline)
    await db.commit()
    await db.refresh(discipline)
    return _discipline_response(discipline)


@router.patch("/disciplines/{discipline_id}", response_model=DisciplineResponse)
async def update_discipline(
    discipline_id: str,
    body: DisciplineUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Altera codigo, nome ou cor de uma disciplina."""
    discipline = await db.get(DisciplineModel, discipline_id)
    if discipline is None or discipline.tutor_id != user["tutor_id"]:
        raise HTTPException(404, "Disciplina nao encontrada")

    if body.code is not None:
        discipline.code = body.code.strip()
    if body.name is not None:
        discipline.name = body.name.strip()
    if body.semester is not None:
        discipline.semester = _semester_code(body.semester)
    if body.active is not None:
        discipline.active = body.active

    # A disciplina e copiada como texto na turma e no aluno: renomear desce.
    groups = (
        await db.execute(
            select(ClassGroupModel).where(ClassGroupModel.discipline_id == discipline.id)
        )
    ).scalars().all()
    label = _discipline_label(discipline)
    for group in groups:
        group.discipline = label
        group.semester = discipline.semester
        students = (
            await db.execute(
                select(StudentModel).where(StudentModel.class_id == group.id)
            )
        ).scalars().all()
        for student in students:
            student.discipline = label

    await db.commit()
    await db.refresh(discipline)
    return _discipline_response(discipline, len(groups))


@router.get("/semesters", response_model=List[SemesterResponse])
async def list_semesters(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lista os semestres letivos com dados registrados."""
    disciplines = list(
        (
            await db.execute(
                select(DisciplineModel).where(
                    DisciplineModel.tutor_id == user["tutor_id"]
                )
            )
        ).scalars().all()
    )
    groups = list(
        (
            await db.execute(
                select(ClassGroupModel).where(
                    ClassGroupModel.tutor_id == user["tutor_id"]
                )
            )
        ).scalars().all()
    )
    codes = sorted(
        {item.semester for item in disciplines if item.semester},
        reverse=True,
    )
    return [
        SemesterResponse(
            code=code,
            active=any(
                item.active for item in disciplines if item.semester == code
            ),
            discipline_count=sum(item.semester == code for item in disciplines),
            class_count=sum(item.semester == code for item in groups),
        )
        for code in codes
    ]


@router.patch("/semesters/{semester}", response_model=SemesterResponse)
async def update_semester(
    semester: str,
    body: SemesterUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Altera o rotulo ou as datas de um semestre."""
    code = _semester_code(semester)
    disciplines = list(
        (
            await db.execute(
                select(DisciplineModel).where(
                    DisciplineModel.tutor_id == user["tutor_id"],
                    DisciplineModel.semester == code,
                )
            )
        ).scalars().all()
    )
    if not disciplines:
        raise HTTPException(404, "Semestre nao encontrado")
    for discipline in disciplines:
        discipline.active = body.active
    class_count = (
        await db.execute(
            select(func.count(ClassGroupModel.id)).where(
                ClassGroupModel.tutor_id == user["tutor_id"],
                ClassGroupModel.semester == code,
            )
        )
    ).scalar_one()
    await db.commit()
    return SemesterResponse(
        code=code,
        active=body.active,
        discipline_count=len(disciplines),
        class_count=class_count,
    )


@router.delete("/disciplines/{discipline_id}")
async def delete_discipline(
    discipline_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove uma disciplina e desvincula o que dependia dela."""
    discipline = await db.get(DisciplineModel, discipline_id)
    if discipline is None or discipline.tutor_id != user["tutor_id"]:
        raise HTTPException(404, "Disciplina nao encontrada")

    linked = (
        await db.execute(
            select(func.count(ClassGroupModel.id)).where(
                ClassGroupModel.discipline_id == discipline.id
            )
        )
    ).scalar_one()
    if linked:
        raise HTTPException(
            409,
            f"A disciplina tem {linked} turma(s). Remova ou mova as turmas antes.",
        )

    await db.delete(discipline)
    await db.commit()
    return {"success": True}


# --- Turmas ----------------------------------------------------------------


@router.get("/classes", response_model=List[ClassGroupResponse])
async def list_classes(
    discipline: Optional[str] = None,
    active_only: bool = True,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lista as turmas, opcionalmente filtradas por disciplina e semestre."""
    query = select(ClassGroupModel).where(
        ClassGroupModel.tutor_id == user["tutor_id"]
    )
    if discipline:
        query = query.where(ClassGroupModel.discipline == discipline)
    if active_only:
        # Turmas de uma disciplina encerrada somem dos fluxos do semestre
        # atual, mas continuam intactas para historico e relatorios.
        active_disciplines = select(DisciplineModel.id).where(
            DisciplineModel.tutor_id == user["tutor_id"],
            DisciplineModel.active.is_(True),
        )
        query = query.where(
            ClassGroupModel.active.is_(True),
            or_(
                ClassGroupModel.discipline_id.is_(None),
                ClassGroupModel.discipline_id.in_(active_disciplines),
            ),
        )
    result = await db.execute(
        query.order_by(ClassGroupModel.discipline, ClassGroupModel.code)
    )
    groups = list(result.scalars().all())

    counts = dict(
        (
            await db.execute(
                select(StudentModel.class_id, func.count(StudentModel.id))
                .where(
                    StudentModel.tutor_id == user["tutor_id"],
                    StudentModel.active.is_(True),
                )
                .group_by(StudentModel.class_id)
            )
        ).all()
    )
    schedules = await _schedules_of([group.id for group in groups], db)
    return [
        _class_response(
            group,
            counts.get(group.id, 0),
            schedules.get(group.id, []),
        )
        for group in groups
    ]


@router.post("/classes", response_model=ClassGroupResponse)
async def create_class(
    body: ClassGroupCreate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cadastra uma turma, com horarios semanais quando informados."""
    discipline_row = await _resolve_discipline(body.discipline_id, user["tutor_id"], db)
    code = body.code.strip()
    discipline = _discipline_label(discipline_row) if discipline_row else body.discipline.strip()
    semester = (
        discipline_row.semester if discipline_row else current_semester_code()
    )
    if not code and not discipline:
        raise HTTPException(422, "Informe ao menos o codigo da turma")

    duplicate = await db.execute(
        select(ClassGroupModel).where(
            ClassGroupModel.tutor_id == user["tutor_id"],
            ClassGroupModel.code == code,
            ClassGroupModel.discipline == discipline,
            ClassGroupModel.semester == semester,
        )
    )
    existing = duplicate.scalars().first()
    if existing is not None:
        raise HTTPException(409, "Ja existe uma turma com esse codigo nessa disciplina")

    group = ClassGroupModel(
        tutor_id=user["tutor_id"],
        code=code,
        name=body.name.strip(),
        discipline_id=discipline_row.id if discipline_row else None,
        discipline=discipline,
        semester=semester,
    )
    db.add(group)
    await db.flush()
    schedules = await _set_schedules(group, body.schedules, db)
    await db.commit()
    await db.refresh(group)
    return _class_response(group, 0, schedules)


@router.patch("/classes/{class_id}", response_model=ClassGroupResponse)
async def update_class(
    class_id: str,
    body: ClassGroupUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Altera dados e horarios de uma turma."""
    group = await db.get(ClassGroupModel, class_id)
    if group is None or group.tutor_id != user["tutor_id"]:
        raise HTTPException(404, "Turma nao encontrada")

    if body.code is not None:
        group.code = body.code.strip()
    if body.name is not None:
        group.name = body.name.strip()
    if body.discipline_id is not None:
        discipline_row = await _resolve_discipline(body.discipline_id, user["tutor_id"], db)
        group.discipline_id = discipline_row.id if discipline_row else None
        group.discipline = _discipline_label(discipline_row) if discipline_row else ""
        group.semester = (
            discipline_row.semester if discipline_row else current_semester_code()
        )
    elif body.discipline is not None:
        group.discipline = body.discipline.strip()
    if body.active is not None:
        group.active = body.active

    schedules = (await _schedules_of([group.id], db)).get(group.id, [])
    if body.schedules is not None:
        schedules = await _set_schedules(group, body.schedules, db)

    # Os campos de texto do aluno sao copia da turma: renomear tem de descer.
    students = (
        await db.execute(
            select(StudentModel).where(StudentModel.class_id == group.id)
        )
    ).scalars().all()
    for student in students:
        student.class_group = _class_label(group)
        student.discipline = group.discipline or ""

    await db.commit()
    await db.refresh(group)
    return _class_response(group, len(students), schedules)


@router.delete("/classes/{class_id}")
async def delete_class(
    class_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove uma turma e os vinculos dela com aulas e alunos."""
    group = await db.get(ClassGroupModel, class_id)
    if group is None or group.tutor_id != user["tutor_id"]:
        raise HTTPException(404, "Turma nao encontrada")

    linked = (
        await db.execute(
            select(func.count(StudentModel.id)).where(
                StudentModel.class_id == group.id
            )
        )
    ).scalar_one()
    if linked:
        raise HTTPException(
            409,
            f"A turma tem {linked} aluno(s). Mova ou remova os alunos antes.",
        )

    await db.execute(
        sql_delete(LessonClassGroupModel).where(
            LessonClassGroupModel.class_group_id == group.id
        )
    )
    await db.execute(
        sql_delete(ClassScheduleModel).where(
            ClassScheduleModel.class_group_id == group.id
        )
    )
    await db.delete(group)
    await db.commit()
    return {"success": True}


# --- Alunos ----------------------------------------------------------------


@router.get("/students", response_model=List[StudentResponse])
async def list_students(
    class_id: Optional[str] = None,
    class_group: Optional[str] = None,
    discipline: Optional[str] = None,
    active_only: bool = True,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lista os alunos, opcionalmente filtrados por turma."""
    query = select(StudentModel).where(StudentModel.tutor_id == user["tutor_id"])
    if class_id:
        query = query.where(StudentModel.class_id == class_id)
    if class_group:
        query = query.where(StudentModel.class_group == class_group)
    if discipline:
        query = query.where(StudentModel.discipline == discipline)
    if active_only:
        query = query.where(StudentModel.active.is_(True))
    result = await db.execute(query.order_by(StudentModel.name))
    return [_student_response(item) for item in result.scalars().all()]


@router.post("/students", response_model=StudentResponse)
async def create_student(
    body: StudentCreate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cadastra um aluno em uma turma."""
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Nome do aluno e obrigatorio")
    external_id = (body.external_id or "").strip() or None
    if external_id:
        duplicate = await db.execute(
            select(StudentModel).where(
                StudentModel.tutor_id == user["tutor_id"],
                StudentModel.external_id == external_id,
            )
        )
        if duplicate.scalars().first() is not None:
            raise HTTPException(409, "Matricula ja cadastrada")
    group = None
    if body.class_id:
        group = (await _resolve_classes([body.class_id], user["tutor_id"], db))[0]
    student = StudentModel(
        tutor_id=user["tutor_id"],
        name=name,
        class_id=group.id if group else None,
        class_group=_class_label(group) if group else body.class_group.strip(),
        discipline=(group.discipline if group else body.discipline).strip(),
        external_id=external_id,
        aliases=[alias.strip() for alias in body.aliases if alias.strip()],
        notes=body.notes,
        active=body.active,
    )
    db.add(student)
    await db.commit()
    await db.refresh(student)
    return _student_response(student)


@router.post("/students/source-preview")
async def preview_student_roster_source(
    file: Optional[UploadFile] = File(None),
    pasted_text: str = Form(""),
    user: dict = Depends(get_current_user),
    _llm_context: None = Depends(user_llm_context),
):
    """Lê fontes variadas; a gravação continua no fluxo de prévia da turma."""
    from ..services.student_roster_source_service import preview_student_roster_source as parse

    if file is None and not pasted_text.strip():
        raise HTTPException(422, "Envie um arquivo ou cole a lista de alunos")
    content = await file.read() if file is not None else None
    filename = file.filename if file is not None else ""
    preview = None
    parse_error = ""
    try:
        preview = await asyncio.to_thread(parse, content, filename, pasted_text)
    except (ValueError, UnicodeError) as exc:
        parse_error = str(exc)

    analysis_text = (preview or {}).pop("_analysis_text", "")
    if not analysis_text and pasted_text.strip():
        analysis_text = pasted_text
    if not analysis_text and content and not filename.lower().endswith(
            (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".xlsx")):
        analysis_text = content.decode("utf-8", errors="replace")
    if not analysis_text and content and filename.lower().endswith(
            (".png", ".jpg", ".jpeg", ".webp", ".bmp")):
        from ..services import ocr_service
        if ocr_service.is_available():
            try:
                analysis_text = await asyncio.to_thread(
                    ocr_service.text_from_image, content)
            except Exception:
                analysis_text = ""

    needs_agent = preview is None or bool(preview.get("warnings")) or (
        float(preview.get("analysis_confidence", 0)) < 0.8)
    agent_result = None
    if needs_agent and analysis_text:
        from ..services.llm_status_service import get_ready_llms
        from ..services.student_roster_agent_service import interpret_student_roster
        agent_result = await interpret_student_roster(analysis_text, await get_ready_llms())

    if agent_result:
        students = agent_result["students"]
        preview = {
            "source_type": (preview or {}).get("source_type", "fonte interpretada"),
            "columns": ["Matrícula", "Nome"],
            "rows": [[item["enrollment"], item["name"]] for item in students],
            "enrollment_column": 0,
            "name_column": 1,
            "class_column": -1,
            "discipline_column": -1,
            "class_values": ([agent_result["class_code"]]
                             if agent_result["class_code"] else []),
            "discipline_values": ([agent_result["discipline"]]
                                  if agent_result["discipline"] else []),
            "warnings": ["Dados interpretados por IA: confira antes de importar."],
            "source_text": (preview or {}).get("source_text", ""),
            "analysis_origin": f"agente {agent_result['provider']}",
            "analysis_confidence": agent_result["confidence"],
            "row_confidences": [item["confidence"] for item in students],
            "semester_hint": agent_result["semester"],
        }
    if preview is None:
        raise HTTPException(422, parse_error or
                            "Não consegui identificar matrícula e nome na fonte")
    preview.setdefault("row_confidences", [])
    preview.setdefault("semester_hint", "")
    preview["agent_attempted"] = needs_agent
    return preview


@router.post("/students/import", response_model=StudentImportResponse)
async def import_students(
    body: StudentImportRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Importa alunos em lote, normalmente de uma planilha ou do SIA.

    Aluno ja existente na turma e atualizado em vez de duplicado.
    """
    group = None
    if body.class_id:
        group = (await _resolve_classes([body.class_id], user["tutor_id"], db))[0]
        class_group = _class_label(group)
        discipline = (group.discipline or "").strip()
    else:
        class_group = body.class_group.strip()
        discipline = body.discipline.strip()
        if not class_group:
            raise HTTPException(422, "Turma e obrigatoria para importar alunos")
        if not discipline:
            raise HTTPException(422, "Disciplina e obrigatoria para importar alunos")

    if not body.students and not body.deactivate_ids:
        raise HTTPException(422, "Nada a importar: sem alunos e sem desativacoes")

    incoming: dict[str, tuple[str, str]] = {}
    for index, item in enumerate(body.students, start=2):
        enrollment = item.enrollment.strip()
        name = item.name.strip()
        if not enrollment or not name:
            raise HTTPException(
                422,
                f"Linha {index}: matricula e nome sao obrigatorios",
            )
        key = enrollment.casefold()
        if key in incoming:
            raise HTTPException(422, f"Matricula duplicada no arquivo: {enrollment}")
        incoming[key] = (enrollment, name)

    # A matricula e procurada **dentro da turma**, nao no tutor inteiro. O mesmo
    # aluno cursando duas disciplinas tem um registro em cada uma, com a presenca
    # e a pontuacao daquela disciplina. Buscando global, importar a turma de uma
    # disciplina *movia* o aluno (class_id e uma coluna so) e esvaziava a outra -
    # era isso que deixava umas turmas cheias e outras faltando gente.
    scope = select(StudentModel).where(
        StudentModel.tutor_id == user["tutor_id"],
        StudentModel.external_id.is_not(None),
    )
    if group is not None:
        scope = scope.where(StudentModel.class_id == group.id)
    else:
        scope = scope.where(
            StudentModel.class_group == class_group,
            StudentModel.discipline == discipline,
        )
    result = await db.execute(scope)
    existing = {
        student.external_id.strip().casefold(): student
        for student in result.scalars().all()
        if student.external_id and student.external_id.strip()
    }

    created = 0
    updated = 0
    for key, (enrollment, name) in incoming.items():
        student = existing.get(key)
        if student is None:
            db.add(
                StudentModel(
                    tutor_id=user["tutor_id"],
                    external_id=enrollment,
                    name=name,
                    class_id=group.id if group else None,
                    class_group=class_group,
                    discipline=discipline,
                    aliases=[],
                    active=True,
                )
            )
            created += 1
            continue

        student.external_id = enrollment
        student.name = name
        student.class_id = group.id if group else student.class_id
        student.class_group = class_group
        student.discipline = discipline
        student.active = True
        updated += 1

    deactivated = await _deactivate_missing(
        db,
        tutor_id=user["tutor_id"],
        student_ids=body.deactivate_ids,
        class_id=group.id if group else None,
        keep_enrollments=set(incoming),
    )

    await db.commit()
    return StudentImportResponse(
        created=created,
        updated=updated,
        total=created + updated,
        deactivated=deactivated,
    )


async def _deactivate_missing(
    db: AsyncSession,
    *,
    tutor_id: str,
    student_ids: list[str],
    class_id: str | None,
    keep_enrollments: set[str],
) -> int:
    """Desativa os alunos que a interface marcou como ausentes do arquivo.

    Desativar, e nao apagar: presenca, pontos e respostas de quiz guardam o
    `student_id` sem chave estrangeira, entao remover a linha deixaria esse
    historico apontando para ninguem.

    A lista vem do cliente, mas quem decide e o servidor: aluno de outra turma
    ou que esta no arquivo importado nunca e desativado.

    Returns:
        Quantos alunos foram desativados agora.
    """
    wanted = {item.strip() for item in student_ids if item and item.strip()}
    if not wanted:
        return 0

    result = await db.execute(
        select(StudentModel).where(
            StudentModel.tutor_id == tutor_id,
            StudentModel.id.in_(wanted),
        )
    )

    deactivated = 0
    for student in result.scalars().all():
        if class_id is not None and student.class_id != class_id:
            continue
        enrollment = (student.external_id or "").strip().casefold()
        if enrollment and enrollment in keep_enrollments:
            continue
        if not student.active:
            continue
        student.active = False
        deactivated += 1
    return deactivated


@router.patch("/students/{student_id}", response_model=StudentResponse)
async def update_student(
    student_id: str,
    body: StudentUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Altera dados de um aluno."""
    student = await db.get(StudentModel, student_id)
    if student is None or student.tutor_id != user["tutor_id"]:
        raise HTTPException(404, "Aluno nao encontrado")

    if body.class_id is not None:
        group = (await _resolve_classes([body.class_id], user["tutor_id"], db))[0]
        student.class_id = group.id
        student.class_group = _class_label(group)
        student.discipline = group.discipline or ""
    for field in ("name", "class_group", "discipline", "external_id", "notes", "active"):
        value = getattr(body, field)
        if value is not None:
            setattr(student, field, value)
    if body.aliases is not None:
        student.aliases = [alias.strip() for alias in body.aliases if alias.strip()]

    await db.commit()
    await db.refresh(student)
    return _student_response(student)


@router.post("/students/bulk-delete", response_model=StudentBulkDeleteResponse)
async def bulk_delete_students(
    body: StudentBulkDeleteRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove varios alunos, sempre dentro de uma unica turma do tutor."""
    class_id = body.class_id.strip()
    student_ids = {
        student_id.strip()
        for student_id in body.student_ids
        if student_id.strip()
    }
    if not class_id or not student_ids:
        raise HTTPException(422, "Turma e alunos sao obrigatorios")

    result = await db.execute(
        select(StudentModel).where(
            StudentModel.tutor_id == user["tutor_id"],
            StudentModel.class_id == class_id,
            StudentModel.id.in_(student_ids),
        )
    )
    students = list(result.scalars().all())
    for student in students:
        await db.delete(student)
    await db.commit()
    return StudentBulkDeleteResponse(
        requested=len(student_ids),
        deleted=len(students),
    )


@router.delete("/students/{student_id}")
async def delete_student(
    student_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove um aluno."""
    student = await db.get(StudentModel, student_id)
    if student is None or student.tutor_id != user["tutor_id"]:
        raise HTTPException(404, "Aluno nao encontrado")
    await db.delete(student)
    await db.commit()
    return {"ok": True}


# --- Aulas -----------------------------------------------------------------


@router.post("/lessons", response_model=LessonResponse)
async def create_lesson(
    body: LessonCreate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Abre uma gravacao e passa a aceitar os blocos de audio.

    A gravacao nasce aberta: os trechos chegam por
    `POST /education/lessons/{id}/segments` enquanto ela acontece, e nao em um
    upload unico no fim. Vale para os tres tipos - o que muda e o que precisa
    estar informado antes de comecar.
    """
    tutor_id = user["tutor_id"]
    kind = body.kind
    title = body.title.strip()
    semester = _semester_code(body.semester)
    group_name = ""
    group_id = None
    classes: Sequence[ClassGroupModel] = ()
    discipline = body.discipline.strip()

    if kind == "apresentacao":
        group = await db.get(ProjectGroupModel, (body.group_id or "").strip())
        if group is None or group.tutor_id != tutor_id:
            raise HTTPException(404, "Grupo de projeto nao encontrado")
        group_id = group.id
        group_name = group.name
        # Disciplina e semestre vem do grupo: sao dele, e repetir na tela so
        # daria chance de divergir do cadastro.
        semester = group.semester or semester
        owner = await db.get(DisciplineModel, group.discipline_id)
        if owner is not None and owner.tutor_id == tutor_id:
            discipline = _discipline_label(owner)
        title = title or f"Apresentacao: {group.name}"
    elif kind == "palestra":
        if not title:
            raise HTTPException(422, "Informe o titulo da palestra")
        # Palestra nao pertence a disciplina nem a turma: a disciplina pode
        # ficar vazia, e o titulo e o que identifica a gravacao.
        classes = ()
    else:
        classes = await _resolve_classes(body.class_ids, tutor_id, db)
        semesters = {group.semester for group in classes if group.semester}
        if len(semesters) > 1:
            raise HTTPException(422, "As turmas pertencem a semestres diferentes")
        if not discipline and classes:
            disciplines = {group.discipline for group in classes if group.discipline}
            discipline = disciplines.pop() if len(disciplines) == 1 else ""
        if not discipline:
            raise HTTPException(422, "Disciplina e obrigatoria")

    lesson = LessonModel(
        tutor_id=tutor_id,
        kind=kind,
        group_id=group_id,
        discipline=discipline,
        semester=semester,
        title=title,
        class_group=body.class_group.strip() if kind == "aula" else "",
        teacher=body.teacher,
        started_at=_as_utc(body.started_at) if body.started_at else datetime.now(timezone.utc),
        metadata_=body.metadata,
    )
    db.add(lesson)
    await db.flush()
    if classes:
        await _link_classes(lesson, classes, db)
    await db.commit()
    await db.refresh(lesson)
    return _lesson_response(lesson, classes, group_name=group_name)


@router.get("/lessons", response_model=List[LessonResponse])
async def list_lessons(
    discipline: Optional[str] = None,
    kind: Optional[str] = None,
    group_id: Optional[str] = None,
    semester: Optional[str] = None,
    class_group: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lista as aulas, filtradas por disciplina, turma ou periodo."""
    query = select(LessonModel).where(LessonModel.tutor_id == user["tutor_id"])
    if discipline:
        query = query.where(LessonModel.discipline == discipline)
    if kind:
        query = query.where(LessonModel.kind == kind)
    if group_id:
        query = query.where(LessonModel.group_id == group_id)
    if semester:
        query = query.where(LessonModel.semester == _semester_code(semester))
    if class_group:
        query = query.where(LessonModel.class_group == class_group)
    start = _parse_date(date_from)
    end = _parse_date(date_to, end_of_day=True)
    if start:
        query = query.where(LessonModel.started_at >= start)
    if end:
        query = query.where(LessonModel.started_at <= end)

    result = await db.execute(query.order_by(LessonModel.started_at.desc()).limit(limit))
    lessons = list(result.scalars().all())
    classes = await _classes_of([item.id for item in lessons], db)
    groups = await _group_names([item.group_id for item in lessons], user["tutor_id"], db)
    return [
        _lesson_response(
            item,
            classes.get(item.id, []),
            group_name=groups.get(item.group_id or "", ""),
        )
        for item in lessons
    ]


async def _group_names(
    group_ids: Sequence[Optional[str]],
    tutor_id: str,
    db: AsyncSession,
) -> Dict[str, str]:
    """Nome de cada grupo de projeto citado, para a tela nao mostrar id."""
    wanted = {item for item in group_ids if item}
    if not wanted:
        return {}
    rows = (await db.execute(
        select(ProjectGroupModel.id, ProjectGroupModel.name).where(
            ProjectGroupModel.id.in_(wanted),
            ProjectGroupModel.tutor_id == tutor_id,
        )
    )).all()
    return {group_id: name for group_id, name in rows}


@router.get("/lessons/{lesson_id}", response_model=LessonDetailResponse)
async def get_lesson(
    lesson_id: str,
    include_segments: bool = True,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Devolve a aula com transcricao, trechos e pontos."""
    lesson = await _get_lesson(lesson_id, user["tutor_id"], db)

    segments: List[LessonSegmentResponse] = []
    if include_segments:
        result = await db.execute(
            select(LessonSegmentModel)
            .where(LessonSegmentModel.lesson_id == lesson_id)
            .order_by(LessonSegmentModel.sequence)
        )
        segments = [_segment_response(item) for item in result.scalars().all()]

    result = await db.execute(
        select(LessonPointModel)
        .where(LessonPointModel.lesson_id == lesson_id)
        .order_by(LessonPointModel.created_at)
    )
    points = [_point_response(item) for item in result.scalars().all()]

    classes = (await _classes_of([lesson.id], db)).get(lesson.id, [])
    return LessonDetailResponse(
        **_lesson_response(lesson, classes).model_dump(),
        segments=segments,
        points=points,
    )


@router.patch("/lessons/{lesson_id}", response_model=LessonResponse)
async def update_lesson(
    lesson_id: str,
    body: LessonUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Altera titulo, disciplina, turmas ou anotacoes de uma aula."""
    lesson = await _get_lesson(lesson_id, user["tutor_id"], db)
    for field in ("discipline", "title", "class_group", "teacher"):
        value = getattr(body, field)
        if value is not None:
            setattr(lesson, field, value)
    if body.metadata is not None:
        lesson.metadata_ = body.metadata

    classes = (await _classes_of([lesson.id], db)).get(lesson.id, [])
    if body.class_ids is not None:
        # Corrigir o vinculo depois da aula e o caminho para consertar
        # pontuacao que ficou na turma errada.
        classes = await _resolve_classes(body.class_ids, user["tutor_id"], db)
        await _link_classes(lesson, classes, db)

    await db.commit()
    await db.refresh(lesson)
    return _lesson_response(lesson, classes)


@router.delete("/lessons/{lesson_id}")
async def delete_lesson(
    lesson_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a aula e os trechos dela, inclusive do indice vetorial."""
    lesson = await _get_lesson(lesson_id, user["tutor_id"], db)
    await db.execute(
        sql_delete(LessonSegmentModel).where(LessonSegmentModel.lesson_id == lesson_id)
    )
    await db.execute(
        sql_delete(LessonPointModel).where(LessonPointModel.lesson_id == lesson_id)
    )
    await db.execute(
        sql_delete(LessonClassGroupModel).where(
            LessonClassGroupModel.lesson_id == lesson_id
        )
    )
    await db.delete(lesson)
    await db.commit()
    await qdrant_service.delete_lesson_points(lesson_id=lesson_id)
    return {"ok": True}


@router.post("/lessons/{lesson_id}/audio", response_model=LessonSegmentIngestResponse)
async def ingest_lesson_audio(
    lesson_id: str,
    file: UploadFile = File(...),
    language: str = Form("pt"),
    duration_ms: int = Form(0),
    extract_points: bool = Form(True),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _llm_context: None = Depends(user_llm_context),
):
    """Recebe um bloco de audio da aula, transcreve, indexa e extrai pontos."""
    lesson = await _get_lesson(lesson_id, user["tutor_id"], db)
    if lesson.status == "closed":
        raise HTTPException(409, "Aula ja encerrada")

    audio_bytes = await file.read()
    context_parts = [lesson.semester or "", lesson.discipline, lesson.title or ""]
    stt = await transcribe_audio(
        audio_bytes,
        language,
        context="; ".join(part.strip() for part in context_parts if part.strip()),
    )
    if not stt.transcript.strip():
        return LessonSegmentIngestResponse(
            lesson=_lesson_response(lesson),
            skipped_reason="nenhuma fala reconhecida no bloco",
        )

    return await _ingest_segment(
        lesson=lesson,
        text=stt.transcript,
        confidence=stt.confidence,
        duration_ms=duration_ms,
        extract_points=extract_points,
        db=db,
    )


@router.post("/lessons/{lesson_id}/segments", response_model=LessonSegmentIngestResponse)
async def ingest_lesson_text(
    lesson_id: str,
    body: LessonSegmentIngestRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _llm_context: None = Depends(user_llm_context),
):
    """Ingestao de texto ja transcrito no cliente (STT nativo do sistema)."""
    lesson = await _get_lesson(lesson_id, user["tutor_id"], db)
    if lesson.status == "closed":
        raise HTTPException(409, "Aula ja encerrada")

    return await _ingest_segment(
        lesson=lesson,
        text=body.text,
        confidence=body.confidence,
        duration_ms=body.duration_ms,
        extract_points=body.extract_points,
        db=db,
    )


@router.patch(
    "/lessons/{lesson_id}/segments/{segment_id}",
    response_model=LessonSegmentResponse,
)
async def update_lesson_segment(
    lesson_id: str,
    segment_id: str,
    body: LessonSegmentUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Corrige uma transcricao e substitui o vetor usado na busca."""
    lesson = await _get_lesson(lesson_id, user["tutor_id"], db)
    segment = await db.get(LessonSegmentModel, segment_id)
    if (
        segment is None
        or segment.lesson_id != lesson.id
        or segment.tutor_id != user["tutor_id"]
    ):
        raise HTTPException(404, "Trecho nao encontrado")

    clean = " ".join(body.text.split())
    if not clean:
        raise HTTPException(422, "A transcricao nao pode ficar vazia")

    old_length = len(segment.text or "")
    segment.text = clean
    segment.indexed = False
    segment.qdrant_point_id = None
    segment.embedding_model = None
    lesson.transcript_chars = max(
        0,
        (lesson.transcript_chars or 0) - old_length + len(clean),
    )
    # Um resumo existente foi criado com o texto anterior e precisa ser
    # gerado novamente para nao continuar exibindo a palavra errada.
    lesson.summary = None
    lesson.summary_llm = None
    lesson.summary_at = None
    lesson.summary_style = None
    await db.commit()
    await db.refresh(segment)

    started = _as_utc(lesson.started_at)
    try:
        written = await qdrant_service.index_lesson_segments(
            tutor_id=lesson.tutor_id,
            lesson_id=lesson.id,
            discipline=lesson.discipline,
            segments=[{
                "id": segment.id,
                "text": clean,
                "sequence": segment.sequence,
                "class_group": lesson.class_group or "",
                "lesson_date": started.date().isoformat(),
                "lesson_ts": int(started.timestamp()),
            }],
        )
        if written:
            segment.indexed = True
            segment.qdrant_point_id = segment.id
            segment.embedding_model = embedding_service.active_signature()
            await db.commit()
            await db.refresh(segment)
    except Exception as e:
        # A correcao fica salva no MySQL; o reindexador recupera o vetor
        # depois caso o Qdrant esteja temporariamente indisponivel.
        logger.warning(f"Falha ao reindexar trecho corrigido {segment.id}: {e}")

    return _segment_response(segment)


# Um resumo de aula inteira e longo, mas nao ilimitado: o corpo chega de um
# cliente e a coluna e Text. O teto so barra payload absurdo.
_MAX_SUMMARY_CHARS = 200_000


async def _lesson_transcript(lesson_id: str, db: AsyncSession) -> List[str]:
    result = await db.execute(
        select(LessonSegmentModel)
        .where(LessonSegmentModel.lesson_id == lesson_id)
        .order_by(LessonSegmentModel.sequence)
    )
    return [item.text for item in result.scalars().all()]


async def _store_summary(
    lesson: LessonModel,
    *,
    summary: str,
    llm: str,
    style: str,
    close_lesson: bool,
    used_segments: int,
    db: AsyncSession,
) -> LessonSummaryResponse:
    """Guarda o resumo na aula, venha ele do backend ou de um agente local."""
    lesson.summary = summary
    lesson.summary_llm = llm
    lesson.summary_at = datetime.now(timezone.utc)
    lesson.summary_style = style
    if close_lesson and lesson.status != "closed":
        lesson.status = "closed"
        lesson.ended_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(lesson)

    result = await db.execute(
        select(LessonPointModel)
        .where(LessonPointModel.lesson_id == lesson.id)
        .order_by(LessonPointModel.created_at)
    )
    points = [_point_response(item) for item in result.scalars().all()]

    return LessonSummaryResponse(
        lesson_id=lesson.id,
        summary=lesson.summary,
        llm=lesson.summary_llm,
        generated_at=lesson.summary_at,
        used_segments=used_segments,
        style=lesson.summary_style or style,
        points=points,
    )


@router.get(
    "/lessons/{lesson_id}/summary/prompt",
    response_model=LessonSummaryPromptResponse,
)
async def lesson_summary_prompt(
    lesson_id: str,
    style: str = "standard",
    focus: str = "",
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Devolve o prompt do resumo para um agente conectado gerar o texto.

    Codex e Claude Code rodam no computador do usuario e nao sao provedores
    do backend. Eles pedem o prompt aqui — mesma redacao, mesmo formato — e
    devolvem o resultado em `/summary/external`.
    """
    lesson = await _get_lesson(lesson_id, user["tutor_id"], db)
    segments = await _lesson_transcript(lesson_id, db)
    if not segments:
        raise HTTPException(409, "A aula ainda nao tem transcricao")

    built = education_service.build_summary_prompt(
        discipline=lesson.discipline,
        title=lesson.title or "",
        segments=segments,
        focus=focus,
        style=style,
    )
    return LessonSummaryPromptResponse(lesson_id=lesson.id, **built)


@router.post(
    "/lessons/{lesson_id}/summary/external",
    response_model=LessonSummaryResponse,
)
async def store_external_summary(
    lesson_id: str,
    body: ExternalLessonSummaryRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Guarda um resumo gerado por um agente conectado do proprio usuario."""
    lesson = await _get_lesson(lesson_id, user["tutor_id"], db)

    summary = (body.summary or "").strip()
    if not summary:
        raise HTTPException(400, "O agente nao devolveu texto para o resumo")
    if len(summary) > _MAX_SUMMARY_CHARS:
        raise HTTPException(
            400,
            f"Resumo acima do limite de {_MAX_SUMMARY_CHARS} caracteres",
        )

    llm = (body.llm or "").strip()
    if not llm:
        raise HTTPException(400, "Informe qual agente gerou o resumo")

    return await _store_summary(
        lesson,
        summary=summary,
        llm=llm,
        style=education_service.normalize_summary_style(body.style),
        close_lesson=body.close_lesson,
        used_segments=len(await _lesson_transcript(lesson_id, db)),
        db=db,
    )


@router.post("/lessons/{lesson_id}/summary", response_model=LessonSummaryResponse)
async def summarize_lesson(
    lesson_id: str,
    body: LessonSummaryRequest = LessonSummaryRequest(),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _llm_context: None = Depends(user_llm_context),
):
    """Gera o resumo da aula a partir da transcricao.

    Prefere provedor local ou gratuito e fatia a transcricao conforme a janela do
    modelo, encadeando resumos parciais quando a aula nao cabe em uma rodada.
    """
    lesson = await _get_lesson(lesson_id, user["tutor_id"], db)

    segments = await _lesson_transcript(lesson_id, db)
    if not segments:
        raise HTTPException(409, "A aula ainda nao tem transcricao")

    style = education_service.normalize_summary_style(body.style)
    outcome = await education_service.generate_summary(
        discipline=lesson.discipline,
        title=lesson.title or "",
        segments=segments,
        llm=body.llm,
        focus=body.focus,
        style=style,
    )
    if not outcome["summary"]:
        raise HTTPException(
            502,
            f"Nao foi possivel gerar o resumo: {outcome.get('error', 'sem resposta do modelo')}",
        )

    return await _store_summary(
        lesson,
        summary=outcome["summary"],
        llm=outcome["llm"],
        style=style,
        close_lesson=body.close_lesson,
        used_segments=outcome["used_segments"],
        db=db,
    )


@router.post("/lessons/{lesson_id}/close", response_model=LessonResponse)
async def close_lesson(
    lesson_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Encerra a aula, marcando o fim da gravacao."""
    lesson = await _get_lesson(lesson_id, user["tutor_id"], db)
    if lesson.status != "closed":
        lesson.status = "closed"
        lesson.ended_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(lesson)
    return _lesson_response(lesson)


@router.post("/lessons/{lesson_id}/status", response_model=LessonResponse)
async def set_lesson_status(
    lesson_id: str,
    body: LessonStatusUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Troca o status da aula na mao, sem depender do resumo.

    Encerrar pela tela de gravacao passa pelo resumo, e o resumo depende de o
    modelo responder: quando ele falha, a aula fica gravando para sempre. Aqui o
    professor encerra a aula que ficou aberta, ou reabre a que encerrou antes da
    hora para continuar gravando no mesmo registro.
    """
    lesson = await _get_lesson(lesson_id, user["tutor_id"], db)
    if lesson.status != body.status:
        lesson.status = body.status
        # `ended_at` acompanha o status: aula reaberta com data de fim antiga
        # aparece encerrada em tudo que le a data em vez do status.
        lesson.ended_at = (
            datetime.now(timezone.utc) if body.status == "closed" else None
        )
        await db.commit()
        await db.refresh(lesson)

    classes = (await _classes_of([lesson.id], db)).get(lesson.id, [])
    return _lesson_response(lesson, classes)


# --- Pontuacao extra -------------------------------------------------------


@router.post("/lessons/{lesson_id}/points", response_model=LessonPointResponse)
async def add_lesson_point(
    lesson_id: str,
    body: LessonPointCreate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Credita manualmente um ponto extra a um aluno na aula."""
    lesson = await _get_lesson(lesson_id, user["tutor_id"], db)
    name = body.student_name.strip()
    if not name:
        raise HTTPException(422, "Nome do aluno e obrigatorio")

    student_id = body.student_id
    confidence = 1.0
    if student_id is None:
        match = education_service.match_student(name, await _roster(lesson, db))
        student_id = match["student_id"]
        name = match["student_name"]
        confidence = match["confidence"] if student_id else 1.0

    point = LessonPointModel(
        tutor_id=lesson.tutor_id,
        lesson_id=lesson.id,
        student_id=student_id,
        student_name=name,
        points=body.points,
        reason=body.reason,
        discipline=lesson.discipline,
        lesson_date=_as_utc(lesson.started_at),
        source="manual",
        confidence=confidence,
    )
    db.add(point)
    await db.commit()
    await db.refresh(point)
    return _point_response(point)


@router.delete("/points/{point_id}")
async def delete_point(
    point_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove um ponto creditado."""
    point = await db.get(LessonPointModel, point_id)
    if point is None or point.tutor_id != user["tutor_id"]:
        raise HTTPException(404, "Pontuacao nao encontrada")
    await db.delete(point)
    await db.commit()
    return {"ok": True}


@router.get("/points", response_model=PointsReportResponse)
async def points_report(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    discipline: Optional[str] = None,
    class_group: Optional[str] = None,
    student_name: Optional[str] = None,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Quanto de extra cada aluno recebeu, por dia, disciplina e turma.

    A turma nao fica no ponto. Ela vem do cadastro do aluno e, quando o nome
    nao casou com ninguem, da aula que originou o ponto — nessa ordem, porque
    aula de turmas reunidas nao tem turma propria.
    """
    query = (
        select(
            LessonPointModel,
            StudentModel.class_group,
            LessonModel.class_group,
        )
        .outerjoin(StudentModel, StudentModel.id == LessonPointModel.student_id)
        .outerjoin(LessonModel, LessonModel.id == LessonPointModel.lesson_id)
        .where(LessonPointModel.tutor_id == user["tutor_id"])
    )
    start = _parse_date(date_from)
    end = _parse_date(date_to, end_of_day=True)
    if start:
        query = query.where(LessonPointModel.lesson_date >= start)
    if end:
        query = query.where(LessonPointModel.lesson_date <= end)
    if discipline:
        query = query.where(LessonPointModel.discipline == discipline)

    result = await db.execute(query.order_by(LessonPointModel.lesson_date))
    items = [
        (point, (student_group or lesson_group or "").strip())
        for point, student_group, lesson_group in result.all()
    ]

    if class_group:
        items = [(point, group) for point, group in items if group == class_group]
    if student_name:
        wanted = education_service.normalize_name(student_name)
        items = [
            (point, group)
            for point, group in items
            if wanted in education_service.normalize_name(point.student_name)
        ]

    grouped: Dict[tuple, List[LessonPointModel]] = defaultdict(list)
    for point, group in items:
        key = (
            education_service.normalize_name(point.student_name),
            point.discipline or "",
            group,
            _as_utc(point.lesson_date).date().isoformat(),
        )
        grouped[key].append(point)

    entries: List[PointsReportEntry] = []
    for (_, discipline_key, group_key, date_key), group in grouped.items():
        entries.append(
            PointsReportEntry(
                student_name=group[0].student_name,
                student_id=next(
                    (item.student_id for item in group if item.student_id), None
                ),
                total_points=round(sum(item.points for item in group), 3),
                discipline=discipline_key,
                class_group=group_key,
                lesson_date=date_key,
                entries=[_point_response(item) for item in group],
            )
        )

    entries.sort(
        key=lambda item: (
            item.lesson_date,
            item.discipline,
            item.class_group,
            item.student_name,
        )
    )
    return PointsReportResponse(
        date_from=date_from,
        date_to=date_to,
        discipline=discipline,
        class_group=class_group,
        total_points=round(sum(entry.total_points for entry in entries), 3),
        students=entries,
    )


# --- Busca e diagnostico ---------------------------------------------------


@router.get("/search", response_model=List[LessonSearchResult])
async def search_transcripts(
    q: str,
    discipline: Optional[str] = None,
    lesson_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(8, ge=1, le=50),
    user: dict = Depends(get_current_user),
):
    """Busca semantica nas transcricoes de aula do usuario.

    Devolve trechos com a aula de origem e o instante, para o professor voltar ao
    ponto exato da gravacao.
    """
    start = _parse_date(date_from)
    end = _parse_date(date_to, end_of_day=True)
    results = await qdrant_service.search_lesson_transcripts(
        tutor_id=user["tutor_id"],
        query=q,
        discipline=discipline,
        lesson_id=lesson_id,
        ts_from=int(start.timestamp()) if start else None,
        ts_to=int(end.timestamp()) if end else None,
        limit=limit,
    )
    return [LessonSearchResult(**item) for item in results]


@router.get("/embedding-status", response_model=EmbeddingStatusResponse)
async def embedding_status():
    """Provedor de embedding em uso e se a busca esta semantica.

    Quando cai no hash offline, a interface avisa que a busca so casa palavra exata.
    """
    return EmbeddingStatusResponse(**await embedding_service.describe())


@router.get("/index-status", response_model=LessonIndexStatusResponse)
async def index_status(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Quantos trechos gravados ainda nao estao no indice de busca."""
    return LessonIndexStatusResponse(
        **await lesson_index_service.status(db, tutor_id=user["tutor_id"])
    )


@router.post("/reindex", response_model=LessonReindexResponse)
async def reindex_lessons(
    body: LessonReindexRequest = LessonReindexRequest(),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Regrava no Qdrant os trechos lidos do MySQL.

    Pedido explicito nao espera o intervalo minimo da reindexacao automatica.
    """
    lesson_index_service.reset_cooldown()
    outcome = await lesson_index_service.reindex(
        db,
        tutor_id=user["tutor_id"],
        lesson_id=body.lesson_id,
        force=body.force,
        limit=body.limit,
    )
    return LessonReindexResponse(**outcome)


# --- Quiz Generation ---


@router.post("/materials", response_model=MaterialResponse)
async def upload_material(
    file: UploadFile = File(...),
    discipline_id: str = Form(""),
    discipline: str = Form(""),
    title: str = Form(""),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Guarda um material da disciplina, ja com o texto extraido.

    Que formatos valem esta escrito no `material_service`, e nao aqui: quem
    registra o extrator ja habilita o upload, sem uma segunda lista para
    esquecer de atualizar.

    A extracao roda fora do event loop: ler uma apostila grande e trabalho de
    CPU e seguraria todas as outras requisicoes durante o upload.

    O nome do material sai, em ordem: do que o professor digitou, do titulo que
    o proprio documento carrega - nome do livro, tema dos slides - e so entao do
    nome do arquivo, que costuma ser "doc1 (2) final.pdf" e nao ajuda ninguem a
    reconhecer o material na lista.
    """
    nome = (file.filename or "material.pdf").strip()

    data = await file.read()
    try:
        extraido = await material_service.extract(data, nome)
    except material_service.MaterialError as exc:
        raise HTTPException(422, str(exc)) from exc

    vinculo, rotulo = await _resolve_discipline(
        discipline_id.strip(), discipline.strip(), user["tutor_id"], db
    )
    material = MaterialModel(
        tutor_id=user["tutor_id"],
        discipline_id=vinculo,
        discipline=rotulo,
        title=(title.strip() or extraido.title or nome.rsplit(".", 1)[0]),
        filename=nome,
        source_type=extraido.source_type,
        page_count=extraido.page_count,
        char_count=extraido.char_count,
        truncated=extraido.truncated,
        content=extraido.text,
    )
    db.add(material)
    await db.commit()
    await db.refresh(material)
    return _material_response(material)


@router.get("/materials", response_model=list[MaterialResponse])
async def list_materials(
    discipline_id: Optional[str] = None,
    discipline: Optional[str] = None,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Materiais do professor, opcionalmente de uma disciplina."""
    query = select(MaterialModel).where(
        MaterialModel.tutor_id == user["tutor_id"]
    )
    if discipline_id:
        query = query.where(MaterialModel.discipline_id == discipline_id)
    elif discipline:
        query = query.where(MaterialModel.discipline == discipline)
    rows = (
        await db.execute(query.order_by(MaterialModel.created_at.desc()))
    ).scalars().all()
    return [_material_response(item) for item in rows]


@router.delete("/materials/{material_id}")
async def delete_material(
    material_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove um material. Quiz ja gerado a partir dele continua valendo."""
    material = await db.get(MaterialModel, material_id)
    if not material or material.tutor_id != user["tutor_id"]:
        raise HTTPException(404, "Material nao encontrado")
    await db.delete(material)
    await db.commit()
    return {"deleted": material_id}


async def _resolve_discipline(
    discipline_id: str,
    texto: str,
    tutor_id: str,
    db: AsyncSession,
) -> tuple[Optional[str], str]:
    """Liga o material a uma disciplina cadastrada quando der.

    Aceita o id (caminho da interface, que lista as disciplinas) ou o texto
    (caminho manual). Texto que casa com uma disciplina existente ganha o id de
    brinde; texto solto continua valendo, para nao travar o upload de quem ainda
    nao cadastrou a disciplina.
    """
    if discipline_id:
        item = await db.get(DisciplineModel, discipline_id)
        if not item or item.tutor_id != tutor_id:
            raise HTTPException(404, "Disciplina nao encontrada")
        return item.id, _discipline_label(item)

    if not texto:
        return None, ""

    alvo = texto.casefold()
    rows = (await db.execute(
        select(DisciplineModel).where(DisciplineModel.tutor_id == tutor_id)
    )).scalars().all()
    for item in rows:
        if alvo in {
            _discipline_label(item).casefold(),
            (item.code or "").strip().casefold(),
            (item.name or "").strip().casefold(),
        }:
            return item.id, _discipline_label(item)
    return None, texto


def _material_response(material: MaterialModel) -> MaterialResponse:
    return MaterialResponse(
        id=material.id,
        discipline_id=material.discipline_id,
        discipline=material.discipline or "",
        title=material.title or "",
        filename=material.filename or "",
        source_type=material.source_type or "pdf",
        page_count=material.page_count or 0,
        char_count=material.char_count or 0,
        truncated=bool(material.truncated),
        created_at=material.created_at,
    )


#: Teto de caracteres do contexto que vai no prompt, somando todas as fontes.
#: A janela do modelo nao cresce porque o professor marcou mais aulas: quatro
#: aulas inteiras passariam do que o provedor aceita e a resposta voltaria
#: cortada - que e o defeito que fazia a geracao devolver quiz vazio.
QUIZ_CONTEXT_CHAR_BUDGET = 60_000

#: Piso por fonte. Abaixo disso a fonte entra sem contexto suficiente para uma
#: pergunta ancorada, e e melhor estourar um pouco o teto do que incluir sobra.
QUIZ_SOURCE_MIN_CHARS = 3_000


async def _lesson_source_text(
    lesson: LessonModel,
    tutor_id: str,
    db: AsyncSession,
    limite: int,
) -> str:
    """Texto de uma aula para o prompt: resumo validado e o que foi transcrito.

    O resumo vem primeiro e inteiro - e o texto que o professor conferiu. A
    transcricao ocupa o que sobrou da cota, porque e a parte que cresce sem
    limite e a que da para cortar sem perder o fio da aula.
    """
    espaco = max(limite, QUIZ_SOURCE_MIN_CHARS)
    resumo = (lesson.summary or "").strip()

    stmt = (
        select(LessonSegmentModel)
        .where(
            LessonSegmentModel.lesson_id == lesson.id,
            LessonSegmentModel.tutor_id == tutor_id,
        )
        .order_by(LessonSegmentModel.sequence, LessonSegmentModel.created_at)
    )
    segments = (await db.execute(stmt)).scalars().all()
    transcript = "\n\n".join(
        segment.text.strip()
        for segment in segments
        if (segment.text or "").strip()
    )

    blocos = []
    if resumo:
        blocos.append(f"RESUMO VALIDADO DA AULA:\n{resumo[:espaco]}")
        espaco -= min(len(resumo), espaco)
    if transcript and espaco > 500:
        blocos.append(f"TRANSCRIÇÃO DA AULA:\n{transcript[:espaco]}")
    return "\n\n".join(blocos)


async def _quiz_generation_context(
    request: QuizCreateRequest,
    tutor_id: str,
    db: AsyncSession,
) -> Dict[str, Any]:
    """Junta as fontes escolhidas em um contexto so para o gerador.

    Aulas e materiais se somam, em qualquer combinacao: uma aula, tres aulas,
    duas aulas com a apostila. O que decide se uma fonte entra e ter texto -
    resumo validado ou a transcricao ja gravada -, nao a aula estar encerrada:
    exigir encerramento impedia o quiz relampago no meio da aula, que e onde ele
    mais serve.

    Roda na requisicao, antes de o job existir, para fonte invalida responder
    404/400 na hora: job aceito que falha minutos depois com "aula nao
    encontrada" e muito pior de entender.
    """

    lesson_ids = request.lesson_sources()
    material_ids = request.material_sources()
    if not lesson_ids and not material_ids:
        raise HTTPException(
            status_code=422,
            detail="Informe ao menos uma aula ou um material como fonte do quiz.",
        )

    cota = max(
        QUIZ_CONTEXT_CHAR_BUDGET // (len(lesson_ids) + len(material_ids)),
        QUIZ_SOURCE_MIN_CHARS,
    )

    blocos: List[str] = []
    fontes: List[Dict[str, str]] = []
    disciplinas: List[str] = []
    sem_texto: List[str] = []
    primeira_aula = ""

    for lesson_id in lesson_ids:
        lesson = await db.get(LessonModel, lesson_id)
        if not lesson or lesson.tutor_id != tutor_id:
            raise HTTPException(status_code=404, detail="Aula não encontrada")

        rotulo = lesson.title or "Aula"
        texto = await _lesson_source_text(lesson, tutor_id, db, cota)
        if not texto:
            sem_texto.append(f'aula "{rotulo}"')
            continue

        blocos.append(f"=== AULA: {rotulo} ===\n{texto}")
        fontes.append({"type": "lesson", "id": lesson.id, "label": rotulo})
        if lesson.discipline:
            disciplinas.append(lesson.discipline)
        primeira_aula = primeira_aula or lesson.id

    for material_id in material_ids:
        material = await db.get(MaterialModel, material_id)
        if not material or material.tutor_id != tutor_id:
            raise HTTPException(status_code=404, detail="Material não encontrado")

        rotulo = material.title or material.filename or "Material"
        texto = material_service.summary_for_quiz(
            material.content or "",
            limit=cota,
        ).strip()
        if not texto:
            sem_texto.append(f'material "{rotulo}"')
            continue

        blocos.append(f"=== MATERIAL DA DISCIPLINA: {rotulo} ===\n{texto}")
        fontes.append({"type": "material", "id": material.id, "label": rotulo})
        if material.discipline:
            disciplinas.append(material.discipline)

    if not blocos:
        raise HTTPException(
            status_code=400,
            detail=(
                "Nenhuma das fontes escolhidas tem texto: "
                f"{', '.join(sem_texto)}. Grave ou resuma a aula, ou importe o "
                "material, antes de gerar o quiz."
            ),
        )

    rotulos = [fonte["label"] for fonte in fontes]
    titulo = (
        f"Quiz: {rotulos[0]}" if len(rotulos) == 1
        else f"Quiz: {rotulos[0]} + {len(rotulos) - 1} fonte(s)"
    )

    return {
        "resumo": "\n\n".join(blocos),
        "disciplina": ", ".join(dict.fromkeys(disciplinas)) or "Geral",
        "titulo_aula": rotulos[0],
        "titulo": titulo,
        "fontes": fontes,
        "ignoradas": sem_texto,
        # Quiz pode nao ter aula nenhuma, e a coluna e NOT NULL: fica a primeira
        # aula que entrou, e a origem completa vive em `quiz_sources`.
        "lesson_id": primeira_aula,
    }


async def _run_quiz_generation(
    context: Dict[str, Any],
    *,
    request: QuizCreateRequest,
    tutor_id: str,
    db: AsyncSession,
    on_progress: Optional[Callable[[int, int], None]] = None,
    questoes_existentes: Sequence[Dict[str, Any]] = (),
) -> QuizGenerateResponse:
    """Gera as perguntas com a IA e grava o quiz para revisao."""

    quiz_data = await quiz_generator_service.generate_quiz(
        resumo=context["resumo"],
        disciplina=context["disciplina"],
        titulo_aula=context["titulo_aula"],
        tipo_quiz=request.tipo_quiz,
        quantidade_questoes=request.quantidade_questoes,
        tipos_questao=["multipla_escolha"],
        dificuldade=request.dificuldade,
        llm=request.llm,
        on_progress=on_progress,
        questoes_existentes=questoes_existentes,
    )

    return await _persist_generated_quiz(
        quiz_data,
        request=request,
        tutor_id=tutor_id,
        titulo=context["titulo"],
        fontes=context["fontes"],
        ignoradas=context["ignoradas"],
        db=db,
        lesson_id=context["lesson_id"],
    )


@router.post("/quiz/generate")
async def generate_quiz_from_lesson(
    request: QuizCreateRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _llm_context: None = Depends(user_llm_context),
):
    """Gera o quiz e so responde quando ele esta pronto.

    A tela usa `/quiz/generate/async`: escrever dez perguntas com a IA passa do
    tempo que o cliente espera por uma resposta HTTP. Esta rota fica para
    integracao e teste, onde esperar e aceitavel.
    """

    tutor_id = user["tutor_id"]
    context = await _quiz_generation_context(request, tutor_id, db)
    return await _run_quiz_generation(
        context,
        request=request,
        tutor_id=tutor_id,
        db=db,
    )


async def _notify_quiz_job(job) -> None:
    """Aviso de fim de geracao pelos canais externos que o professor configurou.

    O aviso dentro do app sai da propria central, que acompanha a fila; este e o
    de fora - Telegram e WhatsApp -, para quem pediu o quiz e fechou o app.
    """
    if not job.user_id:
        return
    async with AsyncSessionLocal() as session:
        config = await load_notif_config(session, user_id=job.user_id)

    if job.status == "done":
        mensagem = (
            f'Quiz "{job.titulo}" pronto: {job.prontas} pergunta(s) '
            "escritas pela IA, esperando sua revisão."
        )
    else:
        mensagem = (
            f'A geração do quiz "{job.titulo}" não terminou: '
            f"{job.error or 'falha desconhecida'}"
        )

    await send_notification(mensagem, config, assistant_name="Modo Educação")


async def _existing_questions_for_sources(
    db: AsyncSession,
    tutor_id: str,
    fontes: Sequence[Dict[str, str]],
    *,
    limit: int = 60,
) -> List[Dict[str, Any]]:
    """Questoes ja geradas a partir das mesmas fontes, para a IA nao repetir.

    Sem isso, o segundo quiz da mesma aula saia com as mesmas perguntas do
    primeiro: cada geracao so conhecia as proprias perguntas. Arquivadas ficam de
    fora - o professor tirou do banco o que nao queria ver de novo.
    """
    source_ids = [fonte.get("id") for fonte in fontes if fonte.get("id")]
    if not source_ids:
        return []

    quiz_ids = (await db.execute(
        select(QuizSourceModel.quiz_id)
        .join(QuizModel, QuizModel.id == QuizSourceModel.quiz_id)
        .where(
            QuizSourceModel.source_id.in_(source_ids),
            QuizModel.tutor_id == tutor_id,
        )
        .distinct()
    )).scalars().all()
    if not quiz_ids:
        return []

    rows = (await db.execute(
        select(QuestionModel)
        .where(
            QuestionModel.quiz_id.in_(quiz_ids),
            QuestionModel.arquivada.is_(False),
        )
        .order_by(QuestionModel.created_at.desc())
        .limit(limit)
    )).scalars().all()

    existentes = []
    for row in reversed(rows):
        try:
            conceitos = json.loads(row.conceitos_relacionados or "[]")
        except (TypeError, ValueError):
            conceitos = []
        existentes.append({
            "enunciado": row.enunciado,
            "opcoes": _quiz_question_options(row),
            "conceitos": conceitos if isinstance(conceitos, list) else [],
            "topico_origem": row.topico_origem,
        })
    return existentes


async def _run_quiz_job(job, progress) -> Dict[str, Any]:
    """Gera o quiz de um pedido da fila.

    Roda no worker, longe da requisicao que fez o pedido: por isso refaz o
    contexto das fontes a partir do pedido gravado e carrega as chaves de
    provedor do professor direto do banco - a ContextVar da requisicao ja nao
    existe quando a fila chega neste pedido.
    """
    request = QuizCreateRequest.model_validate(json.loads(job.request_json or "{}"))
    runtime = await load_user_llm_runtime(job.tutor_id)
    token = activate_user_llms(runtime)
    try:
        async with AsyncSessionLocal() as session:
            context = await _quiz_generation_context(request, job.tutor_id, session)
            existentes = await _existing_questions_for_sources(
                session, job.tutor_id, context["fontes"]
            )
            response = await _run_quiz_generation(
                context,
                request=request,
                tutor_id=job.tutor_id,
                db=session,
                on_progress=progress,
                questoes_existentes=existentes,
            )
    finally:
        reset_user_llms(token)
    return {
        "quiz_id": response.quiz_id,
        "prontas": len(response.questoes),
        "message": response.message,
        "attempts": response.attempts,
    }


quiz_job_service.queue.configure(runner=_run_quiz_job, notifier=_notify_quiz_job)


@router.post("/quiz/generate/async", status_code=202)
async def generate_quiz_in_background(
    request: QuizCreateRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Coloca o pedido na fila do professor e responde na hora.

    A fonte e validada aqui, ainda na requisicao: aula inexistente ou material
    sem texto responde 404/400 imediato, em vez de virar um pedido que falha
    minutos depois na fila.
    """

    tutor_id = user["tutor_id"]
    context = await _quiz_generation_context(request, tutor_id, db)
    return await quiz_job_service.queue.enqueue(
        tutor_id=tutor_id,
        user_id=str(user.get("uid") or ""),
        titulo=context["titulo"],
        total=request.quantidade_questoes,
        request=request.model_dump(mode="json"),
    )


@router.get("/quiz/jobs")
async def list_quiz_jobs(
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    """Pedidos de geracao do professor: em andamento primeiro, depois recentes."""

    jobs = await quiz_job_service.queue.list_jobs(user["tutor_id"], limit=limit)
    return {
        "jobs": jobs,
        "active": sum(1 for job in jobs if job["status"] in ("queued", "running")),
        "unseen": sum(
            1 for job in jobs
            if job["status"] in ("done", "error") and not job["seen"]
        ),
    }


@router.post("/quiz/jobs/seen")
async def mark_quiz_jobs_seen(
    body: QuizJobSeenRequest,
    user: dict = Depends(get_current_user),
):
    """Marca avisos de fim como vistos, para nao aparecerem de novo."""

    changed = await quiz_job_service.queue.mark_seen(user["tutor_id"], body.job_ids)
    return {"updated": changed}


async def _quiz_job_or_404(job_id: str, tutor_id: str) -> Dict[str, Any]:
    job = await quiz_job_service.queue.get(job_id, tutor_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Pedido de quiz não encontrado.")
    return job


@router.get("/quiz/jobs/{job_id}")
async def get_quiz_job(
    job_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Andamento de um pedido; pronto, vem junto com o quiz para revisao."""

    job = await _quiz_job_or_404(job_id, user["tutor_id"])
    job["quiz"] = None
    if job["status"] == "done" and job.get("quiz_id"):
        quiz = await db.get(QuizModel, job["quiz_id"])
        if quiz is not None and quiz.tutor_id == user["tutor_id"]:
            detalhe = (await _build_quiz_response(db, quiz)).model_dump(mode="json")
            detalhe.update(
                quiz_id=quiz.id,
                message=job["message"],
                attempts=job["attempts"],
            )
            job["quiz"] = detalhe
    return job


@router.post("/quiz/jobs/{job_id}/cancel")
async def cancel_quiz_job(
    job_id: str,
    user: dict = Depends(get_current_user),
):
    """Cancela um pedido na fila ou em andamento."""

    job = await quiz_job_service.queue.cancel(job_id, user["tutor_id"])
    if job is None:
        raise HTTPException(status_code=404, detail="Pedido de quiz não encontrado.")
    return job


@router.post("/quiz/jobs/{job_id}/retry", status_code=202)
async def retry_quiz_job(
    job_id: str,
    user: dict = Depends(get_current_user),
):
    """Enfileira de novo, com o mesmo pedido, o que falhou ou foi cancelado."""

    try:
        job = await quiz_job_service.queue.retry(job_id, user["tutor_id"])
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    if job is None:
        raise HTTPException(status_code=404, detail="Pedido de quiz não encontrado.")
    return job


# --- Quizzes e banco de questoes -------------------------------------------


async def _quiz_catalog(
    db: AsyncSession,
    tutor_id: str,
) -> Dict[str, Dict[str, Any]]:
    """Quizzes do professor com fontes e disciplinas, indexados pelo id.

    Quiz nao guarda disciplina: ela vem das fontes (aula ou material). Montar o
    mapa uma vez serve a listagem de quizzes e ao filtro do banco de questoes.
    """
    quizzes = (await db.execute(
        select(QuizModel)
        .where(QuizModel.tutor_id == tutor_id)
        .order_by(QuizModel.created_at.desc())
    )).scalars().all()
    if not quizzes:
        return {}

    quiz_ids = [quiz.id for quiz in quizzes]
    sources = (await db.execute(
        select(QuizSourceModel).where(QuizSourceModel.quiz_id.in_(quiz_ids))
    )).scalars().all()

    lesson_ids = {s.source_id for s in sources if s.source_type == "lesson"}
    lesson_ids |= {quiz.lesson_id for quiz in quizzes if quiz.lesson_id}
    material_ids = {s.source_id for s in sources if s.source_type == "material"}

    lesson_discipline: Dict[str, str] = {}
    if lesson_ids:
        for lesson_id, discipline in (await db.execute(
            select(LessonModel.id, LessonModel.discipline)
            .where(LessonModel.id.in_(lesson_ids), LessonModel.tutor_id == tutor_id)
        )).all():
            lesson_discipline[lesson_id] = discipline or ""
    material_discipline: Dict[str, str] = {}
    if material_ids:
        for material_id, discipline in (await db.execute(
            select(MaterialModel.id, MaterialModel.discipline)
            .where(MaterialModel.id.in_(material_ids), MaterialModel.tutor_id == tutor_id)
        )).all():
            material_discipline[material_id] = discipline or ""

    by_quiz: Dict[str, List[QuizSourceModel]] = defaultdict(list)
    for source in sources:
        by_quiz[source.quiz_id].append(source)

    catalog: Dict[str, Dict[str, Any]] = {}
    for quiz in quizzes:
        fontes = [
            {"type": s.source_type, "id": s.source_id, "label": s.label}
            for s in by_quiz.get(quiz.id, [])
        ]
        if not fontes and quiz.lesson_id:
            fontes = [{"type": "lesson", "id": quiz.lesson_id, "label": ""}]
        disciplinas = []
        for fonte in fontes:
            mapa = lesson_discipline if fonte["type"] == "lesson" else material_discipline
            nome = mapa.get(fonte["id"], "")
            if nome and nome not in disciplinas:
                disciplinas.append(nome)
        catalog[quiz.id] = {"quiz": quiz, "fontes": fontes, "disciplinas": disciplinas}
    return catalog


def _catalog_matches(
    item: Dict[str, Any],
    *,
    discipline: str = "",
    lesson_id: str = "",
    status: str = "",
) -> bool:
    if discipline:
        alvo = discipline.strip().lower()
        if not any(alvo == nome.strip().lower() for nome in item["disciplinas"]):
            return False
    if lesson_id and not any(
        fonte["type"] == "lesson" and fonte["id"] == lesson_id for fonte in item["fontes"]
    ):
        return False
    if status and (item["quiz"].status or "open") != status:
        return False
    return True


def _quiz_summary(item: Dict[str, Any], question_count: int) -> Dict[str, Any]:
    quiz = item["quiz"]
    return {
        "id": quiz.id,
        "titulo": quiz.titulo,
        "tipo_quiz": quiz.tipo_quiz,
        "status": quiz.status or "open",
        "live_phase": quiz.live_phase or "lobby",
        "total_questoes": question_count,
        "tempo_estimado": quiz.tempo_estimado or 0,
        "disciplinas": item["disciplinas"],
        "fontes": item["fontes"],
        "created_at": quiz.created_at.isoformat() if quiz.created_at else None,
        "closed_at": quiz.closed_at.isoformat() if quiz.closed_at else None,
    }


@router.get("/quiz")
async def list_quizzes(
    status: str = Query("", description="draft, open ou closed"),
    discipline: str = Query(""),
    lesson_id: str = Query(""),
    q: str = Query("", description="busca no titulo"),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Quizzes do professor, com disciplina e fontes, para a central."""

    catalog = await _quiz_catalog(db, user["tutor_id"])
    busca = q.strip().lower()
    selecionados = [
        item for item in catalog.values()
        if (not status or (item["quiz"].status or "open") == status)
        and (not busca or busca in (item["quiz"].titulo or "").lower())
        and _catalog_matches(item, discipline=discipline, lesson_id=lesson_id)
    ]

    counts: Dict[str, int] = {}
    if selecionados:
        for quiz_id, count in (await db.execute(
            select(QuestionModel.quiz_id, func.count(QuestionModel.id))
            .where(QuestionModel.quiz_id.in_([i["quiz"].id for i in selecionados]))
            .group_by(QuestionModel.quiz_id)
        )).all():
            counts[quiz_id] = int(count)

    disciplinas = sorted({nome for item in catalog.values() for nome in item["disciplinas"]})
    return {
        "quizzes": [_quiz_summary(item, counts.get(item["quiz"].id, 0)) for item in selecionados],
        "disciplinas": disciplinas,
    }


@router.delete("/quiz/{quiz_id}")
async def discard_quiz_draft(
    quiz_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Descarta um rascunho. Quiz ja liberado guarda respostas e fica."""

    quiz = await db.get(QuizModel, quiz_id)
    if quiz is None or quiz.tutor_id != user["tutor_id"]:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")
    if quiz.status != "draft":
        raise HTTPException(
            status_code=409,
            detail="Só rascunho pode ser descartado: este quiz já foi liberado para a turma.",
        )
    await db.execute(sql_delete(QuestionModel).where(QuestionModel.quiz_id == quiz_id))
    await db.execute(sql_delete(QuizSourceModel).where(QuizSourceModel.quiz_id == quiz_id))
    await db.delete(quiz)
    await db.commit()
    return {"deleted": True}


def _bank_question(row: QuestionModel, item: Dict[str, Any]) -> Dict[str, Any]:
    quiz = item["quiz"]
    try:
        conceitos = json.loads(row.conceitos_relacionados or "[]")
    except (TypeError, ValueError):
        conceitos = []
    return {
        "id": row.id,
        "quiz_id": row.quiz_id,
        "quiz_titulo": quiz.titulo,
        "quiz_status": quiz.status or "open",
        "tipo": row.tipo,
        "dificuldade": row.dificuldade or "medio",
        "enunciado": row.enunciado,
        "opcoes": _quiz_question_options(row),
        "resposta_correta": row.resposta_correta,
        "justificativa": row.justificativa or "",
        "conceitos_relacionados": conceitos if isinstance(conceitos, list) else [],
        "topico_origem": row.topico_origem,
        "verificado": bool(row.verificado),
        "arquivada": bool(row.arquivada),
        "disciplinas": item["disciplinas"],
        "fontes": item["fontes"],
        # Rascunho ainda nao foi respondido por ninguem: editar e seguro. Em quiz
        # liberado a correcao das respostas ja gravadas mudaria por baixo.
        "editavel": (quiz.status or "open") == "draft",
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/quiz/questions")
async def list_bank_questions(
    discipline: str = Query(""),
    lesson_id: str = Query(""),
    q: str = Query(""),
    dificuldade: str = Query(""),
    status: str = Query("", description="draft para so os rascunhos"),
    include_copies: bool = Query(
        False, description="inclui as copias feitas ao montar quiz"),
    include_archived: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Banco de questoes: tudo que ja foi gerado, com filtro e paginacao.

    `status` recorta pelo estado do quiz de origem: "draft" traz so o que ainda
    nao foi aplicado - que e o que se pode apagar de verdade.
    """

    catalog = await _quiz_catalog(db, user["tutor_id"])
    quiz_ids = [
        quiz_id for quiz_id, item in catalog.items()
        if _catalog_matches(
            item, discipline=discipline, lesson_id=lesson_id, status=status
        )
    ]
    disciplinas = sorted({nome for item in catalog.values() for nome in item["disciplinas"]})
    if not quiz_ids:
        return {"questions": [], "total": 0, "disciplinas": disciplinas}

    filtros = [QuestionModel.quiz_id.in_(quiz_ids)]
    if not include_copies:
        # Montar quiz com questoes existentes copia as questoes, para o rascunho
        # novo poder ser corrigido sem mexer no quiz ja aplicado. A copia nao e
        # questao nova: sem este filtro, cada quiz montado duplicava o banco.
        filtros.append(QuestionModel.origem_id.is_(None))
    if not include_archived:
        filtros.append(QuestionModel.arquivada.is_(False))
    if dificuldade:
        filtros.append(QuestionModel.dificuldade == dificuldade)
    busca = q.strip()
    if busca:
        padrao = f"%{busca}%"
        filtros.append(or_(
            QuestionModel.enunciado.ilike(padrao),
            QuestionModel.topico_origem.ilike(padrao),
            QuestionModel.conceitos_relacionados.ilike(padrao),
        ))

    total = int((await db.execute(
        select(func.count(QuestionModel.id)).where(*filtros)
    )).scalar() or 0)
    rows = (await db.execute(
        select(QuestionModel)
        .where(*filtros)
        .order_by(QuestionModel.created_at.desc(), QuestionModel.id)
        .offset(offset)
        .limit(limit)
    )).scalars().all()

    # Os ids de todo o filtro, nao so da pagina: "selecionar todos" precisa
    # alcancar o que a paginacao esconde, e id e barato de trafegar.
    todos_os_ids = list((await db.execute(
        select(QuestionModel.id).where(*filtros)
    )).scalars().all())

    # Em quantos quizzes cada original foi reaproveitada. A copia some da
    # lista, mas o reaproveitamento continua visivel - e o que evita o professor
    # montar duas vezes o mesmo simulado sem perceber.
    copias: Dict[str, int] = {}
    if rows:
        for origem_id, quantidade in (await db.execute(
            select(QuestionModel.origem_id, func.count(QuestionModel.id))
            .where(QuestionModel.origem_id.in_([row.id for row in rows]))
            .group_by(QuestionModel.origem_id)
        )).all():
            copias[origem_id] = int(quantidade)

    return {
        "questions": [
            {**_bank_question(row, catalog[row.quiz_id]),
             "copias": copias.get(row.id, 0)}
            for row in rows
        ],
        "total": total,
        "disciplinas": disciplinas,
        "all_ids": todos_os_ids,
    }


async def _owned_question(
    db: AsyncSession,
    question_id: str,
    tutor_id: str,
) -> tuple[QuestionModel, QuizModel]:
    question = await db.get(QuestionModel, question_id)
    quiz = await db.get(QuizModel, question.quiz_id) if question else None
    if question is None or quiz is None or quiz.tutor_id != tutor_id:
        raise HTTPException(status_code=404, detail="Questão não encontrada")
    return question, quiz


@router.patch("/quiz/questions/{question_id}")
async def update_bank_question(
    question_id: str,
    body: QuestionUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Corrige uma questao de rascunho."""

    question, quiz = await _owned_question(db, question_id, user["tutor_id"])
    if (quiz.status or "open") != "draft":
        raise HTTPException(
            status_code=409,
            detail=(
                "Este quiz já foi liberado: alterar a questão mudaria a correção "
                "das respostas gravadas. Monte um novo quiz com ela e edite lá."
            ),
        )

    if body.enunciado is not None:
        enunciado = body.enunciado.strip()
        if not enunciado:
            raise HTTPException(status_code=422, detail="O enunciado não pode ficar vazio.")
        question.enunciado = enunciado
    if body.opcoes is not None:
        opcoes = [
            {"label": o.label.strip(), "texto": o.texto.strip(), "correta": bool(o.correta)}
            for o in body.opcoes
            if o.texto.strip()
        ]
        if question.tipo == "multipla_escolha":
            if len(opcoes) < 2:
                raise HTTPException(status_code=422, detail="Informe ao menos duas alternativas.")
            corretas = [o for o in opcoes if o["correta"]]
            if len(corretas) != 1:
                raise HTTPException(status_code=422, detail="Marque exatamente uma alternativa correta.")
            question.resposta_correta = corretas[0]["label"]
        question.opcoes = json.dumps(opcoes, ensure_ascii=False)
    elif body.resposta_correta is not None:
        question.resposta_correta = body.resposta_correta.strip()
    if body.justificativa is not None:
        question.justificativa = body.justificativa.strip()
    if body.dificuldade is not None:
        question.dificuldade = body.dificuldade
    # Revisada pelo professor: deixa de ser "baixa confianca".
    question.verificado = True
    await db.commit()
    await db.refresh(question)

    catalog = await _quiz_catalog(db, user["tutor_id"])
    return _bank_question(question, catalog[quiz.id])


@router.delete("/quiz/questions/{question_id}")
async def delete_bank_question(
    question_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Tira a questao do banco.

    Em rascunho ela e apagada. Em quiz ja liberado e arquivada: sai do banco e
    das proximas geracoes, mas continua ligada as respostas que a turma deu.
    """

    question, quiz = await _owned_question(db, question_id, user["tutor_id"])
    if (quiz.status or "open") == "draft":
        await db.delete(question)
        quiz.total_questoes = max(0, (quiz.total_questoes or 1) - 1)
        await db.commit()
        return {"deleted": True, "archived": False}

    question.arquivada = True
    await db.commit()
    return {"deleted": False, "archived": True}


@router.post("/quiz/questions/bulk-delete")
async def delete_bank_questions(
    body: BankQuestionBulkDelete,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Tira varias questoes do banco de uma vez.

    A regra por questao e a mesma da exclusao individual, e nao se afrouxa por
    ser em lote: rascunho e apagado, questao de quiz ja aplicado e arquivada -
    ela tem resposta de aluno apontando para ela e o relatorio precisa continuar
    fechando. Por isso a resposta separa as duas contas, em vez de dizer so
    "pronto": o professor pediu para apagar e precisa saber o que sobrou.

    Id que nao existe ou nao e do professor e ignorado, nao derruba o lote.
    """

    ids = [item for item in dict.fromkeys(body.ids) if item]
    if not ids:
        return {"deleted": 0, "archived": 0, "ignored": 0}

    questions = (await db.execute(
        select(QuestionModel).where(QuestionModel.id.in_(ids))
    )).scalars().all()
    quizzes = {
        quiz.id: quiz
        for quiz in (await db.execute(
            select(QuizModel).where(
                QuizModel.id.in_({item.quiz_id for item in questions}),
                QuizModel.tutor_id == user["tutor_id"],
            )
        )).scalars().all()
    }

    apagadas = 0
    arquivadas = 0
    for question in questions:
        quiz = quizzes.get(question.quiz_id)
        if quiz is None:
            continue
        if (quiz.status or "open") == "draft":
            await db.delete(question)
            quiz.total_questoes = max(0, (quiz.total_questoes or 1) - 1)
            apagadas += 1
        elif not question.arquivada:
            question.arquivada = True
            arquivadas += 1

    await db.commit()
    return {
        "deleted": apagadas,
        "archived": arquivadas,
        "ignored": len(ids) - apagadas - arquivadas,
    }


@router.post("/quiz/questions/{question_id}/restore")
async def restore_bank_question(
    question_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Devolve ao banco uma questao arquivada."""

    question, quiz = await _owned_question(db, question_id, user["tutor_id"])
    question.arquivada = False
    await db.commit()
    await db.refresh(question)
    catalog = await _quiz_catalog(db, user["tutor_id"])
    return _bank_question(question, catalog[quiz.id])


@router.post("/quiz/from-questions", status_code=201)
async def create_quiz_from_questions(
    body: QuizFromQuestionsRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Monta um quiz novo com questoes do banco, sem chamar a IA.

    As questoes sao copiadas, nao movidas: o quiz de origem continua inteiro, e
    corrigir a copia no rascunho novo nao mexe no quiz ja aplicado.
    """

    tutor_id = user["tutor_id"]
    ids = list(dict.fromkeys(item for item in body.question_ids if item))
    if not ids:
        raise HTTPException(status_code=422, detail="Escolha ao menos uma questão.")

    rows = (await db.execute(
        select(QuestionModel).where(QuestionModel.id.in_(ids))
    )).scalars().all()
    by_id = {row.id: row for row in rows}
    catalog = await _quiz_catalog(db, tutor_id)
    faltando = [
        item for item in ids
        if item not in by_id or by_id[item].quiz_id not in catalog
    ]
    if faltando:
        raise HTTPException(status_code=404, detail="Alguma questão escolhida não foi encontrada.")
    arquivadas = [item for item in ids if by_id[item].arquivada]
    if arquivadas:
        raise HTTPException(status_code=409, detail="Questão arquivada não entra em quiz novo: restaure antes.")

    fontes: List[Dict[str, str]] = []
    vistas = set()
    for item in ids:
        for fonte in catalog[by_id[item].quiz_id]["fontes"]:
            chave = (fonte["type"], fonte["id"])
            if fonte["id"] and chave not in vistas:
                vistas.add(chave)
                fontes.append(fonte)
    lesson_id = next((f["id"] for f in fontes if f["type"] == "lesson"), "")

    quiz = QuizModel(
        id=str(uuid.uuid4()),
        tutor_id=tutor_id,
        lesson_id=lesson_id,
        titulo=body.titulo.strip()[:255],
        tipo_quiz=body.tipo_quiz,
        status="draft",
        total_questoes=len(ids),
        tempo_estimado=max(5, len(ids) * 2),
    )
    db.add(quiz)
    for fonte in fontes:
        db.add(QuizSourceModel(
            quiz_id=quiz.id,
            source_type=fonte["type"],
            source_id=fonte["id"],
            label=(fonte.get("label") or "")[:255],
        ))
    agora = datetime.now(timezone.utc)
    for ordem, item in enumerate(ids):
        origem = by_id[item]
        db.add(QuestionModel(
            id=str(uuid.uuid4()),
            quiz_id=quiz.id,
            tipo=origem.tipo,
            dificuldade=origem.dificuldade,
            enunciado=origem.enunciado,
            opcoes=origem.opcoes,
            resposta_correta=origem.resposta_correta,
            justificativa=origem.justificativa,
            conceitos_relacionados=origem.conceitos_relacionados,
            topico_origem=origem.topico_origem,
            grounding_score=origem.grounding_score,
            verificado=origem.verificado,
            # Copia de copia continua apontando para a questao raiz: o banco
            # lista a origem uma vez so, por mais quizzes que ela componha.
            origem_id=origem.origem_id or origem.id,
            # Ordem de escolha vira ordem do quiz: a apresentacao segue
            # created_at, e o DATETIME do MySQL nao guarda fracao de segundo.
            created_at=datetime.fromtimestamp(agora.timestamp() + ordem, timezone.utc),
        ))
    await db.commit()
    await db.refresh(quiz)
    return await _build_quiz_response(db, quiz)


def _mensagem_do_quiz(
    total_questoes: int,
    fontes: Sequence[Dict[str, str]],
    ignoradas: Sequence[str],
) -> str:
    """Diz de onde o quiz saiu e o que ficou de fora.

    Fonte marcada que nao entrou tem de aparecer: sem isso o professor acha que
    a aula de hoje virou pergunta quando ela estava vazia, e so descobre o
    contrario lendo as perguntas uma por uma.
    """
    partes = [
        f"{total_questoes} questões preparadas para revisão",
        f"de {len(fontes)} fonte(s)" if len(fontes) > 1 else "",
        ". Libere o QR Code quando estiver pronto para aplicar.",
    ]
    mensagem = " ".join(parte for parte in partes[:2] if parte) + partes[2]
    if ignoradas:
        mensagem += f" Ficou de fora por não ter texto: {', '.join(ignoradas)}."
    return mensagem


async def _persist_generated_quiz(
    quiz_data: dict,
    *,
    request: QuizCreateRequest,
    tutor_id: str,
    titulo: str,
    fontes: Sequence[Dict[str, str]],
    db: AsyncSession,
    ignoradas: Sequence[str] = (),
    lesson_id: str = "",
):
    """Valida, grava e devolve o quiz gerado, vindo de quantas fontes forem.

    Compartilhado por todos os caminhos de proposito: filtro de questao
    invalida, serializacao das alternativas e resposta sao regra de quiz, nao de
    fonte - duplicar isso deixaria os caminhos divergindo na primeira correcao.

    `lesson_id` vazio marca quiz sem aula. A coluna e NOT NULL e nao ha
    migracao aqui, entao a origem real fica em `quiz_sources`, uma linha por
    fonte.
    """
    if quiz_data.get("error"):
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao gerar quiz: {quiz_data['error']}"
        )

    questoes_geradas = [
        item for item in quiz_data.get("questoes", [])
        if (item.get("enunciado") or "").strip()
        and item.get("tipo") in {"multipla_escolha", "verdadeiro_falso"}
        and (item.get("tipo") != "multipla_escolha" or bool(item.get("opcoes")))
    ]
    if not questoes_geradas:
        raise HTTPException(
            status_code=502,
            detail=(
                "A IA não gerou perguntas válidas para este quiz. "
                "Tente novamente com menos questões ou outro tipo de quiz."
            ),
        )

    quiz_id = str(uuid.uuid4())
    db.add(QuizModel(
        id=quiz_id,
        tutor_id=tutor_id,
        lesson_id=lesson_id,
        titulo=titulo,
        tipo_quiz=request.tipo_quiz,
        status="draft",
        total_questoes=len(questoes_geradas),
        tempo_estimado=quiz_data.get("tempo_estimado", 15),
    ))
    for fonte in fontes:
        db.add(QuizSourceModel(
            quiz_id=quiz_id,
            source_type=fonte.get("type") or "lesson",
            source_id=fonte.get("id") or "",
            label=(fonte.get("label") or "")[:255],
        ))

    questoes_responses = []
    for q_data in questoes_geradas:
        question_id = str(uuid.uuid4())
        opcoes_json = None
        if q_data.get("tipo") == "multipla_escolha" and q_data.get("opcoes"):
            opcoes_json = json.dumps(q_data["opcoes"], ensure_ascii=False)
        conceitos_json = json.dumps(
            q_data.get("conceitos", []),
            ensure_ascii=False
        ) if q_data.get("conceitos") else None

        db.add(QuestionModel(
            id=question_id,
            quiz_id=quiz_id,
            tipo=q_data.get("tipo", "multipla_escolha"),
            dificuldade=q_data.get("dificuldade", "medio"),
            enunciado=q_data.get("enunciado", ""),
            opcoes=opcoes_json,
            resposta_correta=q_data.get("resposta_correta", ""),
            justificativa=q_data.get("justificativa", ""),
            conceitos_relacionados=conceitos_json,
            topico_origem=q_data.get("topico_origem"),
            grounding_score=q_data.get("grounding_score", 0.8),
            verificado=q_data.get("verificado", True),
        ))

        questoes_responses.append(QuestionResponse(
            id=question_id,
            quiz_id=quiz_id,
            tipo=q_data.get("tipo", "multipla_escolha"),
            dificuldade=q_data.get("dificuldade", "medio"),
            enunciado=q_data.get("enunciado", ""),
            opcoes=[QuestionOption(**o) for o in (q_data.get("opcoes", []) or [])],
            resposta_correta=q_data.get("resposta_correta"),
            justificativa=q_data.get("justificativa", ""),
            conceitos_relacionados=q_data.get("conceitos", []),
            topico_origem=q_data.get("topico_origem"),
            grounding_score=q_data.get("grounding_score", 0.8),
            verificado=q_data.get("verificado", True),
            created_at=datetime.now(timezone.utc),
        ))

    await db.commit()

    return QuizGenerateResponse(
        quiz_id=quiz_id,
        titulo=titulo,
        questoes=questoes_responses,
        tempo_estimado_resposta=quiz_data.get("tempo_estimado", 15),
        status="draft",
        message=_mensagem_do_quiz(len(questoes_responses), fontes, ignoradas),
        attempts=quiz_data.get("attempts", []),
    )


async def _build_quiz_response(db: AsyncSession, quiz: QuizModel) -> QuizResponse:
    """Monta um quiz com questoes no contrato consumido pela interface."""

    stmt = select(QuestionModel).where(QuestionModel.quiz_id == quiz.id)
    questions = (await db.execute(stmt)).scalars().all()

    questoes_responses = []
    for q in questions:
        opcoes = []
        if q.opcoes:
            try:
                opcoes = [QuestionOption(**o) for o in json.loads(q.opcoes)]
            except (TypeError, ValueError):
                pass

        try:
            conceitos = json.loads(q.conceitos_relacionados or "[]")
        except (TypeError, ValueError):
            conceitos = []

        questoes_responses.append(QuestionResponse(
            id=q.id,
            quiz_id=q.quiz_id,
            tipo=q.tipo,
            dificuldade=q.dificuldade,
            enunciado=q.enunciado,
            opcoes=opcoes,
            resposta_correta=q.resposta_correta,
            justificativa=q.justificativa or "",
            conceitos_relacionados=conceitos,
            topico_origem=q.topico_origem,
            grounding_score=q.grounding_score or 0.0,
            verificado=bool(q.verificado),
            created_at=q.created_at,
        ))

    return QuizResponse(
        id=quiz.id,
        lesson_id=quiz.lesson_id,
        titulo=quiz.titulo,
        tipo_quiz=quiz.tipo_quiz,
        status=quiz.status or "open",
        total_questoes=quiz.total_questoes,
        tempo_estimado=quiz.tempo_estimado or 0,
        questoes=questoes_responses,
        live_phase=quiz.live_phase or "lobby",
        current_question_id=quiz.current_question_id,
        question_started_at=quiz.question_started_at,
        closed_at=quiz.closed_at,
        created_at=quiz.created_at,
    )


async def _quiz_questions(db: AsyncSession, quiz_id: str) -> list[QuestionModel]:
    stmt = (
        select(QuestionModel)
        .where(QuestionModel.quiz_id == quiz_id)
        .order_by(QuestionModel.created_at, QuestionModel.id)
    )
    return list((await db.execute(stmt)).scalars().all())


def _quiz_question_options(question: QuestionModel) -> list[dict]:
    if question.tipo != "multipla_escolha" or not question.opcoes:
        return []
    try:
        decoded = json.loads(question.opcoes)
        return decoded if isinstance(decoded, list) else []
    except (TypeError, ValueError):
        return []


def _is_quiz_answer_correct(question: QuestionModel, resposta: Optional[str]) -> Optional[bool]:
    if resposta is None:
        return None
    expected = (question.resposta_correta or "").strip().lower()
    received = resposta.strip()
    if question.tipo == "verdadeiro_falso":
        truthy = {"verdadeiro", "v", "true", "sim", "s", "yes"}
        falsy = {"falso", "f", "false", "nao", "não", "n", "no"}
        expected_bool = expected in truthy
        if received.lower() in truthy:
            return expected_bool
        if received.lower() in falsy:
            return not expected_bool
        return False
    if question.tipo == "multipla_escolha":
        for option in _quiz_question_options(question):
            if option.get("correta") is True:
                return received == str(option.get("label", "")).strip()
    return received.lower() == expected


def _quiz_response_time_ms(started_at: Optional[datetime]) -> Optional[int]:
    if started_at is None:
        return None
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    elapsed = datetime.now(timezone.utc) - started_at.astimezone(timezone.utc)
    return max(0, int(elapsed.total_seconds() * 1000))


def _quiz_answer_score(correta: Optional[bool], elapsed_ms: Optional[int]) -> int:
    if correta is not True:
        return 0
    elapsed_seconds = (elapsed_ms or 0) / 1000
    speed_factor = max(0.0, 1.0 - min(elapsed_seconds, 30) / 30)
    return max(100, int(round(1000 * speed_factor)))


@router.get("/quiz/{quiz_id}")
async def get_quiz(
    quiz_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Recupera um quiz específico com suas questões."""

    tutor_id = user["tutor_id"]

    # Valida propriedade
    quiz = await db.get(QuizModel, quiz_id)
    if not quiz or quiz.tutor_id != tutor_id:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")

    return await _build_quiz_response(db, quiz)


@router.post("/quiz/{quiz_id}/publish")
async def publish_quiz(
    quiz_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Libera o quiz validado para os alunos acessarem por link/QR Code."""

    tutor_id = user["tutor_id"]
    quiz = await db.get(QuizModel, quiz_id)
    if not quiz or quiz.tutor_id != tutor_id:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")
    if quiz.status == "closed":
        raise HTTPException(status_code=409, detail="Quiz já encerrado")
    if quiz.total_questoes <= 0:
        raise HTTPException(status_code=409, detail="Quiz sem perguntas")

    if quiz.status != "open":
        quiz.status = "open"
        quiz.live_phase = "lobby"
        quiz.current_question_id = None
        quiz.question_started_at = None
        await db.commit()
        await db.refresh(quiz)

    return await _build_quiz_response(db, quiz)


@router.post("/quiz/{quiz_id}/next-question")
async def next_quiz_question(
    quiz_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Abre a proxima pergunta do quiz ao vivo para todos os alunos."""

    tutor_id = user["tutor_id"]
    quiz = await db.get(QuizModel, quiz_id)
    if not quiz or quiz.tutor_id != tutor_id:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")
    if quiz.status == "closed":
        raise HTTPException(status_code=409, detail="Quiz já encerrado")
    if quiz.status != "open":
        raise HTTPException(status_code=409, detail="Libere o quiz primeiro")

    questions = await _quiz_questions(db, quiz_id)
    if not questions:
        raise HTTPException(status_code=409, detail="Quiz sem perguntas")

    current_index = -1
    if quiz.current_question_id:
        current_index = next(
            (
                index
                for index, question in enumerate(questions)
                if question.id == quiz.current_question_id
            ),
            -1,
        )

    next_index = current_index + 1
    if next_index >= len(questions):
        quiz.live_phase = "finished"
        quiz.current_question_id = None
        quiz.question_started_at = None
    else:
        quiz.live_phase = "question"
        quiz.current_question_id = questions[next_index].id
        quiz.question_started_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(quiz)
    return await _build_quiz_response(db, quiz)


@router.post("/quiz/{quiz_id}/close-question")
async def close_quiz_question(
    quiz_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Encerra a pergunta atual e exibe ranking da rodada."""

    tutor_id = user["tutor_id"]
    quiz = await db.get(QuizModel, quiz_id)
    if not quiz or quiz.tutor_id != tutor_id:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")
    if quiz.status == "closed":
        raise HTTPException(status_code=409, detail="Quiz já encerrado")
    if quiz.live_phase != "question" or not quiz.current_question_id:
        raise HTTPException(status_code=409, detail="Nenhuma pergunta aberta")

    quiz.live_phase = "results"
    await db.commit()
    await db.refresh(quiz)
    return await _build_quiz_response(db, quiz)


@router.post("/quiz/{quiz_id}/close")
async def close_quiz(
    quiz_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Encerra o quiz e bloqueia novas respostas pelo link publico."""

    tutor_id = user["tutor_id"]
    quiz = await db.get(QuizModel, quiz_id)
    if not quiz or quiz.tutor_id != tutor_id:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")

    if quiz.status != "closed":
        quiz.status = "closed"
        quiz.live_phase = "finished"
        quiz.current_question_id = None
        quiz.question_started_at = None
        quiz.closed_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(quiz)

    return await _build_quiz_response(db, quiz)


@router.post("/quiz/{quiz_id}/answer")
async def submit_quiz_answer(
    quiz_id: str,
    answer: StudentAnswerRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Registra resposta de um aluno a uma questão do quiz."""

    tutor_id = user["tutor_id"]

    # Valida quiz
    quiz = await db.get(QuizModel, quiz_id)
    if not quiz or quiz.tutor_id != tutor_id:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")
    if quiz.status == "closed":
        raise HTTPException(status_code=409, detail="Quiz encerrado")
    if quiz.live_phase != "question" or quiz.current_question_id != answer.question_id:
        raise HTTPException(status_code=409, detail="Pergunta não está aberta")

    # Valida questão
    question = await db.get(QuestionModel, answer.question_id)
    if not question or question.quiz_id != quiz_id:
        raise HTTPException(status_code=404, detail="Questão não encontrada")

    resposta_correta = _is_quiz_answer_correct(question, answer.resposta)
    elapsed_ms = answer.tempo_resposta
    if elapsed_ms is None:
        elapsed_ms = _quiz_response_time_ms(quiz.question_started_at)
    pontuacao = _quiz_answer_score(resposta_correta, elapsed_ms)

    # Registra resposta
    student_answer = StudentAnswerModel(
        id=str(uuid.uuid4()),
        question_id=answer.question_id,
        student_id=user.get("id"),
        resposta=answer.resposta,
        correta=resposta_correta,
        tempo_resposta=elapsed_ms,
        pontuacao=pontuacao,
    )
    db.add(student_answer)
    await db.commit()

    return StudentAnswerResponse(
        id=student_answer.id,
        question_id=student_answer.question_id,
        resposta=student_answer.resposta,
        correta=student_answer.correta,
        tempo_resposta=student_answer.tempo_resposta,
        pontuacao=student_answer.pontuacao,
        respondido_em=student_answer.respondido_em,
    )
