"""Agenda de atendimento: faixas semanais, exceções por data e plano de encontros da mentoria.

O que isto protege: dia bloqueado some da semana, horário extra aparece só na data dele, a
agenda do aluno respeita o público de cada faixa, e o plano de encontros cruza de verdade
as faixas com o turno que cada aceito marcou.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import (
    AvailabilityExceptionModel,
    AvailabilitySlotModel,
    MentorshipFormModel,
    MentorshipSignupModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import availability, mentorship
from app.services import availability_service as svc

USER = {"uid": "u1", "tutor_id": "t1"}
TABELAS = (AvailabilitySlotModel, AvailabilityExceptionModel, MentorshipFormModel,
           MentorshipSignupModel)
SEGUNDA = date(2026, 10, 12)  # uma segunda-feira


def slot(weekday, inicio="19:00", fim="21:00", **extra):
    # O objeto nasce fora do banco, entao os padroes das colunas nao se aplicam sozinhos.
    padrao = {"active": True, "mode": "ambos", "audience": "todos", "location": "", "note": ""}
    return AvailabilitySlotModel(
        tutor_id="t1", weekday=weekday, start_time=inicio, end_time=fim, **{**padrao, **extra})


# --- regras puras ------------------------------------------------------------------------------


def test_horarios_e_dias_invalidos_sao_recusados():
    base = {"weekday": 1, "start_time": "19:00", "end_time": "21:00"}
    assert svc.validate_slot(base)["mode"] == "ambos"

    for ruim, trecho in (
        ({**base, "start_time": "7h"}, "HH:MM"),
        ({**base, "end_time": "18:00"}, "depois do início"),
        ({**base, "end_time": "19:00"}, "depois do início"),
        ({**base, "weekday": 9}, "Dia da semana"),
        ({**base, "mode": "telepatia"}, "Modalidade"),
        ({**base, "audience": "todo mundo"}, "Público"),
    ):
        with pytest.raises(svc.AvailabilityError) as erro:
            svc.validate_slot(ruim)
        assert trecho in erro.value.message


def test_excecao_extra_exige_horario_e_bloqueio_nao():
    bloqueio = svc.validate_exception({"day": "2026-10-15", "kind": "blocked"})
    assert bloqueio["start_time"] == bloqueio["end_time"] == ""

    with pytest.raises(svc.AvailabilityError):
        svc.validate_exception({"day": "2026-10-15", "kind": "extra"})
    with pytest.raises(svc.AvailabilityError):
        svc.validate_exception({"day": "15/10/2026", "kind": "blocked"})
    with pytest.raises(svc.AvailabilityError):
        svc.validate_exception({"day": "2026-13-40", "kind": "blocked"})


def test_a_semana_se_repete_nos_dias_certos():
    quinta = slot(3)

    itens = svc.expand([quinta], [], SEGUNDA, 15)

    assert [o["date"] for o in itens] == ["2026-10-15", "2026-10-22"]
    assert itens[0]["start_time"] == "19:00" and itens[0]["weekday"] == 3


def test_dia_bloqueado_some_da_semana_e_vira_aviso():
    bloqueio = AvailabilityExceptionModel(tutor_id="t1", day="2026-10-15", kind="blocked",
                                          note="Viagem", start_time="", end_time="")

    itens = svc.expand([slot(3), slot(3, "14:00", "15:00")], [bloqueio], SEGUNDA, 15)

    dia = [o for o in itens if o["date"] == "2026-10-15"]
    assert len(dia) == 1 and dia[0]["blocked"] is True and dia[0]["note"] == "Viagem"
    assert [o["date"] for o in itens if not o["blocked"]] == ["2026-10-22", "2026-10-22"]


def test_horario_extra_aparece_so_na_data_dele():
    extra = AvailabilityExceptionModel(tutor_id="t1", day="2026-10-13", kind="extra",
                                       start_time="10:00", end_time="12:00", mode="online",
                                       audience="todos", location="", note="")

    itens = svc.expand([slot(3)], [extra], SEGUNDA, 15)

    extras = [o for o in itens if o["source"] == "extra"]
    assert len(extras) == 1 and extras[0]["date"] == "2026-10-13"
    assert extras[0]["weekday"] == 1  # terca, que nao tinha faixa


def test_faixa_desativada_nao_gera_ocorrencia():
    assert svc.expand([slot(3, active=False)], [], SEGUNDA, 15) == []


def test_publico_filtra_as_faixas():
    todas = [slot(0, audience="todos"), slot(1, audience="graduacao"),
             slot(2, audience="mentoria")]

    grad = svc.expand(todas, [], SEGUNDA, 7, {"graduacao"})
    ment = svc.expand(todas, [], SEGUNDA, 7, {"mentoria"})
    professor = svc.expand(todas, [], SEGUNDA, 7, None)

    assert [o["weekday"] for o in grad] == [0, 1]
    assert [o["weekday"] for o in ment] == [0, 2]
    assert [o["weekday"] for o in professor] == [0, 1, 2]


def test_turnos_cobertos_pela_faixa():
    assert svc.shifts_covered("19:00", "21:00") == ["noite"]
    assert svc.shifts_covered("09:00", "11:00") == ["manha"]
    assert svc.shifts_covered("11:00", "14:00") == ["manha", "tarde"]
    # 10 minutos num turno nao conta como cobrir o turno.
    assert svc.shifts_covered("17:50", "19:30") == ["noite"]
    assert svc.shifts_covered("17:00", "19:30") == ["tarde", "noite"]
    assert svc.shifts_covered("11:50", "12:20") == []


def test_janela_de_dias_e_limitada():
    assert len(svc.expand([slot(d) for d in range(7)], [], SEGUNDA, 10_000)) == svc.MAX_DAYS


# --- api ---------------------------------------------------------------------------------------


@pytest.fixture
def api():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/a.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in TABELAS:
                await conn.run_sync(model.__table__.create)

    asyncio.run(seed())

    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(availability.router)
    app.include_router(mentorship.router)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: USER
    client = TestClient(app)
    client.sessions = sessions
    return client


def nova_faixa(api, **extra):
    dados = {"weekday": 3, "start_time": "19:00", "end_time": "21:00", **extra}
    resposta = api.post("/education/availability/slots", json=dados)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def test_cria_edita_e_apaga_faixa(api):
    faixa = nova_faixa(api, mode="online", location="https://meet.exemplo.com/x",
                       audience="mentoria", note="Traga dúvidas")

    assert faixa["weekday_name"] == "Quinta" and faixa["audience"] == "mentoria"

    editada = api.patch(f"/education/availability/slots/{faixa['id']}",
                        json={"end_time": "22:00", "active": False}).json()
    assert editada["end_time"] == "22:00" and editada["active"] is False
    assert editada["location"] == "https://meet.exemplo.com/x"  # o resto fica

    assert api.delete(f"/education/availability/slots/{faixa['id']}").json() == {"ok": True}
    assert api.get("/education/availability").json()["slots"] == []


def test_edicao_invalida_nao_grava(api):
    faixa = nova_faixa(api)

    ruim = api.patch(f"/education/availability/slots/{faixa['id']}", json={"end_time": "18:00"})

    assert ruim.status_code == 400
    assert api.get("/education/availability").json()["slots"][0]["end_time"] == "21:00"


def test_excecoes_listam_so_de_hoje_em_diante(api):
    hoje = svc.today()
    ontem = (hoje - timedelta(days=1)).isoformat()
    amanha = (hoje + timedelta(days=1)).isoformat()
    for dia in (ontem, amanha):
        api.post("/education/availability/exceptions", json={"day": dia, "kind": "blocked"})

    dias = [e["day"] for e in api.get("/education/availability").json()["exceptions"]]

    assert dias == [amanha]


def test_previa_mostra_a_agenda_como_o_aluno_veria(api):
    nova_faixa(api, weekday=0, audience="graduacao")
    nova_faixa(api, weekday=1, audience="mentoria")

    tudo = api.get("/education/availability/preview?days=14").json()["occurrences"]
    grad = api.get("/education/availability/preview?days=14&audience=graduacao").json()
    invalido = api.get("/education/availability/preview?audience=xx")

    assert {o["weekday"] for o in tudo} == {0, 1}
    assert {o["weekday"] for o in grad["occurrences"]} == {0}
    assert invalido.status_code == 400


def test_so_o_dono_mexe_na_agenda(api):
    faixa = nova_faixa(api)

    async def troca_dono():
        async with api.sessions() as db:
            item = await db.get(AvailabilitySlotModel, faixa["id"])
            item.tutor_id = "outro"
            await db.commit()

    asyncio.run(troca_dono())

    assert api.get("/education/availability").json()["slots"] == []
    assert api.patch(f"/education/availability/slots/{faixa['id']}",
                     json={"note": "x"}).status_code == 404
    assert api.delete(f"/education/availability/slots/{faixa['id']}").status_code == 404


# --- plano de encontros --------------------------------------------------------------------------


def mentoria(api, *, faixas, pessoas):
    """`pessoas`: nome -> lista de 'dia-turno' marcados; todos aceitos."""
    async def run():
        async with api.sessions() as db:
            db.add(MentorshipFormModel(
                id="f1", tutor_id="t1", token="tok", title="Mentoria", fields=[
                    {"id": "horarios", "label": "Horários", "type": "availability",
                     "required": True, "options": []}]))
            db.add_all(faixas)
            for i, (nome, marcados) in enumerate(pessoas.items()):
                db.add(MentorshipSignupModel(
                    id=f"s{i}", form_id="f1", tutor_id="t1", enrollment=str(i),
                    enrollment_key=str(i), name=nome, email=f"{i}@x.com", phone="1",
                    status="accepted", answers={"horarios": marcados}))
            await db.commit()

    asyncio.run(run())


def test_plano_ordena_pelas_faixas_que_mais_gente_consegue(api):
    mentoria(api, faixas=[
        slot(3, "19:00", "21:00", audience="todos", location="Online"),   # quinta noite
        slot(5, "09:00", "11:00", audience="mentoria"),                    # sabado manha
        slot(0, "19:00", "21:00", audience="graduacao"),                   # nao vale
    ], pessoas={
        "Ana": ["qui-noite", "sab-manha"],
        "Bia": ["qui-noite"],
        "Caio": ["sab-manha", "seg-noite"],
        "Davi": ["dom-tarde"],
    })

    plano = api.get("/education/mentorships/f1/meeting-plan").json()

    assert plano["accepted"] == 4 and plano["with_availability"] == 4
    assert [(o["weekday_name"], o["count"]) for o in plano["options"]] == [
        ("Quinta", 2), ("Sábado", 2)]
    assert plano["options"][0]["names"] == ["Ana", "Bia"]
    assert plano["options"][1]["names"] == ["Ana", "Caio"]
    assert plano["uncovered"] == ["Davi"]
    assert "Segunda" not in str(plano["options"]), "faixa so de graduacao fica fora"


def test_plano_sem_faixas_ou_sem_horarios_avisa(api):
    mentoria(api, faixas=[], pessoas={"Ana": ["qui-noite"]})

    vazio = api.get("/education/mentorships/f1/meeting-plan").json()

    assert vazio["has_slots"] is False and vazio["options"] == []
    assert vazio["uncovered"] == ["Ana"]


def test_aceito_que_nao_marcou_horario_conta_como_sem_cobertura(api):
    mentoria(api, faixas=[slot(3)], pessoas={"Ana": ["qui-noite"], "Bia": []})

    plano = api.get("/education/mentorships/f1/meeting-plan").json()

    assert plano["accepted"] == 2 and plano["with_availability"] == 1
    assert plano["options"][0]["count"] == 1 and plano["uncovered"] == ["Bia"]
