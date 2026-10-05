"""O que o professor le quando um bloco de audio nao rende fala."""

from __future__ import annotations

import asyncio
import io
import math
import struct
import tempfile
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import LessonModel, get_db
from app.core.security import get_current_user
from app.models.schemas import STTResponse
from app.routers import education
from app.services.user_llm_config_service import user_llm_context

USER = {"uid": "u1", "tutor_id": "t1"}


def wav(amplitude: float) -> bytes:
    rate = 16000
    frames = b"".join(
        struct.pack("<h", int(amplitude * 32767 * math.sin(2 * math.pi * 220 * i / rate)))
        for i in range(rate // 2)
    )
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(rate)
        arquivo.writeframes(frames)
    return buffer.getvalue()


@pytest.fixture
def api(monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/l.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            await conn.run_sync(LessonModel.__table__.create)
        async with sessions() as db:
            db.add(LessonModel(
                id="l1", tutor_id="t1", kind="palestra", discipline="", title="Palestra",
                status="recording",
            ))
            await db.commit()

    asyncio.run(seed())

    chamadas = []

    async def stt_falso(audio, language="pt", context="", assistant_name=""):
        chamadas.append(len(audio))
        return STTResponse(transcript="", confidence=0.0)

    monkeypatch.setattr(education, "transcribe_audio", stt_falso)

    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(education.router)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[user_llm_context] = lambda: None
    with TestClient(app) as client:
        client.stt_chamadas = chamadas
        yield client
    asyncio.run(engine.dispose())


def enviar(api, dados: bytes):
    return api.post(
        "/education/lessons/l1/audio",
        files={"file": ("bloco.wav", dados, "audio/wav")},
    )


@pytest.mark.integration
def test_bloco_mudo_passa_pelo_stt_e_so_depois_culpa_o_microfone(api):
    resposta = enviar(api, wav(0.0))

    assert resposta.status_code == 200
    motivo = resposta.json()["skipped_reason"]
    assert "so silencio" in motivo and "microfone" in motivo
    # O nivel nunca decide no lugar do reconhecimento.
    assert len(api.stt_chamadas) == 1


@pytest.mark.integration
def test_som_fraco_sem_fala_sugere_aproximar_o_microfone(api):
    resposta = enviar(api, wav(0.015))

    motivo = resposta.json()["skipped_reason"]
    assert motivo.startswith("nenhuma fala reconhecida no bloco")
    assert "aproxime o microfone" in motivo
    assert len(api.stt_chamadas) == 1


@pytest.mark.integration
def test_som_normal_sem_fala_nao_culpa_o_microfone(api):
    resposta = enviar(api, wav(0.3))

    assert resposta.json()["skipped_reason"] == "nenhuma fala reconhecida no bloco."
    assert len(api.stt_chamadas) == 1


@pytest.mark.integration
def test_audio_que_nao_e_wav_segue_para_o_reconhecimento(api):
    resposta = enviar(api, b"m4a qualquer")

    assert resposta.json()["skipped_reason"] == "nenhuma fala reconhecida no bloco."
    assert len(api.stt_chamadas) == 1


@pytest.mark.integration
def test_reconhecimento_indisponivel_responde_503_sem_perder_o_bloco(api, monkeypatch):
    from app.services.voice_service import STTUnavailable

    async def indisponivel(*args, **kwargs):
        raise STTUnavailable("O reconhecimento de voz ainda esta carregando.")

    monkeypatch.setattr(education, "transcribe_audio", indisponivel)

    resposta = enviar(api, wav(0.3))

    # 503 (e nao 500): o app trata como "tente de novo" e mantem o audio na fila.
    assert resposta.status_code == 503
    assert "ainda esta carregando" in resposta.json()["detail"]
    assert resposta.headers["retry-after"] == "60"
