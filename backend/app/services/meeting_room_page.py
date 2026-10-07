"""A página que o participante abre: entrar na sala, ver e ouvir os outros, e ter a fala
transcrita.

Uma página só, sem login, em HTML puro com o cliente do LiveKit vindo de uma versão
fixa de CDN. O áudio de cada pessoa é detectado ali mesmo (só há envio quando a pessoa
fala) e mandado em pedaços curtos para o servidor transcrever; o pedaço é descartado
depois de transcrito. Nada é gravado.
"""

from __future__ import annotations

import json
from html import escape

LIVEKIT_CLIENT_URL = (
    "https://cdn.jsdelivr.net/npm/livekit-client@2.22.3/dist/livekit-client.umd.js"
)

_STYLE = """
*{box-sizing:border-box}
body{margin:0;background:#0b1220;color:#e5ecf6;font:16px system-ui,-apple-system,Segoe UI,sans-serif;min-height:100vh}
.brand{font-size:12px;font-weight:900;letter-spacing:2px;color:#7dd3fc}
h1{font-size:22px;margin:8px 0 4px}
p{margin:6px 0;color:#9fb3c8;font-size:14px}
#join{min-height:100vh;display:grid;place-items:center;padding:20px}
.card{width:min(460px,100%);background:#111b2e;border:1px solid #1e3a5f;border-radius:14px;padding:28px}
label{display:block;margin:14px 0 6px;font-size:13px;font-weight:700;color:#cbd5e1}
input[type=text]{width:100%;padding:12px 14px;border:2px solid #25456b;border-radius:10px;font-size:16px;background:#0b1220;color:#e5ecf6}
.consent{display:flex;gap:10px;align-items:flex-start;margin:16px 0 4px;font-size:13px;color:#cbd5e1;line-height:1.4}
.consent input{margin-top:3px}
button{border:0;border-radius:10px;font-weight:800;letter-spacing:.6px;cursor:pointer}
.primary{width:100%;margin-top:16px;padding:14px;background:#0ea5e9;color:#04121f}
.primary:disabled{opacity:.5;cursor:default}
.msg{margin:14px 0 0;padding:10px 12px;border-radius:8px;font-size:14px;font-weight:600}
.err{background:#3b1219;color:#fca5a5}
.info{background:#0f2a3d;color:#7dd3fc}
input:focus-visible,button:focus-visible{outline:3px solid #38bdf8;outline-offset:2px}
#room{display:flex;flex-direction:column;height:100vh}
#bar{display:flex;align-items:center;gap:12px;padding:10px 16px;border-bottom:1px solid #1e3a5f;background:#0f1a2d}
#bar .title{flex:1;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#status{font-size:12px;color:#9fb3c8}
#status.live{color:#86efac}
#grid{flex:1;display:grid;gap:8px;padding:8px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));grid-auto-rows:minmax(160px,1fr);overflow:auto}
.tile{position:relative;background:#06101d;border:2px solid transparent;border-radius:10px;overflow:hidden;min-height:150px}
.tile.speaking{border-color:#22c55e}
.tile.screen{grid-column:1/-1;grid-row:span 2}
.tile video{width:100%;height:100%;object-fit:cover;background:#000}
.tile.screen video{object-fit:contain}
.tile .who{position:absolute;left:8px;bottom:8px;background:#000a;padding:3px 8px;border-radius:6px;font-size:13px}
.tile .avatar{position:absolute;inset:0;display:grid;place-items:center;font-size:42px;font-weight:800;color:#38bdf8;background:#0d1b30}
.tile.hasvideo .avatar{display:none}
#controls{display:flex;justify-content:center;gap:10px;padding:12px;border-top:1px solid #1e3a5f;background:#0f1a2d;flex-wrap:wrap}
#controls button{padding:11px 16px;background:#1e3a5f;color:#e5ecf6}
#controls button.off{background:#7f1d1d}
#controls button.leave{background:#b91c1c}
#controls button.end{background:#92400e}
[hidden]{display:none!important}
"""

_SCRIPT = r"""
(function () {
  var TOKEN = __TOKEN__;
  var BASE = location.pathname.replace(/\/$/, "");
  var HOST_KEY = (new URLSearchParams(location.hash.replace(/^#/, ""))).get("host") || "";
  var $ = function (id) { return document.getElementById(id); };
  var S = { room: null, id: "", secret: "", host: false, leaving: false, timers: [],
            tx: null, queue: [], sending: false };

  function say(kind, text) {
    var box = $("msg");
    box.hidden = !text;
    box.className = "msg " + (kind || "");
    box.textContent = text || "";
  }
  async function api(path, body, form) {
    var init = { method: "POST" };
    if (form) { init.body = form; }
    else { init.headers = { "Content-Type": "application/json" }; init.body = JSON.stringify(body || {}); }
    var res = await fetch(BASE + path, init);
    var data = {};
    try { data = await res.json(); } catch (e) {}
    if (!res.ok) { var err = new Error(data.detail || "Não foi possível concluir. Tente de novo."); err.status = res.status; err.code = data.code; throw err; }
    return data;
  }

  // --- tiles ---------------------------------------------------------------------
  function tile(id, name, screen) {
    var el = document.querySelector('[data-tile="' + id + '"]');
    if (el) return el;
    el = document.createElement("div");
    el.className = "tile" + (screen ? " screen" : "");
    el.setAttribute("data-tile", id);
    var av = document.createElement("div"); av.className = "avatar";
    av.textContent = (name || "?").trim().charAt(0).toUpperCase();
    var v = document.createElement("video"); v.autoplay = true; v.playsInline = true;
    var who = document.createElement("div"); who.className = "who"; who.textContent = name || "";
    el.appendChild(v); el.appendChild(av); el.appendChild(who);
    $("grid").appendChild(el);
    return el;
  }
  function dropTile(id) { var el = document.querySelector('[data-tile="' + id + '"]'); if (el) el.remove(); }
  function attachVideo(id, name, track, screen, local) {
    var el = tile(id, name, screen);
    var v = el.querySelector("video");
    track.attach(v);
    v.muted = !!local;
    el.classList.add("hasvideo");
  }

  // --- sala ----------------------------------------------------------------------
  async function startRoom(data) {
    var LK = window.LivekitClient;
    if (!LK) throw new Error("Não consegui carregar o módulo de vídeo. Confira a internet e recarregue a página.");
    var room = new LK.Room({ adaptiveStream: true, dynacast: true });
    S.room = room;
    room.on(LK.RoomEvent.TrackSubscribed, function (track, pub, p) {
      if (track.kind === LK.Track.Kind.Audio) {
        var a = track.attach(); a.style.display = "none"; document.body.appendChild(a);
      } else if (pub.source === LK.Track.Source.ScreenShare) {
        attachVideo(p.identity + ":screen", (p.name || "") + " (tela)", track, true, false);
      } else {
        attachVideo(p.identity, p.name || p.identity, track, false, false);
      }
    });
    room.on(LK.RoomEvent.TrackUnsubscribed, function (track, pub, p) {
      track.detach();
      if (track.kind === LK.Track.Kind.Video) {
        if (pub.source === LK.Track.Source.ScreenShare) dropTile(p.identity + ":screen");
        else { var el = document.querySelector('[data-tile="' + p.identity + '"]'); if (el) el.classList.remove("hasvideo"); }
      }
    });
    room.on(LK.RoomEvent.ParticipantConnected, function (p) { tile(p.identity, p.name || p.identity); });
    room.on(LK.RoomEvent.ParticipantDisconnected, function (p) { dropTile(p.identity); dropTile(p.identity + ":screen"); });
    room.on(LK.RoomEvent.ActiveSpeakersChanged, function (list) {
      document.querySelectorAll(".tile.speaking").forEach(function (t) { t.classList.remove("speaking"); });
      list.forEach(function (p) { var el = document.querySelector('[data-tile="' + p.identity + '"]'); if (el) el.classList.add("speaking"); });
    });
    room.on(LK.RoomEvent.LocalTrackPublished, function (pub, p) {
      if (pub.source === LK.Track.Source.Camera && pub.track) attachVideo(p.identity, p.name || "Você", pub.track, false, true);
      if (pub.source === LK.Track.Source.ScreenShare && pub.track) attachVideo(p.identity + ":screen", "Sua tela", pub.track, true, true);
      if (pub.source === LK.Track.Source.Microphone && pub.track) bindTranscription(pub.track.mediaStreamTrack);
    });
    room.on(LK.RoomEvent.LocalTrackUnpublished, function (pub, p) {
      if (pub.source === LK.Track.Source.Camera) { var el = document.querySelector('[data-tile="' + p.identity + '"]'); if (el) el.classList.remove("hasvideo"); }
      if (pub.source === LK.Track.Source.ScreenShare) dropTile(p.identity + ":screen");
    });
    room.on(LK.RoomEvent.Disconnected, function () { if (!S.leaving) finish("Você foi desconectado da sala."); });

    $("join").hidden = true; $("room").hidden = false;
    $("title").textContent = data.title || "Reunião";
    tile(data.identity, data.name + " (você)");
    await room.connect(data.livekit_url, data.livekit_token);
    try { await room.localParticipant.enableCameraAndMicrophone(); }
    catch (e) {
      try { await room.localParticipant.setMicrophoneEnabled(true); setStatus("Sem câmera: entrou só com o áudio."); }
      catch (e2) { setStatus("Sem acesso ao microfone: libere o microfone no navegador para ser ouvido e transcrito."); }
    }
    room.remoteParticipants.forEach(function (p) { tile(p.identity, p.name || p.identity); });
    if (data.is_host) $("end").hidden = false;
    S.timers.push(setInterval(beat, 15000));
  }

  function setStatus(text, live) { var s = $("status"); s.textContent = text; s.className = live ? "live" : ""; }

  async function beat() {
    try {
      var r = await api("/heartbeat", { participant_id: S.id, secret: S.secret });
      if (r.ended) finish("A reunião foi encerrada.");
    } catch (e) { if (e.status === 403 || e.status === 409) finish(e.message); }
  }

  function stopAll() {
    S.timers.forEach(clearInterval); S.timers = [];
    if (S.tx) { S.tx.stop(); S.tx = null; }
  }
  function finish(text) {
    S.leaving = true; stopAll();
    try { if (S.room) S.room.disconnect(); } catch (e) {}
    $("room").hidden = true; $("join").hidden = false;
    $("form").hidden = true; $("bye").hidden = false;
    $("byeText").textContent = text;
  }

  // --- transcrição (só a fala; áudio nunca é guardado) -------------------------------
  function pickMime() {
    var list = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
    for (var i = 0; i < list.length; i++) {
      if (window.MediaRecorder && MediaRecorder.isTypeSupported(list[i])) return list[i];
    }
    return "";
  }
  function bindTranscription(mediaTrack) {
    if (S.tx) S.tx.stop();
    if (!mediaTrack || !window.MediaRecorder) { setStatus("Este navegador não transcreve a fala."); return; }
    var AC = window.AudioContext || window.webkitAudioContext;
    var ctx = new AC(), stream = new MediaStream([mediaTrack]);
    var an = ctx.createAnalyser(); an.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(an);
    var buf = new Uint8Array(an.fftSize), mime = pickMime();
    var rec = null, chunks = [], t0 = 0, lastVoice = 0, voice = 0;
    function level() {
      an.getByteTimeDomainData(buf);
      var sum = 0; for (var i = 0; i < buf.length; i++) { var v = (buf[i] - 128) / 128; sum += v * v; }
      return Math.sqrt(sum / buf.length);
    }
    function stopRec() { if (rec && rec.state !== "inactive") rec.stop(); }
    function startRec() {
      chunks = [];
      try { rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream); } catch (e) { rec = null; return; }
      var mine = rec;
      mine.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
      mine.onstop = function () {
        var dur = Date.now() - t0;
        var blob = new Blob(chunks, { type: mine.mimeType || mime || "audio/webm" });
        if (rec === mine) rec = null;
        if (dur >= 700 && blob.size > 0) enqueue(blob, dur);
      };
      mine.start(); t0 = Date.now();
    }
    var timer = setInterval(function () {
      if (ctx.state === "suspended") ctx.resume();
      var now = Date.now(), lvl = level();
      if (lvl > 0.02) { voice++; lastVoice = now; if (!rec && voice >= 2) startRec(); }
      else voice = 0;
      if (rec && (now - lastVoice > 900 || now - t0 > 20000)) stopRec();
    }, 60);
    S.tx = { stop: function () { clearInterval(timer); stopRec(); try { ctx.close(); } catch (e) {} } };
    setStatus("Ao vivo · sua fala é transcrita (áudio e vídeo não são gravados)", true);
  }
  function enqueue(blob, dur) {
    S.queue.push({ blob: blob, dur: dur });
    if (S.queue.length > 6) S.queue.shift();
    drain();
  }
  async function drain() {
    if (S.sending) return; S.sending = true;
    while (S.queue.length) {
      var item = S.queue.shift();
      var form = new FormData();
      form.append("participant_id", S.id); form.append("secret", S.secret);
      form.append("duration_ms", String(item.dur));
      var ext = /mp4/.test(item.blob.type) ? "m4a" : /ogg/.test(item.blob.type) ? "ogg" : "webm";
      form.append("file", item.blob, "fala." + ext);
      try { await api("/audio", null, form); }
      catch (e) { if (e.status === 503) setStatus("Transcrição indisponível no servidor agora: a reunião segue, sem transcrever."); if (e.status === 403 || e.status === 409) { S.queue = []; } }
    }
    S.sending = false;
  }

  // --- ações -----------------------------------------------------------------------
  $("enter").onclick = async function () {
    say("", "");
    var name = $("name").value.trim(), enr = $("enrollment").value.trim();
    if (!$("consent").checked) { say("err", "Para entrar, aceite que a sua fala será transcrita."); return; }
    if (!name && !enr) { say("err", "Digite o seu nome (ou a matrícula)."); return; }
    $("enter").disabled = true; $("enter").textContent = "ENTRANDO...";
    try {
      var data = await api("/join", { name: name, enrollment: enr, consent: true, host_key: HOST_KEY });
      S.id = data.participant_id; S.secret = data.secret; S.host = data.is_host;
      await startRoom(data);
    } catch (e) {
      $("join").hidden = false; $("room").hidden = true; say("err", e.message);
    }
    $("enter").disabled = false; $("enter").textContent = "ENTRAR NA REUNIÃO";
  };
  function toggle(btn, fn, onLabel, offLabel) {
    btn.onclick = async function () {
      if (!S.room) return;
      var lp = S.room.localParticipant, on = btn.classList.contains("off");
      try { await fn(lp, on); btn.classList.toggle("off", !on); btn.textContent = on ? onLabel : offLabel; } catch (e) { setStatus(e.message); }
    };
  }
  toggle($("mic"), function (lp, on) { return lp.setMicrophoneEnabled(on); }, "Microfone ligado", "Microfone desligado");
  toggle($("cam"), function (lp, on) { return lp.setCameraEnabled(on); }, "Câmera ligada", "Câmera desligada");
  $("share").onclick = async function () {
    if (!S.room) return;
    var lp = S.room.localParticipant, on = !lp.isScreenShareEnabled;
    try { await lp.setScreenShareEnabled(on); $("share").textContent = on ? "Parar de compartilhar" : "Compartilhar tela"; } catch (e) { setStatus("Não foi possível compartilhar a tela."); }
  };
  $("leave").onclick = async function () {
    S.leaving = true;
    try { await api("/leave", { participant_id: S.id, secret: S.secret }); } catch (e) {}
    finish("Você saiu da reunião.");
  };
  $("end").onclick = async function () {
    if (!confirm("Encerrar a reunião para todos?")) return;
    try { await api("/end", { participant_id: S.id, secret: S.secret }); S.leaving = true; finish("Reunião encerrada para todos."); }
    catch (e) { setStatus(e.message); }
  };
  window.addEventListener("pagehide", function () {
    if (S.id && !S.leaving && navigator.sendBeacon) {
      navigator.sendBeacon(BASE + "/leave", new Blob([JSON.stringify({ participant_id: S.id, secret: S.secret })], { type: "application/json" }));
    }
  });
})();
"""


def render_closed_page(message: str) -> str:
    return (
        f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Reunião</title>
<style>{_STYLE}</style></head><body><div id="join"><div class="card">
<div class="brand">MODO EDUCAÇÃO</div><h1>Reunião</h1><p>{escape(message)}</p>
</div></div></body></html>"""
    )


def render_room_page(*, token: str, title: str, guests_allowed: bool) -> str:
    """A página de entrada e da sala, para o participante e para o professor."""
    heading = escape(title.strip() or "Reunião online")
    enrollment_hint = (
        "Matrícula (opcional para convidados)" if guests_allowed
        else "Matrícula (obrigatória)")
    token_json = json.dumps(token).replace("</", "<\\/")
    script = _SCRIPT.replace("__TOKEN__", token_json)
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{heading}</title>
<style>{_STYLE}</style></head><body>
<div id="join"><div class="card">
  <div class="brand">MODO EDUCAÇÃO</div>
  <h1>{heading}</h1>
  <div id="form">
    <p>Reunião com vídeo e áudio. <b>Nada é gravado</b>: só a sua fala é transcrita, com o seu nome.</p>
    <label for="name">Seu nome</label>
    <input type="text" id="name" maxlength="80" autocomplete="name" placeholder="Nome e sobrenome">
    <label for="enrollment">{escape(enrollment_hint)}</label>
    <input type="text" id="enrollment" maxlength="64" autocomplete="off" placeholder="Sua matrícula">
    <label class="consent"><input type="checkbox" id="consent">
      <span>Estou de acordo que a minha fala seja transcrita nesta reunião.
      O áudio e o vídeo não são gravados nem guardados.</span></label>
    <button type="button" class="primary" id="enter">ENTRAR NA REUNIÃO</button>
    <div id="msg" class="msg" hidden role="alert"></div>
  </div>
  <div id="bye" hidden><p id="byeText"></p><p>Você já pode fechar esta janela.</p></div>
</div></div>
<div id="room" hidden>
  <div id="bar"><div class="title" id="title"></div><div id="status">Conectando...</div></div>
  <div id="grid"></div>
  <div id="controls">
    <button type="button" id="mic">Microfone ligado</button>
    <button type="button" id="cam">Câmera ligada</button>
    <button type="button" id="share">Compartilhar tela</button>
    <button type="button" class="leave" id="leave">Sair</button>
    <button type="button" class="end" id="end" hidden>Encerrar para todos</button>
  </div>
</div>
<noscript><p style="padding:20px">Ative o JavaScript para entrar na reunião.</p></noscript>
<script src="{LIVEKIT_CLIENT_URL}"></script>
<script>{script}</script>
</body></html>"""
