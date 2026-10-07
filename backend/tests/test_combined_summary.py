"""Resumo conjunto de várias gravações do histórico.

Falha que isto evita: num dia de apresentações de grupo só dava para resumir uma
gravação de cada vez e juntar os textos à mão. Aqui o professor marca as gravações e
recebe um resumo só, com uma seção por grupo, sem misturar o que um grupo disse com o
do outro.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import (
    LessonModel,
    LessonSegmentModel,
    ProjectGroupModel,
    get_db,
)
from app.core.security import get_current_user
from app.models.schemas import LLMResponse
from app.routers import education
from app.services import combined_summary_service as combined
from app.services import education_service
from app.services.user_llm_config_service import user_llm_context

USER = {"uid": "u1", "tutor_id": "t1"}
BASE = datetime(2026, 10, 6, 21, 0)
DISCIPLINA = "ARA0058 - CLOUD, IOT E INDUSTRIA 4.0"


class FakeLLM:
    """Responde por tipo de chamada: resumo de uma gravação ou resumo conjunto."""

    def __init__(self, monkeypatch):
        self.calls: list[dict] = []
        self.fail_single = False
        self.fail_combined = False
        monkeypatch.setattr(education_service, "dispatch_single", self._dispatch)

        async def providers(preferred=None):
            return [preferred or "llama"]

        monkeypatch.setattr(education_service, "_summary_provider_candidates", providers)

    async def _dispatch(self, llm, message, history, system_prompt, **options):
        conjunto = system_prompt.startswith("Voce faz o resumo conjunto")
        self.calls.append(dict(message=message, system=system_prompt, combined=conjunto))
        if conjunto:
            if self.fail_combined:
                return LLMResponse(llm=llm, content="boom", is_error=True)
            return LLMResponse(llm=llm, content="## Visao geral\nResumo conjunto.", is_error=False)
        if self.fail_single:
            return LLMResponse(llm=llm, content="boom", is_error=True)
        return LLMResponse(llm=llm, content="## Resumo\nResumo gerado agora.", is_error=False)

    @property
    def single(self):
        return [c for c in self.calls if not c["combined"]]

    @property
    def joint(self):
        return [c for c in self.calls if c["combined"]]


@pytest.fixture
def llm(monkeypatch):
    return FakeLLM(monkeypatch)


@pytest.fixture
def api(llm):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/c.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in (LessonModel, LessonSegmentModel, ProjectGroupModel):
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                ProjectGroupModel(id="g1", tutor_id="t1", discipline_id="d1", semester="2026.2", name="GRUPO 1"),
                ProjectGroupModel(id="g2", tutor_id="t1", discipline_id="d1", semester="2026.2", name="GRUPO 2"),
                ProjectGroupModel(id="g3", tutor_id="t1", discipline_id="d1", semester="2026.2", name="GRUPO 3"),
                # Apresentacoes de tres grupos: g1 ja resumida, g2 so com transcricao,
                # g3 sem nada.
                lesson("p1", "apresentacao", 0, group="g1", summary="Resumo pronto do grupo 1."),
                lesson("p2", "apresentacao", 15, group="g2"),
                lesson("p3", "apresentacao", 30, group="g3"),
                LessonSegmentModel(lesson_id="p2", tutor_id="t1", sequence=0, text="o grupo dois falou de sensores"),
                LessonSegmentModel(lesson_id="p2", tutor_id="t1", sequence=1, text="e de mqtt"),
                # Gravacoes de outros tipos e de outro professor.
                lesson("a1", "aula", 0, discipline="BANCO DE DADOS", title="Normalizacao", summary="Resumo da aula 1."),
                lesson("a2", "aula", 60, discipline="BANCO DE DADOS", title="Indices", summary="Resumo da aula 2."),
                lesson("pal", "palestra", 0, title="LGPD", summary="Resumo da palestra."),
                lesson("alheia", "aula", 0, tutor="t2", summary="de outro"),
            ])
            await db.commit()

    def lesson(id_, kind, minutes, group=None, discipline=DISCIPLINA, title="",
               summary=None, tutor="t1"):
        return LessonModel(
            id=id_, tutor_id=tutor, kind=kind, group_id=group, discipline=discipline if kind != "palestra" else "",
            semester="2026.2", title=title, status="closed",
            started_at=BASE + timedelta(minutes=minutes), summary=summary)

    asyncio.run(seed())

    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(education.router)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[user_llm_context] = lambda: None
    with TestClient(app) as client:
        client.sessions = sessions
        yield client
    asyncio.run(engine.dispose())


def resumir(api, ids, **extra):
    return api.post("/education/combined-summary", json={"lesson_ids": ids, **extra})


# --- apresentacoes de grupo ---------------------------------------------------------


def test_resume_as_apresentacoes_com_uma_secao_por_grupo(api, llm):
    resposta = resumir(api, ["p1", "p2"])

    assert resposta.status_code == 200, resposta.text
    dados = resposta.json()
    assert dados["summary"].startswith("## Visao geral")
    assert dados["title"] == "Apresentações dos grupos"
    assert dados["kind"] == "selecao-apresentacao"
    assert [item["label"] for item in dados["items"]] == [
        "GRUPO 1 (06/10 21:00)", "GRUPO 2 (06/10 21:15)"]
    assert [item["source"] for item in dados["items"]] == ["resumo", "gerado"]
    assert [item["group_name"] for item in dados["items"]] == ["GRUPO 1", "GRUPO 2"]

    pedido = llm.joint[0]
    assert "## Por grupo" in pedido["message"]
    assert "### GRUPO 1 (06/10 21:00)\nResumo pronto do grupo 1." in pedido["message"]
    assert "### GRUPO 2 (06/10 21:15)\n## Resumo\nResumo gerado agora." in pedido["message"]
    assert "sem atribuir nota" in pedido["system"]
    assert "nunca atribua a uma gravacao o que foi dito em outra" in pedido["system"]


def test_o_subtitulo_traz_disciplina_periodo_e_quantidade(api):
    dados = resumir(api, ["p1", "p2"]).json()

    assert dados["subtitle"] == f"{DISCIPLINA}  -  06/10/2026  -  2 gravações"


def test_periodo_com_dias_diferentes_vai_de_um_a_outro(api):
    async def mover(db):
        (await db.get(LessonModel, "p2")).started_at = BASE + timedelta(days=7)
        await db.commit()

    async def go():
        async with api.sessions() as db:
            await mover(db)
    asyncio.run(go())

    dados = resumir(api, ["p1", "p2"]).json()

    assert "06/10/2026 a 13/10/2026" in dados["subtitle"]


def test_a_gravacao_sem_resumo_e_resumida_no_formato_do_tipo_dela(api, llm):
    resumir(api, ["p1", "p2"])

    unica = llm.single
    assert len(unica) == 1
    assert "apresentacoes de trabalhos de grupo" in unica[0]["system"]
    assert "o grupo dois falou de sensores" in unica[0]["message"]


def test_o_resumo_gerado_na_hora_nao_e_gravado_na_aula(api):
    resumir(api, ["p1", "p2"])

    async def resumos(db):
        return {item.id: item.summary for item in
                (await db.execute(select(LessonModel))).scalars().all()}

    async def go():
        async with api.sessions() as db:
            return await resumos(db)
    assert asyncio.run(go())["p2"] is None


def test_ordem_e_cronologica_mesmo_que_a_selecao_venha_embaralhada(api):
    dados = resumir(api, ["p2", "p1"]).json()

    assert [item["id"] for item in dados["items"]] == ["p1", "p2"]


def test_sem_resumo_e_sem_transcricao_a_gravacao_fica_de_fora_e_e_avisada(api):
    dados = resumir(api, ["p1", "p2", "p3"]).json()

    assert [item["id"] for item in dados["items"]] == ["p1", "p2"]
    assert dados["skipped"] == [
        {"id": "p3", "label": "GRUPO 3 (06/10 21:30)",
         "reason": "sem resumo e sem transcrição"}]
    assert dados["subtitle"].endswith("2 gravações")


def test_se_resumir_a_gravacao_falhar_entra_a_transcricao(api, llm):
    llm.fail_single = True

    dados = resumir(api, ["p1", "p2"]).json()

    assert [item["source"] for item in dados["items"]] == ["resumo", "transcricao"]
    assert "o grupo dois falou de sensores\ne de mqtt" in llm.joint[0]["message"]


def test_menos_de_duas_utilizaveis_recusa_e_diz_quais_ficaram_de_fora(api):
    resposta = resumir(api, ["p1", "p3"])

    assert resposta.status_code == 422
    assert "GRUPO 3" in resposta.json()["detail"]


# --- outras selecoes -----------------------------------------------------------------


def test_aulas_da_mesma_disciplina_tem_titulo_e_subtitulo_de_aulas(api, llm):
    dados = resumir(api, ["a1", "a2"]).json()

    assert dados["title"] == "Aulas selecionadas"
    assert dados["kind"] == "selecao"
    assert dados["subtitle"].startswith("BANCO DE DADOS  -  06/10/2026")
    assert "## Por gravacao" in llm.joint[0]["message"]
    assert "### BANCO DE DADOS — Normalizacao (06/10 21:00)" in llm.joint[0]["message"]


def test_mistura_de_tipos_usa_o_resumo_por_gravacao(api, llm):
    dados = resumir(api, ["a1", "pal", "p1"]).json()

    assert dados["title"] == "Gravações selecionadas"
    assert dados["kind"] == "selecao"
    mensagem = llm.joint[0]["message"]
    assert "### Palestra: LGPD (06/10 21:00)" in mensagem
    assert "### GRUPO 1 (06/10 21:00)" in mensagem
    assert "## Por grupo" not in mensagem
    # Sem disciplina em comum, o cabecalho nao inventa uma.
    assert "Disciplina:" not in mensagem


def test_formato_detalhado_pede_a_estrutura_detalhada(api, llm):
    resumir(api, ["p1", "p2"], style="detailed")
    resumir(api, ["a1", "a2"], style="detailed")

    apresentacoes, aulas = llm.joint
    assert "## Perguntas recorrentes" in apresentacoes["message"]
    assert "## Conceitos e definicoes" in aulas["message"]
    assert "substitui a selecao" in aulas["message"]


def test_foco_vai_no_pedido(api, llm):
    resumir(api, ["p1", "p2"], focus="tecnologias de nuvem")

    assert "De atencao especial a: tecnologias de nuvem" in llm.joint[0]["message"]


def test_textos_longos_sao_cortados_para_caber(api, llm):
    async def encher():
        async with api.sessions() as db:
            for id_ in ("p1",):
                (await db.get(LessonModel, id_)).summary = ("Paragrafo longo do grupo. " * 40 + "\n\n") * 20
            await db.commit()
    asyncio.run(encher())

    resumir(api, ["p1", "p2"])

    mensagem = llm.joint[0]["message"]
    assert "[...]" in mensagem
    # Cabe numa chamada so: nao houve condensacao em blocos, que perderia os titulos.
    assert len(llm.joint) == 1
    assert "Este e um trecho de" not in mensagem
    assert "### GRUPO 1" in mensagem and "### GRUPO 2" in mensagem


def test_o_que_cabe_na_janela_do_modelo_nao_e_condensado(api, llm):
    resumir(api, ["a1", "a2", "pal"])

    assert len(llm.joint) == 1
    assert all("Este e um trecho de" not in call["message"] for call in llm.calls)


def test_o_espaco_das_fontes_segue_a_janela_do_modelo(monkeypatch):
    assert education_service.summary_budget_chars("llama") < combined.SOURCES_CHAR_BUDGET
    assert combined.MIN_BLOCK_CHARS * combined.MAX_LESSONS <= \
        int(education_service.summary_budget_chars("llama") * combined.WINDOW_SHARE)


def test_corte_de_texto_longo():
    assert combined._cut("a" * 100, 50).endswith("[...]")
    assert combined._cut("curto", 50) == "curto"
    assert combined._cut("Primeira frase. Segunda frase longa demais para caber.", 40) \
        .startswith("Primeira frase.")


# --- validacao -----------------------------------------------------------------------


def test_exige_pelo_menos_duas_gravacoes(api):
    assert resumir(api, ["p1"]).status_code == 422
    assert resumir(api, []).status_code == 422
    # Repetida conta uma so.
    resposta = resumir(api, ["p1", "p1"])
    assert resposta.status_code == 422
    assert "pelo menos 2" in resposta.json()["detail"]


def test_limite_de_trinta_gravacoes(api):
    assert resumir(api, [f"x{i}" for i in range(31)]).status_code == 422


def test_gravacao_inexistente_ou_de_outro_professor_da_404(api):
    assert resumir(api, ["p1", "nao-existe"]).status_code == 404
    assert resumir(api, ["p1", "alheia"]).status_code == 404


def test_falha_do_modelo_no_resumo_conjunto_vira_502(api, llm):
    llm.fail_combined = True

    resposta = resumir(api, ["p1", "p2"])

    assert resposta.status_code == 502
    assert "Não foi possível gerar o resumo conjunto" in resposta.json()["detail"]


# --- perfis do prompt ---------------------------------------------------------------


def test_tipos_de_selecao_existem_so_para_resumo_nao_para_gravar():
    assert "selecao" in education_service.SUMMARY_KINDS
    assert "selecao" not in education_service.RECORDING_KINDS
    assert education_service.normalize_recording_kind("selecao") == "aula"
    assert education_service.normalize_summary_kind("selecao-apresentacao") == "selecao-apresentacao"
    assert education_service.normalize_summary_kind("webinar") == "aula"


def test_prompt_de_aula_continua_o_mesmo_com_os_novos_perfis():
    antes = education_service.summary_system_prompt("aula")

    assert antes.startswith("Voce resume aulas")
    assert "Voce faz o resumo conjunto" not in antes
