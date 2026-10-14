"""E-mail com a identidade da INTARQ: cabecalho de marca, corpo legivel e rodape.

Todo e-mail transacional do app passa por aqui (convite, recuperacao de senha, alertas,
confirmacao de mentoria), entao a marca e uniforme sem cada chamador desenhar HTML. Quem
envia continua passando so o texto; a versao HTML e montada a partir dele e o texto segue
indo junto, para leitores que nao exibem HTML.

Cuidados de e-mail, que diferem de uma pagina web: layout em tabelas e CSS inline (muitos
clientes ignoram `<style>`), largura de 600 px, e a marca tambem como **texto** - o Gmail
bloqueia imagens por padrao ("Imagens nao exibidas") e o e-mail nao pode ficar sem
identidade nesse caso. O logo so entra quando ha um endereco publico para ele: imagem de
e-mail e buscada pelo leitor, nao pelo servidor.
"""

from __future__ import annotations

import os
from html import escape
from typing import Optional

from ..core.config import get_settings

NAVY = "#0A1324"
BLUE = "#00D6FF"
BLUE_DARK = "#0A8FB0"
GOLD = "#D4AF37"
SILVER = "#B8C2CC"
INK = "#1F2937"
MUTED = "#6B7280"
PAGE = "#EEF2F7"

#: Caminho publico do logo, servido por `routers/brand.py`.
LOGO_PATH = "/brand/intarq-icon.png"

TAGLINE = "AI · SOFTWARE · CLOUD · ARCHITECTURE"
FOOTER = "Esta é uma mensagem automática da INTARQ. Não responda a este e-mail."


def brand_base_url() -> str:
    """Endereco publico do servidor, de onde o leitor busca o logo.

    `PUBLIC_BASE_URL` manda; na Railway o dominio publico ja vem em
    `RAILWAY_PUBLIC_DOMAIN`, entao nao precisa configurar nada la. Vazio = sem logo.
    """
    configured = str(getattr(get_settings(), "public_base_url", "") or "").strip()
    if configured:
        return configured.rstrip("/")
    railway = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
    return f"https://{railway}" if railway else ""


def _paragraph(lines: list[str], highlight: Optional[str]) -> str:
    """Um bloco de texto; a linha igual a `highlight` vira a caixa de codigo."""
    parts: list[str] = []
    text: list[str] = []

    def flush() -> None:
        if text:
            parts.append(
                f'<p style="margin:0 0 14px;font-size:15px;line-height:1.6;color:{INK};">'
                + "<br>".join(escape(line) for line in text) + "</p>")
            text.clear()

    for line in lines:
        if highlight and line.strip() == highlight:
            flush()
            parts.append(
                f'<div style="margin:2px 0 18px;padding:14px 16px;background:{NAVY};'
                f'border-radius:8px;border-left:4px solid {BLUE};'
                f'font-family:Consolas,Menlo,monospace;font-size:16px;letter-spacing:1px;'
                f'color:{BLUE};word-break:break-all;">{escape(line.strip())}</div>')
        else:
            text.append(line)
    flush()
    return "".join(parts)


def render_html(
    subject: str,
    text: str,
    *,
    highlight: Optional[str] = None,
    base_url: Optional[str] = None,
) -> str:
    """HTML da marca para `text`, que vira o corpo (paragrafos separados por linha vazia)."""
    base = brand_base_url() if base_url is None else base_url.rstrip("/")
    blocks = [b for b in text.replace("\r\n", "\n").split("\n\n") if b.strip()]
    body = "".join(_paragraph(block.strip("\n").split("\n"), highlight) for block in blocks)
    preheader = escape(" ".join(blocks[0].split())[:140]) if blocks else ""
    logo = (
        f'<td width="64" style="padding-right:14px;vertical-align:middle;">'
        f'<img src="{escape(base + LOGO_PATH)}" width="52" alt="" '
        f'style="display:block;border:0;"></td>' if base else "")
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>{escape(subject)}</title></head>
<body style="margin:0;padding:0;background:{PAGE};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{PAGE};">{preheader}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
 style="background:{PAGE};"><tr><td align="center" style="padding:28px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
 style="width:100%;max-width:600px;background:#FFFFFF;border-radius:12px;overflow:hidden;
 font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<tr><td style="background:{NAVY};padding:22px 28px;border-bottom:3px solid {GOLD};">
<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>{logo}
<td style="vertical-align:middle;">
<div style="font-size:26px;font-weight:800;letter-spacing:5px;color:#FFFFFF;
 line-height:1;">INTAR<span style="color:{BLUE};">Q</span></div>
<div style="margin-top:6px;font-size:10px;letter-spacing:2px;color:{SILVER};">{TAGLINE}</div>
</td></tr></table></td></tr>
<tr><td style="padding:30px 28px 10px;">
<h1 style="margin:0 0 18px;font-size:21px;line-height:1.3;color:{NAVY};">{escape(subject)}</h1>
{body}
</td></tr>
<tr><td style="padding:18px 28px 24px;border-top:1px solid #E5E7EB;">
<p style="margin:0;font-size:12px;line-height:1.5;color:{MUTED};">{escape(FOOTER)}</p>
<p style="margin:6px 0 0;font-size:12px;font-weight:700;letter-spacing:2px;color:{BLUE_DARK};">
INTARQ</p></td></tr>
</table></td></tr></table></body></html>"""
