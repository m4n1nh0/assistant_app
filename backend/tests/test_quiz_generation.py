import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers import education
from app.routers import quiz_play
from app.routers import quiz_qrcode
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


def _lesson(status="closed", summary="Resumo da aula"):
    return SimpleNamespace(
        id="lesson-1",
        tutor_id="tutor-1",
        discipline="Banco de Dados",
        title="Normalizacao",
        status=status,
        summary=summary,
    )


def test_quiz_generation_requires_closed_lesson():
    request = education.QuizCreateRequest(lesson_id="lesson-1")

    with pytest.raises(HTTPException) as error:
        run(
            education.generate_quiz_from_lesson(
                request,
                user={"tutor_id": "tutor-1"},
                db=QuizDb(_lesson(status="recording")),
            )
        )

    assert error.value.status_code == 409


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
    assert captured["resumo"] == "Resumo da aula"
    assert captured["disciplina"] == "Banco de Dados"
    quiz = next(item for item in db.added if isinstance(item, education.QuizModel))
    assert quiz.tipo_quiz == "diagnostico"
    assert quiz.status == "draft"
    assert quiz.total_questoes == 1
    assert response.status == "draft"
    assert response.tempo_estimado_resposta == 7
    assert response.questoes[0].dificuldade == "dificil"
    assert response.questoes[0].grounding_score == 0.91
    assert response.questoes[0].verificado is True
    assert db.commits == 1


def test_quiz_generation_requires_summary():
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

    async def fake_dispatch_single(**kwargs):
        prompt = kwargs["prompt"]
        if "Formato de resposta" in prompt:
            return {
                "content": """
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
            }
        return {
            "content": """
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
        }

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

    async def fake_dispatch_single(**kwargs):
        prompt = kwargs["prompt"]
        if "Formato de resposta" in prompt:
            return {
                "content": """
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
            }
        return {
            "content": """
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
        }

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

    async def fake_dispatch_single(**kwargs):
        prompt = kwargs["prompt"]
        if "Formato de resposta" in prompt:
            return {
                "content": """
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
            }
        return {
            "content": """
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
        }

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


def test_quiz_service_builds_reviewable_fallback_when_llm_returns_no_json(monkeypatch):
    async def fake_candidates(_preferred=None):
        return ["bad-llm"]

    async def fake_resolve(_preferred=None):
        return "bad-llm"

    async def fake_dispatch_single(**_kwargs):
        return {"content": "Nao consegui montar o JSON solicitado."}

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
            resumo=(
                "O modelo entidade relacionamento organiza dados em entidades, "
                "atributos e relacionamentos para apoiar o planejamento do banco. "
                "A aula destacou que atributos descrevem características das "
                "entidades e que relacionamentos representam associações."
            ),
            disciplina="Banco de Dados",
            titulo_aula="DER",
            quantidade_questoes=3,
        )
    )

    assert len(result["questoes"]) >= 1
    assert result["questoes"][0]["fallback"] is True
    assert result["questoes"][0]["verificado"] is False
