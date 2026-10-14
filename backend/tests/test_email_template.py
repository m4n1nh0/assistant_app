"""E-mails com a identidade da INTARQ.

Protege duas coisas: o HTML nunca pode deixar texto de usuario (nome, titulo de mentoria)
virar marcacao, e a marca precisa aparecer mesmo quando o cliente bloqueia imagens.
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import brand
from app.services import email_template as tpl


def test_marca_aparece_como_texto_mesmo_sem_logo():
    html = tpl.render_html("Inscrição recebida", "Olá!", base_url="")

    assert "INTAR" in html and ">Q</span>" in html
    assert "AI · SOFTWARE · CLOUD · ARCHITECTURE" in html
    assert "<img" not in html  # sem endereco publico nao ha onde buscar a imagem


def test_logo_entra_quando_ha_endereco_publico():
    html = tpl.render_html("x", "Olá!", base_url="https://app.exemplo.com/")

    assert 'src="https://app.exemplo.com/brand/intarq-icon.png"' in html


def test_texto_de_usuario_nao_vira_marcacao():
    html = tpl.render_html(
        "Mentoria <script>alert(1)</script>",
        'Olá, <img src=x onerror=alert(1)>!\n\nSegundo "bloco" & mais',
        base_url="")

    assert "<script>" not in html and "<img src=x" not in html
    assert "&lt;script&gt;" in html and "&lt;img src=x" in html
    assert "&amp; mais" in html


def test_token_ganha_caixa_de_destaque_sem_repetir_no_texto_corrido():
    texto = "Voce recebeu um convite.\n\nToken de uso unico:\nabc-123_XYZ\n\nValido ate hoje."

    html = tpl.render_html("Convite", texto, highlight="abc-123_XYZ", base_url="")

    assert html.count("abc-123_XYZ") == 1
    assert "Consolas" in html and "Token de uso unico:" in html


def test_paragrafos_e_quebras_de_linha_sao_preservados():
    html = tpl.render_html("x", "linha 1\nlinha 2\n\nsegundo", base_url="")

    assert "linha 1<br>linha 2" in html and html.count("<p ") >= 3  # 2 blocos + rodape


def test_url_publica_vem_da_config_ou_da_railway(monkeypatch):
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)
    monkeypatch.setattr(tpl, "get_settings", lambda: type("S", (), {"public_base_url": ""})())
    assert tpl.brand_base_url() == ""

    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "app.up.railway.app")
    assert tpl.brand_base_url() == "https://app.up.railway.app"

    monkeypatch.setattr(
        tpl, "get_settings",
        lambda: type("S", (), {"public_base_url": "https://meu.dominio.com/"})())
    assert tpl.brand_base_url() == "https://meu.dominio.com"


def test_rota_publica_serve_o_logo_com_cache():
    app = FastAPI()
    app.include_router(brand.router)

    resposta = TestClient(app).get("/brand/intarq-icon.png")

    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == "image/png"
    assert "max-age" in resposta.headers["cache-control"]
    assert resposta.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_envio_manda_texto_e_html_com_a_marca(monkeypatch):
    import app.services.registration_invite_service as invite

    enviado = {}

    class FakeClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def post(self, url, headers, json):
            enviado.update(json)

            class Resposta:
                def raise_for_status(self): ...
            return Resposta()

    monkeypatch.setattr(invite.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(invite.settings, "smtp_from", "no-reply@exemplo.com", raising=False)
    monkeypatch.setattr(invite.settings, "brevo_api_key", "k", raising=False)

    asyncio.run(invite.send_transactional_email(
        "a@b.com", subject="Convite", text_content="Token:\nSEGREDO", highlight="SEGREDO"))

    assert enviado["textContent"] == "Token:\nSEGREDO"
    assert "INTAR" in enviado["htmlContent"] and "SEGREDO" in enviado["htmlContent"]
