"""Reunião online própria: sala, entrada, presença e fala transcrita por pessoa.

Falha que isto evita: reunião de mentoria só dava para fazer no Meet ou no Teams, com a
transcrição presa à plataforma (e sem saber quem falou, ou dependendo do plano). Aqui a
sala é nossa: cada pessoa entra com o nome (ou a matrícula), a fala é transcrita com o
nome de quem falou, e nada de áudio ou vídeo é gravado.
"""

from __future__ import annotations

import asyncio
import io
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import (
    LessonModel,
    LessonSegmentModel,
    MeetingParticipantModel,
    MeetingRoomModel,
    StudentModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import education, meeting_rooms
from app.services import meeting_room_service as rooms
from app.services.voice_service import STTUnavailable

USER = {"uid": "u1", "tutor_id": "t1"}
SECRET = "segredo-do-livekit-com-32-caracteres!!"


@pytest.fixture
def settings(monkeypatch):
    current = get_settings()
    monkeypatch.setattr(current, "livekit_url", "wss://meet.exemplo.com")
    monkeypatch.setattr(current, "livekit_api_key", "chave-api")
    monkeypatch.setattr(current, "livekit_api_secret", SECRET)
    monkeypatch.setattr(current, "meeting_default_max_participants", 30)
    return current


class Calls:
    def __init__(self):
        self.transcribed: list[dict] = []
        self.closed_rooms: list[str] = []
        self.stt_text = "bom dia pessoal"
        self.stt_error = None


@pytest.fixture
def calls(monkeypatch):
    registro = Calls()

    async def transcrever(data, language="pt", context="", assistant_name=""):
        if registro.stt_error:
            raise registro.stt_error
        registro.transcribed.append(dict(size=len(data), language=language, context=context))
        return SimpleNamespace(transcript=registro.stt_text, confidence=0.9)

    async def fechar_sala(room, settings=None):
        registro.closed_rooms.append(room)
        return True

    async def indexar(**kwargs):
        return len(kwargs.get("segments", []))

    async def runtime(tutor_id):
        return None

    monkeypatch.setattr(meeting_rooms, "transcribe_audio", transcrever)
    monkeypatch.setattr(rooms, "close_livekit_room", fechar_sala)
    monkeypatch.setattr(education.qdrant_service, "index_lesson_segments", indexar)
    monkeypatch.setattr(meeting_rooms, "load_user_llm_runtime", runtime)
    monkeypatch.setattr(meeting_rooms, "activate_user_llms", lambda r: None)
    monkeypatch.setattr(meeting_rooms, "reset_user_llms", lambda t: None)
    return registro


@pytest.fixture
def api(settings, calls):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/m.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in (LessonModel, LessonSegmentModel, MeetingRoomModel,
                          MeetingParticipantModel, StudentModel):
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                StudentModel(id="s-ana", tutor_id="t1", name="ANA SOUZA SANTOS", class_id="c1",
                             class_group="3001", external_id="2024-0001", active=True),
                StudentModel(id="s-bia", tutor_id="t1", name="BIA LIMA", class_id="c1",
                             class_group="3001", external_id="20240002", active=True),
                StudentModel(id="s-inativo", tutor_id="t1", name="CAIO ANTIGO", class_id="c1",
                             class_group="3001", external_id="20240003", active=False),
                StudentModel(id="s-alheio", tutor_id="t2", name="DE OUTRO", class_id="c9",
                             class_group="x", external_id="20240004", active=True),
            ])
            await db.commit()

    asyncio.run(seed())

    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(meeting_rooms.public)
    app.include_router(meeting_rooms.router)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: USER
    with TestClient(app) as client:
        client.sessions = sessions
        yield client
    asyncio.run(engine.dispose())


def run(api, fn):
    async def go():
        async with api.sessions() as db:
            return await fn(db)
    return asyncio.run(go())


def criar(api, **extra):
    resposta = api.post("/education/meetings", json={"title": "Mentoria de outubro", **extra})
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def entrar(api, sala, **extra):
    corpo = {"name": "Visitante Teste", "consent": True, **extra}
    return api.post(f"/education/meet/{sala['token']}/join", json=corpo)


def entrar_ok(api, sala, **extra):
    resposta = entrar(api, sala, **extra)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def pedaco(api, sala, pessoa, texto=b"audio-falso", duracao=2500, nome="fala.webm"):
    return api.post(
        f"/education/meet/{sala['token']}/audio",
        data={"participant_id": pessoa["participant_id"], "secret": pessoa["secret"],
              "duration_ms": str(duracao)},
        files={"file": (nome, io.BytesIO(texto), "audio/webm")},
    )


def detalhe(api, sala):
    resposta = api.get(f"/education/meetings/{sala['id']}")
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


# --- acesso ao servidor de mídia ---------------------------------------------------


def test_token_do_servidor_de_midia_traz_quem_e_a_sala(settings):
    token = rooms.build_livekit_token(
        identity="p1", name="Ana", room="sala-1", settings=settings)

    claims = jwt.decode(token, SECRET, algorithms=["HS256"], options={"verify_aud": False})

    assert claims["iss"] == "chave-api" and claims["sub"] == "p1" and claims["name"] == "Ana"
    assert claims["video"] == {
        "room": "sala-1", "roomJoin": True, "canPublish": True,
        "canSubscribe": True, "canPublishData": True}
    assert claims["exp"] > claims["nbf"] and claims["jti"] == "p1"


def test_so_o_professor_ganha_poder_de_administrar_a_sala(settings):
    token = rooms.build_livekit_token(
        identity="p1", name="Prof", room="sala-1", host=True, settings=settings)

    claims = jwt.decode(token, SECRET, algorithms=["HS256"], options={"verify_aud": False})

    assert claims["video"]["roomAdmin"] is True


def test_token_assinado_com_outro_segredo_nao_vale(settings):
    token = rooms.build_livekit_token(identity="p1", name="Ana", room="s", settings=settings)

    with pytest.raises(Exception):
        jwt.decode(token, "outro-segredo", algorithms=["HS256"], options={"verify_aud": False})


def test_endereco_da_api_vem_do_do_websocket():
    assert rooms.livekit_http_url("wss://meet.exemplo.com") == "https://meet.exemplo.com"
    assert rooms.livekit_http_url("ws://localhost:7880") == "http://localhost:7880"
    assert rooms.livekit_http_url("https://ja-e-http") == "https://ja-e-http"


def test_configuracao_so_vale_com_os_tres_valores(settings, monkeypatch):
    assert rooms.livekit_configured(settings) is True
    monkeypatch.setattr(settings, "livekit_api_key", "")
    assert rooms.livekit_configured(settings) is False


def test_config_diz_o_que_falta(api, settings, monkeypatch):
    pronto = api.get("/education/meetings/config").json()
    assert pronto == {"configured": True, "media_host": "meet.exemplo.com",
                      "default_max_participants": 30, "missing": []}

    monkeypatch.setattr(settings, "livekit_url", "")
    monkeypatch.setattr(settings, "livekit_api_secret", "")
    falta = api.get("/education/meetings/config").json()
    assert falta["configured"] is False
    assert falta["missing"] == ["LIVEKIT_URL", "LIVEKIT_API_SECRET"]


def test_normalizacao_de_matricula_e_nome():
    assert rooms.normalize_enrollment(" 2024-0001 ") == "20240001"
    assert rooms.normalize_enrollment(None) == ""
    assert rooms.clean_name("  Ana   Souza  ") == "Ana Souza"
    assert len(rooms.clean_name("x" * 500)) == rooms.MAX_NAME_CHARS


# --- criar a sala --------------------------------------------------------------------


def test_cria_a_sala_com_a_gravacao_so_de_texto(api):
    sala = criar(api)

    assert sala["status"] == "open" and sala["title"] == "Mentoria de outubro"
    assert sala["join_path"] == f"/education/meet/{sala['token']}"
    assert sala["host_path"].startswith(sala["join_path"] + "#host=")
    assert sala["guests_allowed"] is True and sala["max_participants"] == 30

    async def gravacao(db):
        return await db.get(LessonModel, sala["lesson_id"])
    lesson = run(api, gravacao)
    assert lesson.kind == "reuniao" and lesson.title == "Mentoria de outubro"
    assert lesson.discipline == "" and lesson.status == "recording"


def test_cada_sala_tem_token_e_chave_diferentes(api):
    a, b = criar(api), criar(api)

    assert a["token"] != b["token"] and a["host_path"] != b["host_path"]
    assert len(a["token"]) >= 10


def test_limite_de_pessoas_pode_ser_escolhido(api):
    assert criar(api, max_participants=8)["max_participants"] == 8
    assert api.post("/education/meetings",
                    json={"title": "x", "max_participants": 1}).status_code == 422
    assert api.post("/education/meetings",
                    json={"title": "x", "max_participants": 500}).status_code == 422


def test_sala_exige_titulo(api):
    assert api.post("/education/meetings", json={"title": ""}).status_code == 422
    assert api.post("/education/meetings", json={}).status_code == 422


def test_sala_de_outro_professor_nao_aparece(api):
    sala = criar(api)

    async def mudar(db):
        (await db.get(MeetingRoomModel, sala["id"])).tutor_id = "t2"
        await db.commit()
    run(api, mudar)

    assert api.get(f"/education/meetings/{sala['id']}").status_code == 404
    assert api.post(f"/education/meetings/{sala['id']}/end").status_code == 404
    assert api.patch(f"/education/meetings/{sala['id']}", json={"title": "x"}).status_code == 404
    assert api.get("/education/meetings").json() == []


def test_atualiza_titulo_convidados_e_limite(api):
    sala = criar(api)

    resposta = api.patch(f"/education/meetings/{sala['id']}", json={
        "title": "  Orientação   semanal ", "guests_allowed": False, "max_participants": 12})

    assert resposta.status_code == 200
    dados = resposta.json()
    assert dados["title"] == "Orientação semanal" and dados["guests_allowed"] is False
    assert dados["max_participants"] == 12

    async def gravacao(db):
        return (await db.get(LessonModel, sala["lesson_id"])).title
    assert run(api, gravacao) == "Orientação semanal"


# --- a página ---------------------------------------------------------------------------


def test_pagina_traz_titulo_aviso_de_transcricao_e_o_cliente_de_video(api):
    sala = criar(api, **{})
    api.patch(f"/education/meetings/{sala['id']}", json={"title": "Mentoria <b>x</b>"})

    pagina = api.get(sala["join_path"])

    assert pagina.status_code == 200
    assert "Mentoria &lt;b&gt;x&lt;/b&gt;" in pagina.text and "<b>x</b>" not in pagina.text
    assert "Nada é gravado" in pagina.text
    assert "a minha fala seja transcrita" in pagina.text
    assert "livekit-client@2.22.3/dist/livekit-client.umd.js" in pagina.text
    assert "noindex" in pagina.text and "no-store" in pagina.headers["cache-control"]


def test_pagina_marca_matricula_obrigatoria_sem_convidados(api):
    sala = criar(api, guests_allowed=False)

    assert "Matrícula (obrigatória)" in api.get(sala["join_path"]).text
    aberta = criar(api)
    assert "opcional para convidados" in api.get(aberta["join_path"]).text


def test_pagina_de_sala_inexistente_ou_encerrada_explica(api, calls):
    assert "não existe" in api.get("/education/meet/nao-existe").text
    sala = criar(api)
    api.post(f"/education/meetings/{sala['id']}/end")

    assert "já foi encerrada" in api.get(sala["join_path"]).text


def test_a_chave_do_professor_nao_vai_na_pagina(api):
    sala = criar(api)
    chave = sala["host_path"].split("#host=")[1]

    assert chave not in api.get(sala["join_path"]).text


# --- entrar -----------------------------------------------------------------------------


def test_entra_como_convidado_e_recebe_o_token_da_sala(api, settings):
    sala = criar(api)

    dados = entrar_ok(api, sala, name="  Maria   da Silva ")

    assert dados["name"] == "Maria da Silva" and dados["is_host"] is False
    assert dados["guest"] is True and dados["title"] == "Mentoria de outubro"
    assert dados["livekit_url"] == "wss://meet.exemplo.com"
    claims = jwt.decode(dados["livekit_token"], SECRET, algorithms=["HS256"],
                        options={"verify_aud": False})
    assert claims["sub"] == dados["identity"] == dados["participant_id"]
    assert claims["video"]["room"] == sala["id"]
    assert "roomAdmin" not in claims["video"]
    assert len(dados["secret"]) >= 16


def test_sem_aceitar_a_transcricao_nao_entra(api):
    sala = criar(api)

    resposta = api.post(f"/education/meet/{sala['token']}/join",
                        json={"name": "Maria", "consent": False})

    assert resposta.status_code == 422 and resposta.json()["code"] == "consent"
    assert detalhe(api, sala)["participants"] == []


def test_registra_o_aceite_da_transcricao(api):
    sala = criar(api)
    pessoa = entrar_ok(api, sala)

    async def aceite(db):
        return (await db.get(MeetingParticipantModel, pessoa["participant_id"])).consent_at
    assert run(api, aceite) is not None


def test_nome_curto_ou_vazio_e_recusado(api):
    sala = criar(api)

    assert entrar(api, sala, name="").json()["code"] == "name"
    assert entrar(api, sala, name="A").json()["code"] == "name"


def test_matricula_traz_o_nome_do_cadastro_e_a_presenca_do_aluno(api):
    sala = criar(api)

    dados = entrar_ok(api, sala, name="apelido qualquer", enrollment="2024-0001")

    assert dados["name"] == "ANA SOUZA SANTOS" and dados["guest"] is False
    participante = detalhe(api, sala)["participants"][0]
    assert participante["student_id"] == "s-ana" and participante["guest"] is False


def test_matricula_desconhecida_inativa_ou_de_outro_professor_e_recusada(api):
    sala = criar(api)

    for matricula in ("99999999", "20240003", "20240004"):
        resposta = entrar(api, sala, enrollment=matricula)
        assert resposta.status_code == 404 and resposta.json()["code"] == "enrollment", matricula


def test_sem_convidados_a_matricula_e_obrigatoria(api):
    sala = criar(api, guests_allowed=False)

    recusado = entrar(api, sala, name="Visitante")
    assert recusado.status_code == 403 and recusado.json()["code"] == "enrollment_required"
    assert entrar(api, sala, enrollment="20240002").status_code == 200


def test_professor_entra_com_a_chave_mesmo_sem_convidados(api, settings):
    sala = criar(api, guests_allowed=False)
    chave = sala["host_path"].split("#host=")[1]

    dados = entrar_ok(api, sala, name="Prof. Mariano", host_key=chave)

    assert dados["is_host"] is True and dados["guest"] is False
    claims = jwt.decode(dados["livekit_token"], SECRET, algorithms=["HS256"],
                        options={"verify_aud": False})
    assert claims["video"]["roomAdmin"] is True
    assert detalhe(api, sala)["participants"][0]["is_host"] is True


def test_chave_do_professor_errada_e_recusada(api):
    sala = criar(api)

    resposta = entrar(api, sala, host_key="chave-errada")

    assert resposta.status_code == 403 and resposta.json()["code"] == "host"


def test_sala_cheia_recusa_o_proximo_mas_nao_o_professor(api):
    sala = criar(api, max_participants=2)
    entrar_ok(api, sala, name="Primeiro Aluno")
    entrar_ok(api, sala, name="Segundo Aluno")

    cheia = entrar(api, sala, name="Terceiro Aluno")
    assert cheia.status_code == 409 and cheia.json()["code"] == "full"
    chave = sala["host_path"].split("#host=")[1]
    assert entrar(api, sala, name="Professor", host_key=chave).status_code == 200


def test_quem_saiu_libera_a_vaga(api):
    sala = criar(api, max_participants=2)
    primeiro = entrar_ok(api, sala, name="Primeiro Aluno")
    entrar_ok(api, sala, name="Segundo Aluno")
    api.post(f"/education/meet/{sala['token']}/leave",
             json={"participant_id": primeiro["participant_id"], "secret": primeiro["secret"]})

    assert entrar(api, sala, name="Terceiro Aluno").status_code == 200


def test_quem_sumiu_sem_sair_libera_a_vaga_depois_do_tempo(api):
    sala = criar(api, max_participants=2)
    primeiro = entrar_ok(api, sala, name="Primeiro Aluno")
    entrar_ok(api, sala, name="Segundo Aluno")

    async def envelhecer(db):
        item = await db.get(MeetingParticipantModel, primeiro["participant_id"])
        item.last_seen_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            seconds=rooms.HEARTBEAT_TTL_SECONDS + 5)
        await db.commit()
    run(api, envelhecer)

    assert entrar(api, sala, name="Terceiro Aluno").status_code == 200


def test_o_mesmo_aluno_recarregando_nao_ocupa_duas_vagas_nem_conta_duas_vezes(api):
    sala = criar(api, max_participants=2)
    entrar_ok(api, sala, enrollment="20240001")
    entrar_ok(api, sala, name="Segundo Convidado")

    # Ana recarrega a pagina com a sala no limite: continua cabendo.
    de_novo = entrar(api, sala, enrollment="20240001")

    assert de_novo.status_code == 200
    pessoas = detalhe(api, sala)["participants"]
    assert [p["name"] for p in pessoas].count("ANA SOUZA SANTOS") == 1

    async def abertas(db):
        itens = (await db.execute(select(MeetingParticipantModel).where(
            MeetingParticipantModel.student_id == "s-ana"))).scalars().all()
        return sorted((i.left_at is None) for i in itens)
    assert run(api, abertas) == [False, True]


def test_entrar_sem_servidor_de_video_configurado_explica(api, settings, monkeypatch):
    sala = criar(api)
    monkeypatch.setattr(settings, "livekit_api_secret", "")

    resposta = entrar(api, sala)

    assert resposta.status_code == 503 and resposta.json()["code"] == "not_configured"
    assert detalhe(api, sala)["participants"] == []


def test_entrar_em_sala_encerrada_ou_inexistente(api, calls):
    sala = criar(api)
    api.post(f"/education/meetings/{sala['id']}/end")

    assert entrar(api, sala).json()["code"] == "ended"
    assert api.post("/education/meet/nao-existe/join",
                    json={"name": "Maria", "consent": True}).status_code == 404


# --- batimento e saída ---------------------------------------------------------------


def test_batimento_mantem_a_pessoa_na_sala(api):
    sala = criar(api)
    pessoa = entrar_ok(api, sala)

    resposta = api.post(f"/education/meet/{sala['token']}/heartbeat",
                        json={"participant_id": pessoa["participant_id"],
                              "secret": pessoa["secret"]})

    assert resposta.status_code == 200
    assert resposta.json() == {"ended": False, "online": 1}


def test_chave_errada_nunca_e_aceita(api):
    sala = criar(api)
    pessoa = entrar_ok(api, sala)
    base = f"/education/meet/{sala['token']}"
    ruim = {"participant_id": pessoa["participant_id"], "secret": "errada"}

    assert api.post(base + "/heartbeat", json=ruim).status_code == 403
    assert api.post(base + "/leave", json=ruim).status_code == 403
    assert api.post(base + "/end", json=ruim).status_code == 403
    assert pedaco(api, sala, {"participant_id": pessoa["participant_id"], "secret": "x"}).status_code == 403
    assert api.post(base + "/heartbeat",
                    json={"participant_id": "nao-existe", "secret": "x"}).status_code == 403


def test_chave_de_uma_sala_nao_vale_em_outra(api):
    sala_a, sala_b = criar(api), criar(api)
    pessoa = entrar_ok(api, sala_a)

    resposta = api.post(f"/education/meet/{sala_b['token']}/heartbeat",
                        json={"participant_id": pessoa["participant_id"],
                              "secret": pessoa["secret"]})

    assert resposta.status_code == 403


def test_sair_fecha_a_entrada_e_nao_conta_como_online(api):
    sala = criar(api)
    pessoa = entrar_ok(api, sala)
    corpo = {"participant_id": pessoa["participant_id"], "secret": pessoa["secret"]}

    assert api.post(f"/education/meet/{sala['token']}/leave", json=corpo).json() == {"left": True}

    assert detalhe(api, sala)["online"] == 0
    # Quem saiu nao volta pelo mesmo batimento: entra de novo.
    retorno = api.post(f"/education/meet/{sala['token']}/heartbeat", json=corpo)
    assert retorno.status_code == 409 and retorno.json()["code"] == "left"


def test_sair_pelo_sendbeacon_do_navegador_funciona(api):
    sala = criar(api)
    pessoa = entrar_ok(api, sala)

    resposta = api.post(
        f"/education/meet/{sala['token']}/leave",
        content=('{"participant_id": "%s", "secret": "%s"}' % (
            pessoa["participant_id"], pessoa["secret"])).encode(),
        headers={"Content-Type": "application/json"})

    assert resposta.status_code == 200 and detalhe(api, sala)["online"] == 0


# --- encerrar -------------------------------------------------------------------------


def test_professor_encerra_para_todos_e_a_gravacao_fecha(api, calls):
    sala = criar(api)
    entrar_ok(api, sala, name="Aluno Um")
    entrar_ok(api, sala, name="Aluno Dois")

    resposta = api.post(f"/education/meetings/{sala['id']}/end")

    assert resposta.status_code == 200 and resposta.json()["status"] == "ended"
    assert resposta.json()["ended_at"] is not None
    assert calls.closed_rooms == [sala["id"]]
    dados = detalhe(api, sala)
    assert dados["online"] == 0

    async def gravacao(db):
        return await db.get(LessonModel, sala["lesson_id"])
    lesson = run(api, gravacao)
    assert lesson.status == "closed" and lesson.ended_at is not None


def test_encerrar_duas_vezes_nao_repete_nada(api, calls):
    sala = criar(api)

    api.post(f"/education/meetings/{sala['id']}/end")
    segunda = api.post(f"/education/meetings/{sala['id']}/end")

    assert segunda.status_code == 200
    assert calls.closed_rooms == [sala["id"]]


def test_batimento_depois_de_encerrar_manda_sair(api, calls):
    sala = criar(api)
    pessoa = entrar_ok(api, sala)
    api.post(f"/education/meetings/{sala['id']}/end")

    resposta = api.post(f"/education/meet/{sala['token']}/heartbeat",
                        json={"participant_id": pessoa["participant_id"],
                              "secret": pessoa["secret"]})

    assert resposta.json() == {"ended": True, "online": 0}


def test_professor_encerra_pela_propria_pagina(api, calls):
    sala = criar(api)
    chave = sala["host_path"].split("#host=")[1]
    professor = entrar_ok(api, sala, name="Prof. Mariano", host_key=chave)

    resposta = api.post(f"/education/meet/{sala['token']}/end",
                        json={"participant_id": professor["participant_id"],
                              "secret": professor["secret"]})

    assert resposta.json() == {"ended": True}
    assert calls.closed_rooms == [sala["id"]]
    assert api.get("/education/meetings").json()[0]["status"] == "ended"


def test_aluno_nao_encerra_a_reuniao_dos_outros(api, calls):
    sala = criar(api)
    aluno = entrar_ok(api, sala)

    resposta = api.post(f"/education/meet/{sala['token']}/end",
                        json={"participant_id": aluno["participant_id"],
                              "secret": aluno["secret"]})

    assert resposta.status_code == 403 and resposta.json()["code"] == "host"
    assert calls.closed_rooms == []
    assert api.get("/education/meetings").json()[0]["status"] == "open"


# --- transcrição por pessoa ------------------------------------------------------------


def test_fala_vira_trecho_com_o_nome_de_quem_falou(api, calls):
    sala = criar(api)
    ana = entrar_ok(api, sala, enrollment="20240001")
    calls.stt_text = "bom dia pessoal, vamos começar"

    resposta = pedaco(api, sala, ana)

    assert resposta.status_code == 200 and resposta.json()["ok"] is True
    assert calls.transcribed == [dict(size=len(b"audio-falso"), language="pt",
                                      context="Mentoria de outubro")]
    trechos = detalhe(api, sala)["transcript"]
    assert [t["text"] for t in trechos] == ["ANA SOUZA SANTOS: bom dia pessoal, vamos começar"]


def test_cada_pessoa_transcreve_a_si_e_a_ordem_e_a_de_chegada(api, calls):
    sala = criar(api)
    ana = entrar_ok(api, sala, enrollment="20240001")
    bia = entrar_ok(api, sala, enrollment="20240002")
    convidado = entrar_ok(api, sala, name="Visitante Externo")

    for pessoa, fala in ((ana, "primeira fala da Ana"), (bia, "resposta da Bia"),
                         (convidado, "pergunta do visitante"), (ana, "segunda fala da Ana")):
        calls.stt_text = fala
        assert pedaco(api, sala, pessoa).status_code == 200

    trechos = detalhe(api, sala)["transcript"]
    assert [t["text"] for t in trechos] == [
        "ANA SOUZA SANTOS: primeira fala da Ana", "BIA LIMA: resposta da Bia",
        "Visitante Externo: pergunta do visitante", "ANA SOUZA SANTOS: segunda fala da Ana"]
    assert [t["sequence"] for t in trechos] == [1, 2, 3, 4]


def test_fala_curta_como_sim_nao_e_descartada(api, calls):
    sala = criar(api)
    ana = entrar_ok(api, sala, enrollment="20240001")
    calls.stt_text = "sim"

    pedaco(api, sala, ana)

    assert detalhe(api, sala)["transcript"][0]["text"] == "ANA SOUZA SANTOS: sim"


def test_falas_iguais_em_sequencia_nao_sao_confundidas_com_sobreposicao(api, calls):
    """A janela de áudio contínuo corta a repetição; na sala cada pedaço é uma fala."""
    sala = criar(api)
    ana = entrar_ok(api, sala, enrollment="20240001")
    bia = entrar_ok(api, sala, enrollment="20240002")
    calls.stt_text = "concordo com a proposta"

    pedaco(api, sala, ana)
    pedaco(api, sala, bia)

    assert [t["text"] for t in detalhe(api, sala)["transcript"]] == [
        "ANA SOUZA SANTOS: concordo com a proposta", "BIA LIMA: concordo com a proposta"]


def test_conta_quantos_pedacos_cada_um_falou_na_presenca(api, calls):
    sala = criar(api)
    ana = entrar_ok(api, sala, enrollment="20240001")
    bia = entrar_ok(api, sala, enrollment="20240002")
    for pessoa in (ana, ana, bia):
        pedaco(api, sala, pessoa)

    por_nome = {p["name"]: p for p in detalhe(api, sala)["participants"]}

    assert por_nome["ANA SOUZA SANTOS"]["chunks"] == 2
    assert por_nome["BIA LIMA"]["chunks"] == 1


def test_sem_fala_reconhecida_nao_gera_trecho(api, calls):
    sala = criar(api)
    ana = entrar_ok(api, sala, enrollment="20240001")
    calls.stt_text = "   "

    resposta = pedaco(api, sala, ana)

    assert resposta.json() == {"ok": True, "skipped": "sem fala"}
    assert detalhe(api, sala)["transcript"] == []


def test_audio_vazio_e_ignorado_sem_chamar_o_reconhecimento(api, calls):
    sala = criar(api)
    ana = entrar_ok(api, sala, enrollment="20240001")

    resposta = pedaco(api, sala, ana, texto=b"")

    assert resposta.json() == {"ok": True, "skipped": "vazio"}
    assert calls.transcribed == []


def test_audio_grande_demais_e_recusado(api, calls, monkeypatch):
    sala = criar(api)
    ana = entrar_ok(api, sala, enrollment="20240001")
    monkeypatch.setattr(meeting_rooms, "MAX_AUDIO_BYTES", 10)

    resposta = pedaco(api, sala, ana, texto=b"x" * 50)

    assert resposta.status_code == 413 and resposta.json()["code"] == "size"
    assert calls.transcribed == []


def test_reconhecimento_indisponivel_responde_503_sem_perder_a_sala(api, calls):
    sala = criar(api)
    ana = entrar_ok(api, sala, enrollment="20240001")
    calls.stt_error = STTUnavailable("O reconhecimento de voz ainda está carregando")

    resposta = pedaco(api, sala, ana)

    assert resposta.status_code == 503 and resposta.json()["code"] == "stt"
    assert "carregando" in resposta.json()["detail"]
    assert detalhe(api, sala)["online"] == 1


def test_quem_saiu_ou_a_sala_encerrada_nao_transcreve_mais(api, calls):
    sala = criar(api)
    ana = entrar_ok(api, sala, enrollment="20240001")
    bia = entrar_ok(api, sala, enrollment="20240002")
    api.post(f"/education/meet/{sala['token']}/leave",
             json={"participant_id": ana["participant_id"], "secret": ana["secret"]})

    assert pedaco(api, sala, ana).status_code == 409
    api.post(f"/education/meetings/{sala['id']}/end")
    assert pedaco(api, sala, bia).status_code == 409
    assert calls.transcribed == []


def test_audio_nunca_fica_guardado(api, calls):
    """Só o texto vai para o banco: nenhuma coluna das tabelas da sala guarda áudio."""
    colunas = {c.name for model in (MeetingRoomModel, MeetingParticipantModel, LessonSegmentModel)
               for c in model.__table__.columns}

    assert not {c for c in colunas if "audio" in c or "video" in c or "blob" in c}


# --- tela ao vivo ---------------------------------------------------------------------


def test_detalhe_traz_presenca_online_e_o_fim_da_transcricao(api, calls):
    sala = criar(api)
    chave = sala["host_path"].split("#host=")[1]
    entrar_ok(api, sala, name="Prof. Mariano", host_key=chave)
    entrar_ok(api, sala, enrollment="20240001")
    entrar_ok(api, sala, name="Visitante Externo")

    dados = detalhe(api, sala)

    assert dados["online"] == 3 and dados["people"] == 3
    nomes = [(p["name"], p["is_host"], p["guest"], p["online"]) for p in dados["participants"]]
    assert nomes[0] == ("Prof. Mariano", True, False, True)  # professor primeiro
    assert ("ANA SOUZA SANTOS", False, False, True) in nomes
    assert ("Visitante Externo", False, True, True) in nomes


def test_transcricao_ao_vivo_mostra_so_o_final(api, calls, monkeypatch):
    sala = criar(api)
    ana = entrar_ok(api, sala, enrollment="20240001")
    monkeypatch.setattr(meeting_rooms, "TRANSCRIPT_TAIL", 3)
    for numero in range(5):
        calls.stt_text = f"fala numero {numero}"
        pedaco(api, sala, ana)

    dados = detalhe(api, sala)

    assert dados["segments"] == 5
    assert [t["text"] for t in dados["transcript"]] == [
        "ANA SOUZA SANTOS: fala numero 2", "ANA SOUZA SANTOS: fala numero 3",
        "ANA SOUZA SANTOS: fala numero 4"]


def test_lista_traz_as_abertas_primeiro_com_contagens(api, calls):
    antiga = criar(api, **{})
    api.post(f"/education/meetings/{antiga['id']}/end")
    aberta = criar(api)
    entrar_ok(api, aberta, name="Aluno Um")

    lista = api.get("/education/meetings").json()

    assert [item["id"] for item in lista] == [aberta["id"], antiga["id"]]
    assert lista[0]["online"] == 1 and lista[0]["people"] == 1 and lista[0]["segments"] == 0


# --- presença -----------------------------------------------------------------------------


def _participante(**campos):
    base = dict(room_id="r", name="Ana", student_id=None, is_host=False, secret="s",
                joined_at=datetime(2026, 10, 6, 21, 0), last_seen_at=datetime(2026, 10, 6, 21, 0),
                left_at=None, spoken_chunks=0)
    base.update(campos)
    return MeetingParticipantModel(**base)


def test_presenca_soma_as_entradas_da_mesma_pessoa():
    agora = datetime(2026, 10, 6, 22, 0)
    itens = [
        _participante(student_id="s1", joined_at=datetime(2026, 10, 6, 21, 0),
                      left_at=datetime(2026, 10, 6, 21, 10)),
        _participante(student_id="s1", joined_at=datetime(2026, 10, 6, 21, 20),
                      last_seen_at=agora, left_at=None),
    ]

    linhas = rooms.presence(itens, now=agora)

    assert len(linhas) == 1
    assert linhas[0]["seconds"] == 10 * 60 + 40 * 60
    assert linhas[0]["online"] is True


def test_sem_batimento_o_fim_e_o_ultimo_que_se_ouviu_da_pessoa():
    agora = datetime(2026, 10, 6, 23, 0)
    item = _participante(joined_at=datetime(2026, 10, 6, 21, 0),
                         last_seen_at=datetime(2026, 10, 6, 21, 30), left_at=None)

    linha = rooms.presence([item], now=agora)[0]

    assert linha["online"] is False and linha["seconds"] == 30 * 60


def test_convidados_de_mesmo_nome_contam_uma_pessoa_e_aluno_nao_se_mistura():
    itens = [_participante(name="Maria"), _participante(name="MARIA"),
             _participante(name="Maria", student_id="s9")]

    linhas = rooms.presence(itens)

    assert len(linhas) == 2


def test_esta_online_so_com_batimento_recente_e_sem_ter_saido():
    agora = datetime(2026, 10, 6, 21, 1)
    assert rooms.is_online(_participante(last_seen_at=datetime(2026, 10, 6, 21, 0, 30)), agora)
    assert not rooms.is_online(_participante(last_seen_at=datetime(2026, 10, 6, 20, 0)), agora)
    assert not rooms.is_online(_participante(left_at=datetime(2026, 10, 6, 21, 0, 50),
                                             last_seen_at=datetime(2026, 10, 6, 21, 0, 55)), agora)


# --- a gravação (só texto) vira resumo como qualquer reunião ---------------------------------


def test_a_gravacao_da_sala_e_do_tipo_reuniao_e_aparece_no_historico(api, calls):
    sala = criar(api)
    ana = entrar_ok(api, sala, enrollment="20240001")
    calls.stt_text = "vamos revisar o capítulo três"
    pedaco(api, sala, ana)

    async def da_sala(db):
        lesson = await db.get(LessonModel, sala["lesson_id"])
        segs = (await db.execute(select(LessonSegmentModel).where(
            LessonSegmentModel.lesson_id == lesson.id))).scalars().all()
        return lesson, segs
    lesson, segs = run(api, da_sala)

    assert lesson.kind == "reuniao" and lesson.segment_count == 1
    assert segs[0].text.startswith("ANA SOUZA SANTOS: ")
    assert lesson.transcript_chars == len(segs[0].text)
