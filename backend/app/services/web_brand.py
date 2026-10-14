"""Identidade da INTARQ nas páginas web servidas pelo backend.

Duas camadas, para a marca ficar igual em tudo sem reescrever cada página:

1. `page()` é o casco das páginas de formulário (envio de material, inscrição e entrega
   da mentoria): barra de marca, fundo, cartão, botões e rodapé no padrão INTARQ.
2. `BrandHtmlMiddleware` injeta a barra de marca, o ícone da aba e o título em **qualquer**
   outra página HTML (quiz, chamada por QR Code, reunião, retornos de login), sem mexer
   no layout e nas cores de cada uma. Páginas que já trazem a barra não são tocadas.

As cores e o nome vêm da mesma paleta do app e do e-mail (`email_template`).
"""

from __future__ import annotations

import re
from html import escape

from fastapi.responses import HTMLResponse

NAVY = "#0A1324"
NAVY_2 = "#0F2A52"
BLUE = "#00D6FF"
BLUE_DARK = "#0A8FB0"
GOLD = "#D4AF37"
SILVER = "#B8C2CC"

ICON = "/brand/intarq-icon.png"
BAR_HEIGHT = 52
BAR_MARK = "iq-bar"

#: Caminhos que não são páginas da marca (documentação da API).
SKIP_PREFIXES = ("/docs", "/redoc", "/openapi")

_HEAD = (
    f'<link rel="icon" type="image/png" href="{ICON}">'
    f'<meta name="theme-color" content="{NAVY}">'
)


def bar_html(*, fixed: bool = False) -> str:
    """Barra de marca. Estilo inline: nenhuma regra da página consegue desfazê-la."""
    position = "position:fixed;top:0;left:0;right:0;" if fixed else ""
    return (
        f'<header class="{BAR_MARK}" style="{position}z-index:2147483000;'
        f"box-sizing:border-box;height:{BAR_HEIGHT}px;display:flex;align-items:center;"
        f"gap:12px;padding:0 20px;background:{NAVY};border-bottom:3px solid {GOLD};"
        f'font-family:system-ui,-apple-system,Segoe UI,sans-serif;">'
        f'<img src="{ICON}" alt="" width="30" height="32" '
        f'style="display:block;width:auto;height:32px;border:0;">'
        f'<span style="font-size:20px;font-weight:800;letter-spacing:4px;color:#fff;'
        f'line-height:1;">INTAR<span style="color:{BLUE};">Q</span></span>'
        f'<span style="font-size:9px;letter-spacing:2px;color:{SILVER};'
        f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
        f"AI · SOFTWARE · CLOUD · ARCHITECTURE</span></header>"
    )


_BASE_CSS = f"""
*{{box-sizing:border-box}}
body{{margin:0;color:#111827;font:16px system-ui,-apple-system,Segoe UI,sans-serif;
min-height:100vh;display:flex;flex-direction:column;
background:linear-gradient(135deg,{NAVY} 0%,{NAVY_2} 60%,#0A3A5C 100%);}}
.iq-wrap{{flex:1;display:flex;justify-content:center;align-items:flex-start;padding:28px 20px}}
main{{width:min(560px,100%);background:#fff;border-radius:14px;padding:30px;
border-top:4px solid {BLUE};box-shadow:0 18px 45px #00000055}}
.iq-foot{{padding:14px 20px 22px;text-align:center;font-size:11px;letter-spacing:2px;
color:{SILVER}}}
.brand{{font-size:12px;font-weight:900;letter-spacing:2px;color:{BLUE_DARK}}}
h1{{font-size:24px;margin:10px 0 4px;color:{NAVY}}}
p{{margin:6px 0;color:#4b5563;font-size:14px}}
label,legend{{display:block;margin:16px 0 6px;font-size:13px;font-weight:700;color:#374151}}
input[type=text],input[type=email],input[type=tel],input[type=number],input[type=file],
select,textarea{{width:100%;padding:12px 14px;border:2px solid #d1d5db;border-radius:10px;
font:inherit;background:#fff}}
input:focus,select:focus,textarea:focus{{border-color:{BLUE_DARK};outline:none}}
button{{width:100%;margin-top:16px;padding:14px;border:0;border-radius:10px;
background:{NAVY};color:{BLUE};font-weight:900;letter-spacing:.8px;cursor:pointer}}
button:hover:not(:disabled){{background:{NAVY_2}}}
button:disabled{{opacity:.55;cursor:default}}
button.link{{width:auto;margin:0;padding:4px 8px;background:none;color:#b91c1c;
font-weight:700;letter-spacing:0}}
input:focus-visible,button:focus-visible,select:focus-visible,textarea:focus-visible{{
outline:3px solid {BLUE_DARK};outline-offset:2px}}
.msg{{margin:14px 0 0;padding:10px 12px;border-radius:8px;font-size:14px;font-weight:600}}
.err{{background:#fef2f2;color:#b91c1c}}
.ok{{background:#ecfdf5;color:#047857}}
.req{{color:#b91c1c}}
[hidden]{{display:none!important}}
"""


def page(title: str, body: str, script: str = "", extra_css: str = "") -> HTMLResponse:
    """Página pública no padrão INTARQ: barra de marca, cartão e rodapé."""
    return HTMLResponse(
        f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">{_HEAD}
<title>{escape(title)} · INTARQ</title>
<style>{_BASE_CSS}{extra_css}</style></head><body>{bar_html()}
<div class="iq-wrap"><main>{body}</main></div>
<div class="iq-foot">INTARQ</div>{script}</body></html>"""
    )


# --- injeção nas demais páginas ---------------------------------------------------------

_BODY_OPEN = re.compile(r"<body\b[^>]*>", re.IGNORECASE)
_TITLE = re.compile(r"(<title[^>]*>)(.*?)(</title>)", re.IGNORECASE | re.DOTALL)


def inject(html: str) -> str:
    """Põe barra, ícone e título da marca em uma página que não tem."""
    if BAR_MARK in html or "<body" not in html.lower():
        return html
    # A barra fica fixa no topo, então o corpo ganha a altura dela em espaço.
    style = (f"<style>body{{padding-top:{BAR_HEIGHT}px!important;}}"
             f"@media print{{.{BAR_MARK}{{display:none!important}}"
             f"body{{padding-top:0!important}}}}</style>")
    head = _HEAD + style
    if re.search(r"</head>", html, re.IGNORECASE):
        html = re.sub(r"</head>", lambda _m: head + "</head>", html, count=1,
                      flags=re.IGNORECASE)
    else:
        html = _BODY_OPEN.sub(lambda m: "<head>" + head + "</head>" + m.group(0), html, count=1)
    html = _BODY_OPEN.sub(lambda m: m.group(0) + bar_html(fixed=True), html, count=1)

    def retitle(m: re.Match) -> str:
        text = m.group(2).strip()
        return m.group(0) if "INTARQ" in text.upper() else f"{m.group(1)}{text} · INTARQ{m.group(3)}"

    return _TITLE.sub(retitle, html, count=1)


class BrandHtmlMiddleware:
    """ASGI puro: segura só respostas HTML, injeta a marca e repassa o resto direto.

    Precisa ficar **dentro** do GZip (registrado antes dele), senão receberia o corpo já
    comprimido.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or path.startswith(SKIP_PREFIXES):
            await self.app(scope, receive, send)
            return

        held: dict | None = None
        chunks: list[bytes] = []

        async def wrapped(message):
            nonlocal held
            if message["type"] == "http.response.start":
                headers = {k.lower(): v for k, v in message.get("headers", [])}
                if headers.get(b"content-type", b"").lower().startswith(b"text/html"):
                    held = message  # espera o corpo para poder reescrevê-lo
                    return
                await send(message)
                return
            if held is None or message["type"] != "http.response.body":
                await send(message)
                return
            chunks.append(message.get("body", b""))
            if message.get("more_body"):
                return
            raw = b"".join(chunks)
            try:
                body = inject(raw.decode("utf-8")).encode("utf-8")
            except UnicodeDecodeError:
                body = raw  # charset que nao e utf-8: deixa como veio
            headers = [(k, v) for k, v in held["headers"] if k.lower() != b"content-length"]
            headers.append((b"content-length", str(len(body)).encode()))
            await send({**held, "headers": headers})
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, wrapped)
