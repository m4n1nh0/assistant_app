"""Pesquisas científicas: projetos, participantes (da casa ou de fora), etapas e o plano da IA.

O que isto protege: o plano da IA nunca derruba a criação (cai num plano padrão), a
matrícula só *marca* o aluno conhecido (não valida), e o progresso e o atraso saem das
etapas, sem número guardado que fique velho.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import (
    ResearchParticipantModel,
    ResearchProjectModel,
    ResearchJoinLinkModel,
    ResearchStageModel,
    StudentModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import research
from app.services import research_service as svc

USER = {"uid": "u1", "tutor_id": "t1"}
TABELAS = (StudentModel, ResearchProjectModel, ResearchParticipantModel, ResearchStageModel,
           ResearchJoinLinkModel)


def iso(**delta):
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


# --- plano ----------------------------------------------------------------------------------


def test_etapas_invalidas_sao_descartadas_e_a_semana_e_limitada():
    etapas = svc.sanitize_stages([
        {"title": "Revisão", "week": "4", "description": "ler"},
        {"title": "  ", "week": 2},
        {"title": "Sem semana"},
        {"title": "Semana absurda", "week": 99999},
        {"title": "Semana ruim", "week": "x"},
        "lixo",
    ])

    assert [(e["title"], e["week"]) for e in etapas] == [
        ("Revisão", 4), ("Sem semana", None), ("Semana absurda", 520), ("Semana ruim", None)]
    assert svc.sanitize_stages("nao e lista") == []


def test_resposta_da_ia_cercada_de_texto_ainda_e_lida():
    texto = 'Aqui está:\n```json\n{"stages": [{"title": "Coleta", "week": 8}]}\n```'

    assert [e["title"] for e in svc.parse_plan(texto)] == ["Coleta"]
    assert svc.parse_plan("sem json") == []


def test_plano_vira_datas_a_partir_do_inicio():
    inicio = datetime(2026, 3, 2)

    etapas = svc.schedule([{"title": "A", "week": 4}, {"title": "B", "week": None}], inicio)

    assert etapas[0]["due_at"] == datetime(2026, 3, 30) and etapas[1]["due_at"] is None


def test_ia_fora_do_ar_cai_no_plano_padrao_sem_datas(monkeypatch):
    async def quebra(prompt):
        raise RuntimeError("sem provedor")

    monkeypatch.setattr(svc, "_ask_llm", quebra)

    etapas, da_ia = asyncio.run(svc.generate_plan("Tema", "desc"))

    assert da_ia is False and len(etapas) == 6
    assert all(e["due_at"] is None for e in etapas)


def test_ia_com_etapas_suficientes_vale_e_ganha_datas(monkeypatch):
    async def responde(prompt):
        assert "24 semanas" in prompt
        return ('{"stages": [{"title": "A", "week": 2}, {"title": "B", "week": 10},'
                '{"title": "C", "week": 20}]}')

    monkeypatch.setattr(svc, "_ask_llm", responde)

    etapas, da_ia = asyncio.run(svc.generate_plan("Tema", "desc", start=datetime(2026, 1, 5)))

    assert da_ia is True and etapas[1]["due_at"] == datetime(2026, 3, 16)


def test_estado_da_etapa_distingue_atrasada_de_concluida():
    agora = datetime(2026, 5, 1)
    vencida = ResearchStageModel(title="x", status="doing", due_at=datetime(2026, 4, 1))
    feita = ResearchStageModel(title="y", status="done", due_at=datetime(2026, 4, 1))
    futura = ResearchStageModel(title="z", status="todo", due_at=datetime(2026, 6, 1))
    sem_prazo = ResearchStageModel(title="w", status="todo", due_at=None)

    assert [svc.stage_state(s, agora) for s in (vencida, feita, futura, sem_prazo)] == [
        "overdue", "done", "todo", "todo"]


# --- api ------------------------------------------------------------------------------------


@pytest.fixture
def api():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/r.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in TABELAS:
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                StudentModel(id="s-ana", tutor_id="t1", name="Ana", class_group="x",
                             external_id="2024-0001", active=True),
                StudentModel(id="s-velho", tutor_id="t1", name="Velho", class_group="x",
                             external_id="20190001", active=False),
            ])
            await db.commit()

    asyncio.run(seed())

    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(research.router)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: USER
    client = TestClient(app)
    client.sessions = sessions
    return client


def cria(api, **extra):
    body = {"title": "IA no diagnóstico de plantas", "description": "Visão computacional",
            "area": "Computação", "semester": "2026.2", **extra}
    resposta = api.post("/education/research", json=body)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def test_gerar_plano_nao_grava_nada(api, monkeypatch):
    async def responde(prompt):
        return '{"stages": [{"title": "A", "week": 1}, {"title": "B", "week": 2}, {"title": "C", "week": 3}]}'

    monkeypatch.setattr(svc, "_ask_llm", responde)

    plano = api.post("/education/research/generate-plan",
                     json={"title": "Tema", "description": "x", "weeks": 12}).json()

    assert plano["from_ai"] is True and [s["title"] for s in plano["stages"]] == ["A", "B", "C"]
    assert api.get("/education/research").json() == []


def test_cria_com_etapas_e_participantes_e_lista_com_progresso(api):
    pesquisa = cria(api, stages=[
        {"title": "Revisão", "due_at": iso(days=-5)},
        {"title": "Coleta", "due_at": iso(days=20)},
        {"title": "Artigo", "due_at": iso(days=60)},
    ], participants=[{"name": "Bia", "role": "orientando"}])

    assert pesquisa["stages"] == 3 and pesquisa["participants"] == 1
    assert pesquisa["progress"] == 0 and pesquisa["overdue"] == 1
    assert pesquisa["next_title"] == "Coleta"

    detalhe = api.get(f"/education/research/{pesquisa['id']}").json()
    primeira = detalhe["stages"][0]
    api.patch(f"/education/research/stages/{primeira['id']}", json={"status": "done"})

    lista = api.get("/education/research").json()[0]
    assert lista["done"] == 1 and lista["progress"] == 33 and lista["overdue"] == 0


def test_concluir_etapa_registra_a_data_e_reabrir_limpa(api):
    pesquisa = cria(api, stages=[{"title": "A"}])
    etapa = api.get(f"/education/research/{pesquisa['id']}").json()["stages"][0]

    feita = api.patch(f"/education/research/stages/{etapa['id']}", json={"status": "done"}).json()
    reaberta = api.patch(f"/education/research/stages/{etapa['id']}", json={"status": "doing"}).json()

    assert feita["done_at"] is not None and feita["state"] == "done"
    assert reaberta["done_at"] is None and reaberta["status"] == "doing"
    ruim = api.patch(f"/education/research/stages/{etapa['id']}", json={"status": "xx"})
    assert ruim.status_code == 400


def test_participante_de_fora_e_aluno_da_casa_sao_distinguidos(api):
    pesquisa = cria(api)
    url = f"/education/research/{pesquisa['id']}/participants"

    da_casa = api.post(url, json={"name": "Ana Souza", "enrollment": "20240001",
                                  "email": "ana@exemplo.com"}).json()
    de_fora = api.post(url, json={"name": "Dr. Carlos", "role": "colaborador",
                                  "institution": "USP", "enrollment": "99999"}).json()
    inativo = api.post(url, json={"name": "Velho", "enrollment": "20190001"}).json()

    assert da_casa["known_student"] is True
    assert de_fora["known_student"] is False and de_fora["institution"] == "USP"
    assert inativo["known_student"] is False  # aluno inativo nao conta como conhecido


@pytest.mark.parametrize("dados,trecho", [
    ({"name": " "}, "nome"),
    ({"name": "X", "role": "chefe"}, "papel"),
    ({"name": "X", "email": "sem-arroba"}, "e-mail"),
])
def test_participante_invalido_e_recusado(api, dados, trecho):
    pesquisa = cria(api)

    resposta = api.post(f"/education/research/{pesquisa['id']}/participants", json=dados)

    assert resposta.status_code in (400, 422)
    if resposta.status_code == 400:
        assert trecho in resposta.json()["detail"].lower()


def test_mesma_matricula_nao_entra_duas_vezes_mas_pode_voltar_depois_de_sair(api):
    pesquisa = cria(api)
    url = f"/education/research/{pesquisa['id']}/participants"
    primeiro = api.post(url, json={"name": "Ana", "enrollment": "2024-0001"}).json()

    repetido = api.post(url, json={"name": "Ana de novo", "enrollment": "20240001"})
    assert repetido.status_code == 409

    api.delete(f"/education/research/participants/{primeiro['id']}")
    assert api.post(url, json={"name": "Ana", "enrollment": "20240001"}).status_code == 200
    detalhe = api.get(f"/education/research/{pesquisa['id']}").json()
    assert [p["name"] for p in detalhe["participants"]] == ["Ana"]


def test_atualiza_pesquisa_e_valida_a_situacao(api):
    pesquisa = cria(api)
    url = f"/education/research/{pesquisa['id']}"

    ativa = api.patch(url, json={"status": "active", "area": "Agronomia"}).json()

    assert ativa["status"] == "active" and ativa["area"] == "Agronomia"
    assert api.patch(url, json={"status": "inventada"}).status_code == 400


def test_apagar_pesquisa_leva_etapas_e_participantes(api):
    pesquisa = cria(api, stages=[{"title": "A"}], participants=[{"name": "Bia"}])

    assert api.delete(f"/education/research/{pesquisa['id']}").json() == {"ok": True}

    async def sobras():
        async with api.sessions() as db:
            return [len((await db.execute(select(m))).scalars().all()) for m in (
                ResearchProjectModel, ResearchStageModel, ResearchParticipantModel)]

    assert asyncio.run(sobras()) == [0, 0, 0]


def test_so_o_dono_ve_e_mexe(api):
    pesquisa = cria(api, stages=[{"title": "A"}])
    etapa = api.get(f"/education/research/{pesquisa['id']}").json()["stages"][0]

    async def troca_dono():
        async with api.sessions() as db:
            item = await db.get(ResearchProjectModel, pesquisa["id"])
            item.tutor_id = "outro"
            stage = await db.get(ResearchStageModel, etapa["id"])
            stage.tutor_id = "outro"
            await db.commit()

    asyncio.run(troca_dono())

    assert api.get("/education/research").json() == []
    assert api.get(f"/education/research/{pesquisa['id']}").status_code == 404
    assert api.patch(f"/education/research/stages/{etapa['id']}",
                     json={"status": "done"}).status_code == 404
    assert api.post(f"/education/research/{pesquisa['id']}/stages",
                    json={"title": "x"}).status_code == 404
