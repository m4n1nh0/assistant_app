"""Perguntas que a nova geracao precisa evitar.

Falha de aula real: uma aula com 63 perguntas em 8 quizzes (um deles um simulado, que
copia perguntas dos outros) so rendia 1 pergunta nova em 20 pedidas. Duas causas:

- o corte de 60 pegava as copias do simulado como perguntas novas, gastando o limite
  com duplicata e deixando de fora as mais antigas;
- o modelo via so as 30 ultimas no prompt, enquanto a checagem de repeticao
  descartava contra as 60: as mais antigas rejeitavam a resposta sem que ele
  soubesse que devia evita-las, e o lote voltava "todas repetiam as ja geradas".
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import QuestionModel, QuizModel, QuizSourceModel
from app.routers import education
from app.services import quiz_generator_service as service

BASE = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
FONTE = [{"type": "lesson", "id": "aula-1", "label": "Modelagem"}]


def _pergunta(quiz_id, numero, *, minutos, origem=None, arquivada=False, texto=None):
    return QuestionModel(
        id=f"{quiz_id}-{numero}-{minutos}",
        quiz_id=quiz_id,
        tipo="multipla_escolha",
        enunciado=texto or f"Pergunta {numero} sobre modelagem?",
        opcoes='[{"label": "A", "texto": "Resposta", "correta": true}]',
        origem_id=origem,
        arquivada=arquivada,
        created_at=BASE + timedelta(minutes=minutos),
    )


def carregar(perguntas, quizzes=("q1",), limite=None):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/q.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def executar():
        async with engine.begin() as conn:
            for model in (QuizModel, QuestionModel, QuizSourceModel):
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            for quiz in quizzes:
                db.add(QuizModel(id=quiz, tutor_id="t1", lesson_id="aula-1",
                                 titulo=quiz, status="closed"))
                db.add(QuizSourceModel(quiz_id=quiz, source_type="lesson",
                                       source_id="aula-1", label="Modelagem"))
            db.add_all(perguntas)
            await db.commit()
            kwargs = {} if limite is None else {"limit": limite}
            return await education._existing_questions_for_sources(db, "t1", FONTE, **kwargs)

    try:
        return asyncio.run(executar())
    finally:
        asyncio.run(engine.dispose())


@pytest.mark.integration
def test_copia_de_simulado_conta_como_a_mesma_pergunta():
    originais = [_pergunta("q1", n, minutos=n) for n in range(1, 6)]
    # O simulado copia as mesmas cinco perguntas, mais tarde.
    copias = [_pergunta("simulado", n, minutos=100 + n, origem=f"q1-{n}-{n}") for n in range(1, 6)]

    existentes = carregar(originais + copias, quizzes=("q1", "simulado"))

    assert len(existentes) == 5, "cinco perguntas distintas, nao dez"
    assert [e["enunciado"] for e in existentes] == [f"Pergunta {n} sobre modelagem?" for n in range(1, 6)]


@pytest.mark.integration
def test_duplicata_nao_gasta_o_limite_e_as_antigas_continuam_na_lista():
    """Antes: 60 linhas, metade copias; as mais antigas ficavam de fora."""
    originais = [_pergunta("q1", n, minutos=n) for n in range(1, 41)]
    copias = [_pergunta("simulado", n, minutos=200 + n) for n in range(1, 41)]

    existentes = carregar(originais + copias, quizzes=("q1", "simulado"), limite=40)

    textos = {e["enunciado"] for e in existentes}
    assert len(existentes) == 40
    assert "Pergunta 1 sobre modelagem?" in textos, "a mais antiga ainda entra"
    assert "Pergunta 40 sobre modelagem?" in textos


@pytest.mark.integration
def test_limite_vale_para_perguntas_distintas_e_fica_com_as_mais_recentes():
    perguntas = [_pergunta("q1", n, minutos=n) for n in range(1, 151)]

    existentes = carregar(perguntas)

    assert len(existentes) == 120
    assert existentes[-1]["enunciado"] == "Pergunta 150 sobre modelagem?"
    assert existentes[0]["enunciado"] == "Pergunta 31 sobre modelagem?"


@pytest.mark.integration
def test_arquivada_continua_fora_e_maiuscula_ou_espaco_nao_separam_a_mesma_pergunta():
    perguntas = [
        _pergunta("q1", 1, minutos=1),
        _pergunta("q1", 2, minutos=2, arquivada=True),
        _pergunta("q1", 3, minutos=3, texto="Qual  é a  PERGUNTA tres?"),
        _pergunta("q1", 4, minutos=4, texto="qual é a pergunta tres?"),
    ]

    existentes = carregar(perguntas)

    assert [e["enunciado"] for e in existentes] == [
        "Pergunta 1 sobre modelagem?", "qual é a pergunta tres?",
    ]


# --- o que o modelo enxerga ---------------------------------------------------------


def _anteriores(n):
    return [
        {
            "enunciado": f"Pergunta antiga numero {i} sobre modelagem conceitual?",
            "opcoes": [{"label": "A", "texto": f"Resposta {i}", "correta": True}],
            "conceitos": [f"conceito {i}"],
        }
        for i in range(1, n + 1)
    ]


@pytest.mark.unit
def test_o_modelo_ve_todas_as_perguntas_que_a_checagem_vai_descartar():
    bloco = service._avoid_block(_anteriores(70))

    for i in (1, 35, 70):
        assert f"Pergunta antiga numero {i} sobre" in bloco


@pytest.mark.unit
def test_o_prompt_enxerga_tanto_quanto_a_checagem_de_repeticao():
    """Antes: 30 no prompt contra 60 na checagem."""
    assert service.MAX_AVOID_QUESTIONS >= 60
    assert service.MAX_AVOID_QUESTIONS >= 120 - 40, "cobre o que a carga das existentes pode trazer"


@pytest.mark.unit
def test_so_as_mais_recentes_levam_a_resposta_as_antigas_entram_compactas():
    bloco = service._avoid_block(_anteriores(60))
    linhas = [l for l in bloco.splitlines() if l.startswith("- ")]

    com_resposta = [l for l in linhas if "(resposta:" in l]
    assert len(linhas) == 60
    assert len(com_resposta) == service.AVOID_WITH_ANSWER
    # As com resposta sao as ultimas da lista.
    assert all("(resposta:" in l for l in linhas[-service.AVOID_WITH_ANSWER:])
    assert not any("(resposta:" in l for l in linhas[: -service.AVOID_WITH_ANSWER])


@pytest.mark.unit
def test_lista_muito_longa_corta_pelas_mais_antigas_e_mantem_as_recentes():
    bloco = service._avoid_block(_anteriores(150))
    linhas = [l for l in bloco.splitlines() if l.startswith("- ")]

    assert len(linhas) == service.MAX_AVOID_QUESTIONS
    assert "numero 150 sobre" in bloco
    assert "numero 1 sobre" not in bloco


@pytest.mark.unit
def test_pergunta_antiga_compacta_e_cortada_mais_curta_que_a_recente():
    longa = "Enunciado muito longo sobre modelagem conceitual " * 8
    anteriores = [
        {"enunciado": longa, "opcoes": [{"label": "A", "texto": "x", "correta": True}], "conceitos": []}
        for _ in range(40)
    ]

    linhas = [l for l in service._avoid_block(anteriores).splitlines() if l.startswith("- ")]

    antiga, recente = linhas[0], linhas[-1]
    assert len(antiga) < len(recente)
