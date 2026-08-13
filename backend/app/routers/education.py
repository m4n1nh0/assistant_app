"""Modo educacao: grava a aula em blocos, indexa e resume sob demanda."""

from collections import defaultdict
from datetime import datetime, time, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from loguru import logger
from sqlalchemy import delete as sql_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.database import (
    LessonModel,
    LessonPointModel,
    LessonSegmentModel,
    StudentModel,
    get_db,
)
from ..core.security import get_current_user
from ..models.schemas import (
    EmbeddingStatusResponse,
    LessonCreate,
    LessonDetailResponse,
    LessonPointCreate,
    LessonPointResponse,
    LessonResponse,
    LessonSearchResult,
    LessonSegmentIngestRequest,
    LessonSegmentIngestResponse,
    LessonSegmentResponse,
    LessonSummaryRequest,
    LessonSummaryResponse,
    LessonUpdate,
    PointsReportEntry,
    PointsReportResponse,
    StudentCreate,
    StudentImportRequest,
    StudentImportResponse,
    StudentResponse,
    StudentUpdate,
)
from ..services import education_service, embedding_service, qdrant_service
from ..services.voice_service import transcribe_audio

settings = get_settings()

router = APIRouter(
    prefix="/education",
    tags=["Education"],
    dependencies=[Depends(get_current_user)],
)


# --- Mapeadores ------------------------------------------------------------


def _student_response(item: StudentModel) -> StudentResponse:
    return StudentResponse(
        id=item.id,
        tutor_id=item.tutor_id,
        name=item.name,
        class_group=item.class_group or "",
        subject=item.subject or "",
        external_id=item.external_id,
        aliases=list(item.aliases or []),
        notes=item.notes,
        active=bool(item.active),
        created_at=item.created_at,
    )


def _lesson_response(item: LessonModel) -> LessonResponse:
    return LessonResponse(
        id=item.id,
        tutor_id=item.tutor_id,
        subject=item.subject,
        title=item.title or "",
        class_group=item.class_group or "",
        teacher=item.teacher,
        status=item.status,
        started_at=item.started_at,
        ended_at=item.ended_at,
        summary=item.summary,
        summary_llm=item.summary_llm,
        summary_at=item.summary_at,
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
        subject=item.subject or "",
        lesson_date=item.lesson_date,
        source=item.source,
        confidence=item.confidence,
        quote=item.quote,
        created_at=item.created_at,
    )


# --- Helpers ---------------------------------------------------------------


async def _get_lesson(lesson_id: str, tutor_id: str, db: AsyncSession) -> LessonModel:
    lesson = await db.get(LessonModel, lesson_id)
    if lesson is None or lesson.tutor_id != tutor_id:
        raise HTTPException(404, "Aula nao encontrada")
    return lesson


async def _roster(lesson: LessonModel, db: AsyncSession) -> List[Dict[str, Any]]:
    """Alunos da turma da aula, mais os cadastrados sem turma/disciplina.

    O cadastro sem turma funciona como lista geral do usuario, util para quem
    acompanha uma turma so e nao quer preencher esses campos.
    """
    result = await db.execute(
        select(StudentModel).where(
            StudentModel.tutor_id == lesson.tutor_id,
            StudentModel.active.is_(True),
        )
    )
    roster = []
    for student in result.scalars().all():
        group = (student.class_group or "").strip()
        subject = (student.subject or "").strip()
        if group and group != (lesson.class_group or "").strip():
            continue
        if subject and subject != (lesson.subject or "").strip():
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
            subject=lesson.subject,
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
                    subject=lesson.subject,
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


# --- Alunos ----------------------------------------------------------------


@router.get("/students", response_model=List[StudentResponse])
async def list_students(
    class_group: Optional[str] = None,
    subject: Optional[str] = None,
    active_only: bool = True,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(StudentModel).where(StudentModel.tutor_id == user["tutor_id"])
    if class_group:
        query = query.where(StudentModel.class_group == class_group)
    if subject:
        query = query.where(StudentModel.subject == subject)
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
    student = StudentModel(
        tutor_id=user["tutor_id"],
        name=name,
        class_group=body.class_group.strip(),
        subject=body.subject.strip(),
        external_id=external_id,
        aliases=[alias.strip() for alias in body.aliases if alias.strip()],
        notes=body.notes,
        active=body.active,
    )
    db.add(student)
    await db.commit()
    await db.refresh(student)
    return _student_response(student)


@router.post("/students/import", response_model=StudentImportResponse)
async def import_students(
    body: StudentImportRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    class_group = body.class_group.strip()
    subject = body.subject.strip()
    if not class_group:
        raise HTTPException(422, "Turma e obrigatoria para importar alunos")
    if not subject:
        raise HTTPException(422, "Disciplina e obrigatoria para importar alunos")

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

    result = await db.execute(
        select(StudentModel).where(
            StudentModel.tutor_id == user["tutor_id"],
            StudentModel.external_id.is_not(None),
        )
    )
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
                    class_group=class_group,
                    subject=subject,
                    aliases=[],
                    active=True,
                )
            )
            created += 1
            continue

        student.external_id = enrollment
        student.name = name
        student.class_group = class_group
        student.subject = subject
        student.active = True
        updated += 1

    await db.commit()
    return StudentImportResponse(
        created=created,
        updated=updated,
        total=created + updated,
    )


@router.patch("/students/{student_id}", response_model=StudentResponse)
async def update_student(
    student_id: str,
    body: StudentUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    student = await db.get(StudentModel, student_id)
    if student is None or student.tutor_id != user["tutor_id"]:
        raise HTTPException(404, "Aluno nao encontrado")

    for field in ("name", "class_group", "subject", "external_id", "notes", "active"):
        value = getattr(body, field)
        if value is not None:
            setattr(student, field, value)
    if body.aliases is not None:
        student.aliases = [alias.strip() for alias in body.aliases if alias.strip()]

    await db.commit()
    await db.refresh(student)
    return _student_response(student)


@router.delete("/students/{student_id}")
async def delete_student(
    student_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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
    subject = body.subject.strip()
    if not subject:
        raise HTTPException(422, "Disciplina e obrigatoria")

    lesson = LessonModel(
        tutor_id=user["tutor_id"],
        subject=subject,
        title=body.title.strip(),
        class_group=body.class_group.strip(),
        teacher=body.teacher,
        started_at=_as_utc(body.started_at) if body.started_at else datetime.now(timezone.utc),
        metadata_=body.metadata,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return _lesson_response(lesson)


@router.get("/lessons", response_model=List[LessonResponse])
async def list_lessons(
    subject: Optional[str] = None,
    class_group: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(LessonModel).where(LessonModel.tutor_id == user["tutor_id"])
    if subject:
        query = query.where(LessonModel.subject == subject)
    if class_group:
        query = query.where(LessonModel.class_group == class_group)
    start = _parse_date(date_from)
    end = _parse_date(date_to, end_of_day=True)
    if start:
        query = query.where(LessonModel.started_at >= start)
    if end:
        query = query.where(LessonModel.started_at <= end)

    result = await db.execute(query.order_by(LessonModel.started_at.desc()).limit(limit))
    return [_lesson_response(item) for item in result.scalars().all()]


@router.get("/lessons/{lesson_id}", response_model=LessonDetailResponse)
async def get_lesson(
    lesson_id: str,
    include_segments: bool = True,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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

    return LessonDetailResponse(
        **_lesson_response(lesson).model_dump(),
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
    lesson = await _get_lesson(lesson_id, user["tutor_id"], db)
    for field in ("subject", "title", "class_group", "teacher"):
        value = getattr(body, field)
        if value is not None:
            setattr(lesson, field, value)
    if body.metadata is not None:
        lesson.metadata_ = body.metadata
    await db.commit()
    await db.refresh(lesson)
    return _lesson_response(lesson)


@router.delete("/lessons/{lesson_id}")
async def delete_lesson(
    lesson_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lesson = await _get_lesson(lesson_id, user["tutor_id"], db)
    await db.execute(
        sql_delete(LessonSegmentModel).where(LessonSegmentModel.lesson_id == lesson_id)
    )
    await db.execute(
        sql_delete(LessonPointModel).where(LessonPointModel.lesson_id == lesson_id)
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
):
    """Recebe um bloco de audio da aula, transcreve, indexa e extrai pontos."""
    lesson = await _get_lesson(lesson_id, user["tutor_id"], db)
    if lesson.status == "closed":
        raise HTTPException(409, "Aula ja encerrada")

    audio_bytes = await file.read()
    stt = await transcribe_audio(audio_bytes, language)
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


@router.post("/lessons/{lesson_id}/summary", response_model=LessonSummaryResponse)
async def summarize_lesson(
    lesson_id: str,
    body: LessonSummaryRequest = LessonSummaryRequest(),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lesson = await _get_lesson(lesson_id, user["tutor_id"], db)

    result = await db.execute(
        select(LessonSegmentModel)
        .where(LessonSegmentModel.lesson_id == lesson_id)
        .order_by(LessonSegmentModel.sequence)
    )
    segments = [item.text for item in result.scalars().all()]
    if not segments:
        raise HTTPException(409, "A aula ainda nao tem transcricao")

    outcome = await education_service.generate_summary(
        subject=lesson.subject,
        title=lesson.title or "",
        segments=segments,
        llm=body.llm,
        focus=body.focus,
    )
    if not outcome["summary"]:
        raise HTTPException(
            502,
            f"Nao foi possivel gerar o resumo: {outcome.get('error', 'sem resposta do modelo')}",
        )

    lesson.summary = outcome["summary"]
    lesson.summary_llm = outcome["llm"]
    lesson.summary_at = datetime.now(timezone.utc)
    if body.close_lesson and lesson.status != "closed":
        lesson.status = "closed"
        lesson.ended_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(lesson)

    result = await db.execute(
        select(LessonPointModel)
        .where(LessonPointModel.lesson_id == lesson_id)
        .order_by(LessonPointModel.created_at)
    )
    points = [_point_response(item) for item in result.scalars().all()]

    return LessonSummaryResponse(
        lesson_id=lesson.id,
        summary=lesson.summary,
        llm=lesson.summary_llm,
        generated_at=lesson.summary_at,
        used_segments=outcome["used_segments"],
        points=points,
    )


@router.post("/lessons/{lesson_id}/close", response_model=LessonResponse)
async def close_lesson(
    lesson_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lesson = await _get_lesson(lesson_id, user["tutor_id"], db)
    if lesson.status != "closed":
        lesson.status = "closed"
        lesson.ended_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(lesson)
    return _lesson_response(lesson)


# --- Pontuacao extra -------------------------------------------------------


@router.post("/lessons/{lesson_id}/points", response_model=LessonPointResponse)
async def add_lesson_point(
    lesson_id: str,
    body: LessonPointCreate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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
        subject=lesson.subject,
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
    subject: Optional[str] = None,
    class_group: Optional[str] = None,
    student_name: Optional[str] = None,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Quanto de extra cada aluno recebeu, por dia, disciplina e turma.

    A turma nao fica no ponto: ela vem da aula que o originou, entao duas
    turmas da mesma disciplina no mesmo dia so se separam por esse join.
    """
    query = (
        select(LessonPointModel, LessonModel.class_group)
        .outerjoin(LessonModel, LessonModel.id == LessonPointModel.lesson_id)
        .where(LessonPointModel.tutor_id == user["tutor_id"])
    )
    start = _parse_date(date_from)
    end = _parse_date(date_to, end_of_day=True)
    if start:
        query = query.where(LessonPointModel.lesson_date >= start)
    if end:
        query = query.where(LessonPointModel.lesson_date <= end)
    if subject:
        query = query.where(LessonPointModel.subject == subject)
    if class_group:
        query = query.where(LessonModel.class_group == class_group)

    result = await db.execute(query.order_by(LessonPointModel.lesson_date))
    items = [(point, group or "") for point, group in result.all()]

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
            point.subject or "",
            group,
            _as_utc(point.lesson_date).date().isoformat(),
        )
        grouped[key].append(point)

    entries: List[PointsReportEntry] = []
    for (_, subject_key, group_key, date_key), group in grouped.items():
        entries.append(
            PointsReportEntry(
                student_name=group[0].student_name,
                student_id=next(
                    (item.student_id for item in group if item.student_id), None
                ),
                total_points=round(sum(item.points for item in group), 3),
                subject=subject_key,
                class_group=group_key,
                lesson_date=date_key,
                entries=[_point_response(item) for item in group],
            )
        )

    entries.sort(
        key=lambda item: (
            item.lesson_date,
            item.subject,
            item.class_group,
            item.student_name,
        )
    )
    return PointsReportResponse(
        date_from=date_from,
        date_to=date_to,
        subject=subject,
        class_group=class_group,
        total_points=round(sum(entry.total_points for entry in entries), 3),
        students=entries,
    )


# --- Busca e diagnostico ---------------------------------------------------


@router.get("/search", response_model=List[LessonSearchResult])
async def search_transcripts(
    q: str,
    subject: Optional[str] = None,
    lesson_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(8, ge=1, le=50),
    user: dict = Depends(get_current_user),
):
    start = _parse_date(date_from)
    end = _parse_date(date_to, end_of_day=True)
    results = await qdrant_service.search_lesson_transcripts(
        tutor_id=user["tutor_id"],
        query=q,
        subject=subject,
        lesson_id=lesson_id,
        ts_from=int(start.timestamp()) if start else None,
        ts_to=int(end.timestamp()) if end else None,
        limit=limit,
    )
    return [LessonSearchResult(**item) for item in results]


@router.get("/subjects", response_model=List[str])
async def list_subjects(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(LessonModel.subject)
        .where(LessonModel.tutor_id == user["tutor_id"])
        .group_by(LessonModel.subject)
        .order_by(func.min(LessonModel.subject))
    )
    return [row for row in result.scalars().all() if row]


@router.get("/embedding-status", response_model=EmbeddingStatusResponse)
async def embedding_status():
    return EmbeddingStatusResponse(**await embedding_service.describe())
