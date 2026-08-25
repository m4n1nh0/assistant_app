"""Interface web para responder quizzes - Integrada ao Modo Educação."""

import json
from html import escape
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    QuizModel,
    QuestionModel,
    StudentAnswerModel,
    get_db,
)

router = APIRouter(prefix="/education/quiz", tags=["education-quiz"])

# Textos para diferentes idiomas
_PUBLIC_LANGUAGES = ("pt", "es", "en")
_PUBLIC_TEXT = {
    "pt": {
        "html_lang": "pt-BR",
        "page_prefix": "Quiz",
        "brand": "MODO EDUCAÇÃO",
        "question": "Questão",
        "of": "de",
        "answer": "Sua Resposta",
        "placeholder_open": "Digite sua resposta...",
        "submit": "CONFIRMAR RESPOSTA",
        "next": "PRÓXIMA",
        "skip": "PULAR",
        "finish": "FINALIZAR",
        "privacy": "Respostas serão registradas e comparadas com o gabarito.",
        "unavailable_title": "Quiz indisponível",
        "unavailable_message": "Este quiz não existe ou foi removido.",
        "closed_title": "Quiz encerrado",
        "closed_message": "O professor encerrou o recebimento de respostas.",
        "completed_title": "Quiz Completado! 🎉",
        "completed_message": "Suas respostas foram registradas com sucesso.",
        "correct": "✅ Correto!",
        "incorrect": "❌ Incorreto",
        "skipped": "⏭️ Pulada",
        "language_label": "Idioma",
    },
    "es": {
        "html_lang": "es",
        "page_prefix": "Cuestionario",
        "brand": "MODO EDUCACIÓN",
        "question": "Pregunta",
        "of": "de",
        "answer": "Tu Respuesta",
        "placeholder_open": "Escribe tu respuesta...",
        "submit": "CONFIRMAR RESPUESTA",
        "next": "SIGUIENTE",
        "skip": "SALTAR",
        "finish": "TERMINAR",
        "privacy": "Las respuestas se registrarán y se compararán con la clave de respuestas.",
        "unavailable_title": "Cuestionario no disponible",
        "unavailable_message": "Este cuestionario no existe o ha sido eliminado.",
        "closed_title": "Cuestionario finalizado",
        "closed_message": "El profesor cerró la recepción de respuestas.",
        "completed_title": "¡Cuestionario completado! 🎉",
        "completed_message": "Sus respuestas se registraron correctamente.",
        "correct": "✅ ¡Correcto!",
        "incorrect": "❌ Incorrecto",
        "skipped": "⏭️ Omitida",
        "language_label": "Idioma",
    },
    "en": {
        "html_lang": "en",
        "page_prefix": "Quiz",
        "brand": "EDUCATION MODE",
        "question": "Question",
        "of": "of",
        "answer": "Your Answer",
        "placeholder_open": "Type your answer...",
        "submit": "CONFIRM ANSWER",
        "next": "NEXT",
        "skip": "SKIP",
        "finish": "FINISH",
        "privacy": "Answers will be recorded and compared with the answer key.",
        "unavailable_title": "Quiz unavailable",
        "unavailable_message": "This quiz does not exist or has been removed.",
        "closed_title": "Quiz closed",
        "closed_message": "The teacher has closed answer submissions.",
        "completed_title": "Quiz Completed! 🎉",
        "completed_message": "Your answers have been successfully recorded.",
        "correct": "✅ Correct!",
        "incorrect": "❌ Incorrect",
        "skipped": "⏭️ Skipped",
        "language_label": "Language",
    },
}


def _normalize_public_language(language: Optional[str]) -> Optional[str]:
    return language if language in _PUBLIC_LANGUAGES else None


def _public_language(request: Request, override: Optional[str]) -> str:
    if override and override in _PUBLIC_LANGUAGES:
        return override
    accept_lang = request.headers.get("accept-language", "").lower()
    for lang in _PUBLIC_LANGUAGES:
        if lang in accept_lang:
            return lang
    return "pt"


def _generate_quiz_page(
    *,
    quiz_id: str,
    question_index: int,
    total_questions: int,
    question_text: str,
    question_type: str,
    options: Optional[list] = None,
    language: str = "pt",
    status: Optional[str] = None,
    feedback: Optional[str] = None,
) -> HTMLResponse:
    """Gera página HTML para responder questão do quiz."""

    language = _normalize_public_language(language) or "pt"
    text = _PUBLIC_TEXT[language]
    accent = "#059669"

    # Define cor baseada no status
    if status == "correct":
        accent = "#059669"
    elif status == "incorrect":
        accent = "#dc2626"
    elif status == "skipped":
        accent = "#f59e0b"

    # Renderiza opções
    options_html = ""
    if question_type == "multipla_escolha" and options:
        for idx, option in enumerate(options):
            option_html = f"""
            <div class="option">
                <input type="radio" id="opt{idx}" name="answer" value="{escape(option.get('label', ''))}" required>
                <label for="opt{idx}">{escape(option.get('texto', ''))}</label>
            </div>
            """
            options_html += option_html

    elif question_type == "verdadeiro_falso":
        options_html = """
        <div class="option">
            <input type="radio" id="opt_v" name="answer" value="verdadeiro" required>
            <label for="opt_v">Verdadeiro</label>
        </div>
        <div class="option">
            <input type="radio" id="opt_f" name="answer" value="falso" required>
            <label for="opt_f">Falso</label>
        </div>
        """

    elif question_type == "aberta":
        options_html = f"""
        <textarea id="answer" name="answer" maxlength="1000" required autofocus
                  placeholder="{text['placeholder_open']}"></textarea>
        """

    # Botão submit/próxima
    button_text = text["submit"] if status is None else text["next"]
    skip_button = f'<a href="?lang={language}&skip=true" class="btn-secondary">{text["skip"]}</a>' if status is None else ""

    feedback_html = ""
    if feedback:
        feedback_html = f'<div class="feedback {status}">{escape(feedback)}</div>'

    return HTMLResponse(
        f"""<!doctype html>
<html lang="{text["html_lang"]}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{text["page_prefix"]} - {escape(f'Questão {question_index + 1}')}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);
color:#111827;font:16px system-ui,-apple-system,Segoe UI,sans-serif;min-height:100vh;
display:grid;place-items:center;padding:20px}}
main{{width:min(600px,100%);background:white;border-radius:12px;padding:28px;
box-shadow:0 14px 35px #11182740;overflow:hidden}}
.header{{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);color:white;
margin:-28px -28px 28px;padding:20px 28px;}}
.mark{{color:white;font-size:12px;font-weight:800;letter-spacing:2px}}
.progress{{display:flex;justify-content:space-between;align-items:center;
font-size:14px;margin-top:12px;}}
.progress-bar{{flex:1;height:6px;background:rgba(255,255,255,0.3);border-radius:3px;
margin:0 12px;}}
.progress-fill{{height:100%;background:#4ade80;border-radius:3px;
width:{(question_index / total_questions) * 100}%;}}
h1{{font-size:20px;margin:20px 0 8px;color:#1f2937}}
.question-info{{color:#6b7280;font-size:14px;margin-bottom:20px}}
.question-text{{font-size:18px;font-weight:600;margin:20px 0;line-height:1.5;color:#1f2937}}
.option{{display:flex;align-items:center;padding:12px;margin:8px 0;border:2px solid #e5e7eb;
border-radius:8px;cursor:pointer;transition:all 0.3s}}
.option:hover{{border-color:#667eea;background:#f9fafb}}
.option input[type="radio"]{{margin-right:12px;cursor:pointer;width:20px;height:20px}}
.option label{{flex:1;cursor:pointer;margin:0}}
textarea{{width:100%;min-height:120px;padding:12px;border:2px solid #e5e7eb;
border-radius:8px;font-size:16px;font-family:inherit;resize:vertical;margin:12px 0}}
textarea:focus{{outline:none;border-color:#667eea}}
.feedback{{padding:12px;border-radius:8px;margin:12px 0;font-weight:600}}
.feedback.correct{{background:#dcfce7;color:#166534;border-left:4px solid #4ade80}}
.feedback.incorrect{{background:#fee2e2;color:#7f1d1d;border-left:4px solid #ef4444}}
.feedback.skipped{{background:#fef3c7;color:#92400e;border-left:4px solid #f59e0b}}
.actions{{display:flex;gap:10px;margin-top:20px}}
.btn-primary{{flex:1;padding:12px;border:0;border-radius:8px;background:#667eea;
color:white;font-weight:800;letter-spacing:.7px;cursor:pointer;text-decoration:none;
text-align:center;transition:all 0.3s}}
.btn-primary:hover{{transform:translateY(-2px);box-shadow:0 8px 16px rgba(102, 126, 234, 0.3)}}
.btn-secondary{{flex:1;padding:12px;border:2px solid #e5e7eb;border-radius:8px;
background:white;color:#6b7280;font-weight:800;cursor:pointer;text-decoration:none;
text-align:center;transition:all 0.3s}}
.btn-secondary:hover{{border-color:#667eea;color:#667eea}}
small{{display:block;color:#7b8999;margin-top:18px;line-height:1.4;text-align:center}}
.languages{{display:flex;justify-content:center;gap:8px;margin-bottom:16px}}
.languages a{{color:white;text-decoration:none;border:1px solid rgba(255,255,255,0.5);
border-radius:5px;padding:6px 10px;font-size:12px;transition:all 0.3s}}
.languages a:hover{{border-color:white}}
</style></head><body><main>
<div class="header">
<div class="mark">{text["brand"]}</div>
<nav class="languages">
<a href="?lang=pt">Português</a>
<a href="?lang=es">Español</a>
<a href="?lang=en">English</a>
</nav>
<h1>{escape(f'{text["question"]} {question_index + 1}')}</h1>
<div class="progress">
<span>{question_index + 1} {text["of"]} {total_questions}</span>
<div class="progress-bar"><div class="progress-fill"></div></div>
</div>
</div>
<div class="question-text">{escape(question_text)}</div>
{feedback_html}
<form method="post" action="?lang={language}">
{options_html}
<div class="actions">
{skip_button}
<button type="submit" class="btn-primary">{button_text}</button>
</div>
</form>
<small>{text["privacy"]}</small>
</main></body></html>""",
        headers={
            "Cache-Control": "no-store",
            "Content-Language": language,
            "Vary": "Accept-Language",
        },
    )


def _generate_completion_page(
    *, language: str = "pt"
) -> HTMLResponse:
    """Gera página de conclusão do quiz."""

    language = _normalize_public_language(language) or "pt"
    text = _PUBLIC_TEXT[language]

    return HTMLResponse(
        f"""<!doctype html>
<html lang="{text["html_lang"]}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{text["page_prefix"]}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);
color:#111827;font:16px system-ui,-apple-system,Segoe UI,sans-serif;min-height:100vh;
display:grid;place-items:center;padding:20px}}
main{{width:min(500px,100%);background:white;border-radius:12px;padding:40px;
box-shadow:0 14px 35px #11182740;text-align:center;}}
.icon{{font-size:60px;margin-bottom:20px}}
h1{{font-size:28px;margin:20px 0 10px;color:#1f2937}}
p{{color:#6b7280;font-size:16px;margin:10px 0}}
.btn{{display:inline-block;padding:12px 30px;margin-top:20px;border:0;border-radius:8px;
background:#667eea;color:white;font-weight:800;letter-spacing:.7px;cursor:pointer;
text-decoration:none;transition:all 0.3s}}
.btn:hover{{transform:translateY(-2px);box-shadow:0 8px 16px rgba(102, 126, 234, 0.3)}}
</style></head><body><main>
<div class="icon">{text['completed_title'].split()[0]}</div>
<h1>{text["completed_title"]}</h1>
<p>{text["completed_message"]}</p>
<a href="/" class="btn">Voltar ao Dashboard</a>
</main></body></html>""",
        headers={
            "Cache-Control": "no-store",
            "Content-Language": language,
        },
    )


def _generate_closed_page(*, language: str = "pt") -> HTMLResponse:
    """Gera pagina informando que o quiz foi encerrado pelo professor."""

    language = _normalize_public_language(language) or "pt"
    text = _PUBLIC_TEXT[language]

    return HTMLResponse(
        f"""<!doctype html>
<html lang="{text["html_lang"]}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{text["page_prefix"]}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#f3f6fa;color:#111827;font:16px system-ui,-apple-system,Segoe UI,sans-serif;
min-height:100vh;display:grid;place-items:center;padding:20px}}
main{{width:min(440px,100%);background:white;border-radius:12px;padding:40px;
box-shadow:0 14px 35px #11182740;text-align:center;}}
h1{{font-size:24px;margin:0 0 10px;color:#1f2937}}
p{{color:#6b7280;font-size:15px;margin:0}}
</style></head><body><main>
<h1>{text["closed_title"]}</h1>
<p>{text["closed_message"]}</p>
</main></body></html>""",
        status_code=410,
        headers={
            "Cache-Control": "no-store",
            "Content-Language": language,
        },
    )


@router.get("/{quiz_token}/play", response_class=HTMLResponse)
async def quiz_play_page(
    quiz_token: str,
    request: Request,
    lang: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Exibe questão do quiz para responder."""

    language = _public_language(request, lang)

    # Busca quiz
    stmt = select(QuizModel).where(QuizModel.id == quiz_token)
    quiz = (await db.execute(stmt)).scalar_one_or_none()

    if not quiz:
        text = _PUBLIC_TEXT[language]
        return HTMLResponse(
            f"""<!doctype html>
<html lang="{text["html_lang"]}"><head><meta charset="utf-8">
<title>{text["page_prefix"]}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#f3f6fa;color:#111827;font:16px system-ui,-apple-system,Segoe UI,sans-serif;
min-height:100vh;display:grid;place-items:center;padding:20px}}
main{{width:min(440px,100%);background:white;border-radius:12px;padding:40px;
box-shadow:0 14px 35px #11182740;text-align:center;}}
h1{{font-size:20px;margin:0 0 10px;color:#dc2626}}
p{{color:#6b7280;font-size:14px;margin:0}}
</style></head><body><main>
<h1>{text["unavailable_title"]}</h1>
<p>{text["unavailable_message"]}</p>
</main></body></html>""",
            status_code=404,
        )

    if quiz.status == "closed":
        return _generate_closed_page(language=language)

    # Busca primeira questão
    stmt = select(QuestionModel).where(
        QuestionModel.quiz_id == quiz_token
    ).limit(1)
    question = (await db.execute(stmt)).scalar_one_or_none()

    if not question:
        return _generate_completion_page(language=language)

    # Parse opcoes se for multipla escolha
    options = None
    if question.tipo == "multipla_escolha" and question.opcoes:
        try:
            options = json.loads(question.opcoes)
        except:
            options = []

    return _generate_quiz_page(
        quiz_id=quiz_token,
        question_index=0,
        total_questions=quiz.total_questoes,
        question_text=question.enunciado,
        question_type=question.tipo,
        options=options,
        language=language,
    )


@router.post("/{quiz_token}/play", response_class=HTMLResponse)
async def quiz_submit_answer(
    quiz_token: str,
    request: Request,
    lang: Optional[str] = Query(default=None),
    answer: Optional[str] = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Processa resposta e exibe próxima questão."""

    language = _public_language(request, lang)

    # Busca quiz
    stmt = select(QuizModel).where(QuizModel.id == quiz_token)
    quiz = (await db.execute(stmt)).scalar_one_or_none()

    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")
    if quiz.status == "closed":
        return _generate_closed_page(language=language)

    # Busca todas as questões
    stmt = select(QuestionModel).where(
        QuestionModel.quiz_id == quiz_token
    ).order_by(QuestionModel.created_at)
    all_questions = (await db.execute(stmt)).scalars().all()

    if not all_questions:
        return _generate_completion_page(language=language)

    # Encontra questão atual (primeira sem resposta)
    current_index = 0
    current_question = None

    for idx, q in enumerate(all_questions):
        stmt = select(StudentAnswerModel).where(
            StudentAnswerModel.question_id == q.id
        )
        answered = await db.execute(stmt)
        if not answered.scalar_one_or_none():
            current_index = idx
            current_question = q
            break

    # Se chegou ao fim, mostra conclusão
    if current_question is None:
        return _generate_completion_page(language=language)

    # Registra resposta anterior se existir
    if current_index > 0 and answer is not None:
        prev_question = all_questions[current_index - 1]
        student_answer = StudentAnswerModel(
            id=str(__import__("uuid").uuid4()),
            question_id=prev_question.id,
            student_id=None,  # Anônimo em quiz público
            resposta=answer,
            correta=answer == prev_question.resposta_correta if prev_question.tipo != "aberta" else None,
        )
        db.add(student_answer)
        await db.commit()

    # Exibe próxima questão
    options = None
    if current_question.tipo == "multipla_escolha" and current_question.opcoes:
        try:
            options = json.loads(current_question.opcoes)
        except:
            options = []

    return _generate_quiz_page(
        quiz_id=quiz_token,
        question_index=current_index,
        total_questions=len(all_questions),
        question_text=current_question.enunciado,
        question_type=current_question.tipo,
        options=options,
        language=language,
    )
