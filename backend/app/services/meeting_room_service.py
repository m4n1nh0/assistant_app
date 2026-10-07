"""Sala de reunião online própria: acesso, presença e encerramento.

O vídeo e o áudio trafegam por um servidor de mídia LiveKit (nuvem ou próprio), que o
navegador de cada participante acessa com um token assinado aqui. **Nada de áudio ou
vídeo é gravado**: só a fala transcrita fica guardada, como trechos da gravação do tipo
reunião, com o nome de quem falou. Cada participante transcreve o próprio microfone, e
a transcrição por pessoa nasce disso.

Este módulo não fala com Whisper nem com o banco de trechos: é o que vem antes (quem
pode entrar, com que nome, por quanto tempo ficou) e o que vem depois (encerrar).
"""

from __future__ import annotations

import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from jose import jwt
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.database import (
    LessonModel,
    MeetingParticipantModel,
    MeetingRoomModel,
    StudentModel,
)

#: Sem batimento por este tempo, o participante conta como ausente da sala (fechou o
#: navegador sem sair). O navegador bate a cada 15 s.
HEARTBEAT_TTL_SECONDS = 45

#: Validade do acesso ao servidor de mídia; cobre uma reunião longa.
TOKEN_TTL_SECONDS = 6 * 3600

MAX_NAME_CHARS = 80


class MeetingError(Exception):
    """Não dá para fazer isso na sala. `code` diz por quê; `message` é para quem lê."""

    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def new_token() -> str:
    """Parte do link que se divide com os participantes."""
    return secrets.token_urlsafe(9)


def new_secret() -> str:
    """Chave de quem entrou, ou do professor da sala."""
    return secrets.token_urlsafe(16)


def _now() -> datetime:
    # As colunas de data chegam sem fuso do MySQL; compara-se sempre em UTC "ingênuo".
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def normalize_enrollment(value: Optional[str]) -> str:
    """Matrícula comparável: só letras e números, sem caixa (como no quiz em grupo)."""
    return re.sub(r"[^0-9a-z]", "", (value or "").casefold())


def clean_name(value: Optional[str]) -> str:
    return " ".join((value or "").split())[:MAX_NAME_CHARS]


# --- servidor de mídia -------------------------------------------------------------


def livekit_configured(settings=None) -> bool:
    settings = settings or get_settings()
    return bool(settings.livekit_url and settings.livekit_api_key
                and settings.livekit_api_secret)


def livekit_http_url(url: str) -> str:
    """O endereço da API do servidor: o mesmo do WebSocket, com http no lugar de ws."""
    if url.startswith("wss://"):
        return "https://" + url[len("wss://"):]
    if url.startswith("ws://"):
        return "http://" + url[len("ws://"):]
    return url


def build_livekit_token(
    *, identity: str, name: str, room: str, host: bool = False,
    settings=None, ttl: int = TOKEN_TTL_SECONDS,
) -> str:
    """Token que o navegador apresenta ao LiveKit para entrar na sala (JWT HS256)."""
    settings = settings or get_settings()
    now = int(time.time())
    grants = {
        "room": room, "roomJoin": True,
        "canPublish": True, "canSubscribe": True, "canPublishData": True,
    }
    if host:
        grants["roomAdmin"] = True
    claims = {
        "iss": settings.livekit_api_key, "sub": identity, "name": name,
        "nbf": now - 10, "exp": now + ttl, "jti": identity, "video": grants,
    }
    return jwt.encode(claims, settings.livekit_api_secret, algorithm="HS256")


async def close_livekit_room(room: str, settings=None) -> bool:
    """Derruba a sala no servidor de mídia, para ninguém ficar nela depois de encerrar.

    Melhor esforço: se o servidor não responder, a sala some sozinha quando o último
    participante sair, e a reunião já está encerrada para o app.
    """
    settings = settings or get_settings()
    if not livekit_configured(settings):
        return False
    now = int(time.time())
    token = jwt.encode(
        {"iss": settings.livekit_api_key, "sub": "server", "nbf": now - 10,
         "exp": now + 60,
         "video": {"room": room, "roomCreate": True, "roomAdmin": True}},
        settings.livekit_api_secret, algorithm="HS256",
    )
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.post(
                f"{livekit_http_url(settings.livekit_url)}"
                "/twirp/livekit.RoomService/DeleteRoom",
                headers={"Authorization": f"Bearer {token}"}, json={"room": room})
        return response.status_code < 300
    except Exception as exc:  # noqa: BLE001 - a reunião já está encerrada no app
        logger.warning(f"Não consegui encerrar a sala {room} no servidor de mídia: {exc}")
        return False


# --- sala e participantes -------------------------------------------------------------


async def get_room_by_token(db: AsyncSession, token: str) -> Optional[MeetingRoomModel]:
    token = (token or "").strip()
    if not token:
        return None
    return (await db.execute(select(MeetingRoomModel).where(
        MeetingRoomModel.token == token))).scalar_one_or_none()


def is_online(participant: MeetingParticipantModel, now: Optional[datetime] = None) -> bool:
    """Está na sala agora: não saiu e bateu o coração há pouco."""
    if participant.left_at is not None:
        return False
    seen = _naive(participant.last_seen_at)
    if seen is None:
        return False
    return (_naive(now) or _now()) - seen <= timedelta(seconds=HEARTBEAT_TTL_SECONDS)


async def participants_of(db: AsyncSession, room_id: str) -> list[MeetingParticipantModel]:
    return list((await db.execute(
        select(MeetingParticipantModel)
        .where(MeetingParticipantModel.room_id == room_id)
        .order_by(MeetingParticipantModel.joined_at))).scalars().all())


async def online_count(db: AsyncSession, room: MeetingRoomModel,
                       now: Optional[datetime] = None) -> int:
    return sum(1 for item in await participants_of(db, room.id) if is_online(item, now))


async def _student_by_enrollment(db: AsyncSession, tutor_id: str,
                                 enrollment: str) -> Optional[StudentModel]:
    wanted = normalize_enrollment(enrollment)
    if not wanted:
        return None
    rows = (await db.execute(select(StudentModel).where(
        StudentModel.tutor_id == tutor_id, StudentModel.active.is_(True)))).scalars().all()
    for student in rows:
        if normalize_enrollment(student.external_id) == wanted:
            return student
    return None


async def join(
    db: AsyncSession,
    room: MeetingRoomModel,
    *,
    name: str,
    enrollment: str = "",
    consent: bool = False,
    host_key: str = "",
) -> MeetingParticipantModel:
    """Entra na sala. A matrícula (se houver) dá o nome do cadastro e a presença do aluno."""
    if room.status != "open":
        raise MeetingError("ended", "Esta reunião já foi encerrada.", 409)
    if not consent:
        raise MeetingError(
            "consent",
            "Para entrar, aceite que a sua fala será transcrita (áudio e vídeo não "
            "são gravados).")

    is_host = False
    if host_key:
        if not secrets.compare_digest(host_key, room.host_key):
            raise MeetingError("host", "A chave do professor não confere.", 403)
        is_host = True

    student: Optional[StudentModel] = None
    if (enrollment or "").strip():
        student = await _student_by_enrollment(db, room.tutor_id, enrollment)
        if student is None:
            raise MeetingError(
                "enrollment", "Matrícula não encontrada. Confira os números ou "
                              "fale com o professor.", 404)
    elif not is_host and not room.guests_allowed:
        raise MeetingError(
            "enrollment_required",
            "Esta reunião é só para alunos: digite a sua matrícula.", 403)

    display = clean_name(student.name if student else name)
    if len(display) < 2:
        raise MeetingError("name", "Digite o seu nome.")

    existing = await participants_of(db, room.id)
    if not is_host:
        others = sum(1 for item in existing
                     if is_online(item) and not item.is_host
                     and not (student and item.student_id == student.id))
        if others >= max(1, room.max_participants):
            raise MeetingError(
                "full", f"A sala está cheia ({room.max_participants} pessoas).", 409)

    # Quem recarrega a página volta com outra entrada: a anterior fecha, para a mesma
    # pessoa não contar duas vezes na sala nem na presença.
    if student is not None:
        for item in existing:
            if item.student_id == student.id and item.left_at is None:
                item.left_at = _naive(item.last_seen_at) or _now()

    participant = MeetingParticipantModel(
        room_id=room.id, name=display, student_id=student.id if student else None,
        is_host=is_host, secret=new_secret(), consent_at=_now(),
        joined_at=_now(), last_seen_at=_now())
    db.add(participant)
    await db.commit()
    await db.refresh(participant)
    return participant


async def authenticate(
    db: AsyncSession, room: MeetingRoomModel, participant_id: str, secret: str
) -> MeetingParticipantModel:
    """Confere a chave de quem fala com a sala; nunca diz qual parte falhou."""
    participant = await db.get(MeetingParticipantModel, (participant_id or "").strip())
    if (participant is None or participant.room_id != room.id
            or not secrets.compare_digest(participant.secret, secret or "")):
        raise MeetingError("auth", "Entrada não reconhecida. Entre de novo na sala.", 403)
    return participant


async def heartbeat(db: AsyncSession, room: MeetingRoomModel,
                    participant_id: str, secret: str) -> dict:
    participant = await authenticate(db, room, participant_id, secret)
    if room.status != "open":
        return dict(ended=True, online=0)
    if participant.left_at is not None:
        raise MeetingError("left", "Você saiu desta reunião. Entre de novo.", 409)
    participant.last_seen_at = _now()
    await db.commit()
    return dict(ended=False, online=await online_count(db, room))


async def leave(db: AsyncSession, room: MeetingRoomModel,
                participant_id: str, secret: str) -> None:
    participant = await authenticate(db, room, participant_id, secret)
    if participant.left_at is None:
        participant.left_at = _now()
        await db.commit()


async def end_room(db: AsyncSession, room: MeetingRoomModel) -> None:
    """Encerra a sala: todos saem, a gravação (só texto) fecha e o servidor de mídia derruba."""
    if room.status == "ended":
        return
    now = _now()
    room.status = "ended"
    room.ended_at = now
    for item in await participants_of(db, room.id):
        if item.left_at is None:
            item.left_at = now
    if room.lesson_id:
        lesson = await db.get(LessonModel, room.lesson_id)
        if lesson is not None and lesson.status != "closed":
            lesson.status = "closed"
            lesson.ended_at = now
    await db.commit()
    await close_livekit_room(room.id)


def presence(participants: list[MeetingParticipantModel],
             now: Optional[datetime] = None) -> list[dict]:
    """A presença por pessoa: o aluno (pela matrícula) ou o convidado (pelo nome).

    Somam-se as entradas da mesma pessoa; sem batimento recente, o fim é o último que
    se ouviu dela, e não "agora".
    """
    now = _naive(now) or _now()
    grouped: dict[str, dict] = {}
    for item in participants:
        key = f"s:{item.student_id}" if item.student_id else f"n:{item.name.casefold()}"
        end = _naive(item.left_at) or (
            now if is_online(item, now) else (_naive(item.last_seen_at) or now))
        start = _naive(item.joined_at) or end
        seconds = max(0, int((end - start).total_seconds()))
        row = grouped.setdefault(key, dict(
            name=item.name, student_id=item.student_id, is_host=item.is_host,
            guest=item.student_id is None and not item.is_host, online=False,
            seconds=0, first_joined=start, last_seen=end, chunks=0))
        row["seconds"] += seconds
        row["online"] = row["online"] or is_online(item, now)
        row["is_host"] = row["is_host"] or item.is_host
        row["first_joined"] = min(row["first_joined"], start)
        row["last_seen"] = max(row["last_seen"], end)
        row["chunks"] += int(item.spoken_chunks or 0)
    return sorted(grouped.values(),
                  key=lambda row: (not row["is_host"], row["first_joined"], row["name"]))
