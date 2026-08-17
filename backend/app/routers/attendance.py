"""Chamada por QR Code e relatorios de presenca do modo educacional."""

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from html import escape
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    AttendanceRecordModel,
    AttendanceRosterModel,
    AttendanceSessionModel,
    ClassGroupModel,
    LessonModel,
    StudentModel,
    get_db,
)
from ..core.security import get_current_user
from ..core.rate_limit import rate_limit
from ..models.schemas import (
    AttendanceRecordCreate,
    AttendanceRecordResponse,
    AttendanceReportResponse,
    AttendanceSessionCreate,
    AttendanceSessionResponse,
    AttendanceStudentResponse,
)


router = APIRouter(prefix="/education/attendance", tags=["education-attendance"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _class_label(group: ClassGroupModel) -> str:
    label = " ".join(
        part for part in ((group.code or "").strip(), (group.name or "").strip()) if part
    )
    return label or (group.discipline or "").strip() or "turma"


def _session_is_open(session: AttendanceSessionModel) -> bool:
    return session.closed_at is None and _as_utc(session.expires_at) > _now()


def _parse_iso_date(value: Optional[str], field: str) -> Optional[str]:
    clean = (value or "").strip()
    if not clean:
        return None
    try:
        return date.fromisoformat(clean).isoformat()
    except ValueError as exc:
        raise HTTPException(422, f"{field} deve usar o formato AAAA-MM-DD") from exc


async def _owned_group(
    class_id: str,
    tutor_id: str,
    db: AsyncSession,
) -> ClassGroupModel:
    group = await db.get(ClassGroupModel, class_id)
    if group is None or group.tutor_id != tutor_id:
        raise HTTPException(404, "Turma nao encontrada")
    return group


async def _owned_session(
    session_id: str,
    tutor_id: str,
    db: AsyncSession,
) -> AttendanceSessionModel:
    session = await db.get(AttendanceSessionModel, session_id)
    if session is None or session.tutor_id != tutor_id:
        raise HTTPException(404, "Chamada nao encontrada")
    return session


async def _session_response(
    session: AttendanceSessionModel,
    db: AsyncSession,
    *,
    check_in_url: str = "",
    check_in_path: str = "",
) -> AttendanceSessionResponse:
    records = list(
        (
            await db.execute(
                select(AttendanceRecordModel)
                .where(AttendanceRecordModel.session_id == session.id)
                .order_by(AttendanceRecordModel.student_name)
            )
        )
        .scalars()
        .all()
    )
    roster = list(
        (
            await db.execute(
                select(AttendanceRosterModel)
                .where(AttendanceRosterModel.session_id == session.id)
                .order_by(AttendanceRosterModel.student_name)
            )
        )
        .scalars()
        .all()
    )
    present_ids = {record.student_id for record in records}
    return AttendanceSessionResponse(
        id=session.id,
        class_id=session.class_group_id,
        class_label=session.class_label or "",
        discipline=session.discipline or "",
        semester=session.semester or "",
        attendance_date=session.attendance_date,
        title=session.title or "",
        lesson_id=session.lesson_id,
        opened_at=session.opened_at,
        expires_at=session.expires_at,
        closed_at=session.closed_at,
        open=_session_is_open(session),
        check_in_url=check_in_url,
        check_in_path=check_in_path,
        expected_count=session.expected_count,
        present_count=len(records),
        records=[
            AttendanceRecordResponse(
                id=record.id,
                student_id=record.student_id,
                enrollment=record.enrollment,
                student_name=record.student_name,
                source=record.source,
                checked_in_at=record.checked_in_at,
            )
            for record in records
        ],
        absent_students=[
            AttendanceStudentResponse(
                student_id=student.student_id,
                enrollment=student.enrollment,
                student_name=student.student_name,
            )
            for student in roster
            if student.student_id not in present_ids
        ],
    )


@router.post("/sessions", response_model=AttendanceSessionResponse)
async def create_attendance_session(
    body: AttendanceSessionCreate,
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    group = await _owned_group(body.class_id.strip(), user["tutor_id"], db)
    if not group.active:
        raise HTTPException(409, "A turma esta encerrada")
    if body.lesson_id:
        lesson = await db.get(LessonModel, body.lesson_id)
        if lesson is None or lesson.tutor_id != user["tutor_id"]:
            raise HTTPException(404, "Aula nao encontrada")
    attendance_date = _parse_iso_date(body.attendance_date, "Data") or date.today().isoformat()
    now = _now()

    open_sessions = list(
        (
            await db.execute(
                select(AttendanceSessionModel).where(
                    AttendanceSessionModel.tutor_id == user["tutor_id"],
                    AttendanceSessionModel.class_group_id == group.id,
                    AttendanceSessionModel.closed_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for previous in open_sessions:
        previous.closed_at = now

    students = list(
        (
            await db.execute(
                select(StudentModel)
                .where(
                    StudentModel.tutor_id == user["tutor_id"],
                    StudentModel.class_id == group.id,
                    StudentModel.active.is_(True),
                )
                .order_by(StudentModel.name)
            )
        )
        .scalars()
        .all()
    )
    token = secrets.token_urlsafe(32)
    session = AttendanceSessionModel(
        tutor_id=user["tutor_id"],
        class_group_id=group.id,
        class_label=_class_label(group),
        discipline=group.discipline or "",
        semester=group.semester or "",
        lesson_id=body.lesson_id,
        attendance_date=attendance_date,
        title=body.title.strip(),
        token_hash=_token_hash(token),
        expected_count=len(students),
        opened_at=now,
        expires_at=now + timedelta(minutes=body.duration_minutes),
    )
    db.add(session)
    await db.flush()
    for student in students:
        db.add(
            AttendanceRosterModel(
                session_id=session.id,
                student_id=student.id,
                enrollment=(student.external_id or "").strip(),
                student_name=student.name,
            )
        )
    await db.commit()
    await db.refresh(session)

    base_url = str(request.base_url).rstrip("/")
    check_in_path = f"/education/attendance/check-in/{token}"
    check_in_url = f"{base_url}{check_in_path}"
    return await _session_response(
        session,
        db,
        check_in_url=check_in_url,
        check_in_path=check_in_path,
    )


@router.get("/sessions", response_model=list[AttendanceSessionResponse])
async def list_attendance_sessions(
    class_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(AttendanceSessionModel).where(
        AttendanceSessionModel.tutor_id == user["tutor_id"]
    )
    if class_id:
        query = query.where(AttendanceSessionModel.class_group_id == class_id)
    start = _parse_iso_date(date_from, "Data inicial")
    end = _parse_iso_date(date_to, "Data final")
    if start:
        query = query.where(AttendanceSessionModel.attendance_date >= start)
    if end:
        query = query.where(AttendanceSessionModel.attendance_date <= end)
    sessions = list(
        (
            await db.execute(
                query.order_by(
                    AttendanceSessionModel.attendance_date.desc(),
                    AttendanceSessionModel.opened_at.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    responses = []
    for session in sessions:
        responses.append(await _session_response(session, db))
    return responses


@router.get("/sessions/{session_id}", response_model=AttendanceSessionResponse)
async def get_attendance_session(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await _owned_session(session_id, user["tutor_id"], db)
    return await _session_response(session, db)


@router.post("/sessions/{session_id}/close", response_model=AttendanceSessionResponse)
async def close_attendance_session(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await _owned_session(session_id, user["tutor_id"], db)
    if session.closed_at is None:
        session.closed_at = _now()
        await db.commit()
        await db.refresh(session)
    return await _session_response(session, db)


async def _register_attendance(
    session: AttendanceSessionModel,
    enrollment: str,
    source: str,
    db: AsyncSession,
) -> tuple[AttendanceRecordModel, bool]:
    clean = enrollment.strip()
    roster_entry = (
        await db.execute(
            select(AttendanceRosterModel).where(
                AttendanceRosterModel.session_id == session.id,
                AttendanceRosterModel.enrollment == clean,
            )
        )
    ).scalars().first()
    if roster_entry is None:
        raise HTTPException(404, "Matricula nao encontrada nesta turma")

    existing = (
        await db.execute(
            select(AttendanceRecordModel).where(
                AttendanceRecordModel.session_id == session.id,
                AttendanceRecordModel.student_id == roster_entry.student_id,
            )
        )
    ).scalars().first()
    if existing is not None:
        return existing, False

    record = AttendanceRecordModel(
        session_id=session.id,
        student_id=roster_entry.student_id,
        enrollment=roster_entry.enrollment,
        student_name=roster_entry.student_name,
        source=source,
        checked_in_at=_now(),
    )
    db.add(record)
    try:
        await db.commit()
    except IntegrityError:
        # Dois envios simultaneos da mesma matricula continuam idempotentes.
        await db.rollback()
        existing = (
            await db.execute(
                select(AttendanceRecordModel).where(
                    AttendanceRecordModel.session_id == session.id,
                    AttendanceRecordModel.student_id == roster_entry.student_id,
                )
            )
        ).scalars().first()
        if existing is not None:
            return existing, False
        raise
    await db.refresh(record)
    return record, True


@router.post(
    "/sessions/{session_id}/records",
    response_model=AttendanceSessionResponse,
)
async def add_manual_attendance(
    session_id: str,
    body: AttendanceRecordCreate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await _owned_session(session_id, user["tutor_id"], db)
    await _register_attendance(session, body.enrollment, "manual", db)
    return await _session_response(session, db)


@router.delete("/sessions/{session_id}/records/{record_id}")
async def delete_attendance_record(
    session_id: str,
    record_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _owned_session(session_id, user["tutor_id"], db)
    record = await db.get(AttendanceRecordModel, record_id)
    if record is None or record.session_id != session_id:
        raise HTTPException(404, "Presenca nao encontrada")
    await db.delete(record)
    await db.commit()
    return {"ok": True}


@router.get("/report", response_model=AttendanceReportResponse)
async def attendance_report(
    class_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sessions = await list_attendance_sessions(
        class_id=class_id,
        date_from=date_from,
        date_to=date_to,
        user=user,
        db=db,
    )
    return AttendanceReportResponse(
        date_from=_parse_iso_date(date_from, "Data inicial"),
        date_to=_parse_iso_date(date_to, "Data final"),
        class_id=class_id,
        session_count=len(sessions),
        expected_total=sum(session.expected_count for session in sessions),
        present_total=sum(session.present_count for session in sessions),
        sessions=sessions,
    )


async def _public_session(token: str, db: AsyncSession) -> AttendanceSessionModel:
    session = (
        await db.execute(
            select(AttendanceSessionModel).where(
                AttendanceSessionModel.token_hash == _token_hash(token)
            )
        )
    ).scalars().first()
    if session is None:
        raise HTTPException(404, "Chamada nao encontrada")
    return session


def _check_in_page(
    *,
    title: str,
    message: str,
    open_for_check_in: bool,
    ok: Optional[bool] = None,
) -> HTMLResponse:
    accent = "#059669" if ok is not False else "#dc2626"
    form = ""
    if open_for_check_in:
        form = f"""
          <form method="post">
            <label for="enrollment">Matrícula</label>
            <input id="enrollment" name="enrollment" maxlength="80"
                   inputmode="numeric" autocomplete="off" required autofocus
                   placeholder="Digite sua matrícula">
            <button type="submit">CONFIRMAR PRESENÇA</button>
          </form>
        """
    return HTMLResponse(
        f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chamada - {escape(title)}</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;background:#f3f6fa;color:#111827;
font:16px system-ui,-apple-system,Segoe UI,sans-serif;min-height:100vh;display:grid;
place-items:center;padding:20px}} main{{width:min(440px,100%);background:white;border:1px solid
#d8e0ea;border-radius:12px;padding:28px;box-shadow:0 14px 35px #11182718}}
.mark{{color:{accent};font-size:12px;font-weight:800;letter-spacing:2px}}
h1{{font-size:23px;margin:8px 0 6px}} p{{color:#526277;line-height:1.45;margin:0 0 20px}}
label{{display:block;font-size:12px;font-weight:700;margin-bottom:6px}} input{{width:100%;
padding:13px;border:1px solid #b9c5d3;border-radius:7px;font-size:18px;margin-bottom:12px}}
button{{width:100%;padding:13px;border:0;border-radius:7px;background:#059669;color:white;
font-weight:800;letter-spacing:.7px;cursor:pointer}} small{{display:block;color:#7b8999;
margin-top:18px;line-height:1.4}}
</style></head><body><main><div class="mark">ASSISTENTE EDUCACIONAL</div>
<h1>{escape(title)}</h1><p>{escape(message)}</p>{form}
<small>O código é temporário. Sua matrícula é usada somente para confirmar a presença nesta aula.</small>
</main></body></html>"""
    )


@router.get("/check-in/{token}", response_class=HTMLResponse)
async def attendance_check_in_page(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        session = await _public_session(token, db)
    except HTTPException:
        return _check_in_page(
            title="Chamada indisponível",
            message="Este código não existe ou já foi substituído.",
            open_for_check_in=False,
            ok=False,
        )
    if not _session_is_open(session):
        return _check_in_page(
            title="Chamada encerrada",
            message="O período para confirmar presença terminou.",
            open_for_check_in=False,
            ok=False,
        )
    return _check_in_page(
        title=session.title or "Confirmar presença",
        message="Informe sua matrícula para registrar a presença nesta aula.",
        open_for_check_in=True,
    )


@router.post(
    "/check-in/{token}",
    response_class=HTMLResponse,
    dependencies=[Depends(rate_limit(times=120, seconds=60))],
)
async def submit_attendance_check_in(
    token: str,
    enrollment: str = Form(..., min_length=1, max_length=80),
    db: AsyncSession = Depends(get_db),
):
    try:
        session = await _public_session(token, db)
        if not _session_is_open(session):
            return _check_in_page(
                title="Chamada encerrada",
                message="O período para confirmar presença terminou.",
                open_for_check_in=False,
                ok=False,
            )
        record, created = await _register_attendance(session, enrollment, "qr", db)
    except HTTPException as exc:
        return _check_in_page(
            title="Não foi possível confirmar",
            message=str(exc.detail),
            open_for_check_in=True,
            ok=False,
        )
    return _check_in_page(
        title="Presença confirmada",
        message=(
            f"Obrigado, {record.student_name}. Sua presença foi registrada."
            if created
            else f"{record.student_name}, sua presença já estava registrada."
        ),
        open_for_check_in=False,
        ok=True,
    )
