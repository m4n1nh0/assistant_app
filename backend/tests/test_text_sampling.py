"""Recorte de material longo: cobre o documento inteiro, nao so o comeco.

O PDF importado tem 43 paginas e 78 mil caracteres. O recorte para o quiz pegava so
o comeco ate o teto, entao o fim do material nunca virava pergunta - e quanto menor
o espaco (fonte dividida entre aulas, ou encolhida para um provedor menor), menos
paginas sobravam.
"""

from __future__ import annotations

import pytest

from app.services import material_service as ms
from app.services import quiz_generator_service as service
from app.services.text_sampling import OMISSION, sample_evenly


def _livro(paragrafos: int = 200) -> str:
    """Documento com uma marca unica em cada paragrafo, para saber o que entrou."""
    return "\n\n".join(
        f"[P{n:03d}] " + ("Conteudo do paragrafo sobre modelagem de dados. " * 8).strip()
        for n in range(1, paragrafos + 1)
    )


def _marcas(texto: str) -> list[int]:
    import re
    return [int(m) for m in re.findall(r"\[P(\d{3})\]", texto)]


@pytest.mark.unit
def test_texto_que_cabe_volta_inteiro():
    texto = _livro(5)

    assert sample_evenly(texto, len(texto)) == texto
    assert sample_evenly(texto, len(texto) + 1000) == texto
    assert sample_evenly("", 100) == ""


@pytest.mark.unit
def test_o_recorte_respeita_o_limite_com_a_omissao_contada():
    texto = _livro()

    for limite in (1_200, 6_000, 24_000, 60_000):
        recorte = sample_evenly(texto, limite)
        assert len(recorte) <= limite, limite


@pytest.mark.unit
def test_cobre_o_comeco_o_meio_e_o_fim_do_documento():
    """O defeito: so o comeco entrava, e o fim do PDF nunca virava pergunta."""
    texto = _livro(300)

    marcas = _marcas(sample_evenly(texto, 24_000))

    assert marcas[0] <= 3, "o comeco entra"
    assert marcas[-1] >= 297, "o fim entra"
    assert any(130 <= m <= 170 for m in marcas), "o meio entra"
    # O comeco sozinho, como antes, nao passaria dos primeiros paragrafos.
    assert max(_marcas(texto[:24_000])) < 100


@pytest.mark.unit
def test_trechos_vem_de_pontos_espacados_e_em_ordem():
    marcas = _marcas(sample_evenly(_livro(300), 24_000))

    assert marcas == sorted(marcas)
    # Mais de um ponto do documento, nao um bloco colado.
    saltos = [b - a for a, b in zip(marcas, marcas[1:]) if b - a > 1]
    assert len(saltos) >= 3


@pytest.mark.unit
def test_trechos_sao_separados_por_marca_de_omissao():
    recorte = sample_evenly(_livro(300), 24_000)

    assert OMISSION.strip() in recorte
    assert recorte.count(OMISSION) >= 2


@pytest.mark.unit
def test_trecho_nao_termina_no_meio_de_uma_palavra():
    recorte = sample_evenly(_livro(300), 12_000)

    for trecho in recorte.split(OMISSION):
        assert trecho == trecho.strip()
        # Termina em fim de frase ou de paragrafo, nao em "…do paragr".
        assert trecho.endswith((".", "dados")), trecho[-30:]


@pytest.mark.unit
def test_limite_minusculo_cai_no_comeco_em_vez_de_virar_migalha():
    texto = _livro(50)

    recorte = sample_evenly(texto, 300)

    assert len(recorte) <= 300
    assert recorte.startswith("[P001]")
    assert OMISSION not in recorte


@pytest.mark.unit
def test_mais_espaco_mais_trechos_com_teto():
    texto = _livro(600)

    pequeno = sample_evenly(texto, 8_000).count(OMISSION)
    grande = sample_evenly(texto, 60_000).count(OMISSION)

    assert 2 <= pequeno <= grande <= 9


# --- onde o recorte entra ----------------------------------------------------------------


@pytest.mark.unit
def test_recorte_do_material_para_o_quiz_cobre_o_documento_inteiro():
    texto = _livro(300)

    recorte = ms.summary_for_quiz(texto, limit=24_000)

    assert len(recorte) <= 24_000
    assert _marcas(recorte)[-1] >= 297


@pytest.mark.unit
def test_fonte_com_material_e_aula_encolhe_o_material_amostrando_e_a_aula_pelo_fim():
    material = "=== MATERIAL DA DISCIPLINA: 00001 ===\n" + _livro(300)
    aula = (
        "=== AULA: Modelagem ===\nRESUMO VALIDADO DA AULA:\nResumo importante da aula.\n\n"
        "TRANSCRIÇÃO DA AULA:\n" + ("fala longa da aula. " * 2000)
    )

    curta = service._shrink_source(material + "\n\n" + aula, 12_000)

    marcas = _marcas(curta)
    assert marcas and marcas[-1] >= 290, "o fim do PDF entrou"
    assert "Resumo importante da aula." in curta, "o resumo da aula continua la"
    assert "=== AULA: Modelagem ===" in curta and "=== MATERIAL DA DISCIPLINA: 00001 ===" in curta
    assert len(curta) < 13_000


@pytest.mark.unit
def test_material_sozinho_encolhido_para_um_provedor_menor_tambem_cobre_o_documento():
    fonte = "=== MATERIAL DA DISCIPLINA: 00001 ===\n" + _livro(300)

    curta = service._shrink_source(fonte, 9_000)

    assert len(curta) <= 9_600
    assert _marcas(curta)[-1] >= 290


# --- o caminho completo: PDF importado -> contexto da geracao ------------------------------


@pytest.mark.integration
def test_pdf_grande_entra_como_fonte_do_quiz_cobrindo_o_documento_inteiro():
    """O caso real: 43 paginas, cerca de 78 mil caracteres, material como unica fonte."""
    import asyncio
    import tempfile

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.database import LessonModel, MaterialModel
    from app.models.schemas import QuizCreateRequest
    from app.routers import education

    pdf = _livro(450)
    assert len(pdf) > 70_000

    async def montar():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/m.db")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            for model in (MaterialModel, LessonModel):
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add(MaterialModel(
                id="pdf", tutor_id="t1", title="00001", filename="00001.pdf",
                source_type="pdf", discipline="ARA0040 - BANCO DE DADOS",
                content=pdf, page_count=43, char_count=len(pdf), truncated=False,
            ))
            await db.commit()
            contexto = await education._quiz_generation_context(
                QuizCreateRequest(material_ids=["pdf"], quantidade_questoes=20), "t1", db
            )
        await engine.dispose()
        return contexto

    contexto = asyncio.run(montar())

    resumo = contexto["resumo"]
    assert "=== MATERIAL DA DISCIPLINA: 00001 ===" in resumo
    assert len(resumo) <= education.QUIZ_CONTEXT_CHAR_BUDGET + 200
    marcas = _marcas(resumo)
    assert marcas[0] <= 3 and marcas[-1] >= 445, "do comeco ao fim do PDF"
    assert contexto["fontes"] == [{"type": "material", "id": "pdf", "label": "00001"}]
    assert contexto["disciplina"] == "ARA0040 - BANCO DE DADOS"
