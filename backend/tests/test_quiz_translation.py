"""Idioma do aluno no quiz: a pergunta e as alternativas tambem sao traduzidas.

O que estes testes guardam veio de uso real: o aluno escolhia ingles ou espanhol
e lia a interface no idioma escolhido, mas a pergunta e as alternativas
continuavam em portugues. E o idioma so podia ser trocado depois de entrar, nao
na hora de informar o nome.

Regras que mantem o quiz correto: a alternativa e identificada pela letra (o
gabarito nao muda com a traducao), traducao que nao fecha com a pergunta
original e descartada, e falha do modelo nunca deixa o aluno sem pergunta.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import (
    QuestionModel,
    QuestionTranslationModel,
    QuizModel,
    QuizParticipantModel,
    StudentAnswerModel,
    get_db,
)
from app.core.security import get_current_user
from app.models.schemas import LLMResponse
from app.routers import education, quiz_play, quiz_websocket
from app.services import quiz_generator_service, quiz_translation_service

USER = {"uid": "u1", "tutor_id": "t1"}

QUIZ = "quiz-idiomas"
BASE = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
OPCOES = (
    '[{"label": "A", "texto": "Primeira forma normal", "correta": false},'
    ' {"label": "B", "texto": "Terceira forma normal", "correta": true}]'
)
PERGUNTA = "Qual forma normal elimina dependência transitiva?"
PLAY = f"/education/quiz/{QUIZ}/play"


def _questoes():
    return [
        QuestionModel(id="p1", quiz_id=QUIZ, tipo="multipla_escolha",
                      enunciado=PERGUNTA, opcoes=OPCOES, resposta_correta="B",
                      created_at=BASE),
        QuestionModel(id="p2", quiz_id=QUIZ, tipo="multipla_escolha",
                      enunciado="Segunda pergunta?", opcoes=OPCOES,
                      resposta_correta="B", created_at=BASE + timedelta(seconds=1)),
    ]


def _perguntas_do_prompt(prompt: str) -> list[dict]:
    trecho = prompt.split("**Perguntas:**\n", 1)[1].split("\n\nResponda somente", 1)[0]
    return json.loads(trecho)


def traduzir_para_ingles(prompt: str) -> str:
    """Modelo de mentira: prefixa "[EN]" em tudo, mantendo ids e letras."""
    itens = []
    for pergunta in _perguntas_do_prompt(prompt):
        itens.append({
            "id": pergunta["id"],
            "enunciado": f"[EN] {pergunta['enunciado']}",
            "opcoes": [
                {"label": o["label"], "texto": f"[EN] {o['texto']}"}
                for o in pergunta["opcoes"]
            ],
        })
    return json.dumps({"traducoes": itens})


@pytest.fixture
def aula(monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/quiz.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed():
        async with engine.begin() as conn:
            for model in (QuizModel, QuestionModel, StudentAnswerModel,
                          QuizParticipantModel, QuestionTranslationModel):
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add(QuizModel(id=QUIZ, tutor_id="t1", lesson_id="l1", titulo="Modelagem",
                             status="open", live_phase="lobby", total_questoes=2))
            db.add_all(_questoes())
            await db.commit()

    asyncio.run(seed())

    chamadas: list[str] = []
    resposta = {"conteudo": traduzir_para_ingles, "erro": None}

    async def dispatch_falso(llm, prompt, history, system, *, max_tokens=None):
        chamadas.append(prompt)
        if resposta["erro"]:
            return LLMResponse(llm=llm, content=resposta["erro"], is_error=True)
        return LLMResponse(llm=llm, content=resposta["conteudo"](prompt))

    async def candidatos(_preferido=None):
        return ["modelo-falso"]

    async def runtime_falso(_tutor_id):
        return object()

    monkeypatch.setattr(quiz_translation_service, "dispatch_single", dispatch_falso)
    monkeypatch.setattr(quiz_generator_service, "candidate_llms", candidatos)
    monkeypatch.setattr(quiz_translation_service, "load_user_llm_runtime", runtime_falso)
    monkeypatch.setattr(quiz_translation_service, "activate_user_llms", lambda _r: None)
    monkeypatch.setattr(quiz_translation_service, "reset_user_llms", lambda _t: None)
    monkeypatch.setattr(quiz_translation_service, "AsyncSessionLocal", sessions)
    quiz_translation_service._in_flight.clear()
    quiz_translation_service._cooldown_until.clear()

    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(quiz_play.router)
    app.include_router(education.router)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: USER

    def stats():
        async def read():
            async with sessions() as db:
                return await quiz_websocket.get_quiz_stats(QUIZ, db)

        return asyncio.run(read())

    def abrir(question_id="p1", fase="question"):
        async def update():
            async with sessions() as db:
                quiz = await db.get(QuizModel, QUIZ)
                quiz.live_phase = fase
                quiz.current_question_id = question_id
                quiz.question_started_at = datetime.now(timezone.utc)
                await db.commit()

        asyncio.run(update())

    def gravadas(idioma="en") -> dict:
        async def read():
            async with sessions() as db:
                return await quiz_translation_service.cached_translations(
                    db, ["p1", "p2"], idioma
                )

        return asyncio.run(read())

    def esperar_traducao(idioma="en", quantidade=2, limite=5.0):
        fim = time.monotonic() + limite
        while time.monotonic() < fim:
            if len(gravadas(idioma)) >= quantidade:
                return True
            time.sleep(0.05)
        return False

    with TestClient(app) as client:
        client.abrir = abrir
        client.stats = stats
        client.gravadas = gravadas
        client.esperar_traducao = esperar_traducao
        client.chamadas = chamadas
        client.resposta = resposta
        client.sessions = sessions
        yield client
    asyncio.run(engine.dispose())


def entrar(client, nome="Mariano", idioma="en"):
    return client.post(
        f"{PLAY}?lang=pt",
        data={"student_name": nome, "language": idioma},
        follow_redirects=False,
    )


# --- escolha do idioma na entrada -------------------------------------------


@pytest.mark.integration
def test_tela_de_entrada_deixa_escolher_o_idioma_junto_do_nome(aula):
    pagina = aula.get(f"{PLAY}?lang=pt").text

    assert 'name="student_name"' in pagina
    for codigo in ("pt", "es", "en"):
        assert f'name="language" value="{codigo}"' in pagina
    assert 'value="pt" checked' in pagina
    assert "Idioma do quiz" in pagina


@pytest.mark.integration
def test_tela_de_entrada_vem_no_idioma_escolhido_e_guarda_o_nome_digitado(aula):
    pagina = aula.get(f"{PLAY}?lang=es&name=Ana%20Souza").text

    assert 'value="es" checked' in pagina
    assert "Idioma del cuestionario" in pagina
    assert 'value="Ana Souza"' in pagina


@pytest.mark.integration
def test_nome_pre_preenchido_e_escapado(aula):
    pagina = aula.get(f"{PLAY}?lang=pt&name=%22%3E%3Cscript%3Ex%3C/script%3E").text

    assert "<script>x</script>" not in pagina


@pytest.mark.integration
def test_idioma_escolhido_na_entrada_vale_para_as_proximas_telas(aula):
    resposta = entrar(aula, idioma="en")

    assert resposta.status_code == 303
    assert resposta.headers["location"] == "play?lang=en"

    # Sem ?lang= na URL: quem manda e o idioma escolhido ao entrar, nao o do
    # navegador.
    espera = aula.get(PLAY).text
    assert "Waiting for the teacher" in espera


@pytest.mark.integration
def test_idioma_da_entrada_vence_o_da_url(aula):
    resposta = aula.post(
        f"{PLAY}?lang=pt",
        data={"student_name": "Ana", "language": "es"},
        follow_redirects=False,
    )

    assert resposta.headers["location"] == "play?lang=es"


@pytest.mark.integration
def test_idioma_invalido_na_entrada_cai_no_da_url(aula):
    resposta = aula.post(
        f"{PLAY}?lang=es",
        data={"student_name": "Ana", "language": "klingon"},
        follow_redirects=False,
    )

    assert resposta.headers["location"] == "play?lang=es"


# --- traducao da pergunta e das alternativas --------------------------------


@pytest.mark.integration
def test_pergunta_e_alternativas_aparecem_no_idioma_escolhido(aula):
    entrar(aula, idioma="en")
    assert aula.esperar_traducao()
    aula.abrir("p1")

    pagina = aula.get(PLAY).text

    assert f"[EN] {PERGUNTA}" in pagina
    assert "[EN] Terceira forma normal" in pagina
    assert "Your Answer" in pagina or "CONFIRM ANSWER" in pagina


@pytest.mark.integration
def test_traducao_nao_muda_o_valor_enviado_nem_a_correcao(aula):
    entrar(aula, idioma="en")
    assert aula.esperar_traducao()
    aula.abrir("p1")

    pagina = aula.get(PLAY).text

    # O que o aluno envia e a letra: a traducao so troca o texto exibido.
    assert 'value="A"' in pagina and 'value="B"' in pagina

    aula.post(f"{PLAY}?lang=en", data={"question_id": "p1", "answer": "B"},
              follow_redirects=False)

    async def respostas():
        async with aula.sessions() as db:
            from sqlalchemy import select
            return (await db.execute(select(StudentAnswerModel))).scalars().all()

    gravadas = asyncio.run(respostas())
    assert [(r.resposta, r.correta) for r in gravadas] == [("B", True)]


@pytest.mark.integration
def test_aluno_em_portugues_nao_chama_o_modelo(aula):
    entrar(aula, idioma="pt")
    aula.abrir("p1")

    pagina = aula.get(f"{PLAY}?lang=pt").text

    assert PERGUNTA in pagina
    assert aula.chamadas == []


@pytest.mark.integration
def test_traducao_e_gravada_uma_vez_e_a_turma_inteira_le_a_mesma(aula):
    entrar(aula, "Ana", "en")
    assert aula.esperar_traducao()
    chamadas_ate_aqui = len(aula.chamadas)

    aula.cookies.clear()
    entrar(aula, "Bia", "en")
    aula.abrir("p1")
    aula.get(PLAY)
    aula.get(PLAY)

    assert len(aula.chamadas) == chamadas_ate_aqui, "a segunda aluna nao paga outra chamada"


@pytest.mark.integration
def test_traducao_comeca_na_entrada_e_respeita_a_ordem_do_quiz(aula):
    entrar(aula, idioma="es")

    # Sem o professor ter aberto pergunta nenhuma: ja esta pronta ao abrir.
    assert aula.esperar_traducao("es")
    assert "Spanish" not in aula.chamadas[0]
    assert "espanhol" in aula.chamadas[0]


@pytest.mark.integration
def test_idioma_trocado_pelo_seletor_da_pergunta_tambem_traduz(aula):
    entrar(aula, idioma="pt")
    aula.abrir("p1")

    # O aluno clica em "English" na tela da pergunta (?lang=en): a pergunta
    # ainda nao estava traduzida, e a tela espera o modelo.
    pagina = aula.get(f"{PLAY}?lang=en").text

    assert f"[EN] {PERGUNTA}" in pagina


@pytest.mark.integration
def test_modelo_fora_do_ar_deixa_o_aluno_com_a_pergunta_original(aula):
    aula.resposta["erro"] = "401 invalid api key"
    entrar(aula, idioma="en")
    aula.abrir("p1")

    resposta = aula.get(PLAY)

    assert resposta.status_code == 200
    assert PERGUNTA in resposta.text
    assert "[EN]" not in resposta.text
    # A interface continua no idioma escolhido.
    assert "Your Answer" in resposta.text or "CONFIRM ANSWER" in resposta.text


@pytest.mark.integration
def test_falha_da_traducao_nao_dispara_uma_chamada_a_cada_recarga(aula):
    aula.resposta["erro"] = "modelo fora do ar"
    entrar(aula, idioma="en")
    aula.abrir("p1")
    aula.get(PLAY)
    chamadas = len(aula.chamadas)

    for _ in range(5):
        aula.get(PLAY)

    assert len(aula.chamadas) == chamadas, (
        "a tela do aluno recarrega a cada 2s: sem pausa, cada recarga repetiria a chamada"
    )


@pytest.mark.integration
def test_ranking_mostra_a_pergunta_traduzida_quando_ja_ha_traducao(aula):
    entrar(aula, idioma="en")
    assert aula.esperar_traducao()
    aula.abrir("p1", fase="results")

    pagina = aula.get(PLAY).text

    assert f"[EN] {PERGUNTA}" in pagina


# --- validacao da traducao ---------------------------------------------------


def _modelo(id_="p1", opcoes=OPCOES):
    return QuestionModel(id=id_, quiz_id=QUIZ, tipo="multipla_escolha",
                         enunciado=PERGUNTA, opcoes=opcoes, resposta_correta="B")


def _traducao(opcoes, enunciado="Which normal form removes transitive dependency?"):
    return json.dumps({"traducoes": [
        {"id": "p1", "enunciado": enunciado, "opcoes": opcoes}
    ]})


@pytest.mark.unit
def test_traducao_valida_e_aceita_com_as_letras_originais():
    lidas = quiz_translation_service.parse_translations(
        _traducao([{"label": "a", "texto": "First"}, {"label": "B", "texto": "Third"}]),
        [_modelo()],
    )

    assert lidas["p1"]["opcoes"] == [
        {"label": "A", "texto": "First"},
        {"label": "B", "texto": "Third"},
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    "opcoes",
    [
        [{"label": "A", "texto": "First"}],
        [{"label": "A", "texto": "First"}, {"label": "C", "texto": "Third"}],
        [{"label": "A", "texto": "First"}, {"label": "B", "texto": "  "}],
        "texto solto",
    ],
    ids=["faltou-alternativa", "letra-trocada", "texto-vazio", "formato-errado"],
)
def test_traducao_que_nao_fecha_com_o_original_e_descartada(opcoes):
    assert quiz_translation_service.parse_translations(_traducao(opcoes), [_modelo()]) == {}


@pytest.mark.unit
def test_traducao_sem_enunciado_ou_com_id_desconhecido_e_descartada():
    boas = [{"label": "A", "texto": "First"}, {"label": "B", "texto": "Third"}]

    assert quiz_translation_service.parse_translations(
        _traducao(boas, enunciado="  "), [_modelo()]
    ) == {}
    assert quiz_translation_service.parse_translations(
        _traducao(boas), [_modelo(id_="outra")]
    ) == {}
    assert quiz_translation_service.parse_translations("sem json", [_modelo()]) == {}


@pytest.mark.unit
def test_so_idiomas_diferentes_do_original_sao_traduziveis():
    assert quiz_translation_service.is_translatable("en")
    assert quiz_translation_service.is_translatable("es")
    assert not quiz_translation_service.is_translatable("pt")
    assert not quiz_translation_service.is_translatable("fr")
    assert not quiz_translation_service.is_translatable(None)


# --- reserva pelo app do professor (Codex / Claude) --------------------------

ADMIN = f"/education/quiz/{QUIZ}/translation"


def esperar_desistir(idioma="en", limite=5.0):
    """Espera o servidor tentar traduzir e desistir (sem provedor)."""
    ids = ["p1", "p2"]
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if quiz_translation_service.backend_gave_up(ids, idioma):
            return True
        time.sleep(0.05)
    return False


@pytest.mark.integration
def test_painel_e_avisado_quando_o_servidor_nao_consegue_traduzir(aula):
    aula.resposta["erro"] = "nenhum provedor"
    entrar(aula, "Ana", "en")
    assert esperar_desistir()

    pendentes = aula.stats()["translations_pending"]

    assert pendentes == [
        {"language": "en", "students": 1, "missing": 2, "backend_failed": True}
    ]


@pytest.mark.integration
def test_painel_nao_e_avisado_de_aluno_em_portugues_nem_de_idioma_traduzido(aula):
    entrar(aula, "Ana", "pt")
    assert aula.stats()["translations_pending"] == []

    aula.cookies.clear()
    entrar(aula, "Bia", "en")
    assert aula.esperar_traducao()

    assert aula.stats()["translations_pending"] == []


@pytest.mark.integration
def test_idioma_do_aluno_e_gravado_na_entrada(aula):
    entrar(aula, "Ana", "es")

    async def ler():
        async with aula.sessions() as db:
            from sqlalchemy import select
            return (await db.execute(select(QuizParticipantModel))).scalars().all()

    assert [p.language for p in asyncio.run(ler())] == ["es"]


@pytest.mark.integration
def test_app_do_professor_recebe_so_o_que_falta_traduzir(aula):
    aula.resposta["erro"] = "nenhum provedor"
    entrar(aula, idioma="en")
    assert esperar_desistir()

    pedido = aula.get(f"{ADMIN}/prompt", params={"language": "en"})

    assert pedido.status_code == 200
    corpo = pedido.json()
    assert corpo["question_ids"] == ["p1", "p2"]
    assert "inglês" in corpo["prompt"]
    assert '"correta"' not in corpo["prompt"], "a traducao nao precisa do gabarito"
    assert corpo["system_prompt"]


@pytest.mark.integration
def test_traducao_do_agente_e_gravada_e_aparece_para_o_aluno(aula):
    aula.resposta["erro"] = "nenhum provedor"
    entrar(aula, idioma="en")
    assert esperar_desistir()
    prompt = aula.get(f"{ADMIN}/prompt", params={"language": "en"}).json()["prompt"]

    # O agente devolve o JSON cercado de markdown, como costuma fazer.
    enviado = aula.post(
        f"{ADMIN}/external",
        json={"language": "en", "content": f"```json\n{traduzir_para_ingles(prompt)}\n```"},
    )

    assert enviado.status_code == 200
    assert enviado.json() == {"quiz_id": QUIZ, "language": "en", "stored": 2, "missing": 0}
    assert aula.stats()["translations_pending"] == []

    aula.abrir("p1")
    assert f"[EN] {PERGUNTA}" in aula.get(PLAY).text


@pytest.mark.integration
def test_traducao_do_agente_que_nao_fecha_com_o_original_e_recusada(aula):
    ruim = json.dumps({"traducoes": [
        {"id": "p1", "enunciado": "Which?", "opcoes": [{"label": "A", "texto": "x"}]},
    ]})

    enviado = aula.post(f"{ADMIN}/external", json={"language": "en", "content": ruim})

    assert enviado.status_code == 422
    assert aula.gravadas() == {}


@pytest.mark.integration
def test_so_traduz_o_que_ainda_nao_estava_traduzido(aula):
    entrar(aula, idioma="en")
    assert aula.esperar_traducao()

    sem_o_que_traduzir = aula.get(f"{ADMIN}/prompt", params={"language": "en"})
    assert sem_o_que_traduzir.status_code == 409

    # Reenviar a mesma traducao nao duplica nem dispara erro de unicidade.
    prompt_completo = json.dumps({"traducoes": [
        {"id": "p1", "enunciado": "outra", "opcoes": [
            {"label": "A", "texto": "x"}, {"label": "B", "texto": "y"}]},
    ]})
    reenvio = aula.post(f"{ADMIN}/external", json={"language": "en", "content": prompt_completo})
    assert reenvio.status_code == 422, "p1 ja tinha traducao: nada novo foi gravado"
    assert aula.gravadas()["p1"]["enunciado"].startswith("[EN]")


@pytest.mark.integration
def test_idioma_sem_traducao_e_quiz_de_outro_professor_sao_recusados(aula):
    assert aula.get(f"{ADMIN}/prompt", params={"language": "pt"}).status_code == 400
    assert aula.get(f"{ADMIN}/prompt", params={"language": "fr"}).status_code == 400
    assert aula.post(
        f"{ADMIN}/external", json={"language": "pt", "content": "{}"}
    ).status_code == 400

    aula.app.dependency_overrides[get_current_user] = lambda: {"uid": "u2", "tutor_id": "outro"}
    assert aula.get(f"{ADMIN}/prompt", params={"language": "en"}).status_code == 404
    assert aula.post(
        f"{ADMIN}/external", json={"language": "en", "content": "{}"}
    ).status_code == 404


# --- acessibilidade da tela do aluno -----------------------------------------


@pytest.mark.integration
def test_pergunta_traduzida_declara_o_idioma_dela(aula):
    entrar(aula, idioma="en")
    assert aula.esperar_traducao()
    aula.abrir("p1")

    pagina = aula.get(PLAY).text

    assert '<html lang="en">' in pagina
    assert f'<legend class="question-text" lang="en">[EN] {PERGUNTA}</legend>' in pagina
    assert 'lang="en">[EN] Terceira forma normal</label>' in pagina


@pytest.mark.integration
def test_pergunta_que_ficou_em_portugues_nao_se_declara_em_ingles(aula):
    """Traducao falhou: a interface segue em ingles, mas o texto da pergunta e
    portugues. Sem declarar isso, o leitor de tela le portugues com voz inglesa
    e o navegador nao oferece traduzir o trecho certo."""
    aula.resposta["erro"] = "401 invalid api key"
    entrar(aula, idioma="en")
    aula.abrir("p1")

    pagina = aula.get(PLAY).text

    assert '<html lang="en">' in pagina
    assert f'<legend class="question-text" lang="pt-BR">{PERGUNTA}</legend>' in pagina
    assert 'lang="pt-BR">Terceira forma normal</label>' in pagina


@pytest.mark.integration
def test_pergunta_em_portugues_declara_pt_br(aula):
    entrar(aula, idioma="pt")
    aula.abrir("p1")

    pagina = aula.get(f"{PLAY}?lang=pt").text

    assert '<html lang="pt-BR">' in pagina
    assert f'<legend class="question-text" lang="pt-BR">{PERGUNTA}</legend>' in pagina


@pytest.mark.integration
def test_alternativas_ficam_agrupadas_sob_a_pergunta(aula):
    entrar(aula, idioma="pt")
    aula.abrir("p1")

    pagina = aula.get(f"{PLAY}?lang=pt").text

    # fieldset/legend e o que liga a pergunta ao grupo de opcoes para o leitor
    # de tela: sem ele, cada opcao e lida sem dizer a que pergunta pertence.
    inicio = pagina.index('<fieldset class="choices">')
    fim = pagina.index("</fieldset>")
    grupo = pagina[inicio:fim]
    assert "<legend" in grupo
    assert grupo.count('type="radio"') == 2
    assert 'name="answer"' in grupo


@pytest.mark.integration
def test_seletor_de_idioma_da_pergunta_identifica_cada_idioma_e_o_atual(aula):
    entrar(aula, idioma="es")
    aula.abrir("p1")

    pagina = aula.get(f"{PLAY}?lang=es").text

    assert '<a href="?lang=es" lang="es" aria-current="true">Español</a>' in pagina
    assert '<a href="?lang=en" lang="en">English</a>' in pagina
    assert '<a href="?lang=pt" lang="pt-BR">Português</a>' in pagina
    assert 'aria-label="Idioma"' in pagina


@pytest.mark.integration
def test_tela_de_entrada_e_navegavel_por_teclado_e_leitor_de_tela(aula):
    pagina = aula.get(f"{PLAY}?lang=pt").text

    # Idioma como grupo com legenda, nao um paragrafo solto.
    assert '<fieldset class="langs"><legend>Idioma do quiz</legend>' in pagina
    # Os botoes de idioma ficam escondidos da vista, nao do teclado: tem de
    # existir foco visivel, e nenhum `pointer-events:none`/`display:none`.
    assert ".lang:focus-within{outline:3px solid" in pagina
    assert "display:none" not in pagina.split("<style>")[1].split("</style>")[0]
    # Campo do nome com nome acessivel (placeholder sozinho nao conta).
    assert 'aria-label="Seu nome"' in pagina
    assert 'autocomplete="name"' in pagina
    # Cada idioma e lido no proprio idioma.
    assert 'class="lang on" lang="pt-BR"' in pagina
    assert 'lang="es"' in pagina and 'lang="en"' in pagina


@pytest.mark.integration
def test_opcao_e_botoes_tem_foco_visivel_e_animacao_respeita_preferencia(aula):
    entrar(aula, idioma="pt")
    aula.abrir("p1")

    pagina = aula.get(f"{PLAY}?lang=pt").text

    assert ".option:focus-within{" in pagina
    assert ".btn-primary:focus-visible" in pagina
    assert "prefers-reduced-motion:reduce" in pagina


@pytest.mark.integration
def test_ranking_declara_o_idioma_real_da_pergunta(aula):
    aula.resposta["erro"] = "modelo fora do ar"
    entrar(aula, idioma="en")
    aula.abrir("p1", fase="results")

    pagina = aula.get(PLAY).text

    assert f'<div class="question" lang="pt-BR">{PERGUNTA}</div>' in pagina
