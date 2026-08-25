import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers import education
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


class EmptyQuestionResult:
    def scalars(self):
        return self

    def all(self):
        return []


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
                    "tipo": "verdadeiro_falso",
                    "dificuldade": "dificil",
                    "enunciado": "A normalizacao reduz anomalias?",
                    "opcoes": [],
                    "resposta_correta": "verdadeiro",
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
    assert captured["tipos_questao"] == ["verdadeiro_falso"]
    assert captured["dificuldade"] == "dificil"
    assert captured["llm"] == "gpt-4.1"
    assert captured["resumo"] == "Resumo da aula"
    assert captured["disciplina"] == "Banco de Dados"
    quiz = next(item for item in db.added if isinstance(item, education.QuizModel))
    assert quiz.tipo_quiz == "diagnostico"
    assert quiz.total_questoes == 1
    assert response.tempo_estimado_resposta == 7
    assert response.questoes[0].dificuldade == "dificil"
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
