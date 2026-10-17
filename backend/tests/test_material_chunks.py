"""Blocos do material: corte por titulo, caminho de titulos e persistencia.

O que isto protege: um bloco nao atravessa capitulo, leva o caminho de titulos, bloco
grande e partido com sobreposicao, bloco minusculo e juntado, e refazer nao duplica.
"""

from __future__ import annotations

import asyncio
import tempfile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import MaterialChunkModel, MaterialModel
from app.services import material_chunk_service as svc

PARAGRAFO = "Um prompt bem escrito reduz retrabalho e descreve o papel, o contexto e o formato. "


def test_corta_por_titulo_e_leva_o_caminho():
    texto = (
        "CAPÍTULO 1\n\n" + PARAGRAFO * 5 + "\n\n"
        "1.1 Elementos de um prompt\n\n" + PARAGRAFO * 5 + "\n\n"
        "CAPÍTULO 2\n\n" + PARAGRAFO * 5
    )
    blocos = svc.split_into_chunks(texto)

    assert [b.heading_path for b in blocos] == [
        "CAPÍTULO 1", "CAPÍTULO 1 > 1.1 Elementos de um prompt", "CAPÍTULO 2"]
    assert [b.sequence for b in blocos] == [0, 1, 2]
    assert all("CAPÍTULO 2" not in b.text for b in blocos[:2])


def test_bloco_grande_e_partido_com_sobreposicao():
    texto = "Tema\n\n" + "\n\n".join(f"Paragrafo {i}. " + PARAGRAFO * 6 for i in range(8))
    blocos = svc.split_into_chunks(texto)

    assert len(blocos) > 1
    assert all(len(b.text) <= svc.MAX_CHARS + svc.OVERLAP + 10 for b in blocos)
    assert {b.heading_path for b in blocos} == {"Tema"}
    # O fim de um bloco reaparece no comeco do seguinte.
    assert blocos[0].text[-60:].split()[-1] in blocos[1].text[: svc.OVERLAP + 80]


def test_secao_minuscula_e_juntada_ao_vizinho_da_mesma_secao():
    texto = "Tema\n\n" + PARAGRAFO * 4 + "\n\nCurto."
    blocos = svc.split_into_chunks(texto)

    assert len(blocos) == 1 and blocos[0].text.endswith("Curto.")


def test_lista_nao_vira_titulo_e_texto_sem_titulo_tem_caminho_vazio():
    blocos = svc.split_into_chunks("- Papel do modelo\n- Contexto\n\n" + PARAGRAFO * 4)

    assert len(blocos) == 1 and blocos[0].heading_path == ""
    assert "Papel do modelo" in blocos[0].text


def test_refazer_os_blocos_nao_duplica():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/c.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def roda():
        async with engine.begin() as conn:
            await conn.run_sync(MaterialModel.__table__.create)
            await conn.run_sync(MaterialChunkModel.__table__.create)
        async with sessions() as db:
            material = MaterialModel(
                id="m1", tutor_id="t1", discipline_id="d1", discipline="BD", title="Apostila",
                filename="a.pdf", content="CAPÍTULO 1\n\n" + PARAGRAFO * 5)
            db.add(material)
            await db.flush()
            primeiro = await svc.replace_chunks(db, material)
            await db.commit()
            segundo = await svc.replace_chunks(db, material)
            await db.commit()
            linhas = (await db.execute(select(MaterialChunkModel))).scalars().all()
            await svc.delete_chunks(db, "m1")
            await db.commit()
            restantes = (await db.execute(select(MaterialChunkModel))).scalars().all()
            return primeiro, segundo, linhas, restantes

    primeiro, segundo, linhas, restantes = asyncio.run(roda())
    assert primeiro == segundo == len(linhas) == 1
    assert linhas[0].discipline_id == "d1" and linhas[0].indexed is False
    assert restantes == []


def test_texto_picado_de_pdf_vira_paragrafos_e_nao_titulos():
    # Extracao que entrega uma palavra por bloco: cada uma virava "titulo".
    palavras = "Amazon\n\nAWS,\n\nalém\n\nde\n\nBig\n\nData\n\ne\n\nAnalytics\n\npara\n\nindústria\n\n4.0."
    texto = "Tema 6\n\n" + (palavras + "\n\n") * 4 + "CAPÍTULO 2\n\nFim do tema."
    blocos = svc.split_into_chunks(texto)

    caminhos = {b.heading_path for b in blocos}
    assert "Amazon" not in caminhos and "além" not in caminhos
    assert any("CAPÍTULO 2" in c for c in caminhos)
    assert any("Amazon AWS, além de Big Data e Analytics para indústria 4.0." in b.text for b in blocos)
