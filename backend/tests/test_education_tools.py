"""Ferramentas de leitura do Modo Educacao.

Elas existem por causa de uma conversa real: perguntado "pode acessar as
questoes do banco de dados?", o assistente respondeu que nao tinha acesso e
pediu que o usuario colasse as questoes -- estando elas no banco, a uma consulta
de distancia.

O que estes testes guardam:

- a ferramenta le mesmo, e devolve o texto que o modelo usa junto com a leitura
  estruturada que a interface desenha;
- a leitura e sempre do dono da conversa. O `tutor_id` vem da identidade da
  requisicao, nunca dos argumentos, entao nenhum pedido escrito na conversa
  alcanca dado de outro tutor.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import database
from app.core.database import (
    DisciplineModel,
    LessonModel,
    LessonPointModel,
    QuestionModel,
    QuizModel,
    StudentAnswerModel,
    StudentModel,
    StudyTimeModel,
)
from app.services import education_tools
from shared.ports.tools import ToolError, ToolPrincipal
from shared.toolkit.principal import use_principal

pytestmark = pytest.mark.integration

DONO = "tutor-dono"
OUTRO = "tutor-outro"
BASE = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
OPCOES = '[{"label": "A", "texto": "3FN", "correta": true}]'


@pytest.fixture
def banco(monkeypatch):
    """Um banco com dados de dois tutores, para o isolamento ficar testavel."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/edu.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in (
                DisciplineModel,
                LessonModel,
                LessonPointModel,
                QuizModel,
                QuestionModel,
                StudentModel,
                StudentAnswerModel,
                StudyTimeModel,
            ):
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add_all([
                DisciplineModel(id="d1", tutor_id=DONO, code="ARA0040",
                                name="BANCO DE DADOS", semester="2026.2"),
                LessonModel(id="a1", tutor_id=DONO, discipline="BANCO DE DADOS",
                            title="Modelagem Conceitual", class_group="3001",
                            started_at=BASE, status="closed", segment_count=12,
                            summary="A aula tratou de entidades e relacionamentos."),
                QuizModel(id="q1", tutor_id=DONO, lesson_id="a1",
                          titulo="Quiz de Modelagem", status="open",
                          total_questoes=2, created_at=BASE),
                QuestionModel(id="p1", quiz_id="q1", tipo="multipla_escolha",
                              dificuldade="medio", enunciado="O que e uma entidade?",
                              opcoes=OPCOES, resposta_correta="A",
                              justificativa="Definicao vista em aula.",
                              created_at=BASE),
                QuestionModel(id="p2", quiz_id="q1", tipo="multipla_escolha",
                              dificuldade="dificil",
                              enunciado="Quando aplicar a terceira forma normal?",
                              opcoes=OPCOES, resposta_correta="A",
                              justificativa="Normalizacao.",
                              created_at=BASE + timedelta(seconds=1)),
                # Copia feita para montar outro quiz: nao e questao nova do banco.
                QuestionModel(id="p3", quiz_id="q1", tipo="multipla_escolha",
                              dificuldade="medio", enunciado="O que e uma entidade?",
                              opcoes=OPCOES, resposta_correta="A",
                              justificativa="Copia.", origem_id="p1",
                              created_at=BASE + timedelta(seconds=2)),
                StudentAnswerModel(id="r1", question_id="p1", student_id="s1",
                                   student_name="Ana", resposta="A", correta=True,
                                   pontuacao=900, respondido_em=BASE),
                StudentAnswerModel(id="r2", question_id="p1", student_id="s2",
                                   student_name="Bruno", resposta="B", correta=False,
                                   pontuacao=0, respondido_em=BASE),

                # A mesma turma importada em dois periodos: somados, o total
                # diria que ela estudou o dobro de qualquer um dos dois.
                StudyTimeModel(id="t1", tutor_id=DONO, enrollment="111",
                               discipline_code="ARA0040", group_sequence="15052214",
                               course="ADS", semester="2026.2", minutes=600),
                StudyTimeModel(id="t2", tutor_id=DONO, enrollment="111",
                               discipline_code="ARA0040", group_sequence="15052214",
                               course="ADS", semester="2026.3", minutes=120),

                # O outro tutor tem a propria disciplina e o proprio quiz.
                DisciplineModel(id="d9", tutor_id=OUTRO, code="ARA9999",
                                name="ALGORITMOS", semester="2026.2"),
                LessonModel(id="a9", tutor_id=OUTRO, discipline="ALGORITMOS",
                            title="Recursao", started_at=BASE, status="closed"),
                QuizModel(id="q9", tutor_id=OUTRO, lesson_id="a9",
                          titulo="Quiz alheio", status="open", total_questoes=1,
                          created_at=BASE),
                QuestionModel(id="p9", quiz_id="q9", tipo="multipla_escolha",
                              dificuldade="facil", enunciado="Segredo do outro tutor",
                              opcoes=OPCOES, resposta_correta="A",
                              justificativa="-", created_at=BASE),
            ])
            await db.commit()

    asyncio.run(seed())
    monkeypatch.setattr(database, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(education_tools, "AsyncSessionLocal", sessions)
    yield sessions
    asyncio.run(engine.dispose())


def ler(ferramenta, tutor=DONO, **args):
    """Roda uma ferramenta como o executor roda: com a identidade publicada."""

    async def run():
        with use_principal(ToolPrincipal(tutor_id=tutor, user_id="u1")):
            return await ferramenta.ainvoke(args)

    return asyncio.run(run())


def test_banco_de_questoes_responde_com_as_questoes_reais(banco):
    saida = ler(education_tools.education_search_question_bank,
                discipline="banco de dados")

    assert saida["kind"] == "question_bank"
    assert saida["total"] == 2
    enunciados = [item["enunciado"] for item in saida["items"]]
    assert "O que e uma entidade?" in enunciados
    # O texto que vai para o modelo carrega as questoes: e ele que impede a
    # resposta "nao tenho acesso, me mande as questoes".
    assert "entidade" in saida["text"]


def test_copia_de_questao_nao_infla_o_banco(banco):
    saida = ler(education_tools.education_search_question_bank)

    assert [item["id"] for item in saida["items"]] == ["p2", "p1"]


def test_quiz_vem_com_gabarito_e_numeracao_da_aula(banco):
    saida = ler(education_tools.education_get_quiz, quiz_id="q1")

    assert saida["kind"] == "quiz"
    assert [item["numero"] for item in saida["items"]] == [1, 2, 3]
    assert saida["items"][0]["resposta_correta"] == "A"


def test_resultado_do_quiz_ordena_pelo_ranking(banco):
    saida = ler(education_tools.education_get_quiz_results, quiz_id="q1")

    assert [item["aluno"] for item in saida["items"]] == ["Ana", "Bruno"]
    assert saida["items"][0]["posicao"] == 1


def test_aula_traz_resumo_para_o_modelo(banco):
    saida = ler(education_tools.education_get_lesson, lesson_id="a1")

    assert "entidades e relacionamentos" in saida["text"]
    assert "17/09/2026" in saida["title"]


def test_disciplinas_saem_so_do_dono_da_conversa(banco):
    do_dono = ler(education_tools.education_list_disciplines)
    do_outro = ler(education_tools.education_list_disciplines, tutor=OUTRO)

    assert [item["nome"] for item in do_dono["items"]] == ["BANCO DE DADOS"]
    assert [item["nome"] for item in do_outro["items"]] == ["ALGORITMOS"]


def test_questao_de_outro_tutor_nunca_aparece(banco):
    saida = ler(education_tools.education_search_question_bank, search="Segredo")

    assert saida["total"] == 0
    assert saida["items"] == []


def test_quiz_de_outro_tutor_nao_abre_nem_pelo_id(banco):
    """O id do quiz alheio e um argumento, e argumento o modelo escreve."""
    saida = ler(education_tools.education_get_quiz, quiz_id="q9")

    assert saida["items"] == []
    assert "nao encontrado" in saida["text"].lower()


def test_sem_identidade_a_ferramenta_recusa(banco):
    """Chamada fora do chat autenticado nao vira leitura irrestrita."""

    async def run():
        return await education_tools.education_list_disciplines.ainvoke({})

    with pytest.raises(ToolError):
        asyncio.run(run())


def test_filtro_vazio_nao_mente_sobre_estar_vazio(banco):
    saida = ler(education_tools.education_list_lessons, discipline="QUIMICA")

    assert saida["total"] == 0
    assert "nao ha aula" in saida["text"].lower()


def test_tempo_de_estudo_nao_soma_periodos_diferentes(banco):
    """Dois semestres da mesma turma sao duas linhas, nunca um total so.

    Somados, o assistente responderia que a turma estudou 12h quando ela
    estudou 10h num periodo e 2h no outro.
    """
    saida = ler(education_tools.education_study_time_summary)

    periodos = {item["periodo"]: item for item in saida["items"]}
    assert set(periodos) == {"2026.2", "2026.3"}
    assert periodos["2026.2"]["horas"] == 10.0
    assert periodos["2026.3"]["horas"] == 2.0
    assert "2026.2: 10.0h" in saida["text"] and "2026.3: 2.0h" in saida["text"]
    assert "12.0h" not in saida["text"], "o total somado nao pode aparecer"


def test_tempo_de_estudo_aceita_recorte_de_periodo(banco):
    saida = ler(education_tools.education_study_time_summary, semester="2026.3")

    assert [item["periodo"] for item in saida["items"]] == ["2026.3"]
    assert saida["total"] == 1
