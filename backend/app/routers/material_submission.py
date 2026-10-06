"""Pagina publica para os alunos enviarem o material da apresentacao do grupo.

Sem login: quem tem o link abre a pagina, digita a matricula e envia o arquivo. O
professor cria o link (rotas autenticadas em `education.py`); aqui so ficam as rotas
que o aluno usa. O token da URL e a unica credencial, e a matricula identifica o
grupo - o mesmo nivel de seguranca do quiz em grupo, e por isso o professor ve quem
enviou cada arquivo e pode apagar o que estiver errado.
"""

from __future__ import annotations

import json
from html import escape
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    ClassGroupModel,
    DisciplineModel,
    MaterialSubmissionLinkModel,
    get_db,
)
from ..services import material_submission_service as submissions

router = APIRouter(prefix="/education/material-submit", tags=["education-material-submit"])


class LookupBody(BaseModel):
    enrollment: str = Field(default="", max_length=64)


class RemoveBody(BaseModel):
    enrollment: str = Field(default="", max_length=64)
    material_id: str = Field(min_length=1, max_length=64)


def _material_json(item) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "filename": item.filename,
        "source_type": item.source_type,
        "pages": item.page_count or 0,
        "by": item.uploader_name or "",
        "sent_at": item.created_at.isoformat() if item.created_at else "",
    }


def _error(exc: submissions.SubmissionError) -> JSONResponse:
    return JSONResponse(
        {"code": exc.code, "detail": exc.message}, status_code=exc.status,
        headers={"Cache-Control": "no-store"},
    )


async def _link_or_404(db: AsyncSession, token: str) -> MaterialSubmissionLinkModel:
    link = await submissions.get_link_by_token(db, token)
    if link is None:
        raise HTTPException(404, "Link não encontrado")
    return link


def _page(title: str, body: str, script: str = "") -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{escape(title)}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:linear-gradient(135deg,#2563eb,#7c3aed);color:#111827;
font:16px system-ui,-apple-system,Segoe UI,sans-serif;min-height:100vh;display:grid;
place-items:center;padding:20px}}
main{{width:min(520px,100%);background:white;border-radius:14px;padding:30px;
box-shadow:0 18px 45px #11182740}}
.brand{{font-size:12px;font-weight:900;letter-spacing:2px;color:#4f46e5}}
h1{{font-size:24px;margin:10px 0 4px}}
p{{margin:6px 0;color:#4b5563;font-size:14px}}
label{{display:block;margin:16px 0 6px;font-size:13px;font-weight:700;color:#374151}}
input[type=text],input[type=file]{{width:100%;padding:12px 14px;border:2px solid #d1d5db;
border-radius:10px;font-size:16px;background:white}}
button{{width:100%;margin-top:16px;padding:14px;border:0;border-radius:10px;
background:#4f46e5;color:white;font-weight:900;letter-spacing:.8px;cursor:pointer}}
button:disabled{{opacity:.55;cursor:default}}
button.link{{width:auto;margin:0;padding:4px 8px;background:none;color:#b91c1c;
font-weight:700;letter-spacing:0}}
input:focus-visible,button:focus-visible{{outline:3px solid #4f46e5;outline-offset:2px}}
.msg{{margin:14px 0 0;padding:10px 12px;border-radius:8px;font-size:14px;font-weight:600}}
.err{{background:#fef2f2;color:#b91c1c}}
.ok{{background:#ecfdf5;color:#047857}}
.group{{margin-top:16px;padding:12px 14px;border-radius:10px;background:#eef2ff}}
.group strong{{color:#3730a3}}
ul{{margin:8px 0 0;padding:0;list-style:none}}
li{{display:flex;justify-content:space-between;align-items:center;gap:8px;
padding:8px 0;border-top:1px solid #e5e7eb;font-size:14px}}
li small{{display:block;color:#6b7280}}
[hidden]{{display:none!important}}
</style></head><body><main>{body}</main>{script}</body></html>"""
    )


def _closed_page(message: str) -> HTMLResponse:
    return _page(
        "Envio de material",
        f'<div class="brand">MODO EDUCAÇÃO</div><h1>Envio de material</h1>'
        f"<p>{escape(message)}</p>",
    )


_SCRIPT = """
<script>
(function () {
  var TOKEN = %(token)s;
  var base = location.pathname.replace(/\\/$/, "");
  var $ = function (id) { return document.getElementById(id); };
  var enrollment = "";

  function say(kind, text) {
    var box = $("msg");
    box.hidden = !text;
    box.className = "msg " + (kind || "");
    box.textContent = text || "";
  }
  function when(iso) {
    if (!iso) return "";
    var d = new Date(iso + (/[zZ]|[+-]\\d\\d:?\\d\\d$/.test(iso) ? "" : "Z"));
    return isNaN(d) ? "" : d.toLocaleString("pt-BR", {dateStyle: "short", timeStyle: "short"});
  }
  function render(data) {
    $("step2").hidden = false;
    $("grp").textContent = data.group.name;
    $("who").textContent = data.member.name;
    $("members").textContent = data.members.join(", ");
    var ul = $("files");
    ul.textContent = "";
    data.materials.forEach(function (m) {
      var li = document.createElement("li");
      var info = document.createElement("div");
      info.textContent = m.title;
      var small = document.createElement("small");
      small.textContent = m.filename + (m.by ? " · " + m.by : "") +
        (m.sent_at ? " · " + when(m.sent_at) : "");
      info.appendChild(small);
      var del = document.createElement("button");
      del.type = "button"; del.className = "link"; del.textContent = "Remover";
      del.onclick = function () { remove(m.id); };
      li.appendChild(info); li.appendChild(del); ul.appendChild(li);
    });
    $("sent").hidden = data.materials.length === 0;
  }
  async function call(path, init) {
    var res = await fetch(base + path, init);
    var data = {};
    try { data = await res.json(); } catch (e) {}
    if (!res.ok) throw new Error(data.detail || "Não foi possível concluir. Tente de novo.");
    return data;
  }
  async function lookup() {
    enrollment = $("enrollment").value.trim();
    say("", "");
    if (!enrollment) { say("err", "Digite a sua matrícula."); return; }
    $("find").disabled = true;
    try {
      render(await call("/lookup", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({enrollment: enrollment})
      }));
    } catch (e) { $("step2").hidden = true; say("err", e.message); }
    $("find").disabled = false;
  }
  async function remove(id) {
    if (!confirm("Remover este arquivo do grupo?")) return;
    try {
      await call("/remove", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({enrollment: enrollment, material_id: id})
      });
      say("ok", "Arquivo removido.");
      await refresh();
    } catch (e) { say("err", e.message); }
  }
  async function refresh() {
    render(await call("/lookup", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({enrollment: enrollment})
    }));
  }
  $("find").onclick = lookup;
  $("enrollment").addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); lookup(); }
  });
  $("send").onclick = async function () {
    var file = $("file").files[0];
    say("", "");
    if (!file) { say("err", "Escolha o arquivo da apresentação."); return; }
    var form = new FormData();
    form.append("enrollment", enrollment);
    form.append("title", $("title").value);
    form.append("file", file);
    $("send").disabled = true;
    $("send").textContent = "ENVIANDO...";
    try {
      var data = await call("/send", {method: "POST", body: form});
      say("ok", data.replaced ? "Arquivo atualizado. O professor já recebe a versão nova."
                              : "Arquivo recebido! O professor já pode ver.");
      $("file").value = ""; $("title").value = "";
      await refresh();
    } catch (e) { say("err", e.message); }
    $("send").disabled = false;
    $("send").textContent = "ENVIAR MATERIAL";
  };
})();
</script>
"""


@router.get("/{token}", response_class=HTMLResponse)
async def submission_page(token: str, db: AsyncSession = Depends(get_db)):
    link = await submissions.get_link_by_token(db, token)
    if link is None:
        return _closed_page("Este link não existe ou foi apagado. Confira com o professor.")
    state = submissions.link_state(link)
    if state == "closed":
        return _closed_page("O professor encerrou o recebimento deste material.")
    if state == "expired":
        return _closed_page("O prazo para enviar o material terminou.")

    discipline = await db.get(DisciplineModel, link.discipline_id)
    discipline_text = " - ".join(part for part in (
        (discipline.code or "").strip() if discipline else "",
        (discipline.name or "").strip() if discipline else "") if part)
    turmas = []
    for class_id in submissions.link_class_ids(link):
        item = await db.get(ClassGroupModel, class_id)
        if item is not None and item.tutor_id == link.tutor_id:
            turmas.append(" ".join(part for part in (
                (item.code or "").strip(), (item.name or "").strip()) if part))
    heading = link.title.strip() or "Material da apresentação"
    extensions = ", ".join(extension.lstrip(".").upper()
                           for extension in submissions.STUDENT_EXTENSIONS)
    body = f"""
<div class="brand">MODO EDUCAÇÃO</div>
<h1>{escape(heading)}</h1>
<p>{escape(discipline_text)}{(' · ' + escape(', '.join(turmas))) if turmas else ''}</p>
<p>Digite a sua matrícula para achar o seu grupo e enviar o material da apresentação
({escape(extensions)}, até {submissions.MAX_UPLOAD_BYTES // (1024 * 1024)} MB). Quem for
do grupo pode enviar de novo para trocar um arquivo.</p>
<label for="enrollment">Matrícula</label>
<input type="text" id="enrollment" inputmode="text" autocomplete="off" maxlength="64"
 placeholder="Sua matrícula" autofocus>
<button type="button" id="find">BUSCAR MEU GRUPO</button>
<div id="msg" class="msg" hidden role="alert"></div>
<section id="step2" hidden>
  <div class="group"><strong id="grp"></strong><br>
  <span>Enviando como <b id="who"></b></span>
  <p id="members"></p></div>
  <label for="title">Nome do material (opcional)</label>
  <input type="text" id="title" maxlength="200" placeholder="Ex.: Slides finais do projeto">
  <label for="file">Arquivo</label>
  <input type="file" id="file" accept="{escape(','.join(submissions.STUDENT_EXTENSIONS))}">
  <button type="button" id="send">ENVIAR MATERIAL</button>
  <div id="sent" hidden>
    <label>Já enviado pelo grupo</label>
    <ul id="files"></ul>
  </div>
</section>"""
    token_json = json.dumps(token).replace("</", "<\\/")
    return _page(heading, body, _SCRIPT % {"token": token_json})


@router.post("/{token}/lookup")
async def lookup(token: str, body: LookupBody, db: AsyncSession = Depends(get_db)):
    link = await _link_or_404(db, token)
    state = submissions.link_state(link)
    if state != "open":
        return _error(submissions.SubmissionError(
            state, "O recebimento deste material já foi encerrado.", 409))
    try:
        who = await submissions.identify(db, link, body.enrollment)
    except submissions.SubmissionError as exc:
        return _error(exc)
    items = await submissions.group_materials(db, who.group_id, link.id)
    return JSONResponse(
        {
            "group": {"id": who.group_id, "name": who.group_name},
            "member": {"name": who.member_name},
            "members": list(who.members),
            "materials": [_material_json(item) for item in items],
            "limit": link.max_files_per_group,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/{token}/send")
async def send(
    token: str,
    enrollment: str = Form(""),
    title: str = Form(""),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    link = await _link_or_404(db, token)
    # Le um byte a mais que o teto: basta para saber que estourou sem trazer tudo.
    data = await file.read(submissions.MAX_UPLOAD_BYTES + 1)
    try:
        material, who, replaced = await submissions.submit(
            db, link, enrollment=enrollment, filename=file.filename or "",
            data=data, title=title)
    except submissions.SubmissionError as exc:
        return _error(exc)
    return JSONResponse(
        {"material": _material_json(material), "group": who.group_name, "replaced": replaced},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/{token}/remove")
async def remove(token: str, body: RemoveBody, db: AsyncSession = Depends(get_db)):
    link = await _link_or_404(db, token)
    try:
        await submissions.remove_group_material(
            db, link, enrollment=body.enrollment, material_id=body.material_id)
    except submissions.SubmissionError as exc:
        return _error(exc)
    return {"removed": body.material_id}
