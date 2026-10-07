"""Dois navegadores (professor e aluno) numa sala de verdade: video, fala transcrita e encerrar."""
import json, re, sys, time, urllib.request
from playwright.sync_api import sync_playwright

API = "http://localhost:8000"


def http(method, path, body=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"{}")


def check(cond, msg):
    print(("OK   " if cond else "FALHA"), msg, flush=True)
    if not cond:
        raise SystemExit(1)


room = http("POST", "/education/meetings", {"title": "Mentoria E2E", "guests_allowed": True})
host_key = room["host_path"].split("#host=")[1]
print("sala criada", room["id"])

with sync_playwright() as p:
    browser = p.chromium.launch(args=[
        "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
        "--unsafely-treat-insecure-origin-as-secure=" + API,
        "--autoplay-policy=no-user-gesture-required",
    ])

    def abrir(url, nome, matricula=""):
        ctx = browser.new_context(permissions=["microphone", "camera"])
        page = ctx.new_page()
        page.on("pageerror", lambda e: print("  [erro na pagina]", e, flush=True))
        page.on("dialog", lambda d: d.accept())
        page.goto(url)
        page.fill("#name", nome)
        if matricula:
            page.fill("#enrollment", matricula)
        page.check("#consent")
        page.click("#enter")
        page.wait_for_selector("#room:not([hidden])", timeout=30000)
        return ctx, page

    prof_ctx, prof = abrir(API + room["join_path"] + "#host=" + host_key, "Prof. Mariano")
    aluno_ctx, aluno = abrir(API + room["join_path"], "ignorado", matricula="2024-0001")

    check(prof.is_visible("#end"), "professor ve o botao de encerrar para todos")
    check(not aluno.is_visible("#end"), "aluno nao ve o botao de encerrar")

    # Cada um enxerga o outro (tiles) e o servidor de midia entregou o video.
    deadline = time.time() + 40
    while time.time() < deadline:
        if prof.locator("[data-tile]").count() >= 2 and aluno.locator("[data-tile]").count() >= 2:
            break
        time.sleep(1)
    check(prof.locator("[data-tile]").count() >= 2, "professor enxerga os dois participantes")
    check(aluno.locator("[data-tile]").count() >= 2, "aluno enxerga os dois participantes")
    nomes_aluno = aluno.locator(".tile .who").all_inner_texts()
    print("  nomes no aluno:", nomes_aluno)
    check(any("Prof. Mariano" in n for n in nomes_aluno), "aluno ve o nome do professor")
    check(any("ANA SOUZA SANTOS" in n for n in nomes_aluno), "o nome do aluno vem do cadastro (matricula)")

    # Video remoto realmente tocando (frames chegando).
    time.sleep(6)
    diag = aluno.evaluate("""() => Array.from(document.querySelectorAll('.tile')).map(t => {
        const v = t.querySelector('video');
        return {tile: t.getAttribute('data-tile').slice(0, 8), who: t.querySelector('.who').textContent,
                hasvideo: t.classList.contains('hasvideo'), w: v.videoWidth, h: v.videoHeight,
                paused: v.paused, ready: v.readyState, muted: v.muted, src: !!v.srcObject,
                tracks: v.srcObject ? v.srcObject.getTracks().map(x => x.kind + ':' + x.readyState + ':' + x.muted) : []};
    })""")
    print("  diag aluno:", json.dumps(diag, ensure_ascii=False), flush=True)
    diag = prof.evaluate("""() => Array.from(document.querySelectorAll('.tile')).map(t => {
        const v = t.querySelector('video');
        return {who: t.querySelector('.who').textContent, w: v.videoWidth, paused: v.paused, ready: v.readyState,
                tracks: v.srcObject ? v.srcObject.getTracks().map(x => x.kind + ':' + x.readyState + ':' + x.muted) : []};
    })""")
    print("  diag professor:", json.dumps(diag, ensure_ascii=False), flush=True)
    deadline = time.time() + 30
    tocando = False
    while time.time() < deadline and not tocando:
        tocando = aluno.evaluate("""() => Array.from(document.querySelectorAll('.tile video'))
            .some(v => v.videoWidth > 0 && !v.paused)""")
        time.sleep(1)
    check(tocando, "o video do outro participante chega e toca")

    # A fala de cada um e detectada, enviada e vira trecho com o nome.
    deadline = time.time() + 60
    texto = []
    while time.time() < deadline:
        d = http("GET", f"/education/meetings/{room['id']}")
        texto = [t["text"] for t in d["transcript"]]
        if (any(t.startswith("Prof. Mariano: ") for t in texto)
                and any(t.startswith("ANA SOUZA SANTOS: ") for t in texto)):
            break
        time.sleep(2)
    print("  transcricao:", texto[:4])
    check(any(t.startswith("Prof. Mariano: ") for t in texto), "a fala do professor virou trecho com o nome dele")
    check(any(t.startswith("ANA SOUZA SANTOS: ") for t in texto), "a fala do aluno virou trecho com o nome do cadastro")

    d = http("GET", f"/education/meetings/{room['id']}")
    check(d["online"] == 2 and d["people"] == 2, "presenca: duas pessoas online")
    check(prof.inner_text("#status").startswith("Ao vivo"), "a pagina avisa que a fala esta sendo transcrita")

    # O aluno sai pelo botao: some da presenca online.
    aluno.click("#leave")
    aluno.wait_for_selector("#bye:not([hidden])", timeout=15000)
    time.sleep(1)
    d = http("GET", f"/education/meetings/{room['id']}")
    check(d["online"] == 1, "depois de sair, o aluno nao conta mais como online")

    # Professor encerra para todos.
    aluno2_ctx, aluno2 = abrir(API + room["join_path"], "Visitante Dois")
    prof.click("#end")
    prof.wait_for_selector("#bye:not([hidden])", timeout=15000)
    aluno2.wait_for_selector("#bye:not([hidden])", timeout=45000)
    msg = aluno2.inner_text("#byeText")
    print("  mensagem do visitante:", msg)
    check("encerrada" in msg or "desconectado" in msg, "o outro participante e desconectado quando o professor encerra")
    d = http("GET", f"/education/meetings/{room['id']}")
    check(d["status"] == "ended" and d["online"] == 0, "a sala consta como encerrada")
    browser.close()

print("E2E COMPLETO")
