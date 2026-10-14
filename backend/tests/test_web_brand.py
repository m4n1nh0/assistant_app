"""Identidade da INTARQ nas paginas web do backend.

Protege tres coisas: toda pagina HTML sai com a barra de marca (mesmo as que nao foram
escritas para ela), a marca nunca e duplicada, e o que nao e HTML passa intacto.
"""

from __future__ import annotations

import gzip

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.testclient import TestClient
from starlette.middleware.gzip import GZipMiddleware

from app.routers import brand, mentorship, mentorship_delivery
from app.services import web_brand as wb

PAGINA = ("<!doctype html><html><head><meta charset='utf-8'><title>Reunião</title></head>"
          "<body class='x'><main>conteúdo</main></body></html>")


def test_inject_poe_barra_icone_e_titulo():
    html = wb.inject(PAGINA)

    assert html.count("iq-bar") >= 1 and "AI · SOFTWARE" in html
    assert 'rel="icon"' in html and "/brand/intarq-icon.png" in html
    assert "<title>Reunião · INTARQ</title>" in html
    assert html.index('class="iq-bar"') > html.index("<body class='x'>")  # logo apos o body
    assert "padding-top:52px" in html


def test_inject_nao_duplica_a_marca_nem_o_sufixo_do_titulo():
    uma_vez = wb.inject(PAGINA)

    assert wb.inject(uma_vez) == uma_vez
    ja_com_marca = PAGINA.replace("Reunião", "INTARQ Quiz Player")
    assert "INTARQ Quiz Player · INTARQ" not in wb.inject(ja_com_marca)


def test_inject_ignora_o_que_nao_e_pagina():
    assert wb.inject("<p>fragmento sem body</p>") == "<p>fragmento sem body</p>"


def test_inject_funciona_sem_head():
    html = wb.inject("<html><body><p>oi</p></body></html>")

    assert "<head>" in html and "iq-bar" in html


def _app() -> FastAPI:
    app = FastAPI()
    # Mesma ordem do main.py: a marca dentro do GZip.
    app.add_middleware(wb.BrandHtmlMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=100)

    @app.get("/pagina", response_class=HTMLResponse)
    async def pagina():
        return PAGINA * 3

    @app.get("/api")
    async def api():
        return JSONResponse({"ok": True, "texto": "x" * 500})

    @app.get("/docs-falso/pagina", response_class=HTMLResponse)
    async def docs_falso():
        return PAGINA

    @app.get("/texto")
    async def texto():
        return Response("<body>nao e html</body>", media_type="text/plain")

    app.include_router(brand.router)
    return app


def test_middleware_marca_html_e_deixa_json_e_texto_intactos():
    client = TestClient(_app())

    pagina = client.get("/pagina")
    assert "iq-bar" in pagina.text and pagina.headers["content-type"].startswith("text/html")
    assert int(pagina.headers.get("content-length", len(pagina.content))) >= len(PAGINA)

    assert client.get("/api").json()["ok"] is True
    assert "iq-bar" not in client.get("/api").text
    assert client.get("/texto").text == "<body>nao e html</body>"


def test_content_length_acompanha_o_corpo_novo():
    client = TestClient(_app())

    resposta = client.get("/pagina", headers={"Accept-Encoding": "identity"})

    assert int(resposta.headers["content-length"]) == len(resposta.content)


def test_marca_fica_dentro_do_gzip():
    client = TestClient(_app())

    bruto = client.get("/pagina", headers={"Accept-Encoding": "gzip"})

    # O cliente descomprime sozinho; o que importa e a marca estar no HTML final.
    assert bruto.headers.get("content-encoding") == "gzip"
    assert "iq-bar" in bruto.text
    assert gzip.compress(b"x")  # sanity: o modulo gzip esta ai


def test_documentacao_da_api_nao_ganha_a_barra():
    app = _app()
    client = TestClient(app)

    @app.get("/docs/extra", response_class=HTMLResponse)
    async def extra():
        return PAGINA

    assert "iq-bar" not in client.get("/docs/extra").text


def test_favicon_e_icone_sao_servidos():
    client = TestClient(_app())

    for caminho in ("/favicon.ico", "/brand/intarq-icon.png"):
        resposta = client.get(caminho)
        assert resposta.status_code == 200 and resposta.content[:4] == b"\x89PNG"


def test_casco_das_paginas_de_formulario_tem_a_marca_uma_vez_so():
    resposta = wb.page("Inscrição", "<h1>Oi</h1>")

    html = resposta.body.decode()
    assert html.count('class="iq-bar"') == 1
    assert "Inscrição · INTARQ" in html and "<h1>Oi</h1>" in html
    # Passando pelo middleware a barra nao dobra.
    assert wb.inject(html) == html


def test_paginas_de_mentoria_usam_o_casco_da_marca():
    # A pagina "fechada" de cada rota tambem tem de ter a marca, uma vez so.
    for pagina in (mentorship._closed_page("Encerrado."),
                   mentorship_delivery._closed_page("Encerrado.")):
        html = pagina.body.decode()
        assert html.count('class="iq-bar"') == 1 and "INTAR" in html
