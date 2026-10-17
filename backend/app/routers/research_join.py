"""Cadastro online em uma pesquisa: a página pública que a pessoa preenche sozinha.

O link `/education/research-join/{token}` não pede login. O token é o que identifica a
pesquisa; quem preenche entra como **pendente**, com o papel que o professor definiu no link,
e só passa a participante quando o professor aceita.

Como a página é pública e grava no banco, ela tem limite por IP: sem ele, um script
encheria a lista de pendentes de uma pesquisa em segundos.
"""

from __future__ import annotations

import time
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import ResearchProjectModel, get_db
from ..services import research_service as svc
from ..services import web_brand

public_router = APIRouter(prefix="/education/research-join", tags=["education-research-join"])

#: Envios aceitos por IP numa janela. Uma turma inteira na mesma rede (campus) preenche em
#: poucos minutos, então o limite é folgado para gente e curto para script.
_LIMIT = 15
_WINDOW_SECONDS = 600.0
_hits: dict[str, list[float]] = {}

_ROLE_TEXT = {
    "orientando": "como orientando",
    "coorientador": "como coorientador",
    "colaborador": "como colaborador",
}

_EXTRA_CSS = """
.hint{font-size:12px;color:#6b7280;margin:4px 0 0}
"""


def _rate_limited(ip: str, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    recent = [t for t in _hits.get(ip, []) if now - t < _WINDOW_SECONDS]
    limited = len(recent) >= _LIMIT
    if not limited:
        recent.append(now)
    _hits[ip] = recent
    return limited


def _page(title: str, body: str, script: str = "") -> HTMLResponse:
    return web_brand.page(title, body, script, _EXTRA_CSS)


def _closed(message: str) -> HTMLResponse:
    return _page(
        "Cadastro na pesquisa",
        f'<div class="brand">PESQUISA CIENTÍFICA</div><h1>Cadastro na pesquisa</h1>'
        f"<p>{escape(message)}</p>")


_SCRIPT = """
<script>
(function () {
  var $ = function (id) { return document.getElementById(id); };
  function say(kind, text) {
    var box = $("msg"); box.hidden = !text;
    box.className = "msg " + (kind || ""); box.textContent = text || "";
  }
  $("send").onclick = async function () {
    say("", "");
    var body = {name: $("name").value, email: $("email").value, phone: $("phone").value,
                enrollment: $("enrollment").value, institution: $("institution").value};
    $("send").disabled = true; $("send").textContent = "ENVIANDO...";
    try {
      var res = await fetch(location.pathname.replace(/\\/$/, ""), {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)});
      var data = {};
      try { data = await res.json(); } catch (e) {}
      if (!res.ok) throw new Error(data.detail || "Não foi possível enviar. Tente de novo.");
      $("form").hidden = true;
      say("ok", data.message);
    } catch (e) { say("err", e.message); }
    $("send").disabled = false; $("send").textContent = "ENVIAR CADASTRO";
  };
})();
</script>
"""


async def _open_project(db: AsyncSession, token: str):
    """(link, pesquisa, estado) do token, ou `None` se o link não existe."""
    link = await svc.link_by_token(db, token)
    if link is None:
        return None
    project = await db.get(ResearchProjectModel, link.project_id)
    return link, project, svc.join_state(link, project)


@public_router.get("/{token}", response_class=HTMLResponse)
async def join_page(token: str, db: AsyncSession = Depends(get_db)):
    found = await _open_project(db, token)
    if found is None:
        return _closed("Este link não existe ou foi apagado. Confira com o professor.")
    link, project, state = found
    if state != "open":
        return _closed({
            "closed": "O cadastro nesta pesquisa está fechado no momento.",
            "finished": "Esta pesquisa já foi concluída.",
        }[state])
    description = (
        f"<p>{escape(project.description.strip()[:400])}</p>" if project.description.strip() else "")
    role = _ROLE_TEXT.get(link.role, "")
    body = f"""
<div class="brand">PESQUISA CIENTÍFICA</div>
<h1>{escape(project.title)}</h1>
{description}
<div id="form">
<p>Preencha para participar {escape(role)}. O professor confirma o seu cadastro depois.</p>
<label for="name">Nome completo <span class="req">*</span></label>
<input type="text" id="name" maxlength="180" autocomplete="name" required>
<label for="email">E-mail <span class="req">*</span></label>
<input type="email" id="email" maxlength="255" autocomplete="email" required>
<label for="phone">Telefone com DDD</label>
<input type="tel" id="phone" maxlength="40" autocomplete="tel">
<label for="enrollment">Matrícula (se for aluno)</label>
<input type="text" id="enrollment" maxlength="80" autocomplete="off">
<label for="institution">Instituição (se for de fora)</label>
<input type="text" id="institution" maxlength="180" autocomplete="organization">
<p class="hint">Informe a matrícula <b>ou</b> a instituição.</p>
<button type="button" id="send">ENVIAR CADASTRO</button>
</div>
<div id="msg" class="msg" hidden role="alert"></div>"""
    return _page(project.title, body, _SCRIPT)


@public_router.post("/{token}")
async def join_submit(
    token: str, payload: dict, request: Request, db: AsyncSession = Depends(get_db),
):
    found = await _open_project(db, token)
    if found is None:
        raise HTTPException(404, "Link não encontrado")
    ip = request.client.host if request.client else "?"
    if _rate_limited(ip):
        return JSONResponse(
            {"detail": "Muitas tentativas. Aguarde alguns minutos e tente de novo."},
            status_code=429, headers={"Cache-Control": "no-store"})
    link, project, state = found
    if state != "open":
        return JSONResponse(
            {"detail": "O cadastro nesta pesquisa não está aberto."},
            status_code=409, headers={"Cache-Control": "no-store"})
    try:
        await svc.submit_join(db, link, project, payload)
    except svc.ResearchError as exc:
        return JSONResponse(
            {"code": exc.code, "detail": exc.message}, status_code=exc.status,
            headers={"Cache-Control": "no-store"})
    return JSONResponse(
        {"ok": True, "message": "Cadastro recebido! O professor vai analisar e entrar em contato."},
        headers={"Cache-Control": "no-store"})
