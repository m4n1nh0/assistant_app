import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers import education
from app.routers import quiz_play
from app.routers import quiz_qrcode
from app.models.schemas import LLMResponse, QuizCreateRequest
from app.services import quiz_generator_service


def run(coro):
    return asyncio.run(coro)


class QuizDb:
    def __init__(self, lesson):
        self.lesson = lesson
        self.added = []
        self.commits = 0

    async def get(self, model, item_id):
        if model is education.LessonModel and item_id == self.lesson.id:
            return self.lesson
        return None

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.commits += 1

    async def execute(self, _stmt):
        return EmptyQuestionResult()


class EmptyQuestionResult:
    def scalars(self):
        return self

    def all(self):
        return []


class QuestionResult:
    def __init__(self, questions):
        self.questions = questions

    def scalars(self):
        return self

    def all(self):
        return self.questions


class QuizCloseDb:
    def __init__(self, quiz):
        self.quiz = quiz
        self.commits = 0
        self.refreshes = 0

    async def get(self, model, item_id):
        if model is education.QuizModel and item_id == self.quiz.id:
            return self.quiz
        return None

    async def execute(self, _stmt):
        return EmptyQuestionResult()

    async def commit(self):
        self.commits += 1

    async def refresh(self, _item):
        self.refreshes += 1


class QuizLiveDb(QuizCloseDb):
    def __init__(self, quiz, questions):
        super().__init__(quiz)
        self.questions = questions

    async def execute(self, _stmt):
        return QuestionResult(self.questions)


def _lesson(
    status="closed",
    summary="Resumo da aula",
    lesson_id="lesson-1",
    title="Normalizacao",
):
    return SimpleNamespace(
        id=lesson_id,
        tutor_id="tutor-1",
        discipline="Banco de Dados",
        title=title,
        status=status,
        summary=summary,
    )


def _material(material_id="mat-1", title="Apostila", content="Conteudo do material"):
    return SimpleNamespace(
        id=material_id,
        tutor_id="tutor-1",
        discipline="Banco de Dados",
        title=title,
        filename=f"{title.lower()}.pdf",
        content=content,
    )


class MultiSourceDb:
    """Banco de mentira que resolve varias aulas e materiais de uma vez.

    A consulta de segmentos devolve os da ultima aula buscada: no gerador ela
    vem sempre logo depois do `get` daquela aula.
    """

    def __init__(self, lessons=(), materials=(), segments=None):
        self.lessons = {lesson.id: lesson for lesson in lessons}
        self.materials = {item.id: item for item in materials}
        self.segments = dict(segments or {})
        self.added = []
        self.commits = 0
        self._ultima_aula = None

    async def get(self, model, item_id):
        if model is education.LessonModel:
            self._ultima_aula = item_id
            return self.lessons.get(item_id)
        if model is education.MaterialModel:
            return self.materials.get(item_id)
        return None

    async def execute(self, _stmt):
        trechos = [
            SimpleNamespace(text=texto)
            for texto in self.segments.get(self._ultima_aula, [])
        ]
        return QuestionResult(trechos)

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.commits += 1

    def fontes(self):
        return [
            item for item in self.added
            if isinstance(item, education.QuizSourceModel)
        ]


def test_quiz_gera_de_aula_em_andamento(monkeypatch):
    """Exigir aula encerrada matava o quiz relampago no meio da aula.

    E ali que ele mais serve: o professor explica, aplica tres perguntas e ve na
    hora quem nao acompanhou. O que decide se a aula entra e ter texto - resumo
    ou transcricao ja gravada -, nao o status da gravacao.
    """
    capturado = {}

    async def fake_generate_quiz(**kwargs):
        capturado.update(kwargs)
        return {
            "tempo_estimado": 5,
            "questoes": [
                {
                    "tipo": "multipla_escolha",
                    "enunciado": "O que foi dito ate agora?",
                    "opcoes": [
                        {"label": "A", "texto": "Normalizacao", "correta": True},
                        {"label": "B", "texto": "Indice"},
                    ],
                    "resposta_correta": "A",
                }
            ],
        }

    monkeypatch.setattr(
        education.quiz_generator_service, "generate_quiz", fake_generate_quiz
    )

    db = MultiSourceDb(
        lessons=[_lesson(status="recording", summary="")],
        segments={"lesson-1": ["O professor explicou normalizacao de tabelas."]},
    )
    resposta = run(
        education.generate_quiz_from_lesson(
            education.QuizCreateRequest(lesson_id="lesson-1"),
            user={"tutor_id": "tutor-1"},
            db=db,
        )
    )

    assert len(resposta.questoes) == 1
    # Sem resumo ainda: o que vai para a IA e a transcricao do que foi gravado.
    assert "TRANSCRIÇÃO DA AULA" in capturado["resumo"]


def test_quiz_generation_uses_request_configuration(monkeypatch):
    captured = {}

    async def fake_generate_quiz(**kwargs):
        captured.update(kwargs)
        return {
            "tempo_estimado": 7,
            "questoes": [
                {
                    "tipo": "multipla_escolha",
                    "dificuldade": "dificil",
                    "enunciado": "A normalizacao reduz anomalias?",
                    "opcoes": [
                        {"label": "A", "texto": "Sim", "correta": True},
                        {"label": "B", "texto": "Não", "correta": False},
                    ],
                    "resposta_correta": "A",
                    "justificativa": "O resumo cita reducao de anomalias.",
                    "conceitos": ["normalizacao"],
                    "topico_origem": "Resumo",
                    "grounding_score": 0.91,
                    "verificado": True,
                }
            ],
        }

    monkeypatch.setattr(
        education.quiz_generator_service,
        "generate_quiz",
        fake_generate_quiz,
    )

    db = QuizDb(_lesson())
    response = run(
        education.generate_quiz_from_lesson(
            education.QuizCreateRequest(
                lesson_id="lesson-1",
                tipo_quiz="diagnostico",
                quantidade_questoes=3,
                tipos_questao=["verdadeiro_falso"],
                dificuldade="dificil",
                llm="gpt-4.1",
            ),
            user={"tutor_id": "tutor-1"},
            db=db,
        )
    )

    assert captured["tipo_quiz"] == "diagnostico"
    assert captured["quantidade_questoes"] == 3
    assert captured["tipos_questao"] == ["multipla_escolha"]
    assert captured["dificuldade"] == "dificil"
    assert captured["llm"] == "gpt-4.1"
    assert "=== AULA: Normalizacao ===" in captured["resumo"]
    assert "Resumo da aula" in captured["resumo"]
    assert captured["disciplina"] == "Banco de Dados"
    quiz = next(item for item in db.added if isinstance(item, education.QuizModel))
    assert quiz.tipo_quiz == "diagnostico"
    assert quiz.status == "draft"
    assert quiz.total_questoes == 1
    assert response.status == "draft"

    # As alternativas precisam atravessar a serializacao: sem elas o professor
    # revisa um enunciado solto e a pergunta nao e respondivel pela turma.
    questao = response.questoes[0]
    assert [op.label for op in questao.opcoes] == ["A", "B"]
    assert [op.correta for op in questao.opcoes] == [True, False]
    assert response.tempo_estimado_resposta == 7
    assert response.questoes[0].dificuldade == "dificil"
    assert response.questoes[0].grounding_score == 0.91
    assert response.questoes[0].verificado is True
    assert db.commits == 1


def test_quiz_recusa_aula_sem_resumo_e_sem_transcricao():
    """Sem texto nenhum nao ha de onde tirar pergunta ancorada."""
    request = education.QuizCreateRequest(lesson_id="lesson-1")

    with pytest.raises(HTTPException) as error:
        run(
            education.generate_quiz_from_lesson(
                request,
                user={"tutor_id": "tutor-1"},
                db=QuizDb(_lesson(summary="   ")),
            )
        )

    assert error.value.status_code == 400
    assert "Normalizacao" in error.value.detail


def test_quiz_generation_rejects_empty_question_set(monkeypatch):
    async def fake_generate_quiz(**_kwargs):
        return {"tempo_estimado": 5, "questoes": []}

    monkeypatch.setattr(
        education.quiz_generator_service,
        "generate_quiz",
        fake_generate_quiz,
    )

    with pytest.raises(HTTPException) as error:
        run(
            education.generate_quiz_from_lesson(
                education.QuizCreateRequest(lesson_id="lesson-1"),
                user={"tutor_id": "tutor-1"},
                db=QuizDb(_lesson()),
            )
        )

    assert error.value.status_code == 502


def test_close_quiz_marks_status_and_closed_at():
    quiz = education.QuizModel(
        id="quiz-1",
        tutor_id="tutor-1",
        lesson_id="lesson-1",
        titulo="Quiz teste",
        tipo_quiz="pratica",
        status="open",
        total_questoes=0,
        tempo_estimado=0,
    )
    quiz.created_at = datetime.now(timezone.utc)

    db = QuizCloseDb(quiz)

    response = run(
        education.close_quiz(
            "quiz-1",
            user={"tutor_id": "tutor-1"},
            db=db,
        )
    )

    assert quiz.status == "closed"
    assert quiz.closed_at is not None
    assert response.status == "closed"
    assert response.closed_at == quiz.closed_at
    assert db.commits == 1
    assert db.refreshes == 1


def test_publish_quiz_marks_status_open():
    quiz = education.QuizModel(
        id="quiz-1",
        tutor_id="tutor-1",
        lesson_id="lesson-1",
        titulo="Quiz teste",
        tipo_quiz="pratica",
        status="draft",
        total_questoes=2,
        tempo_estimado=5,
    )
    quiz.created_at = datetime.now(timezone.utc)

    db = QuizCloseDb(quiz)

    response = run(
        education.publish_quiz(
            "quiz-1",
            user={"tutor_id": "tutor-1"},
            db=db,
        )
    )

    assert quiz.status == "open"
    assert quiz.live_phase == "lobby"
    assert quiz.current_question_id is None
    assert response.status == "open"
    assert db.commits == 1
    assert db.refreshes == 1


def test_live_quiz_opens_and_closes_current_question():
    quiz = education.QuizModel(
        id="quiz-1",
        tutor_id="tutor-1",
        lesson_id="lesson-1",
        titulo="Quiz",
        tipo_quiz="pratica",
        status="open",
        total_questoes=2,
    )
    quiz.created_at = datetime.now(timezone.utc)
    questions = [
        education.QuestionModel(
            id="q1",
            quiz_id="quiz-1",
            tipo="multipla_escolha",
            dificuldade="facil",
            enunciado="Pergunta 1?",
            opcoes='[{"label":"A","texto":"Sim","correta":true}]',
            resposta_correta="A",
        ),
        education.QuestionModel(
            id="q2",
            quiz_id="quiz-1",
            tipo="multipla_escolha",
            dificuldade="facil",
            enunciado="Pergunta 2?",
            opcoes='[{"label":"A","texto":"Não","correta":true}]',
            resposta_correta="A",
        ),
    ]
    for question in questions:
        question.created_at = datetime.now(timezone.utc)
    db = QuizLiveDb(quiz, questions)

    response = run(
        education.next_quiz_question(
            "quiz-1",
            user={"tutor_id": "tutor-1"},
            db=db,
        )
    )

    assert quiz.live_phase == "question"
    assert quiz.current_question_id == "q1"
    assert quiz.question_started_at is not None
    assert response.current_question_id == "q1"

    response = run(
        education.close_quiz_question(
            "quiz-1",
            user={"tutor_id": "tutor-1"},
            db=db,
        )
    )

    assert quiz.live_phase == "results"
    assert response.live_phase == "results"


def test_public_quiz_attempt_progress_is_scoped_per_browser():
    q1 = education.QuestionModel(
        id="q1",
        quiz_id="quiz-1",
        tipo="verdadeiro_falso",
        dificuldade="facil",
        enunciado="Teste 1?",
        resposta_correta="verdadeiro",
    )
    q2 = education.QuestionModel(
        id="q2",
        quiz_id="quiz-1",
        tipo="verdadeiro_falso",
        dificuldade="facil",
        enunciado="Teste 2?",
        resposta_correta="falso",
    )

    index, question = quiz_play._next_unanswered_question(
        [q1, q2],
        {"q1"},
    )

    assert index == 1
    assert question is q2
    assert quiz_play._is_correct_answer(q1, "verdadeiro") is True
    assert quiz_play._is_correct_answer(q2, "verdadeiro") is False


def test_quiz_speed_score_rewards_faster_correct_answers():
    fast = quiz_play._score_answer(correta=True, elapsed_ms=2_000)
    slow = quiz_play._score_answer(correta=True, elapsed_ms=20_000)

    assert fast > slow
    assert slow >= 100
    assert quiz_play._score_answer(correta=False, elapsed_ms=1_000) == 0


def test_quiz_attempt_id_fits_database_column_and_migrates_legacy_cookie():
    quiz_id = "f2103ef0-95a0-4fdd-8dec-70d217c9bc54"
    legacy = f"{quiz_id}:17957f1234567890abcdef1234567890"
    request = SimpleNamespace(cookies={quiz_play._attempt_cookie_name(quiz_id): legacy})

    attempt_id = quiz_play._attempt_id(request, quiz_id)

    assert attempt_id == "17957f1234567890abcdef1234567890"
    assert len(attempt_id) <= 64


def test_quiz_ranking_orders_by_score_and_keeps_positions():
    answers = [
        education.StudentAnswerModel(
            id="a1",
            question_id="q1",
            student_id="s1",
            student_name="Ana",
            resposta="A",
            correta=True,
            pontuacao=600,
        ),
        education.StudentAnswerModel(
            id="a2",
            question_id="q1",
            student_id="s2",
            student_name="Bia",
            resposta="A",
            correta=True,
            pontuacao=900,
        ),
        education.StudentAnswerModel(
            id="a3",
            question_id="q2",
            student_id="s1",
            student_name="Ana",
            resposta="B",
            correta=False,
            pontuacao=0,
        ),
    ]

    rows = quiz_play._ranking_rows(answers)

    assert rows[0]["student_name"] == "Bia"
    assert rows[0]["position"] == 1
    assert rows[1]["student_name"] == "Ana"
    assert rows[1]["position"] == 2


def test_quiz_public_base_url_uses_request_when_no_override():
    request = SimpleNamespace(base_url="http://localhost:8000/")

    assert quiz_qrcode._public_base_url(request) == "http://localhost:8000"
    assert (
        quiz_qrcode._public_base_url(request, "https://intarq.example/")
        == "https://intarq.example"
    )


def test_quiz_qrcode_svg_generation_produces_svg_content():
    svg = quiz_qrcode._generate_qrcode_svg(
        "http://localhost:8000/education/quiz/q1/play"
    )

    assert b"<svg" in svg[:200]


def test_quiz_service_preserves_estimated_time(monkeypatch):
    async def fake_candidates(_preferred=None):
        return ["fake-llm"]

    async def fake_resolve(_preferred=None):
        return "fake-llm"

    async def fake_dispatch_single(
        _llm, prompt, _history, _system_prompt, *, max_tokens=None
    ):
        if "Formato de resposta" in prompt:
            # So a geracao carrega teto proprio: e o JSON longo que vinha
            # cortado e derrubava o quiz no template. A validacao segue com o
            # padrao do provedor.
            assert max_tokens and max_tokens >= 2000
            return LLMResponse(
                llm="fake-llm",
                content="""
                {
                  "questoes": [
                    {
                      "tipo": "verdadeiro_falso",
                      "dificuldade": "facil",
                      "enunciado": "Teste?",
                      "opcoes": [],
                      "resposta_correta": "verdadeiro",
                      "justificativa": "Baseado no resumo",
                      "conceitos": ["teste"],
                      "topico_origem": "Resumo"
                    }
                  ],
                  "tempo_estimado": 9
                }
                """
            )
        return LLMResponse(
            llm="fake-llm",
            content="""
            {
              "validacoes": [
                {
                  "indice": 0,
                  "grounding_score": 0.92,
                  "bem_formulada": true,
                  "risco_alucinacao": false,
                  "feedback": "ok"
                }
              ],
              "media_grounding": 0.92,
              "aprovacao_geral": true
            }
            """
        )

    monkeypatch.setattr(
        quiz_generator_service,
        "_candidate_llms_for_quiz",
        fake_candidates,
    )
    monkeypatch.setattr(
        quiz_generator_service,
        "_resolve_llm_for_quiz",
        fake_resolve,
    )
    monkeypatch.setattr(
        quiz_generator_service,
        "dispatch_single",
        fake_dispatch_single,
    )

    result = run(
        quiz_generator_service.generate_quiz(
            resumo="Resumo com conteudo",
            disciplina="Banco de Dados",
            titulo_aula="Normalizacao",
            quantidade_questoes=1,
        )
    )

    assert result["tempo_estimado"] == 9
    assert result["questoes"][0]["grounding_score"] == 0.92


def test_quiz_service_normalizes_alternate_llm_question_shape(monkeypatch):
    async def fake_candidates(_preferred=None):
        return ["fake-llm"]

    async def fake_resolve(_preferred=None):
        return "fake-llm"

    async def fake_dispatch_single(
        _llm, prompt, _history, _system_prompt, *, max_tokens=None
    ):
        if "Formato de resposta" in prompt:
            # So a geracao carrega teto proprio: e o JSON longo que vinha
            # cortado e derrubava o quiz no template. A validacao segue com o
            # padrao do provedor.
            assert max_tokens and max_tokens >= 2000
            return LLMResponse(
                llm="fake-llm",
                content="""
                {
                  "questions": [
                    {
                      "type": "multiple_choice",
                      "difficulty": "medium",
                      "question": "Qual atributo identifica a entidade?",
                      "choices": ["Nome", "CPF", "Cor", "Altura"],
                      "correct_answer": "B",
                      "explanation": "A transcrição cita CPF como identificador.",
                      "concepts": ["entidade", "atributo"]
                    }
                  ],
                  "tempo_estimado": 6
                }
                """
            )
        return LLMResponse(
            llm="fake-llm",
            content="""
            {
              "validacoes": [
                {
                  "indice": 0,
                  "grounding_score": 0.66,
                  "bem_formulada": true,
                  "risco_alucinacao": false
                }
              ]
            }
            """
        )

    monkeypatch.setattr(
        quiz_generator_service,
        "_candidate_llms_for_quiz",
        fake_candidates,
    )
    monkeypatch.setattr(
        quiz_generator_service,
        "_resolve_llm_for_quiz",
        fake_resolve,
    )
    monkeypatch.setattr(
        quiz_generator_service,
        "dispatch_single",
        fake_dispatch_single,
    )

    result = run(
        quiz_generator_service.generate_quiz(
            resumo="Resumo sobre entidades e atributos.",
            disciplina="Banco de Dados",
            titulo_aula="DER",
            quantidade_questoes=1,
        )
    )

    question = result["questoes"][0]
    assert question["tipo"] == "multipla_escolha"
    assert question["dificuldade"] == "medio"
    assert question["enunciado"] == "Qual atributo identifica a entidade?"
    assert question["opcoes"][1]["correta"] is True


def test_quiz_service_keeps_reviewable_question_with_low_grounding(monkeypatch):
    async def fake_candidates(_preferred=None):
        return ["fake-llm"]

    async def fake_resolve(_preferred=None):
        return "fake-llm"

    async def fake_dispatch_single(
        _llm, prompt, _history, _system_prompt, *, max_tokens=None
    ):
        if "Formato de resposta" in prompt:
            # So a geracao carrega teto proprio: e o JSON longo que vinha
            # cortado e derrubava o quiz no template. A validacao segue com o
            # padrao do provedor.
            assert max_tokens and max_tokens >= 2000
            return LLMResponse(
                llm="fake-llm",
                content="""
                {
                  "questoes": [
                    {
                      "tipo": "verdadeiro_falso",
                      "dificuldade": "facil",
                      "enunciado": "O DER usa entidades e atributos?",
                      "opcoes": [],
                      "resposta_correta": "verdadeiro",
                      "justificativa": "Baseado no conteúdo da aula."
                    }
                  ]
                }
                """
            )
        return LLMResponse(
            llm="fake-llm",
            content="""
            {
              "validacoes": [
                {
                  "indice": 0,
                  "grounding_score": 0.52,
                  "bem_formulada": true,
                  "risco_alucinacao": false
                }
              ]
            }
            """
        )

    monkeypatch.setattr(
        quiz_generator_service,
        "_candidate_llms_for_quiz",
        fake_candidates,
    )
    monkeypatch.setattr(
        quiz_generator_service,
        "_resolve_llm_for_quiz",
        fake_resolve,
    )
    monkeypatch.setattr(
        quiz_generator_service,
        "dispatch_single",
        fake_dispatch_single,
    )

    result = run(
        quiz_generator_service.generate_quiz(
            resumo="Resumo sobre DER, entidades e atributos.",
            disciplina="Banco de Dados",
            titulo_aula="DER",
            quantidade_questoes=1,
        )
    )

    assert len(result["questoes"]) == 1
    assert result["questoes"][0]["verificado"] is False


def _fake_quiz_llm(
    chamadas,
    *,
    por_lote=None,
    repetidas=False,
    opcao_longa=None,
    encurtamento=None,
):
    """Modelo de mentira que responde geracao, validacao e encurtamento.

    `chamadas` recebe os prompts de geracao, para o teste conferir em quantos
    lotes a geracao foi e o que foi pedido em cada um.
    """

    import json as _json
    import re as _re

    estado = {"indice": 0}

    async def fake(_llm, prompt, _history, _system_prompt, *, max_tokens=None):
        if "Valide as seguintes" in prompt:
            return LLMResponse(llm="fake-llm", content='{"validacoes": []}')

        if "Reescreva cada alternativa" in prompt:
            return LLMResponse(
                llm="fake-llm",
                content=encurtamento or "sem json aqui",
            )

        chamadas.append(prompt)
        pedido = int(_re.search(r"gere (\d+) quest", prompt).group(1))
        quantidade = pedido if por_lote is None else min(por_lote, pedido)

        questoes = []
        for _ in range(quantidade):
            if repetidas:
                numero = 1
            else:
                estado["indice"] += 1
                numero = estado["indice"]
            questoes.append({
                "tipo": "multipla_escolha",
                "dificuldade": "medio",
                "enunciado": f"Pergunta {numero} sobre a aula?",
                "opcoes": [
                    {
                        "label": "A",
                        "texto": opcao_longa or "Primeira forma normal",
                        "correta": True,
                    },
                    {"label": "B", "texto": "Chave estrangeira"},
                    {"label": "C", "texto": "Indice composto"},
                    {"label": "D", "texto": "Gatilho"},
                ],
                "resposta_correta": "A",
                "justificativa": "A aula trata disso.",
            })

        return LLMResponse(
            llm="fake-llm",
            content=_json.dumps(
                {"questoes": questoes, "tempo_estimado": 12},
                ensure_ascii=False,
            ),
        )

    return fake


def _usa_fake_llm(monkeypatch, fake):
    async def fake_candidates(_preferred=None):
        return ["fake-llm"]

    async def fake_resolve(_preferred=None):
        return "fake-llm"

    monkeypatch.setattr(
        quiz_generator_service, "_candidate_llms_for_quiz", fake_candidates
    )
    monkeypatch.setattr(
        quiz_generator_service, "_resolve_llm_for_quiz", fake_resolve
    )
    monkeypatch.setattr(quiz_generator_service, "dispatch_single", fake)


def test_quiz_sem_json_valido_falha_em_vez_de_usar_template(monkeypatch):
    """Pergunta de quiz e escrita pela IA, ou nao existe.

    Antes, modelo que nao entregava JSON derrubava a geracao em um montador por
    template: o professor recebia frase recortada da aula com cara de pergunta,
    sem gabarito que se sustentasse. Falhar dizendo o motivo e melhor - da para
    tentar de novo; pergunta ruim liberada para a turma nao volta atras.
    """

    async def fake_dispatch_single(
        _llm, _prompt, _history, _system_prompt, *, max_tokens=None
    ):
        return LLMResponse(
            llm="bad-llm", content="Nao consegui montar o JSON solicitado."
        )

    _usa_fake_llm(monkeypatch, fake_dispatch_single)

    result = run(
        quiz_generator_service.generate_quiz(
            resumo=(
                "O modelo entidade relacionamento organiza dados em entidades, "
                "atributos e relacionamentos para apoiar o planejamento do banco."
            ),
            disciplina="Banco de Dados",
            titulo_aula="DER",
            quantidade_questoes=3,
        )
    )

    assert result["questoes"] == []
    assert result["error"]
    assert result["attempts"]


def test_geracao_vai_em_lotes_ate_completar_o_pedido(monkeypatch):
    """Dez questoes em um JSON so voltavam cortadas do provedor.

    Em lote de quatro cada resposta fecha, e o que o professor pediu sai
    inteiro - antes o corte no meio do array era o que levava tudo para o
    template.
    """
    chamadas = []
    _usa_fake_llm(monkeypatch, _fake_quiz_llm(chamadas))

    result = run(
        quiz_generator_service.generate_quiz(
            resumo="Resumo da aula sobre normalizacao e chaves.",
            disciplina="Banco de Dados",
            titulo_aula="Normalizacao",
            quantidade_questoes=6,
        )
    )

    assert len(result["questoes"]) == 6
    assert len(chamadas) == 2
    # Segundo lote pede so o que falta, e leva a lista do que ja saiu.
    assert "gere 2 quest" in chamadas[1]
    assert "Perguntas já geradas" in chamadas[1]


def test_progresso_e_reportado_lote_a_lote(monkeypatch):
    """A tela espera minutos: sem andamento, parece travada."""
    _usa_fake_llm(monkeypatch, _fake_quiz_llm([]))
    marcos = []

    run(
        quiz_generator_service.generate_quiz(
            resumo="Resumo da aula sobre normalizacao e chaves.",
            disciplina="Banco de Dados",
            titulo_aula="Normalizacao",
            quantidade_questoes=6,
            on_progress=lambda prontas, total: marcos.append((prontas, total)),
        )
    )

    assert marcos[0] == (0, 6)
    assert marcos[-1] == (6, 6)


def test_pergunta_repetida_no_lote_seguinte_nao_entra_duas_vezes(monkeypatch):
    """Pedir mais questoes nao pode virar a mesma pergunta N vezes."""
    _usa_fake_llm(monkeypatch, _fake_quiz_llm([], repetidas=True))

    result = run(
        quiz_generator_service.generate_quiz(
            resumo="Resumo da aula sobre normalizacao.",
            disciplina="Banco de Dados",
            titulo_aula="Normalizacao",
            quantidade_questoes=6,
        )
    )

    enunciados = [questao["enunciado"] for questao in result["questoes"]]
    assert len(enunciados) == len(set(enunciados)) == 1


def test_alternativa_longa_volta_para_o_modelo_encurtar(monkeypatch):
    """Alternativa longa nao cabe na tela nem da para ler no tempo da pergunta.

    Encurtar mantendo o sentido e trabalho de quem escreveu a alternativa,
    entao a primeira tentativa e devolver ao modelo.
    """
    longa = (
        "A organizacao das tabelas em formas normais para eliminar "
        "redundancia de dados e dependencias parciais"
    )
    _usa_fake_llm(
        monkeypatch,
        _fake_quiz_llm(
            [],
            opcao_longa=longa,
            encurtamento=(
                '{"questoes": [{"indice": 0, "opcoes": '
                '[{"label": "A", "texto": "Normalizacao de tabelas"}]}]}'
            ),
        ),
    )

    result = run(
        quiz_generator_service.generate_quiz(
            resumo="Resumo da aula sobre normalizacao.",
            disciplina="Banco de Dados",
            titulo_aula="Normalizacao",
            quantidade_questoes=1,
        )
    )

    opcoes = result["questoes"][0]["opcoes"]
    assert opcoes[0]["texto"] == "Normalizacao de tabelas"
    # O gabarito e casado por label: encurtar texto nao muda a resposta.
    assert opcoes[0]["correta"] is True


def test_alternativa_que_o_modelo_nao_encurtou_sai_aparada(monkeypatch):
    """Se a reescrita falha, a alternativa ainda tem que caber na tela."""
    longa = (
        "A organizacao das tabelas em formas normais para eliminar "
        "redundancia de dados e dependencias parciais"
    )
    _usa_fake_llm(monkeypatch, _fake_quiz_llm([], opcao_longa=longa))

    result = run(
        quiz_generator_service.generate_quiz(
            resumo="Resumo da aula sobre normalizacao.",
            disciplina="Banco de Dados",
            titulo_aula="Normalizacao",
            quantidade_questoes=1,
        )
    )

    for opcao in result["questoes"][0]["opcoes"]:
        assert not quiz_generator_service._option_is_long(opcao["texto"])


def test_aparo_corta_a_explicacao_pendurada_na_alternativa():
    """O modelo alonga pendurando explicacao depois de travessao ou parenteses."""
    from app.services.quiz_generator_service import _trim_option

    assert (
        _trim_option(
            "Terceira forma normal — quando nenhum atributo depende de outro "
            "atributo nao chave"
        )
        == "Terceira forma normal"
    )
    assert (
        _trim_option("Chave estrangeira (referencia a chave primaria de outra tabela)")
        == "Chave estrangeira"
    )


def test_aparo_nao_deixa_palavra_solta_no_fim():
    """Alternativa terminada em "de" sugere que falta texto."""
    from app.services.quiz_generator_service import _trim_option

    aparada = _trim_option(
        "Conjunto de regras de integridade referencial aplicadas entre tabelas de "
        "um mesmo banco"
    )

    assert not aparada.split()[-1].lower() in {"de", "da", "do", "e", "entre"}
    assert not quiz_generator_service._option_is_long(aparada)


# --- Geracao em segundo plano ---------------------------------------------


async def _aguarda_job(job):
    for _ in range(500):
        if job.finished_at is not None:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("o job não terminou")


def test_job_guarda_o_quiz_pronto_e_avisa_no_fim():
    """Gerar leva minutos: a rota devolve o job e o aviso fecha o ciclo."""
    from app.services import quiz_job_service

    quiz_job_service.reset()
    avisos = []

    async def runner(job):
        job.report(2, 2)
        return {"quiz_id": "quiz-1", "questoes": [{"id": "a"}, {"id": "b"}]}

    async def notify(job):
        avisos.append((job.status, job.prontas))

    async def cenario():
        job = quiz_job_service.submit(
            tutor_id="tutor-1",
            total=2,
            titulo="Quiz: Aula",
            runner=runner,
            notify=notify,
        )
        await _aguarda_job(job)
        return job

    job = run(cenario())

    assert job.status == "done"
    assert job.result["quiz_id"] == "quiz-1"
    assert job.prontas == 2
    assert avisos == [("done", 2)]
    assert quiz_job_service.get_job(job.id, "tutor-1") is job


def test_job_que_falha_guarda_a_frase_escrita_para_o_professor():
    """`repr` de excecao nao diz nada a quem esta esperando o quiz."""
    from app.services import quiz_job_service

    quiz_job_service.reset()
    avisos = []

    async def runner(_job):
        raise HTTPException(status_code=502, detail="A IA não gerou perguntas válidas.")

    async def notify(job):
        avisos.append(job.error)

    async def cenario():
        job = quiz_job_service.submit(
            tutor_id="tutor-1",
            total=3,
            titulo="Quiz: Aula",
            runner=runner,
            notify=notify,
        )
        await _aguarda_job(job)
        return job

    job = run(cenario())

    assert job.status == "error"
    assert job.error == "A IA não gerou perguntas válidas."
    assert avisos == ["A IA não gerou perguntas válidas."]


def test_job_de_outro_professor_nao_e_visivel():
    """Quiz em preparo e material de prova: nao vaza entre contas."""
    from app.services import quiz_job_service

    quiz_job_service.reset()

    async def runner(_job):
        return {"quiz_id": "quiz-1", "questoes": []}

    async def cenario():
        job = quiz_job_service.submit(
            tutor_id="tutor-1",
            total=1,
            titulo="Quiz: Aula",
            runner=runner,
        )
        await _aguarda_job(job)
        return job

    job = run(cenario())

    assert quiz_job_service.get_job(job.id, "tutor-2") is None


def test_rota_assincrona_devolve_o_job_sem_esperar_a_ia(monkeypatch):
    """A fonte e validada na hora; so a parte demorada vai para a task."""
    from app.services import quiz_job_service

    capturado = {}

    def fake_submit(*, tutor_id, total, titulo, runner, notify):
        capturado.update(tutor_id=tutor_id, total=total, titulo=titulo)
        return quiz_job_service.QuizJob(
            id="job-1", tutor_id=tutor_id, total=total, titulo=titulo
        )

    monkeypatch.setattr(education.quiz_job_service, "submit", fake_submit)

    resposta = run(
        education.generate_quiz_in_background(
            education.QuizCreateRequest(lesson_id="lesson-1", quantidade_questoes=7),
            user={"tutor_id": "tutor-1", "uid": "user-1"},
            db=QuizDb(_lesson()),
        )
    )

    assert resposta["job_id"] == "job-1"
    assert resposta["status"] == "pending"
    assert capturado == {
        "tutor_id": "tutor-1",
        "total": 7,
        "titulo": "Quiz: Normalizacao",
    }


def test_rota_assincrona_recusa_aula_sem_resumo():
    """Job aceito que falha minutos depois e pior que um 400 imediato."""
    with pytest.raises(HTTPException) as error:
        run(
            education.generate_quiz_in_background(
                education.QuizCreateRequest(lesson_id="lesson-1"),
                user={"tutor_id": "tutor-1", "uid": "user-1"},
                db=QuizDb(_lesson(summary="")),
            )
        )

    assert error.value.status_code == 400


def test_andamento_de_job_inexistente_responde_404():
    from app.services import quiz_job_service

    quiz_job_service.reset()

    with pytest.raises(HTTPException) as error:
        run(education.get_quiz_job("nao-existe", user={"tutor_id": "tutor-1"}))

    assert error.value.status_code == 404


def test_teto_de_tokens_acompanha_o_tamanho_do_quiz():
    """2000 tokens e teto de resposta de chat, nao de um JSON com N questoes.

    Era o que cortava a resposta no meio e derrubava tudo no template - e o
    corte ficava mais garantido quanto mais questoes o professor pedia.
    """
    from app.services.quiz_generator_service import _token_budget

    assert _token_budget(1) >= 2000
    assert _token_budget(20) > _token_budget(5)
    # Teto proprio: pedir 50 nao pode estourar o limite de saida do provedor.
    assert _token_budget(50) <= 8000


def test_resposta_cortada_aproveita_as_questoes_completas():
    """Sete questoes de verdade valem mais que dez de template."""
    from app.services.quiz_generator_service import _json_from_content

    cortada = """{
      "questoes": [
        {"tipo": "multipla_escolha", "enunciado": "O que e normalizacao?",
         "opcoes": [{"label": "A", "texto": "Organizar dados", "correta": true}]},
        {"tipo": "multipla_escolha", "enunciado": "Para que serve uma chave?",
         "opcoes": [{"label": "A", "texto": "Identificar", "correta": true}]},
        {"tipo": "multipla_escolha", "enunciado": "O que e uma tabela inc"""

    data = _json_from_content(cortada)

    assert len(data["questoes"]) == 2
    assert data["questoes"][0]["enunciado"] == "O que e normalizacao?"


def test_json_inteiro_continua_sendo_lido_normalmente():
    from app.services.quiz_generator_service import _json_from_content

    data = _json_from_content(
        'Segue o quiz:\n```json\n{"questoes": [{"enunciado": "Pergunta?"}]}\n```'
    )

    assert data["questoes"][0]["enunciado"] == "Pergunta?"


def test_texto_sem_json_nao_inventa_questao():
    from app.services.quiz_generator_service import _json_from_content

    assert _json_from_content("Desculpe, nao consegui gerar o quiz.") == {}


def test_gabarito_nao_marca_duas_alternativas():
    """`resposta_correta` somava a marcacao do modelo em vez de substituir.

    A questao saia com duas corretas e a turma era corrigida errado - foi o que
    apareceu na primeira geracao real depois de destravar a IA.
    """
    from app.services.quiz_generator_service import _normalize_options

    opcoes = _normalize_options(
        [
            {"label": "A", "texto": "Depende de outro atributo", "correta": True},
            {"label": "B", "texto": "Depende da chave inteira"},
            {"label": "C", "texto": "Esta em 1FN", "correta": False},
        ],
        "C",
    )

    corretas = [o for o in opcoes if o["correta"]]
    assert len(corretas) == 1
    assert corretas[0]["label"] == "C"


def test_sem_gabarito_nao_inventa_alternativa_correta():
    """Marcar a primeira criava uma chave errada com cara de legitima."""
    from app.services.quiz_generator_service import _normalize_options

    opcoes = _normalize_options(
        [
            {"label": "A", "texto": "Primeira"},
            {"label": "B", "texto": "Segunda"},
        ],
        "",
    )

    assert len(opcoes) == 2
    assert not any(o["correta"] for o in opcoes)


def test_duas_marcadas_pelo_modelo_sem_gabarito_viram_nenhuma():
    """Ambiguidade nao se resolve no chute: sobra para a revisao."""
    from app.services.quiz_generator_service import _normalize_options

    opcoes = _normalize_options(
        [
            {"label": "A", "texto": "Uma", "correta": True},
            {"label": "B", "texto": "Outra", "correta": True},
        ],
        "",
    )

    assert not any(o["correta"] for o in opcoes)


def test_marcacao_unica_do_modelo_vale_sem_gabarito():
    from app.services.quiz_generator_service import _normalize_options

    opcoes = _normalize_options(
        [
            {"label": "A", "texto": "Uma"},
            {"label": "B", "texto": "Outra", "correta": True},
        ],
        "",
    )

    assert [o["correta"] for o in opcoes] == [False, True]


def test_questao_sem_gabarito_e_marcada_para_revisao():
    from app.services.quiz_generator_service import _normalize_question

    questao = _normalize_question(
        {
            "tipo": "multipla_escolha",
            "enunciado": "Qual e a primeira forma normal?",
            "opcoes": [
                {"label": "A", "texto": "Uma", "correta": True},
                {"label": "B", "texto": "Outra", "correta": True},
            ],
        },
        ["multipla_escolha"],
    )

    assert questao["chave_ambigua"] is True


def test_quiz_exige_ao_menos_uma_fonte():
    """Sem fonte nao ha conteudo: o pedido e recusado antes de chamar a IA."""
    with pytest.raises(HTTPException) as error:
        run(
            education.generate_quiz_from_lesson(
                QuizCreateRequest(),
                user={"tutor_id": "tutor-1"},
                db=QuizDb(_lesson()),
            )
        )

    assert error.value.status_code == 422


def _fake_generate(capturado, questoes=1):
    async def fake_generate_quiz(**kwargs):
        capturado.update(kwargs)
        return {
            "tempo_estimado": 8,
            "questoes": [
                {
                    "tipo": "multipla_escolha",
                    "enunciado": f"Pergunta {indice + 1}?",
                    "opcoes": [
                        {"label": "A", "texto": "Certa", "correta": True},
                        {"label": "B", "texto": "Errada"},
                    ],
                    "resposta_correta": "A",
                }
                for indice in range(questoes)
            ],
        }

    return fake_generate_quiz


def test_quiz_junta_varias_aulas_com_material(monkeypatch):
    """Revisao de prova junta as aulas do bimestre com a apostila.

    Era o que a regra de "uma fonte so" impedia: o professor tinha de gerar um
    quiz por aula e aplicar tres QR Codes seguidos.
    """
    capturado = {}
    monkeypatch.setattr(
        education.quiz_generator_service,
        "generate_quiz",
        _fake_generate(capturado),
    )

    db = MultiSourceDb(
        lessons=[
            _lesson(lesson_id="aula-1", title="Normalizacao"),
            _lesson(lesson_id="aula-2", title="Chaves", summary="Resumo de chaves"),
        ],
        materials=[_material(content="Texto da apostila sobre SQL")],
        segments={"aula-1": ["Transcricao da primeira aula."]},
    )

    resposta = run(
        education.generate_quiz_from_lesson(
            QuizCreateRequest(
                lesson_ids=["aula-1", "aula-2"],
                material_ids=["mat-1"],
            ),
            user={"tutor_id": "tutor-1"},
            db=db,
        )
    )

    contexto = capturado["resumo"]
    assert "=== AULA: Normalizacao ===" in contexto
    assert "=== AULA: Chaves ===" in contexto
    assert "=== MATERIAL DA DISCIPLINA: Apostila ===" in contexto

    # Uma linha por fonte: e o que deixa rastrear de onde a pergunta saiu.
    fontes = db.fontes()
    assert [fonte.source_type for fonte in fontes] == [
        "lesson",
        "lesson",
        "material",
    ]
    assert [fonte.source_id for fonte in fontes] == ["aula-1", "aula-2", "mat-1"]

    quiz = next(item for item in db.added if isinstance(item, education.QuizModel))
    assert quiz.titulo == "Quiz: Normalizacao + 2 fonte(s)"
    # A coluna e NOT NULL: fica a primeira aula, e a origem completa esta acima.
    assert quiz.lesson_id == "aula-1"
    assert "3 fonte(s)" in resposta.message


def test_quiz_aceita_atalho_singular_junto_com_a_lista(monkeypatch):
    """`lesson_id` e o que cliente antigo manda, e soma com os plurais."""
    capturado = {}
    monkeypatch.setattr(
        education.quiz_generator_service,
        "generate_quiz",
        _fake_generate(capturado),
    )

    db = MultiSourceDb(
        lessons=[_lesson(lesson_id="aula-1")],
        materials=[_material()],
    )

    run(
        education.generate_quiz_from_lesson(
            QuizCreateRequest(lesson_id="aula-1", material_id="mat-1"),
            user={"tutor_id": "tutor-1"},
            db=db,
        )
    )

    assert len(db.fontes()) == 2


def test_fonte_repetida_entra_uma_vez_so(monkeypatch):
    """Marcar a aula atual e a mesma aula na lista nao duplica o conteudo."""
    capturado = {}
    monkeypatch.setattr(
        education.quiz_generator_service,
        "generate_quiz",
        _fake_generate(capturado),
    )

    db = MultiSourceDb(lessons=[_lesson(lesson_id="aula-1")])

    run(
        education.generate_quiz_from_lesson(
            QuizCreateRequest(lesson_id="aula-1", lesson_ids=["aula-1"]),
            user={"tutor_id": "tutor-1"},
            db=db,
        )
    )

    assert len(db.fontes()) == 1
    assert capturado["resumo"].count("=== AULA: Normalizacao ===") == 1


def test_fonte_sem_texto_e_ignorada_e_dita_na_mensagem(monkeypatch):
    """Fonte marcada que nao entrou precisa aparecer.

    Sem isso o professor acha que a aula de hoje virou pergunta quando ela
    estava vazia, e so descobre lendo as perguntas uma por uma.
    """
    capturado = {}
    monkeypatch.setattr(
        education.quiz_generator_service,
        "generate_quiz",
        _fake_generate(capturado),
    )

    db = MultiSourceDb(
        lessons=[
            _lesson(lesson_id="aula-1"),
            _lesson(lesson_id="aula-2", title="Aula vazia", summary=""),
        ],
    )

    resposta = run(
        education.generate_quiz_from_lesson(
            QuizCreateRequest(lesson_ids=["aula-1", "aula-2"]),
            user={"tutor_id": "tutor-1"},
            db=db,
        )
    )

    assert len(db.fontes()) == 1
    assert "Aula vazia" in resposta.message
    assert "=== AULA: Aula vazia ===" not in capturado["resumo"]


def test_quiz_recusa_quando_nenhuma_fonte_tem_texto():
    db = MultiSourceDb(
        lessons=[_lesson(lesson_id="aula-1", summary="")],
        materials=[_material(content="   ")],
    )

    with pytest.raises(HTTPException) as error:
        run(
            education.generate_quiz_from_lesson(
                QuizCreateRequest(lesson_ids=["aula-1"], material_ids=["mat-1"]),
                user={"tutor_id": "tutor-1"},
                db=db,
            )
        )

    assert error.value.status_code == 400
    assert "Apostila" in error.value.detail


def test_aula_de_outro_professor_nao_entra_como_fonte():
    """Marcar id alheio na lista nao pode virar pergunta com conteudo de outro."""
    alheia = _lesson(lesson_id="aula-2")
    alheia.tutor_id = "tutor-2"
    db = MultiSourceDb(lessons=[_lesson(lesson_id="aula-1"), alheia])

    with pytest.raises(HTTPException) as error:
        run(
            education.generate_quiz_from_lesson(
                QuizCreateRequest(lesson_ids=["aula-1", "aula-2"]),
                user={"tutor_id": "tutor-1"},
                db=db,
            )
        )

    assert error.value.status_code == 404


def test_muitas_fontes_dividem_o_teto_de_contexto(monkeypatch):
    """Janela de modelo nao cresce porque o professor marcou mais aulas.

    Quatro aulas inteiras passariam do que o provedor aceita, e a resposta
    voltaria cortada - o defeito que fazia a geracao devolver quiz vazio.
    """
    capturado = {}
    monkeypatch.setattr(
        education.quiz_generator_service,
        "generate_quiz",
        _fake_generate(capturado),
    )

    enorme = "Frase longa da aula repetida muitas vezes. " * 3_000
    db = MultiSourceDb(
        lessons=[
            _lesson(lesson_id=f"aula-{indice}", title=f"Aula {indice}", summary=enorme)
            for indice in range(1, 5)
        ],
    )

    run(
        education.generate_quiz_from_lesson(
            QuizCreateRequest(lesson_ids=[f"aula-{i}" for i in range(1, 5)]),
            user={"tutor_id": "tutor-1"},
            db=db,
        )
    )

    contexto = capturado["resumo"]
    assert all(f"=== AULA: Aula {i} ===" in contexto for i in range(1, 5))
    # Quatro fontes, cada uma com a sua cota do teto - mais a moldura dos
    # rotulos, que e curta.
    assert len(contexto) <= education.QUIZ_CONTEXT_CHAR_BUDGET + 1_000
