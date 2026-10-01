"""Revisao das perguntas do quiz por Codex e Claude.

Os dois agentes rodam no computador do professor; o servidor entrega o prompt,
recebe o texto bruto de cada um e decide o veredito. Estas regras evitam o vicio
da revisao por IA, que e concordar com o que ja esta escrito:

- o agente nunca recebe o gabarito: resolve a pergunta so com o texto da aula;
- quem compara com a chave gravada e o servidor;
- divergencia nunca e resolvida em silencio, e o gabarito nunca muda sozinho.
"""

from __future__ import annotations

import asyncio
import json
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import (
    LessonModel,
    LessonSegmentModel,
    MaterialModel,
    QuestionModel,
    QuizModel,
    QuizSourceModel,
    get_db,
)
from app.core.security import get_current_user
from app.routers import education
from app.services import quiz_review_service as review

USER = {"uid": "u1", "tutor_id": "t1"}

PERGUNTA = {
    "id": "q1",
    "enunciado": "Qual forma normal elimina dependencia transitiva?",
    "opcoes": [
        {"label": "A", "texto": "1FN", "correta": False},
        {"label": "B", "texto": "3FN", "correta": True},
        {"label": "C", "texto": "2FN", "correta": False},
    ],
}


def _leitura(resposta="B", ancorada=True, problemas=None, sugestao=None):
    return {
        "resposta": resposta,
        "ancorada": ancorada,
        "confianca": 0.9,
        "problemas": problemas or [],
        "sugestao": sugestao,
    }


# --- prompt ----------------------------------------------------------------


@pytest.mark.unit
def test_prompt_de_revisao_nao_entrega_o_gabarito():
    montado = review.build_review_prompt(
        source_text="A 3FN elimina dependencia transitiva.", questions=[PERGUNTA]
    )

    # O texto das instrucoes fala em "alternativa correta"; o que nao pode haver
    # e a marcacao do gabarito nas perguntas.
    perguntas = montado["prompt"].split("**Perguntas")[1].split("Para cada")[0]
    assert '"correta"' not in perguntas
    assert "true" not in perguntas
    assert "Qual forma normal elimina dependencia transitiva?" in montado["prompt"]
    assert "3FN" in montado["prompt"], "as alternativas vao, so a marcacao nao"
    assert montado["question_ids"] == ["q1"]
    assert montado["has_source"] is True


@pytest.mark.unit
def test_prompt_sem_texto_de_aula_avisa_o_agente_para_nao_avaliar_ancoragem():
    montado = review.build_review_prompt(source_text="  ", questions=[PERGUNTA])

    assert montado["has_source"] is False
    assert "Nenhum texto de aula está disponível" in montado["prompt"]


# --- leitura da resposta do agente -----------------------------------------


@pytest.mark.unit
def test_le_o_json_mesmo_cercado_de_markdown_e_casa_pelo_id():
    bruto = (
        "Segue a revisão:\n```json\n"
        + json.dumps({"revisoes": [
            {"id": "q2", "resposta": "c", "ancorada": True, "confianca": 0.8,
             "problemas": [], "sugestao": None},
            {"id": "q1", "resposta": "b", "ancorada": False, "confianca": 3,
             "problemas": ["a aula nao ensinou isso"], "sugestao": None},
        ]})
        + "\n```"
    )

    leituras = review.parse_agent_review(bruto, ["q1", "q2"])

    assert leituras["q1"]["resposta"] == "B"
    assert leituras["q1"]["ancorada"] is False
    assert leituras["q1"]["confianca"] == 1.0, "confianca fora da faixa e limitada"
    assert leituras["q1"]["problemas"] == ["a aula nao ensinou isso"]
    assert leituras["q2"]["resposta"] == "C"


@pytest.mark.unit
def test_id_errado_cai_no_indice_e_indice_fora_da_lista_e_ignorado():
    bruto = json.dumps({"revisoes": [
        {"id": "inventado", "indice": 1, "resposta": "A"},
        {"id": "inventado", "indice": 9, "resposta": "A"},
    ]})

    leituras = review.parse_agent_review(bruto, ["q1", "q2"])

    assert list(leituras) == ["q2"]


@pytest.mark.unit
def test_texto_sem_json_nao_vira_revisao():
    assert review.parse_agent_review("Não consegui revisar.", ["q1"]) == {}
    assert review.parse_agent_review(json.dumps({"outra": 1}), ["q1"]) == {}


@pytest.mark.unit
def test_sugestao_so_vale_se_der_para_responder_a_pergunta():
    sem_gabarito = {
        "enunciado": "Nova?",
        "opcoes": [{"label": "A", "texto": "x"}, {"label": "B", "texto": "y"}],
    }
    gabarito_inexistente = {**sem_gabarito, "resposta_correta": "D"}
    uma_alternativa = {
        "enunciado": "Nova?",
        "opcoes": [{"label": "A", "texto": "x"}],
        "resposta_correta": "A",
    }
    valida = {**sem_gabarito, "resposta_correta": "b", "justificativa": "porque"}

    for ruim in (sem_gabarito, gabarito_inexistente, uma_alternativa, "texto", None):
        bruto = json.dumps({"revisoes": [{"id": "q1", "resposta": "A", "sugestao": ruim}]})
        assert review.parse_agent_review(bruto, ["q1"])["q1"]["sugestao"] is None

    bruto = json.dumps({"revisoes": [{"id": "q1", "resposta": "A", "sugestao": valida}]})
    sugestao = review.parse_agent_review(bruto, ["q1"])["q1"]["sugestao"]
    assert sugestao["resposta_correta"] == "B"
    assert [o["correta"] for o in sugestao["opcoes"]] == [False, True]


# --- veredito --------------------------------------------------------------


@pytest.mark.unit
def test_stored_key_le_a_alternativa_marcada():
    assert review.stored_key(PERGUNTA) == "B"
    assert review.stored_key({"opcoes": [{"label": "A", "correta": False}]}) == ""


@pytest.mark.unit
def test_aprovada_exige_que_todo_agente_resolva_com_a_letra_do_gabarito():
    assert review.assess("B", {"codex_cli": _leitura("B")}) == review.STATUS_APPROVED
    assert review.assess(
        "B", {"codex_cli": _leitura("B"), "claude_cli": _leitura("B")}
    ) == review.STATUS_APPROVED


@pytest.mark.unit
def test_um_agente_discordando_do_gabarito_basta_para_divergir():
    veredito = review.assess(
        "B", {"codex_cli": _leitura("B"), "claude_cli": _leitura("C")}
    )

    assert veredito == review.STATUS_DIVERGENT


@pytest.mark.unit
def test_resposta_vazia_do_agente_conta_como_divergencia():
    # "Nenhuma alternativa esta correta" ou "duas se defendem" sao os piores casos.
    assert review.assess("B", {"codex_cli": _leitura("")}) == review.STATUS_DIVERGENT


@pytest.mark.unit
def test_gabarito_bate_mas_aula_nao_sustenta_ou_ha_defeito_pede_revisao():
    assert review.assess(
        "B", {"codex_cli": _leitura("B", ancorada=False)}
    ) == review.STATUS_REVIEW
    assert review.assess(
        "B", {"codex_cli": _leitura("B", problemas=["enunciado ambíguo"])}
    ) == review.STATUS_REVIEW


@pytest.mark.unit
def test_ancorada_nula_nao_reprova():
    # Sem texto de aula o agente nao avalia ancoragem (null): nao e defeito.
    assert review.assess(
        "B", {"codex_cli": _leitura("B", ancorada=None)}
    ) == review.STATUS_APPROVED


@pytest.mark.unit
def test_sem_gabarito_resolvido_nunca_e_aprovada():
    assert review.assess("", {"codex_cli": _leitura("B")}) == review.STATUS_NO_KEY
    assert review.assess("B", {}) == ""


@pytest.mark.unit
def test_segundo_agente_soma_ao_primeiro_em_vez_de_apagar():
    primeiro = review.merge_review(
        None, agent_id="codex_cli", reading=_leitura("B"), key="B"
    )
    assert primeiro["status"] == review.STATUS_APPROVED

    segundo = review.merge_review(
        primeiro, agent_id="claude_cli", reading=_leitura("C"), key="B"
    )

    assert set(segundo["agentes"]) == {"codex_cli", "claude_cli"}
    assert segundo["status"] == review.STATUS_DIVERGENT
    assert review.verified_flag(segundo["status"]) is False


@pytest.mark.unit
def test_o_mesmo_agente_rodando_de_novo_substitui_a_propria_leitura():
    primeiro = review.merge_review(
        None, agent_id="codex_cli", reading=_leitura("C"), key="B"
    )
    assert primeiro["status"] == review.STATUS_DIVERGENT

    refeito = review.merge_review(
        primeiro, agent_id="codex_cli", reading=_leitura("B"), key="B"
    )

    assert refeito["status"] == review.STATUS_APPROVED
    assert list(refeito["agentes"]) == ["codex_cli"]


@pytest.mark.unit
def test_verified_flag_so_liga_para_aprovada():
    assert review.verified_flag(review.STATUS_APPROVED) is True
    assert review.verified_flag(review.STATUS_DIVERGENT) is False
    assert review.verified_flag(review.STATUS_REVIEW) is False
    assert review.verified_flag("") is None


@pytest.mark.unit
def test_resumo_conta_por_veredito():
    contagem = review.summarize([
        {"status": review.STATUS_APPROVED},
        {"status": review.STATUS_APPROVED},
        {"status": review.STATUS_DIVERGENT},
        None,
    ])

    assert contagem == {review.STATUS_APPROVED: 2, review.STATUS_DIVERGENT: 1}


# --- endpoints -------------------------------------------------------------


def _opcoes(*corretas_por_label):
    return json.dumps([
        {"label": label, "texto": texto, "correta": label == correta}
        for label, texto, correta in corretas_por_label
    ])


@pytest.fixture
def api():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/quiz.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    opcoes = _opcoes(("A", "1FN", "B"), ("B", "3FN", "B"), ("C", "2FN", "B"))

    async def seed():
        async with engine.begin() as conn:
            for model in (QuizModel, QuestionModel, QuizSourceModel, LessonModel,
                          LessonSegmentModel, MaterialModel):
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                LessonModel(id="l1", tutor_id="t1", discipline="BD", title="Normalizacao",
                            summary="A 3FN elimina dependencia transitiva."),
                QuizModel(id="rascunho", tutor_id="t1", lesson_id="l1", titulo="Quiz",
                          status="draft", total_questoes=2),
                QuizSourceModel(quiz_id="rascunho", source_type="lesson",
                                source_id="l1", label="Normalizacao"),
                QuestionModel(id="q1", quiz_id="rascunho", tipo="multipla_escolha",
                              enunciado="Qual elimina dependencia transitiva?",
                              opcoes=opcoes, resposta_correta="B", verificado=False),
                QuestionModel(id="q2", quiz_id="rascunho", tipo="multipla_escolha",
                              enunciado="Qual elimina dependencia parcial?",
                              opcoes=_opcoes(("A", "1FN", "C"), ("B", "3FN", "C"),
                                             ("C", "2FN", "C")),
                              resposta_correta="C", verificado=False),
                QuizModel(id="no-ar", tutor_id="t1", lesson_id="l1", titulo="No ar",
                          status="open", total_questoes=1),
                QuizModel(id="alheio", tutor_id="outro", lesson_id="l1", titulo="Alheio",
                          status="draft", total_questoes=1),
            ])
            await db.commit()

    asyncio.run(seed())

    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(education.router)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: USER
    with TestClient(app) as client:
        client.sessions = sessions
        yield client
    asyncio.run(engine.dispose())


def _resposta_do_agente(*itens):
    return json.dumps({"revisoes": list(itens)})


def _item(question_id, resposta, **extra):
    return {"id": question_id, "resposta": resposta, "ancorada": True,
            "confianca": 0.9, "problemas": [], "sugestao": None, **extra}


@pytest.mark.integration
def test_prompt_da_api_leva_a_aula_e_nao_leva_o_gabarito(api):
    resposta = api.get("/education/quiz/rascunho/review/prompt")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert "A 3FN elimina dependencia transitiva." in corpo["prompt"]
    assert corpo["question_ids"] == ["q1", "q2"]
    assert '"correta"' not in corpo["prompt"]
    assert corpo["system_prompt"]


@pytest.mark.integration
def test_revisao_so_vale_para_rascunho_e_do_proprio_professor(api):
    assert api.get("/education/quiz/no-ar/review/prompt").status_code == 409
    assert api.get("/education/quiz/alheio/review/prompt").status_code == 404
    assert api.get("/education/quiz/nao-existe/review/prompt").status_code == 404
    enviada = api.post(
        "/education/quiz/no-ar/review/external",
        json={"agent": "codex_cli", "content": _resposta_do_agente(_item("q1", "B"))},
    )
    assert enviada.status_code == 409


@pytest.mark.integration
def test_agente_que_concorda_marca_a_pergunta_como_verificada(api):
    resposta = api.post(
        "/education/quiz/rascunho/review/external",
        json={
            "agent": "codex_cli",
            "content": _resposta_do_agente(_item("q1", "B"), _item("q2", "C")),
        },
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["reviewed"] == 2
    assert corpo["review_summary"] == {"aprovada": 2}
    assert all(q["verificado"] for q in corpo["questoes"])
    assert corpo["questoes"][0]["revisao"]["status"] == "aprovada"
    assert "codex_cli" in corpo["questoes"][0]["revisao"]["agentes"]


@pytest.mark.integration
def test_divergencia_desliga_verificado_mas_nao_troca_o_gabarito(api):
    api.post(
        "/education/quiz/rascunho/review/external",
        json={"agent": "codex_cli",
              "content": _resposta_do_agente(_item("q1", "B"), _item("q2", "C"))},
    )

    resposta = api.post(
        "/education/quiz/rascunho/review/external",
        json={"agent": "claude_cli",
              "content": _resposta_do_agente(_item("q1", "A"), _item("q2", "C"))},
    )

    corpo = resposta.json()
    primeira, segunda = corpo["questoes"]
    assert primeira["revisao"]["status"] == "divergente"
    assert primeira["verificado"] is False
    assert set(primeira["revisao"]["agentes"]) == {"codex_cli", "claude_cli"}
    assert primeira["resposta_correta"] == "B", "o servidor nunca troca o gabarito sozinho"
    assert [o["correta"] for o in primeira["opcoes"]] == [False, True, False]
    assert segunda["revisao"]["status"] == "aprovada"
    assert segunda["verificado"] is True
    assert corpo["review_summary"] == {"divergente": 1, "aprovada": 1}


@pytest.mark.integration
def test_agente_desconhecido_e_resposta_ilegivel_sao_recusados(api):
    desconhecido = api.post(
        "/education/quiz/rascunho/review/external",
        json={"agent": "gpt_cli", "content": _resposta_do_agente(_item("q1", "B"))},
    )
    ilegivel = api.post(
        "/education/quiz/rascunho/review/external",
        json={"agent": "codex_cli", "content": "Não consegui."},
    )

    assert desconhecido.status_code == 400
    assert ilegivel.status_code == 422
    assert "Codex" in ilegivel.json()["detail"]


@pytest.mark.integration
def test_professor_editar_a_pergunta_descarta_a_revisao_que_ficou_velha(api):
    api.post(
        "/education/quiz/rascunho/review/external",
        json={"agent": "codex_cli", "content": _resposta_do_agente(_item("q1", "B"))},
    )

    editada = api.patch(
        "/education/quiz/questions/q1",
        json={"enunciado": "Qual forma normal elimina dependencia transitiva entre atributos?"},
    )
    assert editada.status_code == 200

    detalhe = api.get("/education/quiz/rascunho").json()
    q1 = next(q for q in detalhe["questoes"] if q["id"] == "q1")
    assert q1["revisao"] is None
    assert q1["verificado"] is True, "professor revisou: deixa de ser baixa confianca"
