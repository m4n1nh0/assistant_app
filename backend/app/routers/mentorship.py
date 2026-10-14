"""Inscricao em mentorias: rotas do professor e a pagina publica do formulario.

As rotas do professor ficam em `/education/mentorships` (autenticadas); a pagina que
o inscrito abre fica em `/education/mentorship-signup/{token}`, sem login. O token da
URL e a unica credencial, como no envio de material.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from html import escape
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    MentorshipFormModel,
    MentorshipSignupModel,
    get_db,
)
from ..core.security import get_current_user
from ..services import mentorship_service as svc

router = APIRouter(prefix="/education/mentorships", tags=["education-mentorships"])
public_router = APIRouter(
    prefix="/education/mentorship-signup", tags=["education-mentorship-signup"])


def _link_path(form: MentorshipFormModel) -> str:
    return f"/education/mentorship-signup/{form.token}"


def _current_semester() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year}.{1 if now.month <= 6 else 2}"


class GenerateBody(BaseModel):
    description: str = Field(min_length=3, max_length=2000)


class FormCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    semester: str = Field(default="", max_length=16)
    fields: list[dict] = Field(default_factory=list)
    closes_at: Optional[datetime] = None
    max_slots: Optional[int] = Field(default=None, ge=1, le=5000)


class FormUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    fields: Optional[list[dict]] = None
    active: Optional[bool] = None
    closes_at: Optional[datetime] = None
    clear_deadline: bool = False
    max_slots: Optional[int] = Field(default=None, ge=1, le=5000)
    clear_slots: bool = False


class StatusBody(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    status: str


async def _form_out(form: MentorshipFormModel, db: AsyncSession) -> dict[str, Any]:
    rows = (await db.execute(select(MentorshipSignupModel.status).where(
        MentorshipSignupModel.form_id == form.id))).scalars().all()
    taken = sum(1 for s in rows if s in ("pending", "accepted"))
    return dict(
        id=form.id, token=form.token, path=_link_path(form), title=form.title,
        description=form.description, semester=form.semester,
        fields=svc.sanitize_fields(form.fields), active=bool(form.active),
        state=svc.form_state(form, taken), closes_at=form.closes_at,
        max_slots=form.max_slots, signups=len(rows),
        pending=sum(1 for s in rows if s == "pending"),
        accepted=sum(1 for s in rows if s == "accepted"),
        class_id=form.class_id, discipline_id=form.discipline_id,
        created_at=form.created_at,
    )


async def _owned(form_id: str, tutor_id: str, db: AsyncSession) -> MentorshipFormModel:
    form = await db.get(MentorshipFormModel, form_id)
    if form is None or form.tutor_id != tutor_id:
        raise HTTPException(404, "Formulário não encontrado")
    return form


def _signup_out(item: MentorshipSignupModel) -> dict[str, Any]:
    return dict(
        id=item.id, enrollment=item.enrollment, name=item.name, email=item.email,
        phone=item.phone, answers=item.answers or {}, known_student=bool(item.known_student),
        status=item.status, created_at=item.created_at)


@router.post("/generate-fields")
async def generate_fields(body: GenerateBody, user: dict = Depends(get_current_user)):
    """A IA propõe os campos; nada é gravado, o professor revisa antes de criar."""
    fields, from_ai = await svc.generate_fields(body.description)
    return {"fields": fields, "from_ai": from_ai}


@router.post("")
async def create_form(
    body: FormCreate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    fields = svc.sanitize_fields(body.fields) or svc.default_fields()
    form = MentorshipFormModel(
        tutor_id=user["tutor_id"], token=svc.new_token(), title=" ".join(body.title.split()),
        description=body.description.strip(), semester=body.semester.strip() or _current_semester(),
        fields=fields, closes_at=svc.naive(body.closes_at), max_slots=body.max_slots)
    db.add(form)
    await db.commit()
    await db.refresh(form)
    return await _form_out(form, db)


@router.get("")
async def list_forms(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(MentorshipFormModel).where(
        MentorshipFormModel.tutor_id == user["tutor_id"]
    ).order_by(MentorshipFormModel.created_at.desc()))).scalars().all()
    return [await _form_out(item, db) for item in rows]


@router.patch("/{form_id}")
async def update_form(
    form_id: str,
    body: FormUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    form = await _owned(form_id, user["tutor_id"], db)
    if body.title is not None:
        form.title = " ".join(body.title.split())
    if body.description is not None:
        form.description = body.description.strip()
    if body.fields is not None:
        form.fields = svc.sanitize_fields(body.fields) or svc.default_fields()
    if body.active is not None:
        form.active = body.active
    if body.clear_deadline:
        form.closes_at = None
    elif body.closes_at is not None:
        form.closes_at = svc.naive(body.closes_at)
    if body.clear_slots:
        form.max_slots = None
    elif body.max_slots is not None:
        form.max_slots = body.max_slots
    await db.commit()
    return await _form_out(form, db)


@router.delete("/{form_id}")
async def delete_form(
    form_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apaga o formulário e as inscrições; a turma e os alunos já aceitos continuam."""
    form = await _owned(form_id, user["tutor_id"], db)
    await db.execute(delete(MentorshipSignupModel).where(
        MentorshipSignupModel.form_id == form.id))
    await db.delete(form)
    await db.commit()
    return {"ok": True}


@router.get("/{form_id}/signups")
async def list_signups(
    form_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    form = await _owned(form_id, user["tutor_id"], db)
    rows = (await db.execute(select(MentorshipSignupModel).where(
        MentorshipSignupModel.form_id == form.id
    ).order_by(MentorshipSignupModel.created_at))).scalars().all()
    return [_signup_out(item) for item in rows]


@router.post("/{form_id}/signups/status")
async def set_signup_status(
    form_id: str,
    body: StatusBody,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aceita, recusa ou remove inscritos. Aceitar põe o aluno na turma da mentoria."""
    form = await _owned(form_id, user["tutor_id"], db)
    rows = (await db.execute(select(MentorshipSignupModel).where(
        MentorshipSignupModel.form_id == form.id,
        MentorshipSignupModel.id.in_(body.ids)))).scalars().all()
    try:
        changed = await svc.set_status(db, form, list(rows), body.status)
    except svc.MentorshipError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    sent = [await svc.notify_decision(form, item, body.status) for item in changed]
    return {"changed": len(rows), "emailed": sum(sent), "class_id": form.class_id, "form": await _form_out(form, db)}


@router.get("/{form_id}/export")
async def export_signups(
    form_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Inscritos em CSV (ponto e vírgula, para abrir direto no Excel em português)."""
    form = await _owned(form_id, user["tutor_id"], db)
    fields = svc.sanitize_fields(form.fields)
    rows = (await db.execute(select(MentorshipSignupModel).where(
        MentorshipSignupModel.form_id == form.id
    ).order_by(MentorshipSignupModel.created_at))).scalars().all()
    days = dict(svc.DAYS)
    shifts = dict(svc.SHIFTS)

    def cell(field: dict, value: Any) -> str:
        if field["type"] == "availability":
            return ", ".join(
                f"{days.get(v.split('-')[0], v)} {shifts.get(v.split('-')[1], '').lower()}"
                for v in (value or []))
        return "" if value is None else str(value)

    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(["Matrícula", "Nome", "E-mail", "Telefone", "Aluno conhecido",
                     "Situação", *[f["label"] for f in fields]])
    for item in rows:
        answers = item.answers or {}
        writer.writerow([item.enrollment, item.name, item.email, item.phone,
                         "sim" if item.known_student else "não", item.status,
                         *[cell(f, answers.get(f["id"])) for f in fields]])
    return {"csv": out.getvalue(), "count": len(rows)}


# --- pagina publica ------------------------------------------------------------------


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
font:16px system-ui,-apple-system,Segoe UI,sans-serif;min-height:100vh;padding:20px;
display:flex;justify-content:center;align-items:flex-start}}
main{{width:min(560px,100%);background:white;border-radius:14px;padding:30px;
box-shadow:0 18px 45px #11182740;margin:20px 0}}
.brand{{font-size:12px;font-weight:900;letter-spacing:2px;color:#4f46e5}}
h1{{font-size:24px;margin:10px 0 4px}}
p{{margin:6px 0;color:#4b5563;font-size:14px;white-space:pre-line}}
label,legend{{display:block;margin:16px 0 6px;font-size:13px;font-weight:700;color:#374151}}
input[type=text],input[type=email],input[type=tel],input[type=number],select,textarea{{
width:100%;padding:12px 14px;border:2px solid #d1d5db;border-radius:10px;font:inherit;
background:white}}
textarea{{min-height:84px;resize:vertical}}
fieldset{{border:0;padding:0;margin:0}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{padding:6px 4px;text-align:center;border-top:1px solid #e5e7eb}}
th:first-child,td:first-child{{text-align:left}}
td input{{width:20px;height:20px}}
button{{width:100%;margin-top:20px;padding:14px;border:0;border-radius:10px;
background:#4f46e5;color:white;font-weight:900;letter-spacing:.8px;cursor:pointer}}
button:disabled{{opacity:.55;cursor:default}}
input:focus-visible,select:focus-visible,textarea:focus-visible,button:focus-visible{{
outline:3px solid #4f46e5;outline-offset:2px}}
.msg{{margin:14px 0 0;padding:10px 12px;border-radius:8px;font-size:14px;font-weight:600}}
.err{{background:#fef2f2;color:#b91c1c}}
.ok{{background:#ecfdf5;color:#047857}}
.req{{color:#b91c1c}}
[hidden]{{display:none!important}}
</style></head><body><main>{body}</main>{script}</body></html>"""
    )


def _closed_page(message: str) -> HTMLResponse:
    return _page(
        "Inscrição na mentoria",
        f'<div class="brand">MODO EDUCAÇÃO</div><h1>Inscrição na mentoria</h1>'
        f"<p>{escape(message)}</p>")


def _field_html(field: dict) -> str:
    fid = escape(field["id"])
    star = ' <span class="req" aria-hidden="true">*</span>' if field["required"] else ""
    req = " required" if field["required"] else ""
    label = escape(field["label"])
    kind = field["type"]
    if kind == "availability":
        head = "".join(f"<th>{escape(name)}</th>" for _, name in svc.SHIFTS)
        rows = "".join(
            f"<tr><td>{escape(day_name)}</td>" + "".join(
                f'<td><input type="checkbox" data-av="{day}-{shift}" '
                f'aria-label="{escape(day_name)} {escape(shift_name)}"></td>'
                for shift, shift_name in svc.SHIFTS) + "</tr>"
            for day, day_name in svc.DAYS)
        return (f'<fieldset data-field="{fid}" data-type="availability" '
                f'data-required="{int(field["required"])}"><legend>{label}{star}</legend>'
                f"<table><tr><th></th>{head}</tr>{rows}</table></fieldset>")
    if kind == "textarea":
        control = f'<textarea id="f_{fid}" data-field="{fid}" maxlength="1000"{req}></textarea>'
    elif kind == "select":
        options = "".join(f"<option>{escape(o)}</option>" for o in field["options"])
        control = (f'<select id="f_{fid}" data-field="{fid}"{req}>'
                   f'<option value="">Escolha…</option>{options}</select>')
    elif kind == "number":
        control = (f'<input type="number" id="f_{fid}" data-field="{fid}" '
                   f'inputmode="decimal" step="any"{req}>')
    else:
        control = f'<input type="text" id="f_{fid}" data-field="{fid}" maxlength="200"{req}>'
    return f'<label for="f_{fid}">{label}{star}</label>{control}'


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
    var body = {enrollment: $("enrollment").value, name: $("name").value,
                email: $("email").value, phone: $("phone").value, answers: {}};
    document.querySelectorAll("[data-field]").forEach(function (el) {
      var id = el.getAttribute("data-field");
      if (el.getAttribute("data-type") === "availability") {
        body.answers[id] = Array.prototype.map.call(
          el.querySelectorAll("input[data-av]:checked"),
          function (c) { return c.getAttribute("data-av"); });
      } else { body.answers[id] = el.value; }
    });
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
    $("send").disabled = false; $("send").textContent = "ENVIAR INSCRIÇÃO";
  };
})();
</script>
"""


@public_router.get("/{token}", response_class=HTMLResponse)
async def signup_page(token: str, db: AsyncSession = Depends(get_db)):
    form = await svc.get_form_by_token(db, token)
    if form is None:
        return _closed_page("Este link não existe ou foi apagado. Confira com o professor.")
    state = svc.form_state(form, await svc.count_signups(db, form.id))
    if state != "open":
        return _closed_page({
            "closed": "As inscrições foram encerradas.",
            "expired": "O prazo de inscrição terminou.",
            "full": "As vagas acabaram.",
        }[state])
    extra = "".join(_field_html(f) for f in svc.sanitize_fields(form.fields))
    description = f"<p>{escape(form.description)}</p>" if form.description.strip() else ""
    body = f"""
<div class="brand">MODO EDUCAÇÃO</div>
<h1>{escape(form.title)}</h1>
{description}
<div id="form">
<p>Campos com <span class="req">*</span> são obrigatórios.</p>
<label for="enrollment">Matrícula <span class="req">*</span></label>
<input type="text" id="enrollment" maxlength="80" autocomplete="off" required>
<label for="name">Nome completo <span class="req">*</span></label>
<input type="text" id="name" maxlength="180" autocomplete="name" required>
<label for="email">E-mail <span class="req">*</span></label>
<input type="email" id="email" maxlength="255" autocomplete="email" required>
<label for="phone">Telefone com DDD <span class="req">*</span></label>
<input type="tel" id="phone" maxlength="40" autocomplete="tel" required>
{extra}
<button type="button" id="send">ENVIAR INSCRIÇÃO</button>
</div>
<div id="msg" class="msg" hidden role="alert"></div>"""
    return _page(form.title, body, _SCRIPT)


@public_router.post("/{token}")
async def signup_submit(token: str, payload: dict, db: AsyncSession = Depends(get_db)):
    form = await svc.get_form_by_token(db, token)
    if form is None:
        raise HTTPException(404, "Link não encontrado")
    try:
        signup = await svc.submit(db, form, payload)
    except svc.MentorshipError as exc:
        return JSONResponse(
            {"code": exc.code, "detail": exc.message}, status_code=exc.status,
            headers={"Cache-Control": "no-store"})
    emailed = await svc.send_confirmation(form, signup)
    message = "Inscrição recebida! " + (
        "Enviamos uma confirmação para o seu e-mail." if emailed
        else "O professor vai analisar e entrar em contato.")
    return JSONResponse({"ok": True, "message": message}, headers={"Cache-Control": "no-store"})


# --- atividades e entregas (professor) ------------------------------------------------


class ActivityCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    instructions: str = Field(default="", max_length=5000)
    due_at: Optional[datetime] = None
    remind: bool = True


class ActivityUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    instructions: Optional[str] = Field(default=None, max_length=5000)
    due_at: Optional[datetime] = None
    clear_due: bool = False
    remind: Optional[bool] = None


def _activity_out(item, delivered: int = 0, expected: int = 0) -> dict[str, Any]:
    return dict(
        id=item.id, form_id=item.form_id, title=item.title,
        instructions=item.instructions, due_at=item.due_at, remind=bool(item.remind),
        delivered=delivered, expected=expected, created_at=item.created_at)


def _delivery_link(form: MentorshipFormModel) -> str:
    return f"/education/mentorship-deliver/{form.token}"


async def _owned_activity(activity_id: str, tutor_id: str, db: AsyncSession):
    from ..core.database import MentorshipActivityModel

    item = await db.get(MentorshipActivityModel, activity_id)
    if item is None or item.tutor_id != tutor_id:
        raise HTTPException(404, "Atividade não encontrada")
    return item


@router.get("/{form_id}/activities")
async def list_activities(
    form_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """As atividades, com quantos aceitos já entregaram cada uma, e o link de entrega."""
    form = await _owned(form_id, user["tutor_id"], db)
    activities = await svc.list_activities(db, form.id)
    expected = len(await svc.accepted_signups(db, form.id))
    counts: dict[str, int] = {}
    accepted_ids = {s.id for s in await svc.accepted_signups(db, form.id)}
    for delivery in await svc.deliveries_of(db, form.id):
        if delivery.signup_id in accepted_ids:
            counts[delivery.activity_id] = counts.get(delivery.activity_id, 0) + 1
    return {
        "path": _delivery_link(form),
        "activities": [_activity_out(a, counts.get(a.id, 0), expected) for a in activities],
    }


@router.post("/{form_id}/activities")
async def create_activity(
    form_id: str,
    body: ActivityCreate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from ..core.database import MentorshipActivityModel

    form = await _owned(form_id, user["tutor_id"], db)
    position = len(await svc.list_activities(db, form.id))
    item = MentorshipActivityModel(
        form_id=form.id, tutor_id=form.tutor_id, title=" ".join(body.title.split()),
        instructions=body.instructions.strip(), due_at=svc.naive(body.due_at),
        remind=body.remind, position=position)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _activity_out(item, 0, len(await svc.accepted_signups(db, form.id)))


@router.patch("/activities/{activity_id}")
async def update_activity(
    activity_id: str,
    body: ActivityUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await _owned_activity(activity_id, user["tutor_id"], db)
    if body.title is not None:
        item.title = " ".join(body.title.split())
    if body.instructions is not None:
        item.instructions = body.instructions.strip()
    if body.clear_due:
        item.due_at = None
        item.reminded_at = None
    elif body.due_at is not None:
        item.due_at = svc.naive(body.due_at)
        item.reminded_at = None  # novo prazo, novo lembrete
    if body.remind is not None:
        item.remind = body.remind
    await db.commit()
    return _activity_out(item)


@router.delete("/activities/{activity_id}")
async def delete_activity(
    activity_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apaga a atividade e as entregas dela."""
    from ..core.database import MentorshipDeliveryModel

    item = await _owned_activity(activity_id, user["tutor_id"], db)
    await db.execute(delete(MentorshipDeliveryModel).where(
        MentorshipDeliveryModel.activity_id == item.id))
    await db.delete(item)
    await db.commit()
    return {"ok": True}


@router.get("/{form_id}/deliveries")
async def delivery_matrix(
    form_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aceitos x atividades: entregue, atrasada, vencida sem entrega ou pendente."""
    form = await _owned(form_id, user["tutor_id"], db)
    matrix = await svc.delivery_matrix(db, form)
    return {
        "activities": [_activity_out(a) for a in matrix["activities"]],
        "rows": matrix["rows"],
    }


@router.get("/{form_id}/at-risk")
async def at_risk(
    form_id: str,
    misses: int = 2,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Quem deixou de entregar as últimas `misses` atividades vencidas. Só sugere."""
    form = await _owned(form_id, user["tutor_id"], db)
    return {"misses": max(1, misses), "students": await svc.at_risk(db, form, misses)}


async def _owned_delivery(delivery_id: str, tutor_id: str, db: AsyncSession):
    from ..core.database import MentorshipDeliveryModel

    item = await db.get(MentorshipDeliveryModel, delivery_id)
    if item is None or item.tutor_id != tutor_id:
        raise HTTPException(404, "Entrega não encontrada")
    return item


@router.get("/deliveries/{delivery_id}")
async def delivery_detail(
    delivery_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await _owned_delivery(delivery_id, user["tutor_id"], db)
    return dict(
        id=item.id, activity_id=item.activity_id, signup_id=item.signup_id,
        text=item.text, filename=item.filename, file_size=item.file_size,
        late=bool(item.late), delivered_at=item.delivered_at)


@router.get("/deliveries/{delivery_id}/file")
async def delivery_file(
    delivery_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from urllib.parse import quote

    from fastapi.responses import Response

    item = await _owned_delivery(delivery_id, user["tutor_id"], db)
    if not item.file_data:
        raise HTTPException(404, "Esta entrega não tem arquivo")
    return Response(
        content=bytes(item.file_data), media_type="application/octet-stream",
        headers={"Content-Disposition":
                 f"attachment; filename*=UTF-8''{quote(item.filename or 'entrega')}"})
