"""Cadastro online em uma pesquisa: link público, pendente, aceitar e recusar.

O que isto protege: quem preenche o link entra como pendente e não conta como participante
até o professor aceitar; o papel vem do link, e não do formulário; link fechado ou pesquisa
concluída não recebe cadastro; a mesma matrícula não entra duas vezes; o link tem limite por
IP; e um professor não mexe na pesquisa de outro.
"""

from __future__ import annotations

import asyncio
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import (
    ResearchJoinLinkModel,
    ResearchParticipantModel,
    ResearchProjectModel,
    ResearchStageModel,
    StudentModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import research, research_join

USER = {"uid": "u1", "tutor_id": "t1"}
TABELAS = (ResearchProjectModel, ResearchParticipantModel, ResearchStageModel,
           ResearchJoinLinkModel, StudentModel)


@pytest.fixture
def api():
    research_join._hits.clear()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/r.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in TABELAS:
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                ResearchProjectModel(id="p1", tutor_id="t1", title="RAG em recomendação",
                                     description="Estudo de ablação.", status="active"),
                ResearchProjectModel(id="p-outro", tutor_id="outro", title="Alheia",
                                     status="active"),
                StudentModel(id="s1", tutor_id="t1", name="Ana", class_group="x",
                             external_id="2024-0001", active=True),
            ])
            await db.commit()

    asyncio.run(seed())

    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(research.router)
    app.include_router(research_join.public_router)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: USER
    client = TestClient(app)
    client.sessions = sessions
    return client


def token(api, project="p1"):
    return api.get(f"/education/research/{project}/join-link").json()["path"].rsplit("/", 1)[1]


def preencher(api, tok, **campos):
    base = {"name": "Bia Lima", "email": "bia@x.com", "enrollment": "2024-0001"}
    return api.post(f"/education/research-join/{tok}", json={**base, **campos})


def linhas(api, model, **filtros):
    async def run():
        async with api.sessions() as db:
            query = select(model)
            for campo, valor in filtros.items():
                query = query.where(getattr(model, campo) == valor)
            return (await db.execute(query)).scalars().all()
    return asyncio.run(run())


# --- o link do professor -----------------------------------------------------------------------


def test_link_e_criado_na_primeira_vez_e_depois_e_o_mesmo(api):
    primeiro = api.get("/education/research/p1/join-link").json()
    segundo = api.get("/education/research/p1/join-link").json()

    assert primeiro["path"].startswith("/education/research-join/")
    assert primeiro == segundo
    assert primeiro["active"] is True and primeiro["role"] == "orientando"
    assert primeiro["pending"] == 0


def test_professor_fecha_o_link_e_muda_o_papel(api):
    resp = api.patch("/education/research/p1/join-link",
                     json={"active": False, "role": "colaborador"}).json()

    assert resp["active"] is False and resp["role"] == "colaborador"
    assert api.patch("/education/research/p1/join-link", json={"role": "chefe"}).status_code == 400


def test_pesquisa_de_outro_professor_nao_e_alcancavel(api):
    assert api.get("/education/research/p-outro/join-link").status_code == 404
    assert api.patch("/education/research/p-outro/join-link", json={"active": False}).status_code == 404


# --- a página pública --------------------------------------------------------------------------


def test_pagina_publica_mostra_o_titulo_e_o_formulario(api):
    tok = token(api)
    html = api.get(f"/education/research-join/{tok}").text

    assert "RAG em recomendação" in html and 'id="enrollment"' in html
    assert "como orientando" in html


def test_link_inexistente_fechado_ou_de_pesquisa_concluida_nao_abre_formulario(api):
    assert 'id="send"' not in api.get("/education/research-join/nao-existe").text

    tok = token(api)
    api.patch("/education/research/p1/join-link", json={"active": False})
    assert "fechado" in api.get(f"/education/research-join/{tok}").text
    assert preencher(api, tok).status_code == 409

    api.patch("/education/research/p1/join-link", json={"active": True})
    api.patch("/education/research/p1", json={"status": "done"})
    assert "concluída" in api.get(f"/education/research-join/{tok}").text
    assert preencher(api, tok).status_code == 409


# --- o cadastro --------------------------------------------------------------------------------


def test_quem_preenche_entra_pendente_e_nao_conta_como_participante(api):
    tok = token(api)
    resp = preencher(api, tok)

    assert resp.status_code == 200 and "Cadastro recebido" in resp.json()["message"]
    pessoa = linhas(api, ResearchParticipantModel)[0]
    assert pessoa.status == "pending" and pessoa.role == "orientando"
    assert pessoa.known_student is True  # a matrícula casa com a Ana cadastrada

    detalhe = api.get("/education/research/p1").json()
    assert detalhe["project"]["participants"] == 0 and detalhe["project"]["pending"] == 1
    assert [p["status"] for p in detalhe["participants"]] == ["pending"]
    assert api.get("/education/research/p1/join-link").json()["pending"] == 1


def test_papel_vem_do_link_e_nao_do_que_a_pessoa_manda(api):
    tok = token(api)
    api.patch("/education/research/p1/join-link", json={"role": "colaborador"})
    preencher(api, tok, role="coorientador", name="Quem tenta")

    assert linhas(api, ResearchParticipantModel)[0].role == "colaborador"


def test_pessoa_de_fora_entra_com_instituicao_sem_matricula(api):
    tok = token(api)
    resp = preencher(api, tok, enrollment="", institution="UFS", name="Carlos")

    assert resp.status_code == 200
    pessoa = linhas(api, ResearchParticipantModel)[0]
    assert pessoa.institution == "UFS" and pessoa.known_student is False


@pytest.mark.parametrize("campos,codigo", [
    ({"name": "  "}, "name"),
    ({"email": ""}, "email"),
    ({"email": "isso-nao-e-email"}, "email"),
    ({"enrollment": "", "institution": ""}, "who"),
])
def test_cadastro_incompleto_ou_invalido_e_recusado(api, campos, codigo):
    resp = preencher(api, token(api), **campos)

    assert resp.status_code == 400 and resp.json()["code"] == codigo
    assert linhas(api, ResearchParticipantModel) == []


def test_mesma_matricula_nao_entra_duas_vezes_nem_enquanto_pendente(api):
    tok = token(api)
    assert preencher(api, tok).status_code == 200
    repetido = preencher(api, tok, name="Outra pessoa")

    assert repetido.status_code == 409 and repetido.json()["code"] == "duplicate"
    assert len(linhas(api, ResearchParticipantModel)) == 1


def test_link_tem_limite_de_envios_por_ip(api):
    tok = token(api)
    for i in range(research_join._LIMIT):
        preencher(api, tok, name=f"Pessoa {i}", enrollment=f"M{i}")

    assert preencher(api, tok, name="Demais", enrollment="MX").status_code == 429


# --- a decisão do professor --------------------------------------------------------------------


def test_aceitar_faz_a_pessoa_virar_participante(api):
    preencher(api, token(api))
    pid = linhas(api, ResearchParticipantModel)[0].id

    resp = api.post(f"/education/research/participants/{pid}/decision", json={"accept": True})

    assert resp.status_code == 200 and resp.json()["status"] == "accepted"
    projeto = api.get("/education/research/p1").json()["project"]
    assert projeto["participants"] == 1 and projeto["pending"] == 0


def test_recusar_tira_da_lista_e_libera_a_matricula(api):
    tok = token(api)
    preencher(api, tok)
    pid = linhas(api, ResearchParticipantModel)[0].id

    api.post(f"/education/research/participants/{pid}/decision", json={"accept": False})

    assert api.get("/education/research/p1").json()["participants"] == []
    # Recusada, a matrícula pode voltar a se cadastrar.
    assert preencher(api, tok).status_code == 200


def test_so_se_decide_quem_esta_aguardando_e_so_na_propria_pesquisa(api):
    manual = api.post("/education/research/p1/participants",
                      json={"name": "Dona Maria", "enrollment": "M1"}).json()

    ja_aceito = api.post(f"/education/research/participants/{manual['id']}/decision",
                         json={"accept": False})
    assert ja_aceito.status_code == 409
    assert manual["status"] == "accepted"  # o que o professor adiciona entra direto

    assert api.post("/education/research/participants/nao-existe/decision",
                    json={"accept": True}).status_code == 404


def test_apagar_a_pesquisa_apaga_o_link(api):
    token(api)
    api.delete("/education/research/p1")

    assert linhas(api, ResearchJoinLinkModel) == []
