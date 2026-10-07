"""Backend minimo so com as rotas da sala, para o teste de navegador de ponta a ponta.

A fala e transcrita por um reconhecimento de mentira (devolve uma frase com contador): o que
se verifica aqui e o caminho navegador -> servidor -> trecho com o nome, nao o Whisper.
"""
import asyncio
import os

os.environ.update(
    LIVEKIT_URL="ws://lk:7880", LIVEKIT_API_KEY="devkey", LIVEKIT_API_SECRET="secret",
    DATABASE_URL="sqlite+aiosqlite:////tmp/e2e.db",
)

from types import SimpleNamespace

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import (
    LessonModel, LessonSegmentModel, MeetingParticipantModel, MeetingRoomModel,
    StudentModel, get_db,
)
from app.core.security import get_current_user
from app.routers import education, meeting_rooms

engine = create_async_engine("sqlite+aiosqlite:////tmp/e2e_rooms.db")
sessions = async_sessionmaker(engine, expire_on_commit=False)
contador = {"n": 0, "ouvidos": []}


async def transcrever(data, language="pt", context="", assistant_name=""):
    contador["n"] += 1
    contador["ouvidos"].append(len(data))
    return SimpleNamespace(transcript=f"fala de teste numero {contador['n']}", confidence=0.9)


async def indexar(**kwargs):
    return 1


async def runtime(tutor_id):
    return None


meeting_rooms.transcribe_audio = transcrever
education.qdrant_service.index_lesson_segments = indexar
meeting_rooms.load_user_llm_runtime = runtime
meeting_rooms.activate_user_llms = lambda r: None
meeting_rooms.reset_user_llms = lambda t: None


async def db_dependency():
    async with sessions() as session:
        yield session


app = FastAPI()
app.include_router(meeting_rooms.public)
app.include_router(meeting_rooms.router)
app.dependency_overrides[get_db] = db_dependency
app.dependency_overrides[get_current_user] = lambda: {"uid": "u1", "tutor_id": "t1"}


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        for model in (LessonModel, LessonSegmentModel, MeetingRoomModel,
                      MeetingParticipantModel, StudentModel):
            await conn.run_sync(model.__table__.drop, checkfirst=True)
            await conn.run_sync(model.__table__.create)
    async with sessions() as db:
        db.add(StudentModel(id="s-ana", tutor_id="t1", name="ANA SOUZA SANTOS", class_id="c1",
                            class_group="3001", external_id="20240001", active=True))
        await db.commit()


@app.get("/__stats")
async def stats():
    return contador
