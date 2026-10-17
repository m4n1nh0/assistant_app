"""Melhoria do material por IA: reescrita fiel, versão guardada ao lado do original.

O que isto protege: a IA nunca grava por cima do original, resumo ou invenção é recusado,
o agente conectado entra pelo mesmo caminho, o descarte volta ao original, e o portal do
aluno passa a servir a versão melhorada em Markdown.
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
    ClassGroupModel,
    DisciplineModel,
    MaterialChunkModel,
    MaterialImprovementModel,
    MaterialModel,
    StudentModel,
    StudentPortalModel,
    get_db,
)
from app.core.security import get_current_user
from app.models.schemas import LLMResponse
from app.routers import education, student_portal
from app.services import material_improve_service as svc
from app.services.user_llm_config_service import user_llm_context

USER = {"uid": "u1", "tutor_id": "t1"}
PICADO = "Amazon\n\nAWS,\n\nalém\n\nde\n\nBig\n\nData\n\ne\n\nAnalytics\n\npara\n\nindústria\n\n4.0."
REESCRITO = "## Tema 6\n\nAmazon AWS, além de Big Data e Analytics para indústria 4.0."


# --- regras puras ------------------------------------------------------------------------------


def test_parte_o_texto_so_entre_paragrafos():
    texto = "\n\n".join(f"Paragrafo {i} " + "x" * 50 for i in range(10))
    partes = svc.split_parts(texto, limit=200)

    assert len(partes) > 1 and all(len(p) <= 200 for p in partes)
    assert "\n\n".join(partes) == texto


def test_paragrafo_gigante_sem_quebra_e_cortado_no_limite():
    partes = svc.split_parts("palavra " * 500, limit=300)

    assert len(partes) > 1 and all(len(p) <= 300 for p in partes)


def test_tira_a_cerca_de_codigo_que_o_modelo_poe_em_volta():
    assert svc.clean_output("```markdown\n## Titulo\n\nTexto\n```") == "## Titulo\n\nTexto"
    assert svc.clean_output("## Titulo") == "## Titulo"


def test_resumo_e_invencao_nao_passam_como_reescrita_fiel():
    original = "palavra " * 100
    assert svc.looks_faithful(original, "palavra " * 90)
    assert not svc.looks_faithful(original, "resumo curto")          # resumiu
    assert not svc.looks_faithful(original, "palavra " * 400)        # inventou
    assert not svc.looks_faithful("", "algo")


def test_prompt_traz_titulo_disciplina_e_o_pedido_do_professor():
    built = svc.build_prompt(title="Tema 6", discipline="Nuvem", content="texto",
                             instructions="manter os nomes das plataformas")

    assert "Tema 6" in built["prompt"] and "Nuvem" in built["prompt"]
    assert "manter os nomes das plataformas" in built["prompt"]
    assert "nao resuma" in built["system_prompt"].lower()


# --- endpoints ---------------------------------------------------------------------------------

TABELAS = (
    DisciplineModel, ClassGroupModel, StudentModel, MaterialModel, MaterialChunkModel,
    MaterialImprovementModel, StudentPortalModel,
)


@pytest.fixture
def api(monkeypatch):
    student_portal._hits.clear()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/m.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in TABELAS:
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                DisciplineModel(id="d1", tutor_id="t1", code="NUV", name="Nuvem"),
                ClassGroupModel(id="c1", tutor_id="t1", code="1", name="T1",
                                discipline_id="d1", discipline="Nuvem", semester="2026.2"),
                StudentModel(id="s1", tutor_id="t1", name="Ana", class_id="c1",
                             class_group="x", external_id="111", active=True),
                MaterialModel(id="m1", tutor_id="t1", discipline_id="d1", discipline="Nuvem",
                              title="Tema 6", filename="t6.pdf", content=PICADO),
                MaterialModel(id="m-outro", tutor_id="outro", discipline_id="d1",
                              discipline="Nuvem", title="Alheio", filename="a.pdf", content=PICADO),
                StudentPortalModel(id="p1", tutor_id="t1", token="tok", active=True),
            ])
            await db.commit()

    asyncio.run(seed())
    chamadas = []

    async def dispatch_falso(provider, message, history, system, **kwargs):
        chamadas.append(provider)
        return LLMResponse(llm=provider, content=REESCRITO)

    monkeypatch.setattr(svc, "dispatch_single", dispatch_falso)

    async def sempre(preferred=None):
        return preferred if preferred and preferred != "auto" else "claude"

    monkeypatch.setattr(svc, "resolve_llm", sempre)

    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(education.router)
    app.include_router(student_portal.router)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[user_llm_context] = lambda: None
    with TestClient(app) as client:
        client.sessions = sessions
        client.chamadas = chamadas
        yield client
    asyncio.run(engine.dispose())


def linhas(api, model, **filtros):
    async def run():
        async with api.sessions() as db:
            query = select(model)
            for campo, valor in filtros.items():
                query = query.where(getattr(model, campo) == valor)
            return (await db.execute(query)).scalars().all()
    return asyncio.run(run())


def test_ia_do_backend_reescreve_e_guarda_ao_lado_do_original(api):
    resp = api.post("/education/materials/m1/improve", json={"llm": "gemini"})

    assert resp.status_code == 200
    dados = resp.json()
    assert dados["improved"] is True and dados["improved_llm"] == "gemini"
    assert api.chamadas == ["gemini"]
    # O original segue intacto.
    assert linhas(api, MaterialModel, id="m1")[0].content == PICADO
    assert linhas(api, MaterialImprovementModel)[0].content == REESCRITO


def test_blocos_passam_a_ser_cortados_da_versao_melhorada(api):
    api.post("/education/materials/m1/improve", json={})

    blocos = linhas(api, MaterialChunkModel, material_id="m1")
    assert [b.heading_path for b in blocos] == ["Tema 6"]
    assert "Big Data" in blocos[0].text


def test_lista_de_materiais_diz_quais_foram_melhorados(api):
    antes = {m["id"]: m["improved"] for m in api.get("/education/materials").json()}
    api.post("/education/materials/m1/improve", json={})
    depois = {m["id"]: m for m in api.get("/education/materials").json()}

    assert antes == {"m1": False}
    assert depois["m1"]["improved"] is True and depois["m1"]["improved_llm"] == "claude"


def test_resposta_que_resume_e_recusada_e_nada_e_gravado(api, monkeypatch):
    async def resume(provider, message, history, system, **kwargs):
        return LLMResponse(llm=provider, content="Resumo.")

    monkeypatch.setattr(svc, "dispatch_single", resume)
    resp = api.post("/education/materials/m1/improve", json={})

    assert resp.status_code == 502 and "fiel" in resp.json()["detail"]
    assert linhas(api, MaterialImprovementModel) == []


def test_erro_do_provedor_vira_502_com_o_motivo(api, monkeypatch):
    async def quebra(provider, message, history, system, **kwargs):
        return LLMResponse(llm=provider, content="chave vencida", is_error=True)

    monkeypatch.setattr(svc, "dispatch_single", quebra)
    resp = api.post("/education/materials/m1/improve", json={})

    assert resp.status_code == 502 and "chave vencida" in resp.json()["detail"]


def test_material_de_outro_professor_nao_e_alcancavel(api):
    assert api.post("/education/materials/m-outro/improve", json={}).status_code == 404
    assert api.get("/education/materials/m-outro/improve/prompt").status_code == 404
    assert api.get("/education/materials/m-outro/improved").status_code == 404


def test_agente_conectado_pega_o_prompt_e_devolve_o_texto(api):
    prompt = api.get("/education/materials/m1/improve/prompt",
                     params={"instructions": "manter siglas"}).json()
    assert "manter siglas" in prompt["prompt"] and PICADO in prompt["prompt"]
    assert "nao resuma" in prompt["system_prompt"].lower()

    resp = api.post("/education/materials/m1/improve/external",
                    json={"text": f"```markdown\n{REESCRITO}\n```", "llm": "claude-code"})

    assert resp.status_code == 200 and resp.json()["improved_llm"] == "claude-code"
    assert api.get("/education/materials/m1/improved").json()["content"] == REESCRITO


def test_texto_externo_vazio_sem_agente_ou_infiel_e_recusado(api):
    url = "/education/materials/m1/improve/external"

    assert api.post(url, json={"text": REESCRITO, "llm": ""}).status_code == 400
    assert api.post(url, json={"text": "   ", "llm": "codex"}).status_code == 400
    assert api.post(url, json={"text": "curto", "llm": "codex"}).status_code == 422
    assert linhas(api, MaterialImprovementModel) == []


def test_melhorar_de_novo_substitui_a_versao_anterior(api):
    api.post("/education/materials/m1/improve", json={"llm": "gemini"})
    api.post("/education/materials/m1/improve", json={"llm": "claude"})

    rows = linhas(api, MaterialImprovementModel)
    assert len(rows) == 1 and rows[0].llm == "claude"


def test_descartar_volta_ao_original_e_refaz_os_blocos(api):
    api.post("/education/materials/m1/improve", json={})
    resp = api.delete("/education/materials/m1/improved")

    assert resp.status_code == 200 and resp.json()["improved"] is False
    assert linhas(api, MaterialImprovementModel) == []
    assert api.get("/education/materials/m1/improved").status_code == 404
    textos = " ".join(b.text for b in linhas(api, MaterialChunkModel, material_id="m1"))
    assert "Amazon" in textos and "##" not in textos


def test_excluir_o_material_leva_a_versao_melhorada_junto(api):
    api.post("/education/materials/m1/improve", json={})
    api.delete("/education/materials/m1")

    assert linhas(api, MaterialImprovementModel) == []
    assert linhas(api, MaterialChunkModel, material_id="m1") == []


def test_portal_serve_o_original_ate_haver_melhoria_e_depois_o_markdown(api):
    url = "/education/portal/tok/material"
    corpo = {"enrollment": "111", "material_id": "m1"}

    antes = api.post(url, json=corpo).json()
    api.post("/education/materials/m1/improve", json={})
    depois = api.post(url, json=corpo).json()

    assert antes["format"] == "text" and antes["content"] == PICADO
    assert depois["format"] == "markdown" and depois["content"] == REESCRITO
