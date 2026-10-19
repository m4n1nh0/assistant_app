"""Calendario letivo: periodo do semestre e datas sem aula.

O horario semanal diz "segunda, 18:30" e repete para sempre. Estes testes guardam o que o cruza com
o inicio e o fim do semestre e com as datas sem aula (feriado, recesso, aula cancelada), e que a
projecao das proximas aulas e a API respeitam isso.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import database
from app.core.database import (
    ClassBreakModel,
    ClassGroupModel,
    ClassScheduleModel,
    DisciplineModel,
    SemesterPeriodModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import education
from app.services import academic_calendar_service as cal
from app.services import academic_query_service as query

DONO = "tutor-dono"
OUTRO = "tutor-outro"
SEMESTRE = "2026.2"
TABELAS = (DisciplineModel, ClassGroupModel, ClassScheduleModel, SemesterPeriodModel, ClassBreakModel)

# 2026-10-19 e uma segunda-feira.
SEGUNDA = date(2026, 10, 19)


def run(coro):
    return asyncio.run(coro)


# --- regra pura ----------------------------------------------------------------------------------


def test_without_a_period_or_breaks_every_day_has_class():
    assert cal.day_status(SEGUNDA, "g1", cal.Period(), []).has_class


def test_the_period_limits_are_inclusive_and_outside_has_a_reason():
    period = cal.Period(date(2026, 8, 3), date(2026, 12, 14))

    assert cal.day_status(date(2026, 8, 3), "g1", period).has_class
    assert cal.day_status(date(2026, 12, 14), "g1", period).has_class
    before = cal.day_status(date(2026, 7, 27), "g1", period)
    after = cal.day_status(date(2026, 12, 21), "g1", period)
    assert (before.state, after.state) == (cal.BEFORE, cal.AFTER)
    assert "03/08/2026" in before.reason and "14/12/2026" in after.reason


def test_only_an_end_date_is_enough_to_cut_the_semester():
    period = cal.Period(None, date(2026, 12, 14))

    assert cal.day_status(date(2026, 8, 1), "g1", period).has_class
    assert cal.day_status(date(2026, 12, 15), "g1", period).state == cal.AFTER


def test_a_break_for_everybody_hits_every_class_and_one_for_a_class_only_that_one():
    holiday = cal.Break("b1", date(2026, 11, 2), date(2026, 11, 2), None, "Finados")
    cancelled = cal.Break("b2", date(2026, 10, 26), date(2026, 10, 26), "g1", "Professor em congresso")

    assert cal.day_status(date(2026, 11, 2), "g1", cal.Period(), [holiday]).state == cal.BREAK
    assert cal.day_status(date(2026, 11, 2), "g2", cal.Period(), [holiday]).reason == "Finados"
    assert cal.day_status(date(2026, 10, 26), "g1", cal.Period(), [cancelled]).state == cal.BREAK
    assert cal.day_status(date(2026, 10, 26), "g2", cal.Period(), [cancelled]).has_class


def test_a_break_range_covers_every_day_in_it_and_none_outside():
    recess = cal.Break("b1", date(2026, 10, 12), date(2026, 10, 16), None, "Recesso")

    assert cal.day_status(date(2026, 10, 12), "g1", cal.Period(), [recess]).state == cal.BREAK
    assert cal.day_status(date(2026, 10, 16), "g1", cal.Period(), [recess]).state == cal.BREAK
    assert cal.day_status(date(2026, 10, 19), "g1", cal.Period(), [recess]).has_class


def test_a_break_without_a_reason_still_says_there_is_no_class():
    quiet = cal.Break("b1", date(2026, 10, 19), date(2026, 10, 19))

    assert cal.day_status(SEGUNDA, "g1", cal.Period(), [quiet]).reason == "sem aula"


def test_outside_the_semester_wins_over_a_break():
    period = cal.Period(date(2026, 8, 3), date(2026, 12, 14))
    inside_break_after_end = cal.Break("b1", date(2026, 12, 21), date(2026, 12, 21))

    assert cal.day_status(date(2026, 12, 21), "g1", period, [inside_break_after_end]).state == cal.AFTER


def test_parse_day_accepts_iso_and_ignores_garbage():
    assert cal.parse_day("2026-10-19") == SEGUNDA
    assert cal.parse_day("") is None
    assert cal.parse_day("19/10/2026") is None
    assert cal.parse_day(None) is None


# --- banco -----------------------------------------------------------------------------------------


@pytest.fixture
def banco(monkeypatch):
    """Dois grupos de Banco de Dados na segunda, 18:30, mais um grupo de outro professor."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/cal.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in TABELAS:
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add(DisciplineModel(id="d1", tutor_id=DONO, code="ARA0040", name="BANCO DE DADOS",
                                   semester=SEMESTRE, active=True))
            db.add_all([
                ClassGroupModel(id="g3002", tutor_id=DONO, code="3002", name="", discipline_id="d1",
                                discipline="ARA0040 - BANCO DE DADOS", semester=SEMESTRE, active=True),
                ClassGroupModel(id="g3030", tutor_id=DONO, code="3030", name="", discipline_id="d1",
                                discipline="ARA0040 - BANCO DE DADOS", semester=SEMESTRE, active=True),
                ClassGroupModel(id="gx", tutor_id=OUTRO, code="9999", name="", discipline="Alheia",
                                semester=SEMESTRE, active=True),
            ])
            db.add_all([
                ClassScheduleModel(class_group_id="g3002", weekday=0, start_time="18:30", end_time="20:10"),
                ClassScheduleModel(class_group_id="g3030", weekday=0, start_time="18:30", end_time="20:10"),
                ClassScheduleModel(class_group_id="gx", weekday=0, start_time="09:00", end_time="10:00"),
            ])
            await db.commit()

    run(seed())
    monkeypatch.setattr(database, "AsyncSessionLocal", sessions)
    return sessions


def add(sessions, *items):
    async def go():
        async with sessions() as db:
            db.add_all(items)
            await db.commit()

    run(go())


def days(found):
    return [(item.day, item.group_label) for item in found]


def test_a_monday_has_the_classes_of_that_weekday_only_for_the_owner(banco):
    found = run(cal.occurrences(DONO, SEGUNDA, SEGUNDA))

    assert days(found) == [(SEGUNDA, "3002"), (SEGUNDA, "3030")]
    assert found[0].discipline_label == "ARA0040 BANCO DE DADOS"
    assert (found[0].start_time, found[0].end_time) == ("18:30", "20:10")


def test_other_weekdays_have_nothing(banco):
    assert run(cal.occurrences(DONO, date(2026, 10, 20), date(2026, 10, 25))) == []


def test_the_semester_end_cuts_the_projection_and_can_be_listed_as_skipped(banco):
    add(banco, SemesterPeriodModel(tutor_id=DONO, code=SEMESTRE, start_date="2026-08-03", end_date="2026-10-26"))

    real = run(cal.occurrences(DONO, SEGUNDA, date(2026, 11, 9)))
    everything = run(cal.occurrences(DONO, SEGUNDA, date(2026, 11, 9), include_skipped=True))

    assert sorted({item.day for item in real}) == [SEGUNDA, date(2026, 10, 26)]
    skipped = [item for item in everything if not item.status.has_class]
    assert {item.day for item in skipped} == {date(2026, 11, 2), date(2026, 11, 9)}
    assert all(item.status.state == cal.AFTER for item in skipped)


def test_a_break_for_everybody_removes_the_day_and_one_for_a_class_removes_only_that_class(banco):
    add(
        banco,
        ClassBreakModel(tutor_id=DONO, semester=SEMESTRE, date_from="2026-10-26", date_to="2026-10-26",
                        class_group_id=None, reason="Recesso"),
        ClassBreakModel(tutor_id=DONO, semester=SEMESTRE, date_from="2026-11-02", date_to="2026-11-02",
                        class_group_id="g3002", reason="Congresso"),
    )

    found = run(cal.occurrences(DONO, SEGUNDA, date(2026, 11, 2)))

    assert days(found) == [
        (SEGUNDA, "3002"), (SEGUNDA, "3030"),
        (date(2026, 11, 2), "3030"),  # 3002 cancelada, 3030 mantida; 26/10 sem aula para todas
    ]


def test_another_tutors_breaks_and_periods_do_not_apply(banco):
    add(
        banco,
        SemesterPeriodModel(tutor_id=OUTRO, code=SEMESTRE, start_date="2026-01-01", end_date="2026-01-31"),
        ClassBreakModel(tutor_id=OUTRO, semester=SEMESTRE, date_from="2026-10-19", date_to="2026-10-19", reason="x"),
    )

    assert len(run(cal.occurrences(DONO, SEGUNDA, SEGUNDA))) == 2


def test_a_closed_class_group_has_no_occurrences(banco):
    async def close():
        async with banco() as db:
            group = await db.get(ClassGroupModel, "g3002")
            group.active = False
            await db.commit()

    run(close())

    assert days(run(cal.occurrences(DONO, SEGUNDA, SEGUNDA))) == [(SEGUNDA, "3030")]


# --- resposta do assistente --------------------------------------------------------------------------------


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 19, 12, 0, tzinfo=tz)


@pytest.fixture
def hoje(monkeypatch):
    monkeypatch.setattr(query, "datetime", FixedClock)


def test_the_schedule_answer_lists_classes_and_admits_it_does_not_know_the_semester_end(banco, hoje):
    text = run(query.academic_schedule_response(DONO, "America/Sao_Paulo"))

    assert "19/10/2026: ARA0040 BANCO DE DADOS — turma 3002 — 18:30–20:10" in text
    assert "26/10/2026" in text
    assert "O fim do semestre 2026.2 não está cadastrado." in text
    assert "Feriados e cancelamentos só aparecem se cadastrados" in text


def test_the_schedule_answer_respects_the_semester_end_and_the_breaks(banco, hoje):
    add(
        banco,
        SemesterPeriodModel(tutor_id=DONO, code=SEMESTRE, start_date="2026-08-03", end_date="2026-11-02"),
        ClassBreakModel(tutor_id=DONO, semester=SEMESTRE, date_from="2026-10-26", date_to="2026-10-26",
                        class_group_id=None, reason="Recesso"),
    )

    text = run(query.academic_schedule_response(DONO, "America/Sao_Paulo"))
    listed, _, rest = text.partition("Sem aula nesse período")

    assert "19/10/2026" in listed and "02/11/2026" in listed
    assert "26/10/2026" not in listed and "09/11/2026" not in listed
    assert "26/10/2026" in rest and "Recesso" in rest
    assert "09/11/2026" in rest and "o semestre terminou em 02/11/2026" in rest
    assert "O semestre 2026.2 termina em 02/11/2026." in text
    assert "Feriados e cancelamentos" not in text  # o periodo esta cadastrado


def test_the_schedule_answer_without_any_schedule_says_so(banco, hoje):
    assert "Não encontrei horários" in run(query.academic_schedule_response("tutor-sem-nada", "America/Sao_Paulo"))


# --- API -------------------------------------------------------------------------------------------------------


@pytest.fixture
def api(banco):
    app = FastAPI()
    app.include_router(education.router)

    async def db_dependency():
        async with banco() as db:
            yield db

    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: {"uid": "u1", "tutor_id": DONO}
    return TestClient(app)


def test_listing_semesters_brings_the_period_and_the_break_count(api, banco):
    add(
        banco,
        SemesterPeriodModel(tutor_id=DONO, code=SEMESTRE, start_date="2026-08-03", end_date="2026-12-14"),
        ClassBreakModel(tutor_id=DONO, semester=SEMESTRE, date_from="2026-10-26", date_to="2026-10-26", reason="x"),
    )

    body = api.get("/education/semesters").json()

    assert body == [{
        "code": SEMESTRE, "active": True, "discipline_count": 1, "class_count": 2,
        "start_date": "2026-08-03", "end_date": "2026-12-14", "break_count": 1,
    }]


def test_a_semester_without_a_period_lists_it_as_empty(api):
    body = api.get("/education/semesters").json()[0]

    assert (body["start_date"], body["end_date"], body["break_count"]) == ("", "", 0)


def test_setting_the_period_keeps_the_active_flag_and_can_be_changed_in_parts(api):
    first = api.patch(f"/education/semesters/{SEMESTRE}", json={"start_date": "2026-08-03", "end_date": "2026-12-14"})
    later = api.patch(f"/education/semesters/{SEMESTRE}", json={"end_date": "2026-12-18"})

    assert first.status_code == 200 and first.json()["active"] is True
    assert (later.json()["start_date"], later.json()["end_date"]) == ("2026-08-03", "2026-12-18")


def test_clearing_the_dates_with_empty_strings(api):
    api.patch(f"/education/semesters/{SEMESTRE}", json={"start_date": "2026-08-03", "end_date": "2026-12-14"})

    cleared = api.patch(f"/education/semesters/{SEMESTRE}", json={"start_date": "", "end_date": ""}).json()

    assert (cleared["start_date"], cleared["end_date"]) == ("", "")


def test_closing_a_semester_still_works_without_touching_the_period(api):
    api.patch(f"/education/semesters/{SEMESTRE}", json={"start_date": "2026-08-03", "end_date": "2026-12-14"})

    closed = api.patch(f"/education/semesters/{SEMESTRE}", json={"active": False}).json()

    assert closed["active"] is False and closed["end_date"] == "2026-12-14"


@pytest.mark.parametrize(
    "body",
    [
        {"start_date": "2026-12-14", "end_date": "2026-08-03"},
        {"start_date": "03/08/2026"},
        {"end_date": "2026-13-40"},
    ],
)
def test_an_invalid_period_is_refused(api, body):
    assert api.patch(f"/education/semesters/{SEMESTRE}", json=body).status_code == 422


def test_an_end_before_the_start_already_saved_is_refused_too(api):
    api.patch(f"/education/semesters/{SEMESTRE}", json={"start_date": "2026-08-03"})

    response = api.patch(f"/education/semesters/{SEMESTRE}", json={"end_date": "2026-07-01"})

    assert response.status_code == 422
    assert api.get("/education/semesters").json()[0]["end_date"] == ""


def test_an_unknown_semester_is_not_found(api):
    assert api.patch("/education/semesters/2031.1", json={"start_date": "2031-02-01"}).status_code == 404


def test_creating_listing_and_deleting_breaks(api):
    created = api.post(f"/education/semesters/{SEMESTRE}/breaks",
                       json={"date_from": "2026-10-12", "date_to": "2026-10-16", "reason": " Recesso "})
    single = api.post(f"/education/semesters/{SEMESTRE}/breaks",
                      json={"date_from": "2026-11-02", "class_group_id": "g3002", "reason": "Finados"})

    assert created.status_code == 201 and created.json()["reason"] == "Recesso"
    assert single.json()["date_to"] == "2026-11-02"       # sem data final, e um dia so
    assert single.json()["class_label"] == "3002"

    listed = api.get(f"/education/semesters/{SEMESTRE}/breaks").json()
    assert [item["date_from"] for item in listed] == ["2026-10-12", "2026-11-02"]
    assert api.get("/education/semesters").json()[0]["break_count"] == 2

    assert api.delete(f"/education/semesters/{SEMESTRE}/breaks/{created.json()['id']}").status_code == 200
    assert len(api.get(f"/education/semesters/{SEMESTRE}/breaks").json()) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"date_from": "2026-10-16", "date_to": "2026-10-12"},
        {"date_from": "amanha"},
        {"date_from": ""},
    ],
)
def test_an_invalid_break_is_refused(api, body):
    assert api.post(f"/education/semesters/{SEMESTRE}/breaks", json=body).status_code == 422


def test_a_break_for_a_class_of_another_tutor_or_semester_is_refused(api):
    assert api.post(f"/education/semesters/{SEMESTRE}/breaks",
                    json={"date_from": "2026-10-12", "class_group_id": "gx"}).status_code == 404
    assert api.post(f"/education/semesters/{SEMESTRE}/breaks",
                    json={"date_from": "2026-10-12", "class_group_id": "inexistente"}).status_code == 404


def test_one_tutor_cannot_see_or_delete_the_breaks_of_another(api, banco):
    foreign = ClassBreakModel(id="alheia", tutor_id=OUTRO, semester=SEMESTRE, date_from="2026-10-12",
                              date_to="2026-10-12", reason="x")
    add(banco, foreign)

    assert api.get(f"/education/semesters/{SEMESTRE}/breaks").json() == []
    assert api.delete(f"/education/semesters/{SEMESTRE}/breaks/alheia").status_code == 404


def test_the_break_affects_the_projection_right_after_it_is_created(api, banco, hoje):
    api.post(f"/education/semesters/{SEMESTRE}/breaks", json={"date_from": "2026-10-26", "reason": "Recesso"})

    text = run(query.academic_schedule_response(DONO, "America/Sao_Paulo"))
    listed = text.partition("Sem aula nesse período")[0]

    assert "26/10/2026" not in listed and "Recesso" in text
