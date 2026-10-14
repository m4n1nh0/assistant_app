"""Inscricao em mentorias: formulario da IA, link publico, vagas e aceite.

O que isto protege: a matricula nao pode ser validada (o app nao tem como), entao ela e
obrigatoria mas so *marca* quem ja e aluno conhecido do semestre; e aceitar um inscrito
tem de coloca-lo numa turma de verdade, para que presenca e reuniao funcionem nela.
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
    ClassGroupModel,
    DisciplineModel,
    MentorshipFormModel,
    MentorshipSignupModel,
    StudentModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import mentorship
from app.services import mentorship_service as svc

USER = {"uid": "u1", "tutor_id": "t1"}
TABELAS = (DisciplineModel, ClassGroupModel, StudentModel,
           MentorshipFormModel, MentorshipSignupModel)


# --- campos ---------------------------------------------------------------------------


def test_campos_invalidos_sao_descartados_e_ids_repetidos_ganham_sufixo():
    campos = svc.sanitize_fields([
        {"label": "Curso", "type": "text", "required": True},
        {"label": "Curso", "type": "text"},
        {"label": "", "type": "text"},
        {"label": "Tipo estranho", "type": "video"},
        "lixo",
        {"label": "Turno", "type": "select", "options": ["Manhã"]},
    ])

    assert [c["id"] for c in campos] == ["curso", "curso_2", "turno"]
    # select com menos de duas opcoes nao serve de escolha: vira texto
    assert campos[2]["type"] == "text" and campos[2]["options"] == []
    assert svc.sanitize_fields("nao e lista") == []


def test_resposta_da_ia_cercada_de_texto_ainda_e_lida():
    texto = 'Claro!\n```json\n{"fields": [{"label": "Área de interesse", "type": "text"}]}\n```'

    assert [c["label"] for c in svc.parse_fields(texto)] == ["Área de interesse"]
    assert svc.parse_fields("sem json") == []


def test_ia_fora_do_ar_cai_nos_campos_padrao(monkeypatch):
    async def quebra(prompt):
        raise RuntimeError("sem provedor")

    monkeypatch.setattr(svc, "_ask_llm", quebra)

    campos, da_ia = asyncio.run(svc.generate_fields("mentoria de dados"))

    assert da_ia is False
    assert {"idade", "curso", "periodo", "horarios_livres"} <= {c["id"] for c in campos}


def test_ia_com_campos_suficientes_vale(monkeypatch):
    async def responde(prompt):
        return ('{"fields": [{"label": "Objetivo", "type": "textarea"},'
                '{"label": "Experiência", "type": "text"}]}')

    monkeypatch.setattr(svc, "_ask_llm", responde)

    campos, da_ia = asyncio.run(svc.generate_fields("mentoria"))

    assert da_ia is True and [c["id"] for c in campos] == ["objetivo", "experiencia"]


def test_respostas_sao_conferidas_contra_os_campos():
    campos = svc.sanitize_fields([
        {"label": "Idade", "type": "number", "required": True},
        {"label": "Área", "type": "select", "options": ["Dados", "Web"], "required": True},
        {"label": "Horários", "type": "availability", "required": True},
    ])

    ok = svc.validate_answers(campos, {
        "idade": "21", "area": "Dados", "horarios": ["sab-manha", "seg-noite", "xxx-yyy"]})
    assert ok == {"idade": 21, "area": "Dados", "horarios": ["sab-manha", "seg-noite"]}

    for ruim, trecho in (
        ({"idade": "vinte", "area": "Dados", "horarios": ["sab-manha"]}, "número"),
        ({"idade": "21", "area": "Java", "horarios": ["sab-manha"]}, "opção"),
        ({"idade": "21", "area": "Dados", "horarios": []}, "Preencha"),
    ):
        with pytest.raises(svc.MentorshipError) as erro:
            svc.validate_answers(campos, ruim)
        assert trecho in erro.value.message


# --- api ------------------------------------------------------------------------------


@pytest.fixture
def api(monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/m.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in TABELAS:
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                DisciplineModel(id="d1", tutor_id="t1", code="ARA0040", name="BD",
                                semester="2026.2"),
                ClassGroupModel(id="c1", tutor_id="t1", code="3001", name="A",
                                discipline_id="d1", discipline="BD", semester="2026.2"),
                ClassGroupModel(id="c-velha", tutor_id="t1", code="1001", name="Velha",
                                discipline_id="d1", discipline="BD", semester="2025.1"),
                StudentModel(id="s-ana", tutor_id="t1", name="Ana", class_id="c1",
                             class_group="3001", external_id="2024-0001", active=True),
                StudentModel(id="s-velho", tutor_id="t1", name="Velho", class_id="c-velha",
                             class_group="1001", external_id="20190001", active=True),
            ])
            await db.commit()

    asyncio.run(seed())

    async def db_dependency():
        async with sessions() as session:
            yield session

    enviados = []

    async def fake_email(recipient, *, subject, text_content):
        enviados.append((recipient, subject))

    import app.services.registration_invite_service as invite
    monkeypatch.setattr(invite, "send_transactional_email", fake_email)
    monkeypatch.setattr(invite, "registration_delivery_configured", lambda *_: True)

    app = FastAPI()
    app.include_router(mentorship.router)
    app.include_router(mentorship.public_router)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: USER
    client = TestClient(app)
    client.sessions, client.emails = sessions, enviados
    return client


def cria(api, **extra):
    body = {"title": "Mentoria de dados", "semester": "2026.2",
            "fields": [{"label": "Idade", "type": "number", "required": True},
                       {"label": "Horários", "type": "availability", "required": True}],
            **extra}
    resposta = api.post("/education/mentorships", json=body)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def inscreve(api, form, matricula="2024-0001", **extra):
    dados = {"enrollment": matricula, "name": "Ana Souza", "email": "ana@exemplo.com",
             "phone": "(11) 91234-5678",
             "answers": {"idade": "21", "horarios": ["sab-manha"]}, **extra}
    return api.post(form["path"], json=dados)


def test_cria_o_formulario_e_a_pagina_publica_mostra_campos_fixos_e_dinamicos(api):
    form = cria(api, description="Encontros quinzenais")

    pagina = api.get(form["path"])

    assert pagina.status_code == 200
    for esperado in ("Matrícula", "Telefone com DDD", "E-mail", "Idade", "Sábado",
                     "Encontros quinzenais"):
        assert esperado in pagina.text


def test_inscricao_valida_marca_aluno_conhecido_e_confirma_por_email(api):
    form = cria(api)

    resposta = inscreve(api, form)

    assert resposta.status_code == 200
    assert "confirmação" in resposta.json()["message"]
    assert api.emails and api.emails[0][0] == "ana@exemplo.com"
    inscritos = api.get(f"/education/mentorships/{form['id']}/signups").json()
    assert inscritos[0]["known_student"] is True
    assert inscritos[0]["answers"] == {"idade": 21, "horarios": ["sab-manha"]}


def test_matricula_so_de_outro_semestre_ou_desconhecida_nao_e_marcada(api):
    form = cria(api)

    inscreve(api, form, matricula="20190001")  # aluno de turma de 2025.1
    inscreve(api, form, matricula="99999999")

    marcas = [i["known_student"] for i in
              api.get(f"/education/mentorships/{form['id']}/signups").json()]
    assert marcas == [False, False]


@pytest.mark.parametrize("campo,valor,trecho", [
    ("enrollment", " ", "matrícula"),
    ("email", "sem-arroba", "e-mail"),
    ("phone", "123", "telefone"),
    ("name", "", "nome"),
])
def test_campos_obrigatorios_sao_cobrados(api, campo, valor, trecho):
    form = cria(api)

    resposta = inscreve(api, form, **{campo: valor})

    assert resposta.status_code == 400
    assert trecho in resposta.json()["detail"].lower()


def test_mesma_matricula_nao_se_inscreve_duas_vezes_mesmo_com_pontuacao_diferente(api):
    form = cria(api)
    assert inscreve(api, form, matricula="2024-0001").status_code == 200

    repetida = inscreve(api, form, matricula="20240001")

    assert repetida.status_code == 409 and repetida.json()["code"] == "duplicate"


def test_vagas_acabam_e_recusar_libera_a_vaga(api):
    form = cria(api, max_slots=1)
    assert inscreve(api, form, matricula="111").status_code == 200

    cheio = inscreve(api, form, matricula="222")
    assert cheio.status_code == 409 and cheio.json()["code"] == "full"
    assert "vagas acabaram" in api.get(form["path"]).text

    inscrito = api.get(f"/education/mentorships/{form['id']}/signups").json()[0]
    api.post(f"/education/mentorships/{form['id']}/signups/status",
             json={"ids": [inscrito["id"]], "status": "rejected"})

    assert inscreve(api, form, matricula="222").status_code == 200


def test_prazo_vencido_e_formulario_fechado_recusam(api):
    vencido = cria(api, closes_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat())
    assert inscreve(api, vencido).json()["code"] == "expired"

    form = cria(api)
    api.patch(f"/education/mentorships/{form['id']}", json={"active": False})
    assert inscreve(api, form).json()["code"] == "closed"


def test_aceitar_cria_a_turma_da_mentoria_e_o_aluno_entra_nela(api):
    form = cria(api)
    inscreve(api, form, matricula="777", name="Novo Aluno")
    inscrito = api.get(f"/education/mentorships/{form['id']}/signups").json()[0]

    resposta = api.post(f"/education/mentorships/{form['id']}/signups/status",
                        json={"ids": [inscrito["id"]], "status": "accepted"})

    assert resposta.status_code == 200 and resposta.json()["class_id"]

    async def le():
        async with api.sessions() as db:
            turma = await db.get(ClassGroupModel, resposta.json()["class_id"])
            disciplina = await db.get(DisciplineModel, turma.discipline_id)
            alunos = (await db.execute(select(StudentModel).where(
                StudentModel.class_id == turma.id))).scalars().all()
            return turma, disciplina, alunos

    turma, disciplina, alunos = asyncio.run(le())
    assert disciplina.code == "MENTORIA" and disciplina.name == "Mentoria de dados"
    assert [(a.name, a.external_id, a.active) for a in alunos] == [("Novo Aluno", "777", True)]


def test_remover_tira_o_aluno_da_turma_e_aceitar_de_novo_traz_de_volta(api):
    form = cria(api)
    inscreve(api, form, matricula="777")
    inscrito = api.get(f"/education/mentorships/{form['id']}/signups").json()[0]
    url = f"/education/mentorships/{form['id']}/signups/status"

    api.post(url, json={"ids": [inscrito["id"]], "status": "accepted"})
    api.post(url, json={"ids": [inscrito["id"]], "status": "removed"})

    async def ativo():
        async with api.sessions() as db:
            return (await db.execute(select(StudentModel.active).where(
                StudentModel.external_id == "777"))).scalars().all()

    assert asyncio.run(ativo()) == [False]
    api.post(url, json={"ids": [inscrito["id"]], "status": "accepted"})
    assert asyncio.run(ativo()) == [True]  # o mesmo aluno, sem duplicar


def test_exporta_csv_com_horarios_legiveis(api):
    form = cria(api)
    inscreve(api, form)

    csv_text = api.get(f"/education/mentorships/{form['id']}/export").json()["csv"]

    linhas = csv_text.strip().splitlines()
    assert linhas[0].startswith("Matrícula;Nome;E-mail;Telefone;Aluno conhecido")
    assert "Sábado manhã" in linhas[1] and ";sim;" in linhas[1]


def test_so_o_dono_ve_e_mexe_no_formulario(api):
    form = cria(api)

    async def troca_dono():
        async with api.sessions() as db:
            item = await db.get(MentorshipFormModel, form["id"])
            item.tutor_id = "outro"
            await db.commit()

    asyncio.run(troca_dono())

    assert api.get("/education/mentorships").json() == []
    assert api.patch(f"/education/mentorships/{form['id']}", json={"active": False}
                     ).status_code == 404
    assert api.get(f"/education/mentorships/{form['id']}/signups").status_code == 404


def test_aceitar_avisa_por_email_so_quem_mudou_de_situacao(api):
    form = cria(api)
    inscreve(api, form, matricula="777")
    inscrito = api.get(f"/education/mentorships/{form['id']}/signups").json()[0]
    url = f"/education/mentorships/{form['id']}/signups/status"
    api.emails.clear()  # a confirmacao do envio nao conta

    primeiro = api.post(url, json={"ids": [inscrito["id"]], "status": "accepted"}).json()
    repetido = api.post(url, json={"ids": [inscrito["id"]], "status": "accepted"}).json()

    assert primeiro["emailed"] == 1 and repetido["emailed"] == 0
    assert [assunto for _, assunto in api.emails] == ["Inscrição aceita: Mentoria de dados"]

    api.post(url, json={"ids": [inscrito["id"]], "status": "removed"})
    api.emails.clear()
    de_volta = api.post(url, json={"ids": [inscrito["id"]], "status": "accepted"}).json()

    assert de_volta["emailed"] == 1  # removido e aceito de novo e avisado outra vez
    assert len(api.emails) == 1


def test_recusar_e_remover_nao_mandam_email(api):
    form = cria(api)
    inscreve(api, form, matricula="777")
    inscrito = api.get(f"/education/mentorships/{form['id']}/signups").json()[0]
    api.emails.clear()

    resposta = api.post(f"/education/mentorships/{form['id']}/signups/status",
                        json={"ids": [inscrito["id"]], "status": "rejected"}).json()

    assert resposta["emailed"] == 0 and api.emails == []
