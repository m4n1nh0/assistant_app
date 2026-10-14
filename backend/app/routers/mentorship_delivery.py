"""Link de entrega das atividades da mentoria: a página que o aluno aceito abre.

Sem login. A credencial é o token da URL somada à matrícula, e só entra quem está
**aceito** na mentoria — o mesmo nível de segurança do envio de material. O professor
vê quem entregou e pode conferir cada entrega.
"""

from __future__ import annotations

import json
from html import escape

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..services import mentorship_service as svc
from .mentorship import _closed_page, _page

router = APIRouter(
    prefix="/education/mentorship-deliver", tags=["education-mentorship-deliver"])


class LookupBody(BaseModel):
    enrollment: str = Field(default="", max_length=80)


def _error(exc: svc.MentorshipError) -> JSONResponse:
    return JSONResponse(
        {"code": exc.code, "detail": exc.message}, status_code=exc.status,
        headers={"Cache-Control": "no-store"})


async def _state(db: AsyncSession, form, signup) -> dict:
    """O que o aluno vê: cada atividade com a situação da entrega dele."""
    activities = await svc.list_activities(db, form.id)
    mine = {d.activity_id: d for d in await svc.deliveries_of(db, form.id)
            if d.signup_id == signup.id}
    items = []
    for activity in activities:
        delivery = mine.get(activity.id)
        items.append({
            "id": activity.id, "title": activity.title,
            "instructions": activity.instructions,
            "due_at": activity.due_at.isoformat() if activity.due_at else "",
            "status": svc.delivery_status(activity, delivery),
            "delivery": None if delivery is None else {
                "text": delivery.text, "filename": delivery.filename,
                "late": bool(delivery.late),
                "at": delivery.delivered_at.isoformat() if delivery.delivered_at else "",
            },
        })
    return {"student": {"name": signup.name}, "mentorship": form.title, "activities": items}


_SCRIPT = """
<script>
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var base = location.pathname.replace(/\\/$/, "");
  var enrollment = "";
  var LABEL = {delivered: "Entregue", late: "Entregue com atraso",
               overdue: "Prazo vencido", pending: "Pendente"};
  function say(kind, text) {
    var box = $("msg"); box.hidden = !text;
    box.className = "msg " + (kind || ""); box.textContent = text || "";
  }
  function when(iso) {
    if (!iso) return "";
    var d = new Date(iso + (/[zZ]|[+-]\\d\\d:?\\d\\d$/.test(iso) ? "" : "Z"));
    return isNaN(d) ? "" : d.toLocaleString("pt-BR", {dateStyle: "short", timeStyle: "short"});
  }
  async function call(path, init) {
    var res = await fetch(base + path, init);
    var data = {};
    try { data = await res.json(); } catch (e) {}
    if (!res.ok) throw new Error(data.detail || "Não foi possível concluir. Tente de novo.");
    return data;
  }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function render(data) {
    $("who").textContent = data.student.name;
    var list = $("acts"); list.textContent = "";
    if (!data.activities.length) {
      list.appendChild(el("p", "", "O professor ainda não publicou atividades."));
    }
    data.activities.forEach(function (a) {
      var card = el("div", "act");
      card.appendChild(el("strong", "", a.title));
      card.appendChild(el("span", "tag " + a.status, LABEL[a.status] || a.status));
      if (a.due_at) card.appendChild(el("p", "due", "Prazo: " + when(a.due_at)));
      if (a.instructions) card.appendChild(el("p", "", a.instructions));
      if (a.delivery) {
        var mine = a.delivery.filename ? "Arquivo enviado: " + a.delivery.filename : "Resposta enviada";
        card.appendChild(el("p", "mine", mine + " · " + when(a.delivery.at)));
      }
      var text = el("textarea"); text.maxLength = 10000;
      text.placeholder = "Resposta ou link (opcional se enviar arquivo)";
      text.value = a.delivery ? a.delivery.text : "";
      var file = el("input"); file.type = "file";
      var btn = el("button", "", a.delivery ? "ENVIAR DE NOVO" : "ENTREGAR");
      btn.type = "button";
      btn.onclick = async function () {
        say("", "");
        var form = new FormData();
        form.append("enrollment", enrollment);
        form.append("activity_id", a.id);
        form.append("text", text.value);
        if (file.files[0]) form.append("file", file.files[0]);
        btn.disabled = true; btn.textContent = "ENVIANDO...";
        try {
          var out = await call("/send", {method: "POST", body: form});
          say("ok", out.replaced ? "Entrega atualizada." : "Entrega recebida!");
          render(await call("/lookup", {method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({enrollment: enrollment})}));
        } catch (e) { say("err", e.message); btn.disabled = false;
                      btn.textContent = a.delivery ? "ENVIAR DE NOVO" : "ENTREGAR"; }
      };
      card.appendChild(text); card.appendChild(file); card.appendChild(btn);
      list.appendChild(card);
    });
    $("step2").hidden = false;
  }
  async function lookup() {
    enrollment = $("enrollment").value.trim();
    say("", "");
    if (!enrollment) { say("err", "Digite a sua matrícula."); return; }
    $("find").disabled = true;
    try {
      render(await call("/lookup", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({enrollment: enrollment})}));
    } catch (e) { $("step2").hidden = true; say("err", e.message); }
    $("find").disabled = false;
  }
  $("find").onclick = lookup;
  $("enrollment").addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); lookup(); }
  });
})();
</script>
"""

_STYLE = """<style>
.act{margin-top:16px;padding:14px;border:1px solid #e5e7eb;border-radius:10px}
.act textarea,.act input[type=file]{margin-top:10px}
.tag{margin-left:8px;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700;
background:#e5e7eb;color:#374151}
.tag.delivered{background:#ecfdf5;color:#047857}
.tag.late{background:#fffbeb;color:#b45309}
.tag.overdue{background:#fef2f2;color:#b91c1c}
.due{font-size:12px;color:#6b7280}.mine{font-size:12px;color:#047857}
</style>"""


@router.get("/{token}", response_class=HTMLResponse)
async def delivery_page(token: str, db: AsyncSession = Depends(get_db)):
    form = await svc.get_form_by_token(db, token)
    if form is None:
        return _closed_page("Este link não existe ou foi apagado. Confira com o professor.")
    body = f"""{_STYLE}
<div class="brand">MODO EDUCAÇÃO</div>
<h1>{escape(form.title)}</h1>
<p>Entrega de atividades. Digite a sua matrícula para ver as atividades e entregar.
Só quem teve a inscrição aceita consegue entrar.</p>
<label for="enrollment">Matrícula</label>
<input type="text" id="enrollment" maxlength="80" autocomplete="off" autofocus>
<button type="button" id="find">ENTRAR</button>
<div id="msg" class="msg" hidden role="alert"></div>
<section id="step2" hidden>
  <p>Entregando como <b id="who"></b></p>
  <div id="acts"></div>
</section>"""
    return _page(form.title, body, _SCRIPT)


async def _signup_or_error(db: AsyncSession, token: str, enrollment: str):
    form = await svc.get_form_by_token(db, token)
    if form is None:
        raise svc.MentorshipError("link", "Link não encontrado.", 404)
    return form, await svc.accepted_by_enrollment(db, form, enrollment)


@router.post("/{token}/lookup")
async def lookup(token: str, body: LookupBody, db: AsyncSession = Depends(get_db)):
    try:
        form, signup = await _signup_or_error(db, token, body.enrollment)
    except svc.MentorshipError as exc:
        return _error(exc)
    return JSONResponse(await _state(db, form, signup), headers={"Cache-Control": "no-store"})


@router.post("/{token}/send")
async def send(
    token: str,
    enrollment: str = Form(""),
    activity_id: str = Form(""),
    text: str = Form(""),
    file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
):
    try:
        form, signup = await _signup_or_error(db, token, enrollment)
        activity = await svc.get_activity(db, form, activity_id)
        data = b""
        filename = ""
        if file is not None and file.filename:
            # Um byte a mais que o teto basta para saber que estourou.
            data = await file.read(svc.MAX_DELIVERY_BYTES + 1)
            filename = file.filename
        delivery, replaced = await svc.deliver(
            db, form, activity, signup, text=text, filename=filename, data=data)
    except svc.MentorshipError as exc:
        return _error(exc)
    return JSONResponse(
        {"ok": True, "replaced": replaced, "late": bool(delivery.late)},
        headers={"Cache-Control": "no-store"})
