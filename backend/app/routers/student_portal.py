"""Portal do aluno: o link do professor e a página pública onde o aluno vê o que é dele.

O professor tem um link único (`/education/portal/{token}`) para todas as turmas. O aluno
digita a matrícula e vê resumos de aulas, resultado dos quizzes em grupo, pontos extras,
materiais e, na mentoria, as atividades. O acesso é só pela matrícula, por decisão do
professor, então as tentativas são limitadas por IP para ninguém varrer matrículas.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.net import client_ip
from ..core.security import get_current_user
from ..services import student_portal_service as svc
from ..services import web_brand

router = APIRouter(prefix="/education", tags=["education-portal"])

#: Tentativas de consulta por IP em uma janela. Matrícula não é segredo forte; isto só
#: impede varredura em massa.
RATE_LIMIT = 30
RATE_WINDOW_SECONDS = 60
_hits: dict[str, deque] = defaultdict(deque)


def _rate_limited(ip: str, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    hits = _hits[ip]
    while hits and now - hits[0] > RATE_WINDOW_SECONDS:
        hits.popleft()
    if len(hits) >= RATE_LIMIT:
        return True
    hits.append(now)
    return False


class PortalToggle(BaseModel):
    active: bool


class LookupBody(BaseModel):
    enrollment: str = Field(default="", max_length=80)


class MaterialBody(BaseModel):
    enrollment: str = Field(default="", max_length=80)
    material_id: str = Field(min_length=1, max_length=64)


def _portal_out(portal) -> dict:
    return {"path": f"/education/portal/{portal.token}", "active": bool(portal.active)}


# --- professor ------------------------------------------------------------------------------


@router.get("/portal-link")
async def portal_link(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """O link do portal do aluno; criado na primeira vez."""
    return _portal_out(await svc.get_or_create_portal(db, user["tutor_id"]))


@router.patch("/portal-link")
async def portal_toggle(
    body: PortalToggle,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fecha ou reabre o portal sem apagar nada."""
    portal = await svc.get_or_create_portal(db, user["tutor_id"])
    portal.active = body.active
    await db.commit()
    return _portal_out(portal)


# --- aluno ----------------------------------------------------------------------------------


def _closed(message: str) -> HTMLResponse:
    return web_brand.page(
        "Portal do aluno",
        f'<div class="brand">PORTAL DO ALUNO</div><h1>Portal do aluno</h1>'
        f"<p>{escape(message)}</p>")


_EXTRA_CSS = """
.iq-wrap{padding:12px}
main{width:min(560px,100%);padding:20px 16px}
main.logged{width:100%}
main.logged>.intro,main.logged #login{display:none}
.tabs{display:flex;gap:6px;margin:14px 0 6px;border-bottom:1px solid #e5e7eb;
overflow-x:auto;white-space:nowrap;scrollbar-width:thin}
.tab{flex:none;width:auto;margin:0;padding:10px 14px;border-radius:8px 8px 0 0;background:none;
color:#4b5563;letter-spacing:.4px;font-size:13px}
.tab[aria-selected=true]{background:#0A1324;color:#00D6FF}
.card{margin-top:14px;padding:16px;border:1px solid #e5e7eb;border-radius:10px}
.card h3{margin:0 0 4px;font-size:16px;color:#0A1324}
.meta{font-size:12px;color:#6b7280;margin-bottom:8px}
.sum{font-size:14px;line-height:1.6;color:#1f2937}
.sum h4{margin:14px 0 4px;font-size:14px;color:#0A8FB0}
.sum ul{margin:4px 0 8px 18px;padding:0;list-style:disc}
.sum li{display:list-item;border:0;padding:2px 0}
.chip{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700;
background:#e5e7eb;color:#374151;margin-right:6px}
.chip.ok{background:#ecfdf5;color:#047857}.chip.warn{background:#fffbeb;color:#b45309}
.chip.bad{background:#fef2f2;color:#b91c1c}.chip.info{background:#e6f4f8;color:#0A6E8A}
.big{font-size:28px;font-weight:800;color:#0A1324}
button.open{width:auto;margin:8px 0 0;padding:8px 14px;font-size:12px}
.sum.doc{max-height:520px;overflow:auto;background:#f9fafb;padding:12px;border-radius:8px;margin-top:10px}
.grp{margin:18px 0 0;padding-bottom:4px;font-size:15px;letter-spacing:.4px;color:#0A8FB0;border-bottom:1px solid #e5e7eb}
#filters{margin-top:10px}
.bar{display:flex;flex-wrap:wrap;gap:8px}
.bar input,.bar select{flex:1 1 200px;width:auto;max-width:360px;margin:0}
.card.past{opacity:.7}
.card.wide{grid-column:1/-1}
.reader{margin-top:10px}
.toc{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:8px 0}
.toc .meta{margin:0 4px 0 0}
.toc-item{width:auto;margin:0;padding:5px 10px;border-radius:14px;background:#e6f4f8;color:#0A6E8A;
font-size:12px;letter-spacing:0;font-weight:700}
.toc-item:hover:not(:disabled){background:#cfeaf2}
#pane{min-width:0}
pre.text{white-space:pre-wrap;font:13px/1.5 system-ui;margin:10px 0 0;max-height:420px;
overflow:auto;background:#f9fafb;padding:12px;border-radius:8px}
#exit{color:#0A6E8A;margin-left:6px;text-decoration:underline}
a.go{display:inline-block;margin-top:8px;color:#0A6E8A;font-weight:700}
@media (min-width:700px){
.iq-wrap{padding:28px 20px}
main{padding:30px}
main.logged{width:min(900px,100%)}
}
@media (min-width:1000px){
main.logged{width:min(1360px,100%)}

#step2{display:grid;grid-template-columns:210px minmax(0,1fr);column-gap:28px;align-items:start}
#step2>p{grid-column:1/-1}
.tabs{flex-direction:column;overflow:visible;white-space:normal;margin:0;gap:4px;
border-bottom:0;border-right:1px solid #e5e7eb;padding-right:14px;position:sticky;top:16px}
.tab{text-align:left;padding:12px 14px;border-radius:8px;font-size:14px}
#view{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px;
align-items:start}
#view>.card{margin-top:0}
#view>.meta,#view>.grp{grid-column:1/-1}
.reader{display:grid;grid-template-columns:240px minmax(0,1fr);gap:16px;align-items:start}
.reader-top{grid-column:1/-1}
.toc{flex-direction:column;align-items:stretch;position:sticky;top:16px;max-height:520px;overflow:auto}
.toc-item{text-align:left;border-radius:8px}
}
@media (min-width:1600px){
main.logged{width:min(1560px,100%)}
#view{grid-template-columns:repeat(auto-fill,minmax(400px,1fr))}
}
"""

_SCRIPT = """
<script>
(function () {
  var base = location.pathname.replace(/\\/$/, "");
  var $ = function (id) { return document.getElementById(id); };
  var enrollment = "", data = null, current = "inicio";
  var MODE = {presencial: "Presencial", online: "Online", ambos: "Presencial ou online"};
  var STATUS = {delivered: ["Entregue", "ok"], late: ["Entregue com atraso", "warn"],
                overdue: ["Prazo vencido", "bad"], pending: ["Pendente", "info"]};

  function say(kind, text) {
    var box = $("msg"); box.hidden = !text;
    box.className = "msg " + (kind || ""); box.textContent = text || "";
  }
  function when(iso, withTime) {
    if (!iso) return "";
    var d = new Date(iso + (/[zZ]|[+-]\\d\\d:?\\d\\d$/.test(iso) ? "" : "Z"));
    if (isNaN(d)) return "";
    return d.toLocaleString("pt-BR", withTime ? {dateStyle: "short", timeStyle: "short"}
                                              : {dateStyle: "short"});
  }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function chip(text, kind) { return el("span", "chip " + (kind || ""), text); }
  function empty(text) { return el("p", "meta", text); }

  // Markdown minimo do resumo, montado por DOM (nunca innerHTML): titulos, listas e negrito.
  function inline(parent, text) {
    text.split(/(\\*\\*[^*]+\\*\\*)/).forEach(function (part) {
      if (/^\\*\\*[^*]+\\*\\*$/.test(part)) parent.appendChild(el("b", "", part.slice(2, -2)));
      else if (part) parent.appendChild(document.createTextNode(part));
    });
  }
  function markdown(text) {
    var box = el("div", "sum"), list = null;
    text.split("\\n").forEach(function (raw) {
      var line = raw.trimEnd();
      var h = /^#{1,4}\\s+(.*)$/.exec(line), li = /^\\s*[-*]\\s+(.*)$/.exec(line);
      if (li) {
        if (!list) { list = el("ul"); box.appendChild(list); }
        var item = el("li"); inline(item, li[1]); list.appendChild(item); return;
      }
      list = null;
      if (h) { box.appendChild(el("h4", "", h[1])); return; }
      if (line.trim()) { var p = el("p"); inline(p, line); box.appendChild(p); }
    });
    return box;
  }

  // Texto extraido de apostila/slide: blocos separados por linha em branco. Linha curta sem
  // pontuacao final vira titulo; "-", "•" e "1." viram lista; o resto, paragrafo.
  var BULLET = /^\\s*(?:[-*•▪◦–]|\\d{1,2}[.)])\\s+(.*)$/;
  function isHeading(line) {
    var t = line.trim();
    if (!t || t.length > 90 || /[.;,:!?]$/.test(t) || BULLET.test(t)) return false;
    var words = t.split(/\\s+/).length;
    return words <= 12 && (t === t.toUpperCase() && /[A-ZÀ-Ú]/.test(t) ||
      /^(cap[ií]tulo|unidade|aula|se[cç][aã]o|m[oó]dulo)\\b/i.test(t) || /^\\d+(\\.\\d+)*\\.?\\s+\\S/.test(t) ||
      words <= 8);
  }
  function structure(text) {
    var box = el("div", "sum doc"); box.heads = [];
    text.split(/\\n\\s*\\n/).forEach(function (block) {
      var lines = block.split("\\n").map(function (l) { return l.trim(); }).filter(Boolean);
      var list = null, para = null;
      lines.forEach(function (line, i) {
        var li = BULLET.exec(line);
        if (li) {
          para = null;
          if (!list) { list = el("ul"); box.appendChild(list); }
          var item = el("li"); inline(item, li[1]); list.appendChild(item); return;
        }
        list = null;
        if (lines.length > 1 ? i === 0 && isHeading(line) && lines.length > 1 && !isHeading(lines[1]) :
            isHeading(line)) {
          var head = el("h4", "", line); box.appendChild(head); box.heads.push(head);
          para = null; return;
        }
        if (!para) { para = el("p"); box.appendChild(para); } else para.appendChild(document.createTextNode(" "));
        inline(para, line);
      });
    });
    return box;
  }

  // Leitor do material: indice pelos titulos que a estrutura achou, e botao para fechar.
  function reader(text, close) {
    var doc = structure(text), wrap = el("div", "reader");
    var top = el("div", "reader-top");
    var closeBtn = el("button", "open", "Fechar leitura"); closeBtn.type = "button";
    closeBtn.onclick = close; top.appendChild(closeBtn); wrap.appendChild(top);
    if (doc.heads.length > 1) {
      var nav = el("nav", "toc"); nav.setAttribute("aria-label", "Índice");
      nav.appendChild(el("div", "meta", "Índice"));
      doc.heads.forEach(function (h) {
        var b = el("button", "toc-item", h.textContent); b.type = "button";
        b.onclick = function () { h.scrollIntoView({behavior: "smooth", block: "start"}); };
        nav.appendChild(b);
      });
      wrap.appendChild(nav);
    }
    wrap.appendChild(doc);
    return wrap;
  }

  async function call(path, body) {
    var res = await fetch(base + path, {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    var out = {};
    try { out = await res.json(); } catch (e) {}
    if (!res.ok) throw new Error(out.detail || "Não foi possível concluir. Tente de novo.");
    return out;
  }

  // A aba fica no endereco (#materiais): o botao voltar do navegador e o link compartilhado
  // funcionam. A matricula nao vai no endereco, entao o link so abre depois de entrar.
  function tabAllowed(t) { return !!VIEWS[t] && (t !== "mentoria" || data.mentorships.length > 0); }
  function setTab(tab) {
    current = tab; render(); window.scrollTo(0, 0);
    try { if (location.hash !== "#" + tab) history.pushState(null, "", "#" + tab); } catch (e) {}
  }
  function go(tab) { setTab(tab); }
  window.addEventListener("popstate", function () {
    var t = location.hash.slice(1);
    if (data && t && t !== current && tabAllowed(t)) { current = t; render(); }
  });
  function more(card, tab, text) {
    var b = el("button", "open", text || "Ver tudo"); b.type = "button";
    b.onclick = function () { go(tab); }; card.appendChild(b);
  }
  function dayLabel(iso) {
    var p = iso.split("-");
    return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2])).toLocaleDateString("pt-BR",
      {weekday: "short", day: "2-digit", month: "2-digit"});
  }

  // Filtro por disciplina (aulas, pontos e materiais): "Todas" agrupa por disciplina.
  var discipline = "", FILTERED = {aulas: 1, pontos: 1, materiais: 1};
  function disciplines() {
    var seen = {};
    data.lessons.concat(data.points.items, data.materials).forEach(function (i) {
      if (i.discipline) seen[i.discipline] = 1;
    });
    return Object.keys(seen).sort();
  }
  // Busca (sem acento e sem diferenciar maiuscula) e ordem por data, junto do filtro.
  var query = "", order = "recent";
  function fold(s) {
    return String(s || "").toLowerCase().normalize("NFD").replace(/[\\u0300-\\u036f]/g, "");
  }
  function haystack(i) {
    return fold([i.title, i.summary, i.reason, i.filename, i.discipline, i.class_label].join(" "));
  }
  function visible(items) {
    var q = fold(query).trim();
    var out = items.filter(function (i) {
      return (!discipline || i.discipline === discipline) && (!q || haystack(i).indexOf(q) >= 0);
    });
    return out.slice().sort(function (a, b) {
      var x = a.date || "", y = b.date || "";
      return order === "old" ? x.localeCompare(y) : y.localeCompare(x);
    });
  }
  function grouped(root, items, build) {
    var by = {}, order = [];
    if (!items.length) {
      root.appendChild(empty(query || discipline ? "Nada encontrado com esses filtros." : "Nada por aqui ainda."));
      return;
    }
    items.forEach(function (i) {
      var k = i.discipline || "Outras";
      if (!by[k]) { by[k] = []; order.push(k); }
      by[k].push(i);
    });
    if (discipline || order.length < 2) { items.forEach(build); return; }
    order.forEach(function (k) { root.appendChild(el("h2", "grp", k)); by[k].forEach(build); });
  }
  function drawFilters() {
    var box = $("filters"); box.textContent = "";
    if (!FILTERED[current]) return;
    var names = disciplines();
    if (names.indexOf(discipline) < 0) discipline = "";
    var bar = el("div", "bar");
    var q = el("input"); q.type = "text"; q.id = "q"; q.placeholder = "Buscar";
    q.setAttribute("aria-label", "Buscar"); q.value = query;
    // So a lista e redesenhada: refazer o campo tiraria o foco a cada letra digitada.
    q.oninput = function () { query = q.value; drawView(); };
    bar.appendChild(q);
    if (names.length > 1) {
      var sel = el("select"); sel.id = "disc"; sel.setAttribute("aria-label", "Disciplina");
      [""].concat(names).forEach(function (n) {
        var o = el("option", "", n || "Todas as disciplinas"); o.value = n; sel.appendChild(o);
      });
      sel.value = discipline;
      sel.onchange = function () { discipline = sel.value; drawView(); };
      bar.appendChild(sel);
    }
    var ord = el("select"); ord.id = "ord"; ord.setAttribute("aria-label", "Ordem");
    [["recent", "Mais recentes primeiro"], ["old", "Mais antigos primeiro"]].forEach(function (p) {
      var o = el("option", "", p[1]); o.value = p[0]; ord.appendChild(o);
    });
    ord.value = order;
    ord.onchange = function () { order = ord.value; drawView(); };
    bar.appendChild(ord);
    box.appendChild(bar);
  }

  var VIEWS = {
    inicio: function (root) {
      var open = [];
      data.mentorships.forEach(function (m) {
        m.activities.forEach(function (a) {
          if (a.status === "pending" || a.status === "overdue") open.push([m, a]);
        });
      });
      open.sort(function (x, y) { return (x[1].due_at || "9").localeCompare(y[1].due_at || "9"); });
      if (open.length) {
        var due = el("div", "card");
        due.appendChild(el("h3", "", "Atividades para entregar"));
        open.slice(0, 4).forEach(function (pair) {
          var a = pair[1], s = STATUS[a.status];
          var row = el("p"); row.appendChild(chip(s[0], s[1]));
          row.appendChild(document.createTextNode(a.title + (a.due_at ? " · prazo " + when(a.due_at, true) : "")));
          due.appendChild(row);
        });
        more(due, "mentoria", "Ver atividades"); root.appendChild(due);
      }
      var a = data.availability, next = a.upcoming.filter(function (o) { return !o.blocked; })[0];
      var meet = el("div", "card"); meet.appendChild(el("h3", "", "Próximo atendimento"));
      if (next) {
        var p = el("p"); p.appendChild(chip(dayLabel(next.date), "ok"));
        p.appendChild(document.createTextNode(next.start_time + " às " + next.end_time + " · " +
          (MODE[next.mode] || "")));
        meet.appendChild(p);
      } else meet.appendChild(empty("Sem atendimento marcado nos próximos dias."));
      more(meet, "atendimento", "Ver horários"); root.appendChild(meet);

      var last = data.lessons[0];
      var lesson = el("div", "card"); lesson.appendChild(el("h3", "", "Última aula"));
      if (last) {
        lesson.appendChild(el("p", "", last.title));
        lesson.appendChild(el("div", "meta", [when(last.date), last.class_label].filter(Boolean).join(" · ")));
        more(lesson, "aulas", "Ler o resumo");
      } else lesson.appendChild(empty("Ainda não há resumos."));
      root.appendChild(lesson);

      var pts = el("div", "card"); pts.appendChild(el("div", "meta", "Pontos extras"));
      pts.appendChild(el("div", "big", String(data.points.total)));
      if (data.points.items[0]) pts.appendChild(el("div", "meta", "Último: +" +
        data.points.items[0].points + (data.points.items[0].reason ? " · " + data.points.items[0].reason : "")));
      more(pts, "pontos"); root.appendChild(pts);

      var q = data.quizzes[0];
      if (q) {
        var quiz = el("div", "card"); quiz.appendChild(el("h3", "", "Último quiz"));
        quiz.appendChild(el("div", "meta", q.title + " · " + when(q.date)));
        var r = el("p");
        if (q.position) r.appendChild(chip(q.position + "º de " + q.groups_total + " grupos", "info"));
        r.appendChild(chip("Você: " + q.my_score + " pts", "ok")); quiz.appendChild(r);
        more(quiz, "quizzes"); root.appendChild(quiz);
      }
    },
    // Linha do tempo: aulas das ultimas 2 semanas, prazos da mentoria e atendimentos, por dia.
    agenda: function (root) {
      function pad(n) { return (n < 10 ? "0" : "") + n; }
      function key(d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); }
      function parse(iso) {
        var d = new Date(iso + (/[zZ]|[+-]\\d\\d:?\\d\\d$/.test(iso) ? "" : "Z"));
        return isNaN(d) ? null : d;
      }
      var ev = [], today = key(new Date()), cutoff = Date.now() - 14 * 86400000;
      data.lessons.forEach(function (l) {
        var d = l.date && parse(l.date);
        if (d && d.getTime() >= cutoff) ev.push({day: key(d), time: pad(d.getHours()) + ":" + pad(d.getMinutes()),
          kind: "Aula", tone: "", text: l.title, sub: l.class_label});
      });
      data.availability.upcoming.forEach(function (o) {
        if (!o.blocked) ev.push({day: o.date, time: o.start_time, kind: "Atendimento", tone: "ok",
          text: o.start_time + " às " + o.end_time + " · " + (MODE[o.mode] || ""), sub: o.note});
      });
      data.mentorships.forEach(function (m) {
        m.activities.forEach(function (a) {
          var d = a.due_at && parse(a.due_at);
          if (d && (a.status === "pending" || a.status === "overdue")) ev.push({day: key(d),
            time: pad(d.getHours()) + ":" + pad(d.getMinutes()), kind: "Prazo",
            tone: a.status === "overdue" ? "bad" : "warn", text: a.title, sub: m.title});
        });
      });
      if (!ev.length) return root.appendChild(empty("Nada na agenda por enquanto."));
      ev.sort(function (x, y) { return (x.day + " " + x.time).localeCompare(y.day + " " + y.time); });
      var days = {}, order = [];
      ev.forEach(function (e) { if (!days[e.day]) { days[e.day] = []; order.push(e.day); } days[e.day].push(e); });
      order.forEach(function (day) {
        var c = el("div", "card" + (day < today ? " past" : ""));
        c.appendChild(el("h3", "", dayLabel(day) + (day === today ? " · hoje" : "")));
        days[day].forEach(function (e) {
          var row = el("p"); row.appendChild(chip(e.kind, e.tone));
          row.appendChild(document.createTextNode(e.text));
          c.appendChild(row);
          if (e.sub) c.appendChild(el("div", "meta", e.sub));
        });
        root.appendChild(c);
      });
    },
    aulas: function (root) {
      if (!data.lessons.length) return root.appendChild(
        empty("Ainda não há resumos de aulas das suas turmas."));
      grouped(root, visible(data.lessons), function (l) {
        var c = el("div", "card");
        c.appendChild(el("h3", "", l.title));
        var meta = el("div", "meta", [when(l.date), l.class_label].filter(Boolean).join(" · "));
        if (l.mentorship) meta.appendChild(chip("Mentoria", "info"));
        c.appendChild(meta); c.appendChild(markdown(l.summary)); root.appendChild(c);
      });
    },
    quizzes: function (root) {
      if (!data.quizzes.length) return root.appendChild(
        empty("Você ainda não participou de quizzes em grupo."));
      data.quizzes.forEach(function (q) {
        var c = el("div", "card");
        c.appendChild(el("h3", "", q.title));
        c.appendChild(el("div", "meta", when(q.date) + (q.group_name ? " · " + q.group_name : "")));
        var row = el("p");
        if (q.position) row.appendChild(chip(q.position + "º de " + q.groups_total + " grupos", "info"));
        row.appendChild(chip("Grupo: " + q.group_score + " pts", ""));
        row.appendChild(chip("Você: " + q.my_score + " pts · " + q.my_correct + "/" +
                             q.questions + " acertos", "ok"));
        if (!q.finished) row.appendChild(chip("Em andamento", "warn"));
        c.appendChild(row); root.appendChild(c);
      });
    },
    pontos: function (root) {
      var items = visible(data.points.items), c = el("div", "card");
      var total = discipline ? Math.round(items.reduce(function (s, p) { return s + p.points; }, 0) * 100) / 100
                             : data.points.total;
      c.appendChild(el("div", "meta", "Total de pontos extras" + (discipline ? " · " + discipline : "")));
      c.appendChild(el("div", "big", String(total)));
      root.appendChild(c);
      if (!items.length) return root.appendChild(empty("Nenhum ponto extra ainda."));
      grouped(root, items, function (p) {
        var r = el("div", "card");
        r.appendChild(el("h3", "", "+" + p.points + " pts"));
        r.appendChild(el("div", "meta", [when(p.date), p.discipline].filter(Boolean).join(" · ")));
        if (p.reason) r.appendChild(el("p", "", p.reason));
        root.appendChild(r);
      });
    },
    materiais: function (root) {
      if (!data.materials.length) return root.appendChild(
        empty("Ainda não há materiais das suas disciplinas."));
      grouped(root, visible(data.materials), function (m) {
        var c = el("div", "card");
        c.appendChild(el("h3", "", m.title));
        c.appendChild(el("div", "meta", [m.discipline, m.filename,
          m.pages ? m.pages + " pág." : "", when(m.date)].filter(Boolean).join(" · ")));
        var out = el("div");
        var btn = el("button", "open", "LER NO PORTAL"); btn.type = "button";
        btn.onclick = async function () {
          btn.disabled = true;
          try {
            var r = await call("/material", {enrollment: enrollment, material_id: m.id});
            out.textContent = "";
            out.appendChild(reader(r.content, function () {
              out.textContent = ""; c.className = "card"; btn.hidden = false; btn.disabled = false;
            }));
            c.className = "card wide"; btn.hidden = true;
          } catch (e) { say("err", e.message); btn.disabled = false; }
        };
        c.appendChild(btn); c.appendChild(out); root.appendChild(c);
      });
    },
    atendimento: function (root) {
      var a = data.availability;
      if (!a.weekly.length && !a.upcoming.length) return root.appendChild(
        empty("O professor ainda não publicou horários de atendimento."));
      function where(parent, s) {
        var text = MODE[s.mode] || "";
        parent.appendChild(document.createTextNode(text));
        if (!s.location) return;
        parent.appendChild(document.createTextNode(" · "));
        if (/^https?:\/\//i.test(s.location)) {
          var link = el("a", "go", "entrar na reunião");
          link.href = s.location; link.rel = "noopener noreferrer"; link.target = "_blank";
          parent.appendChild(link);
        } else parent.appendChild(document.createTextNode(s.location));
      }
      var week = el("div", "card");
      week.appendChild(el("h3", "", "Horários da semana"));
      week.appendChild(el("div", "meta", "Repetem toda semana, exceto nos dias avisados abaixo."));
      if (!a.weekly.length) week.appendChild(empty("Nenhum horário fixo."));
      a.weekly.forEach(function (s) {
        var p = el("p");
        p.appendChild(chip(s.weekday_name, "info"));
        p.appendChild(document.createTextNode(s.start_time + " às " + s.end_time + " · "));
        where(p, s);
        if (s.audience !== "todos") {
          var who = chip(s.audience === "mentoria" ? "só mentoria" : "só graduação", "");
          who.style.marginLeft = "8px"; p.appendChild(who);
        }
        if (s.note) p.appendChild(el("div", "meta", s.note));
        week.appendChild(p);
      });
      root.appendChild(week);

      var next = el("div", "card");
      next.appendChild(el("h3", "", "Próximos 28 dias"));
      if (!a.upcoming.length) next.appendChild(empty("Nenhum atendimento nos próximos dias."));
      a.upcoming.forEach(function (o) {
        var parts = o.date.split("-");
        var day = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
        var p = el("p");
        p.appendChild(chip(day.toLocaleDateString("pt-BR",
          {weekday: "short", day: "2-digit", month: "2-digit"}), o.blocked ? "bad" : "ok"));
        if (o.blocked) {
          p.appendChild(document.createTextNode("Sem atendimento" + (o.note ? " · " + o.note : "")));
        } else {
          p.appendChild(document.createTextNode(o.start_time + " às " + o.end_time + " · "));
          where(p, o);
          if (o.source === "extra") {
            var extra = chip("horário extra", "warn");
            extra.style.marginLeft = "8px"; p.appendChild(extra);
          }
          if (o.note) p.appendChild(el("div", "meta", o.note));
        }
        next.appendChild(p);
      });
      root.appendChild(next);
    },
    mentoria: function (root) {
      if (!data.mentorships.length) return root.appendChild(
        empty("Você não está em nenhuma mentoria."));
      data.mentorships.forEach(function (m) {
        var c = el("div", "card");
        c.appendChild(el("h3", "", m.title));
        if (!m.activities.length) c.appendChild(empty("Ainda não há atividades."));
        m.activities.forEach(function (a) {
          var row = el("p");
          var s = STATUS[a.status] || [a.status, ""];
          row.appendChild(chip(s[0], s[1]));
          row.appendChild(document.createTextNode(a.title + (a.due_at ? " · prazo " + when(a.due_at, true) : "")));
          c.appendChild(row);
          if (a.instructions) c.appendChild(el("div", "meta", a.instructions));
        });
        var go = el("a", "go", "Ir para a entrega de atividades →");
        go.href = m.deliver_path; c.appendChild(go); root.appendChild(c);
      });
    }
  };

  function render() {
    $("who").textContent = data.student.name;
    var tabs = $("tabs"); tabs.textContent = "";
    var defs = [["inicio", "Início", true], ["agenda", "Agenda", true], ["aulas", "Aulas", true], ["quizzes", "Quizzes", true],
                ["pontos", "Pontos", true], ["materiais", "Materiais", true],
                ["atendimento", "Atendimento", true],
                ["mentoria", "Mentoria", data.mentorships.length > 0]];
    defs.filter(function (d) { return d[2]; }).forEach(function (d) {
      var b = el("button", "tab", d[1]); b.type = "button"; b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", String(d[0] === current));
      b.onclick = function () { setTab(d[0]); };
      tabs.appendChild(b);
    });
    drawFilters();
    drawView();
    $("step2").hidden = false;
    document.querySelector("main").classList.add("logged");
  }
  function drawView() {
    var root = $("view"); root.textContent = "";
    VIEWS[current](root);
  }

  async function lookup() {
    enrollment = $("enrollment").value.trim();
    say("", "");
    if (!enrollment) { say("err", "Digite a sua matrícula."); return; }
    $("find").disabled = true;
    try { data = await call("/lookup", {enrollment: enrollment});
      var h = location.hash.slice(1);
      current = h && tabAllowed(h) ? h : "inicio"; render(); }
    catch (e) { $("step2").hidden = true;
      document.querySelector("main").classList.remove("logged"); say("err", e.message); }
    $("find").disabled = false;
  }
  $("find").onclick = lookup;
  $("exit").onclick = function () {
    data = null; enrollment = ""; $("enrollment").value = ""; say("", "");
    $("step2").hidden = true; document.querySelector("main").classList.remove("logged");
    $("enrollment").focus();
  };
  $("enrollment").addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); lookup(); }
  });
})();
</script>
"""


@router.get("/portal/{token}", response_class=HTMLResponse)
async def portal_page(token: str, db: AsyncSession = Depends(get_db)):
    portal = await svc.get_portal_by_token(db, token)
    if portal is None:
        return _closed("Este link não existe ou foi trocado. Confira com o professor.")
    if not portal.active:
        return _closed("O portal está fechado no momento. Confira com o professor.")
    body = """
<div class="brand">PORTAL DO ALUNO</div>
<h1>Portal do aluno</h1>
<p class="intro">Digite a sua matrícula para ver os resumos das aulas, o resultado dos quizzes em grupo,
seus pontos, os materiais das disciplinas e, se estiver em uma mentoria, as atividades.</p>
<div id="login">
<div><label for="enrollment">Matrícula</label>
<input type="text" id="enrollment" maxlength="80" autocomplete="off" autofocus></div>
<button type="button" id="find">ENTRAR</button>
</div>
<div id="msg" class="msg" hidden role="alert"></div>
<section id="step2" hidden>
  <p>Olá, <b id="who"></b>! <button type="button" class="link" id="exit">Sair</button></p>
  <div id="tabs" class="tabs" role="tablist"></div>
  <div id="pane"><div id="filters"></div><div id="view"></div></div>
</section>"""
    return web_brand.page("Portal do aluno", body, _SCRIPT, _EXTRA_CSS)


async def _students_or_error(request: Request, db: AsyncSession, token: str, enrollment: str):
    if _rate_limited(client_ip(request)):
        return None, None, JSONResponse(
            {"code": "rate", "detail": "Muitas tentativas. Aguarde um minuto e tente de novo."},
            status_code=429, headers={"Retry-After": str(RATE_WINDOW_SECONDS)})
    portal = await svc.get_portal_by_token(db, token)
    if portal is None or not portal.active:
        return None, None, JSONResponse(
            {"code": "closed", "detail": "O portal está fechado."}, status_code=404)
    students = await svc.find_students(db, portal.tutor_id, enrollment)
    if not students:
        return None, None, JSONResponse(
            {"code": "unknown", "detail": "Não encontrei esta matrícula. Confira com o professor."},
            status_code=404, headers={"Cache-Control": "no-store"})
    return portal, students, None


@router.post("/portal/{token}/lookup")
async def portal_lookup(
    token: str, body: LookupBody, request: Request, db: AsyncSession = Depends(get_db),
):
    portal, students, error = await _students_or_error(request, db, token, body.enrollment)
    if error is not None:
        return error
    data = await svc.build_portal(db, portal.tutor_id, students, body.enrollment)
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


@router.post("/portal/{token}/material")
async def portal_material(
    token: str, body: MaterialBody, request: Request, db: AsyncSession = Depends(get_db),
):
    portal, students, error = await _students_or_error(request, db, token, body.enrollment)
    if error is not None:
        return error
    material = await svc.material_text(db, portal.tutor_id, students, body.material_id)
    if material is None:
        raise HTTPException(404, "Material não encontrado.")
    return JSONResponse({"title": material.title, "content": material.content},
                        headers={"Cache-Control": "no-store"})
