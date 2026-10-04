"""Sorteio da ordem de apresentacao: regra verificavel e API."""

from __future__ import annotations

import asyncio
import tempfile
from collections import Counter

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import (
    DisciplineModel,
    GroupDrawEntryModel,
    GroupDrawModel,
    ProjectGroupMemberModel,
    ProjectGroupModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import group_draw
from app.services import group_draw_service as rule

IDS = ["g1", "g2", "g3", "g4", "g5", "g6"]


# --- regra --------------------------------------------------------------------------


@pytest.mark.unit
def test_mesma_semente_mesma_ordem_e_cobre_todos_os_grupos():
    ordem = rule.draw_order("semente", IDS)
    assert ordem == rule.draw_order("semente", IDS)
    assert sorted(ordem) == sorted(IDS)


@pytest.mark.unit
def test_a_ordem_nao_depende_da_ordem_em_que_os_grupos_chegam():
    assert rule.draw_order("s", IDS) == rule.draw_order("s", list(reversed(IDS)))


@pytest.mark.unit
def test_sementes_diferentes_dao_ordens_diferentes():
    ordens = {tuple(rule.draw_order(f"semente-{i}", IDS)) for i in range(30)}
    assert len(ordens) > 20


@pytest.mark.unit
def test_cada_grupo_tem_chance_parecida_de_abrir_a_fila():
    primeiros = Counter(rule.draw_order(f"s{i}", IDS)[0] for i in range(1200))
    esperado = 1200 / len(IDS)
    assert set(primeiros) == set(IDS)
    assert all(abs(vezes - esperado) < esperado * 0.3 for vezes in primeiros.values())


@pytest.mark.unit
def test_sorteio_avulso_chega_na_mesma_ordem_da_fila_completa():
    restantes, avulso = list(IDS), []
    for passo in range(len(IDS)):
        escolhido = rule.pick_step("abc", passo, restantes)
        avulso.append(escolhido)
        restantes.remove(escolhido)
    assert avulso == rule.draw_order("abc", IDS)


@pytest.mark.unit
def test_verificacao_aceita_a_ordem_certa_e_recusa_a_adulterada():
    ordem = rule.draw_order("abc", IDS)
    assert rule.verify_order("abc", IDS, ordem)
    assert rule.verify_order("abc", IDS, ordem[:3])
    trocada = [ordem[1], ordem[0], *ordem[2:]]
    assert not rule.verify_order("abc", IDS, trocada)
    assert not rule.verify_order("outra", IDS, ordem)


@pytest.mark.unit
def test_grupos_repetidos_na_entrada_contam_uma_vez():
    assert sorted(rule.draw_order("s", ["a", "b", "a"])) == ["a", "b"]


@pytest.mark.unit
def test_sem_grupos_nao_ha_o_que_sortear():
    with pytest.raises(ValueError):
        rule.pick_step("s", 0, [])
    assert rule.draw_order("s", []) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "posicao, por_dia, dia",
    [(1, None, 1), (9, None, 1), (1, 3, 1), (3, 3, 1), (4, 3, 2), (7, 3, 3), (5, 0, 1)],
)
def test_dia_da_apresentacao(posicao, por_dia, dia):
    assert rule.day_of(posicao, por_dia) == dia


@pytest.mark.unit
def test_representante_e_do_grupo_e_muda_a_cada_rodada():
    membros = ["m1", "m2", "m3", "m4"]
    escolhas = {rule.pick_representative("s", "g1", membros, round_=r) for r in range(20)}
    assert escolhas <= set(membros)
    assert len(escolhas) > 1
    assert rule.pick_representative("s", "g1", membros) == rule.pick_representative(
        "s", "g1", list(reversed(membros))
    )


@pytest.mark.unit
def test_grupo_sem_integrantes_nao_tem_representante():
    with pytest.raises(ValueError):
        rule.pick_representative("s", "g1", [])


# --- API ----------------------------------------------------------------------------

USER = {"uid": "u1", "tutor_id": "t1"}


@pytest.fixture
def api():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/d.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in (
                DisciplineModel, ProjectGroupModel, ProjectGroupMemberModel,
                GroupDrawModel, GroupDrawEntryModel,
            ):
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                DisciplineModel(id="d1", tutor_id="t1", code="ARA0040", name="BANCO DE DADOS"),
                DisciplineModel(id="d-alheia", tutor_id="outro", code="X", name="Y"),
            ])
            for numero in range(1, 5):
                db.add(ProjectGroupModel(
                    id=f"g{numero}", tutor_id="t1", discipline_id="d1",
                    semester="2026.2", name=f"Grupo {numero}",
                ))
            db.add(ProjectGroupModel(
                id="g-velho", tutor_id="t1", discipline_id="d1",
                semester="2026.1", name="Grupo antigo",
            ))
            db.add_all([
                ProjectGroupMemberModel(id="m1", group_id="g1", name="Ana", position=0),
                ProjectGroupMemberModel(id="m2", group_id="g1", name="Bia", position=1),
                ProjectGroupMemberModel(id="m3", group_id="g1", name="Caio", position=2),
                ProjectGroupMemberModel(id="m4", group_id="g2", name="Davi", position=0),
            ])
            await db.commit()

    asyncio.run(seed())

    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(group_draw.router)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: USER
    with TestClient(app) as client:
        yield client
    asyncio.run(engine.dispose())


def criar(api, **extra):
    corpo = {"discipline_id": "d1", "semester": "2026.2", **extra}
    return api.post("/education/group-draws", json=corpo)


@pytest.mark.integration
def test_fila_completa_sai_pronta_e_confere_com_a_semente(api):
    resposta = criar(api, mode="fila")

    assert resposta.status_code == 200
    sorteio = resposta.json()
    assert sorteio["total"] == 4 and sorteio["remaining"] == 0
    assert sorteio["verified"] is True
    assert sorteio["discipline"] == "ARA0040 - BANCO DE DADOS"
    posicoes = [item["position"] for item in sorteio["entries"]]
    assert posicoes == [1, 2, 3, 4]
    # A conta e refeita por quem tiver a semente: a mesma ordem.
    esperado = rule.draw_order(sorteio["seed"], ["g1", "g2", "g3", "g4"])
    assert [item["group_id"] for item in sorteio["entries"]] == esperado


@pytest.mark.integration
def test_so_entram_os_grupos_do_semestre_pedido(api):
    nomes = {item["group_name"] for item in criar(api).json()["entries"]}
    assert nomes == {"Grupo 1", "Grupo 2", "Grupo 3", "Grupo 4"}
    assert "Grupo antigo" in {
        item["group_name"] for item in criar(api, semester="2026.1").json()["entries"]
    }


@pytest.mark.integration
def test_varias_apresentacoes_no_mesmo_dia(api):
    sorteio = criar(api, per_day=3).json()
    assert [item["day"] for item in sorteio["entries"]] == [1, 1, 1, 2]
    assert {item["day"] for item in criar(api).json()["entries"]} == {1}


@pytest.mark.integration
def test_subconjunto_de_grupos(api):
    sorteio = criar(api, group_ids=["g2", "g3"]).json()
    assert {item["group_id"] for item in sorteio["entries"]} == {"g2", "g3"}


@pytest.mark.integration
def test_grupo_de_outro_semestre_ou_inexistente_e_recusado(api):
    assert criar(api, group_ids=["g1", "g-velho"]).status_code == 422
    assert criar(api, group_ids=["nao-existe"]).status_code == 422


@pytest.mark.integration
def test_disciplina_alheia_ou_sem_grupos(api):
    assert criar(api, discipline_id="d-alheia").status_code == 404
    assert criar(api, discipline_id="nao-existe").status_code == 404
    assert criar(api, semester="1999.1").status_code == 422


@pytest.mark.integration
def test_modo_avulso_revela_um_grupo_por_vez_ate_acabar(api):
    sorteio = criar(api, mode="avulso", per_day=2).json()
    assert sorteio["remaining"] == 4
    assert all(item["position"] is None for item in sorteio["entries"])

    ordem = []
    for esperado in (3, 2, 1, 0):
        sorteio = api.post(f"/education/group-draws/{sorteio['id']}/next").json()
        assert sorteio["remaining"] == esperado
        assert sorteio["verified"] is True
        ordem = [item["group_id"] for item in sorteio["entries"] if item["position"]]

    assert ordem == rule.draw_order(sorteio["seed"], ["g1", "g2", "g3", "g4"])
    assert [item["day"] for item in sorteio["entries"]] == [1, 1, 2, 2]
    assert api.post(f"/education/group-draws/{sorteio['id']}/next").status_code == 409


@pytest.mark.integration
def test_fila_completa_nao_aceita_sorteio_avulso(api):
    sorteio = criar(api, mode="fila").json()
    assert api.post(f"/education/group-draws/{sorteio['id']}/next").status_code == 409


@pytest.mark.integration
def test_marcar_apresentou_ausente_e_na_vez(api):
    sorteio = criar(api).json()
    entrada = sorteio["entries"][0]["id"]
    url = f"/education/group-draws/{sorteio['id']}/entries/{entrada}"

    feito = api.patch(url, json={"status": "apresentou"}).json()["entries"][0]
    assert feito["status"] == "apresentou" and feito["presented_at"]

    voltou = api.patch(url, json={"status": "ausente"}).json()["entries"][0]
    assert voltou["status"] == "ausente" and voltou["presented_at"] is None

    assert api.patch(url, json={"status": "inventado"}).status_code == 422


@pytest.mark.integration
def test_grupo_ainda_nao_sorteado_nao_recebe_status(api):
    sorteio = criar(api, mode="avulso").json()
    entrada = sorteio["entries"][0]["id"]
    resposta = api.patch(
        f"/education/group-draws/{sorteio['id']}/entries/{entrada}",
        json={"status": "apresentando"},
    )
    assert resposta.status_code == 409


@pytest.mark.integration
def test_representante_sai_do_grupo_e_sorteia_outro_na_repeticao(api):
    sorteio = criar(api).json()
    entrada = next(item for item in sorteio["entries"] if item["group_id"] == "g1")
    url = f"/education/group-draws/{sorteio['id']}/entries/{entrada['id']}/representative"

    primeiro = next(
        item for item in api.post(url).json()["entries"] if item["group_id"] == "g1"
    )
    assert primeiro["representative_name"] in {"Ana", "Bia", "Caio"}
    assert primeiro["representative_round"] == 0

    esperado = rule.pick_representative(sorteio["seed"], "g1", ["m1", "m2", "m3"], round_=0)
    assert primeiro["representative_member_id"] == esperado

    segundo = next(
        item for item in api.post(url).json()["entries"] if item["group_id"] == "g1"
    )
    assert segundo["representative_round"] == 1


@pytest.mark.integration
def test_representante_de_grupo_de_um_so_e_ele_mesmo_e_sem_integrantes_da_422(api):
    sorteio = criar(api).json()
    por_grupo = {item["group_id"]: item["id"] for item in sorteio["entries"]}
    base = f"/education/group-draws/{sorteio['id']}/entries"

    unico = api.post(f"{base}/{por_grupo['g2']}/representative").json()
    davi = next(item for item in unico["entries"] if item["group_id"] == "g2")
    assert davi["representative_name"] == "Davi"
    outra = api.post(f"{base}/{por_grupo['g2']}/representative").json()
    assert next(i for i in outra["entries"] if i["group_id"] == "g2")["representative_round"] == 0

    assert api.post(f"{base}/{por_grupo['g3']}/representative").status_code == 422


@pytest.mark.integration
def test_listar_buscar_e_apagar(api):
    primeiro = criar(api, title="Primeiro").json()
    segundo = criar(api, title="Segundo").json()

    lista = api.get("/education/group-draws").json()
    assert {item["id"] for item in lista} == {primeiro["id"], segundo["id"]}
    assert all("entries" not in item for item in lista)

    assert api.get(f"/education/group-draws/{primeiro['id']}").json()["title"] == "Primeiro"
    assert api.delete(f"/education/group-draws/{primeiro['id']}").status_code == 200
    assert api.get(f"/education/group-draws/{primeiro['id']}").status_code == 404
    assert [item["id"] for item in api.get("/education/group-draws").json()] == [segundo["id"]]


@pytest.mark.integration
def test_sorteio_de_outro_professor_nao_existe_para_mim(api):
    sorteio = criar(api).json()
    api.app.dependency_overrides[get_current_user] = lambda: {"uid": "u2", "tutor_id": "outro"}

    assert api.get(f"/education/group-draws/{sorteio['id']}").status_code == 404
    assert api.post(f"/education/group-draws/{sorteio['id']}/next").status_code == 404
    assert api.delete(f"/education/group-draws/{sorteio['id']}").status_code == 404
    assert api.get("/education/group-draws").json() == []
