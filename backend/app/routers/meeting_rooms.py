"""Reunião online própria: a sala do professor e a página de quem entra.

Duas partes. `/education/meet/{token}` é pública: a página, a entrada, o batimento e o
envio da fala para transcrever (a chave de quem entrou é a credencial). `/education/
meetings` é do professor, autenticada: criar a sala, ver quem está nela e a transcrição
ao vivo, e encerrar. Áudio e vídeo nunca são gravados; só a fala transcrita fica, como
trechos da gravação (tipo reunião) ligada à sala.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.database import (
    LessonModel,
    LessonSegmentModel,
    MeetingRoomModel,
    get_db,
)
from ..core.security import get_current_user
from ..services import meeting_room_page as page
from ..services import meeting_room_service as rooms
from ..services.user_llm_config_service import (
    activate_user_llms,
    load_user_llm_runtime,
    reset_user_llms,
)
from ..services.voice_service import STTUnavailable, transcribe_audio

public = APIRouter(prefix="/education/meet", tags=["education-meet"])
router = APIRouter(prefix="/education/meetings", tags=["education-meetings"])

#: Um pedaço de fala tem poucos segundos; acima disso não é fala de uma pessoa.
MAX_AUDIO_BYTES = 3 * 1024 * 1024
MAX_AUDIO_MS = 60_000
TRANSCRIPT_TAIL = 40


class JoinBody(BaseModel):
    name: str = Field(default="", max_length=120)
    enrollment: str = Field(default="", max_length=64)
    consent: bool = False
    host_key: str = Field(default="", max_length=128)


class ParticipantBody(BaseModel):
    participant_id: str = Field(default="", max_length=64)
    secret: str = Field(default="", max_length=128)


class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    guests_allowed: bool = True
    max_participants: Optional[int] = Field(default=None, ge=2, le=100)
    scheduled_at: Optional[datetime] = None


class MeetingUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    guests_allowed: Optional[bool] = None
    max_participants: Optional[int] = Field(default=None, ge=2, le=100)


def _error(exc: rooms.MeetingError) -> JSONResponse:
    return JSONResponse(
        {"code": exc.code, "detail": exc.message}, status_code=exc.status,
        headers={"Cache-Control": "no-store"})


async def _room_or_404(db: AsyncSession, token: str) -> MeetingRoomModel:
    room = await rooms.get_room_by_token(db, token)
    if room is None:
        raise HTTPException(404, "Reunião não encontrada")
    return room


# --- pública: a página e a sala -----------------------------------------------------


@public.get("/{token}", response_class=HTMLResponse)
async def meeting_page(token: str, db: AsyncSession = Depends(get_db)):
    room = await rooms.get_room_by_token(db, token)
    if room is None:
        return HTMLResponse(page.render_closed_page(
            "Este link não existe ou foi apagado. Confira com o professor."))
    if room.status != "open":
        return HTMLResponse(page.render_closed_page("Esta reunião já foi encerrada."))
    return HTMLResponse(
        page.render_room_page(
            token=room.token, title=room.title, guests_allowed=room.guests_allowed),
        headers={"Cache-Control": "no-store"},
    )


@public.post("/{token}/join")
async def join(token: str, body: JoinBody, db: AsyncSession = Depends(get_db)):
    room = await _room_or_404(db, token)
    settings = get_settings()
    if not rooms.livekit_configured(settings):
        return _error(rooms.MeetingError(
            "not_configured",
            "A sala de vídeo ainda não foi configurada neste servidor. Avise o professor.",
            503))
    try:
        participant = await rooms.join(
            db, room, name=body.name, enrollment=body.enrollment,
            consent=body.consent, host_key=body.host_key)
    except rooms.MeetingError as exc:
        return _error(exc)
    return JSONResponse(
        {
            "participant_id": participant.id,
            "secret": participant.secret,
            "identity": participant.id,
            "name": participant.name,
            "title": room.title,
            "is_host": participant.is_host,
            "guest": participant.student_id is None and not participant.is_host,
            "livekit_url": settings.livekit_url,
            "livekit_token": rooms.build_livekit_token(
                identity=participant.id, name=participant.name, room=room.id,
                host=participant.is_host, settings=settings),
        },
        headers={"Cache-Control": "no-store"},
    )


@public.post("/{token}/heartbeat")
async def heartbeat(token: str, body: ParticipantBody, db: AsyncSession = Depends(get_db)):
    room = await _room_or_404(db, token)
    try:
        return await rooms.heartbeat(db, room, body.participant_id, body.secret)
    except rooms.MeetingError as exc:
        return _error(exc)


@public.post("/{token}/leave")
async def leave(token: str, body: ParticipantBody, db: AsyncSession = Depends(get_db)):
    room = await _room_or_404(db, token)
    try:
        await rooms.leave(db, room, body.participant_id, body.secret)
    except rooms.MeetingError as exc:
        return _error(exc)
    return {"left": True}


@public.post("/{token}/end")
async def end_by_host(token: str, body: ParticipantBody,
                      db: AsyncSession = Depends(get_db)):
    """O professor encerra a reunião pela própria página, para todos."""
    room = await _room_or_404(db, token)
    try:
        participant = await rooms.authenticate(db, room, body.participant_id, body.secret)
    except rooms.MeetingError as exc:
        return _error(exc)
    if not participant.is_host:
        return _error(rooms.MeetingError(
            "host", "Só o professor encerra a reunião para todos.", 403))
    await rooms.end_room(db, room)
    return {"ended": True}


@public.post("/{token}/audio")
async def audio(
    token: str,
    participant_id: str = Form(""),
    secret: str = Form(""),
    duration_ms: int = Form(0),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Transcreve um pedaço da fala de quem está na sala.

    O pedaço só existe durante esta chamada: é transcrito e descartado. O texto entra
    como trecho da gravação da sala, com o nome de quem falou na frente.
    """
    from . import education

    room = await _room_or_404(db, token)
    try:
        participant = await rooms.authenticate(db, room, participant_id, secret)
    except rooms.MeetingError as exc:
        return _error(exc)
    if room.status != "open" or participant.left_at is not None:
        return _error(rooms.MeetingError("ended", "A reunião não está aberta.", 409))
    data = await file.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        return _error(rooms.MeetingError("size", "Pedaço de áudio grande demais.", 413))
    if not data:
        return {"ok": True, "skipped": "vazio"}
    lesson = await db.get(LessonModel, room.lesson_id) if room.lesson_id else None
    if lesson is None or lesson.status == "closed":
        return _error(rooms.MeetingError("ended", "A reunião não está aberta.", 409))

    # O reconhecimento e a indexação usam as chaves do professor, não as de quem fala.
    token_ctx = activate_user_llms(await load_user_llm_runtime(room.tutor_id))
    try:
        try:
            stt = await transcribe_audio(data, "pt", context=room.title)
        except STTUnavailable as exc:
            return JSONResponse({"code": "stt", "detail": str(exc)}, status_code=503,
                                headers={"Retry-After": "30"})
        text = " ".join((stt.transcript or "").split())
        if not text:
            return {"ok": True, "skipped": "sem fala"}
        result = await education._ingest_segment(
            lesson=lesson, text=f"{participant.name}: {text}",
            confidence=stt.confidence,
            duration_ms=max(0, min(int(duration_ms or 0), MAX_AUDIO_MS)),
            extract_points=False, min_chars=1, trim_overlap=False, db=db)
    finally:
        reset_user_llms(token_ctx)
    if result.segment is not None:
        participant.spoken_chunks = int(participant.spoken_chunks or 0) + 1
        await db.commit()
    return {"ok": True, "skipped": result.skipped_reason or "", "indexed": result.indexed}


# --- do professor -------------------------------------------------------------------


def _host_of(url: str) -> str:
    return urlparse(url).netloc or url


def _room_out(room: MeetingRoomModel, *, online: int = 0, people: int = 0,
              segments: int = 0) -> dict:
    return dict(
        id=room.id, title=room.title, status=room.status, token=room.token,
        join_path=f"/education/meet/{room.token}",
        host_path=f"/education/meet/{room.token}#host={room.host_key}",
        guests_allowed=bool(room.guests_allowed),
        max_participants=room.max_participants, lesson_id=room.lesson_id,
        scheduled_at=room.scheduled_at, created_at=room.created_at,
        ended_at=room.ended_at, online=online, people=people, segments=segments,
    )


async def _owned_room(db: AsyncSession, room_id: str, tutor_id: str) -> MeetingRoomModel:
    room = await db.get(MeetingRoomModel, room_id)
    if room is None or room.tutor_id != tutor_id:
        raise HTTPException(404, "Reunião não encontrada")
    return room


@router.get("/config")
async def meeting_config(user: dict = Depends(get_current_user)):
    """Diz se a sala de vídeo está configurada neste servidor, para a tela avisar."""
    settings = get_settings()
    return {
        "configured": rooms.livekit_configured(settings),
        "media_host": _host_of(settings.livekit_url) if settings.livekit_url else "",
        "default_max_participants": settings.meeting_default_max_participants,
        "missing": [
            name for name, value in (
                ("LIVEKIT_URL", settings.livekit_url),
                ("LIVEKIT_API_KEY", settings.livekit_api_key),
                ("LIVEKIT_API_SECRET", settings.livekit_api_secret),
            ) if not value
        ],
    }


@router.post("")
async def create_meeting(
    body: MeetingCreate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cria a sala e a gravação (só texto) onde a transcrição vai entrando."""
    from . import education

    settings = get_settings()
    title = " ".join(body.title.split())
    now = datetime.now(timezone.utc)
    lesson = LessonModel(
        tutor_id=user["tutor_id"], kind="reuniao", discipline="",
        semester=education._semester_code(""), title=title, class_group="",
        started_at=now, metadata_={"source": "sala-propria"},
    )
    db.add(lesson)
    await db.flush()
    room = MeetingRoomModel(
        tutor_id=user["tutor_id"], lesson_id=lesson.id, title=title,
        token=rooms.new_token(), host_key=rooms.new_secret(),
        guests_allowed=body.guests_allowed,
        max_participants=body.max_participants or settings.meeting_default_max_participants,
        scheduled_at=rooms._naive(body.scheduled_at),
    )
    db.add(room)
    await db.commit()
    await db.refresh(room)
    return _room_out(room)


@router.get("")
async def list_meetings(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """As salas do professor: abertas primeiro, depois as mais recentes."""
    rows = (await db.execute(
        select(MeetingRoomModel).where(MeetingRoomModel.tutor_id == user["tutor_id"])
        .order_by(MeetingRoomModel.created_at.desc()).limit(50))).scalars().all()
    out = []
    for room in rows:
        people = await rooms.participants_of(db, room.id)
        lesson = await db.get(LessonModel, room.lesson_id) if room.lesson_id else None
        out.append(_room_out(
            room, online=sum(1 for item in people if rooms.is_online(item)),
            people=len(rooms.presence(people)),
            segments=int(lesson.segment_count or 0) if lesson else 0))
    out.sort(key=lambda item: item["status"] != "open")
    return out


@router.get("/{room_id}")
async def get_meeting(
    room_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A sala, quem está nela (presença) e o fim da transcrição, para a tela ao vivo."""
    room = await _owned_room(db, room_id, user["tutor_id"])
    people = await rooms.participants_of(db, room.id)
    presence = rooms.presence(people)
    lesson = await db.get(LessonModel, room.lesson_id) if room.lesson_id else None
    tail = []
    if lesson is not None:
        rows = (await db.execute(
            select(LessonSegmentModel).where(LessonSegmentModel.lesson_id == lesson.id)
            .order_by(LessonSegmentModel.sequence.desc()).limit(TRANSCRIPT_TAIL)
        )).scalars().all()
        tail = [dict(id=item.id, sequence=item.sequence, text=item.text,
                     created_at=item.created_at) for item in reversed(rows)]
    return {
        **_room_out(
            room, online=sum(1 for item in people if rooms.is_online(item)),
            people=len(presence),
            segments=int(lesson.segment_count or 0) if lesson else 0),
        "participants": presence,
        "transcript": tail,
    }


@router.patch("/{room_id}")
async def update_meeting(
    room_id: str,
    body: MeetingUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    room = await _owned_room(db, room_id, user["tutor_id"])
    if body.title is not None:
        room.title = " ".join(body.title.split())
        lesson = await db.get(LessonModel, room.lesson_id) if room.lesson_id else None
        if lesson is not None:
            lesson.title = room.title
    if body.guests_allowed is not None:
        room.guests_allowed = body.guests_allowed
    if body.max_participants is not None:
        room.max_participants = body.max_participants
    await db.commit()
    await db.refresh(room)
    return _room_out(room)


@router.post("/{room_id}/end")
async def end_meeting(
    room_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Encerra para todos. A gravação (só texto) fecha e fica no histórico, pronta para resumo."""
    room = await _owned_room(db, room_id, user["tutor_id"])
    await rooms.end_room(db, room)
    await db.refresh(room)
    return _room_out(room)
