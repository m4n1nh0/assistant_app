"""Interface web para responder quizzes - Integrada ao Modo Educação."""

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    QuizModel,
    QuizParticipantModel,
    QuestionModel,
    StudentAnswerModel,
    get_db,
)
from ..services import quiz_group_service, quiz_live_service, quiz_translation_service

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
        "name": "Seu nome",
        "enrollment": "Sua matrícula",
        "group_intro": "Quiz em grupo: entre com a sua matrícula.",
        "enrollment_invalid": "Digite a sua matrícula.",
        "enrollment_unknown": "Não encontrei essa matrícula. Confira o número e tente de novo.",
        "enrollment_no_group": "Essa matrícula não está em nenhum grupo desta disciplina. Fale com o professor.",
        "group": "Grupo",
        "rep_only_title": "Quem responde é o representante",
        "rep_only_message": "O representante do {group} é {name}. Acompanhe e ajude o grupo a decidir.",
        "rep_missing_message": "O professor ainda não escolheu o representante do {group}.",
        "join": "ENTRAR NO QUIZ",
        "waiting_title": "Aguardando o professor",
        "waiting_message": "A próxima pergunta aparecerá automaticamente.",
        "answer_saved": "Resposta registrada",
        "ranking": "Ranking",
        "your_position": "Sua posição",
        "score": "pontos",
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
        "draft_title": "Quiz ainda não liberado",
        "draft_message": "Aguarde o professor liberar o QR Code para a turma.",
        "empty_title": "Quiz sem perguntas",
        "empty_message": "Este quiz foi criado sem perguntas válidas. Gere um novo quiz.",
        "completed_title": "Quiz Completado! 🎉",
        "completed_message": "Suas respostas foram registradas com sucesso.",
        "correct": "✅ Correto!",
        "incorrect": "❌ Incorreto",
        "skipped": "⏭️ Pulada",
        "language_label": "Idioma",
        "seconds_left": "s restantes",
        "round_points": "nesta pergunta",
        "total_points": "acumulado",
        "waiting_ranking": "Aguardando respostas...",
        "you_got_it": "Você acertou",
        "you_missed": "Você errou",
        "no_answer": "Você não respondeu",
        "ranking_next": "A próxima pergunta aparecerá quando o professor liberar.",
        "waiting_for_answer": "aguardando resposta",
        "seconds_word": "segundos restantes",
        "true_label": "Verdadeiro",
        "false_label": "Falso",
        "join_language": "Idioma do quiz",
    },
    "es": {
        "html_lang": "es",
        "page_prefix": "Cuestionario",
        "brand": "MODO EDUCACIÓN",
        "question": "Pregunta",
        "of": "de",
        "answer": "Tu Respuesta",
        "name": "Tu nombre",
        "enrollment": "Tu matrícula",
        "group_intro": "Quiz en grupo: entra con tu matrícula.",
        "enrollment_invalid": "Escribe tu matrícula.",
        "enrollment_unknown": "No encontré esa matrícula. Revisa el número e inténtalo de nuevo.",
        "enrollment_no_group": "Esa matrícula no está en ningún grupo de esta asignatura. Habla con el profesor.",
        "group": "Grupo",
        "rep_only_title": "Responde el representante",
        "rep_only_message": "El representante de {group} es {name}. Acompaña y ayuda al grupo a decidir.",
        "rep_missing_message": "El profesor aún no eligió al representante de {group}.",
        "join": "ENTRAR",
        "waiting_title": "Esperando al profesor",
        "waiting_message": "La próxima pregunta aparecerá automáticamente.",
        "answer_saved": "Respuesta registrada",
        "ranking": "Clasificación",
        "your_position": "Tu posición",
        "score": "puntos",
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
        "draft_title": "Cuestionario aún no liberado",
        "draft_message": "Espera a que el profesor libere el código QR para la clase.",
        "empty_title": "Cuestionario sin preguntas",
        "empty_message": "Este cuestionario se creó sin preguntas válidas. Genera uno nuevo.",
        "completed_title": "¡Cuestionario completado! 🎉",
        "completed_message": "Sus respuestas se registraron correctamente.",
        "correct": "✅ ¡Correcto!",
        "incorrect": "❌ Incorrecto",
        "skipped": "⏭️ Omitida",
        "language_label": "Idioma",
        "seconds_left": "s restantes",
        "round_points": "en esta pregunta",
        "total_points": "acumulado",
        "waiting_ranking": "Esperando respuestas...",
        "you_got_it": "Acertaste",
        "you_missed": "Fallaste",
        "no_answer": "No respondiste",
        "ranking_next": "La próxima pregunta aparecerá cuando el profesor la libere.",
        "waiting_for_answer": "esperando respuesta",
        "seconds_word": "segundos restantes",
        "true_label": "Verdadero",
        "false_label": "Falso",
        "join_language": "Idioma del cuestionario",
    },
    "en": {
        "html_lang": "en",
        "page_prefix": "Quiz",
        "brand": "EDUCATION MODE",
        "question": "Question",
        "of": "of",
        "answer": "Your Answer",
        "name": "Your name",
        "enrollment": "Your student ID",
        "group_intro": "Group quiz: join with your student ID.",
        "enrollment_invalid": "Enter your student ID.",
        "enrollment_unknown": "I could not find that student ID. Check the number and try again.",
        "enrollment_no_group": "That student ID is not in any group of this course. Talk to the teacher.",
        "group": "Group",
        "rep_only_title": "The representative answers",
        "rep_only_message": "The representative of {group} is {name}. Follow along and help the group decide.",
        "rep_missing_message": "The teacher has not chosen the representative of {group} yet.",
        "join": "JOIN QUIZ",
        "waiting_title": "Waiting for the teacher",
        "waiting_message": "The next question will appear automatically.",
        "answer_saved": "Answer recorded",
        "ranking": "Ranking",
        "your_position": "Your position",
        "score": "points",
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
        "draft_title": "Quiz not released yet",
        "draft_message": "Wait for the teacher to release the QR Code to the class.",
        "empty_title": "Quiz has no questions",
        "empty_message": "This quiz was created without valid questions. Generate a new one.",
        "completed_title": "Quiz Completed! 🎉",
        "completed_message": "Your answers have been successfully recorded.",
        "correct": "✅ Correct!",
        "incorrect": "❌ Incorrect",
        "skipped": "⏭️ Skipped",
        "language_label": "Language",
        "seconds_left": "s left",
        "round_points": "this question",
        "total_points": "total",
        "waiting_ranking": "Waiting for answers...",
        "you_got_it": "You got it right",
        "you_missed": "You got it wrong",
        "no_answer": "You did not answer",
        "ranking_next": "The next question will appear when the teacher releases it.",
        "waiting_for_answer": "waiting for an answer",
        "seconds_word": "seconds left",
        "true_label": "True",
        "false_label": "False",
        "join_language": "Quiz language",
    },
}


def _normalize_public_language(language: Optional[str]) -> Optional[str]:
    return language if language in _PUBLIC_LANGUAGES else None


def _language_cookie_name(quiz_id: str) -> str:
    return f"intarq_quiz_lang_{quiz_id.replace('-', '_')}"


# --- Atualizacao ao vivo da tela do aluno ----------------------------------
#
# A tela se recarregava inteira a cada 2s (meta refresh). Para quem usa leitor de
# tela isso devolve a leitura ao inicio da pagina a cada recarga, e perde o foco
# do teclado. Agora a pagina consulta `/state` e so troca o conteudo quando o
# estado do quiz muda (nova pergunta, resultado, fim) - movendo o foco para o novo
# titulo - e anuncia o relogio apenas em marcos. Sem JavaScript, o `noscript`
# mantem o recarregamento antigo.

_LIVE_CSS = (
    ".sr-only{position:absolute;width:1px;height:1px;margin:-1px;padding:0;"
    "overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}"
    "#live-heading:focus{outline:none}"
)

#: Instantes, em segundos restantes, em que o leitor de tela anuncia o relogio.
#: Anunciar a cada segundo tornaria a pergunta impossivel de ler.
_LIVE_JS = """
(() => {
  const me = document.getElementById('live-script');
  const quiz = me.dataset.quiz;
  let lang = me.dataset.lang;
  let unit = me.dataset.unit;
  let signature = me.dataset.signature;
  let left = null;
  let busy = false;
  let pollTimer = null;
  let clockTimer = null;

  const announce = (message) => {
    const region = document.getElementById('live-announce');
    if (region) region.textContent = message;
  };

  const bindClock = () => {
    const el = document.getElementById('left');
    left = el ? parseInt(el.dataset.seconds, 10) : null;
    if (Number.isNaN(left)) left = null;
  };

  const stop = () => { clearInterval(pollTimer); clearInterval(clockTimer); };

  const swap = async () => {
    busy = true;
    try {
      const res = await fetch(location.href, {cache: 'no-store', credentials: 'same-origin'});
      if (!res.ok) { location.reload(); return; }
      const doc = new DOMParser().parseFromString(await res.text(), 'text/html');
      const incoming = doc.getElementById('live-script');
      const style = document.querySelector('style');
      const nextStyle = doc.querySelector('style');
      if (style && nextStyle) style.textContent = nextStyle.textContent;
      document.title = doc.title;
      document.documentElement.lang = doc.documentElement.lang;
      Array.from(document.body.children).forEach((child) => {
        if (child !== me) child.remove();
      });
      Array.from(doc.body.children).forEach((child) => {
        if (child.id !== 'live-script') document.body.insertBefore(child, me);
      });
      bindClock();
      const heading = document.getElementById('live-heading');
      if (heading) heading.focus();
      if (incoming) {
        // A pagina nova manda: idioma e unidade do relogio seguem o que ela declara.
        signature = incoming.dataset.signature;
        lang = incoming.dataset.lang;
        unit = incoming.dataset.unit;
      } else {
        stop();
      }
    } catch (_) {
      location.reload();
    } finally {
      busy = false;
    }
  };

  const poll = async () => {
    if (busy) return;
    try {
      const res = await fetch(
        '/education/quiz/' + encodeURIComponent(quiz) + '/state?lang=' + encodeURIComponent(lang),
        {cache: 'no-store', credentials: 'same-origin'},
      );
      if (!res.ok) return;
      const s = await res.json();
      const next = [s.status || 'open', s.live_phase || 'lobby', s.current_question_id || ''].join('|');
      if (next !== signature) await swap();
    } catch (_) {}
  };

  const tick = () => {
    if (left === null) return;
    left = Math.max(0, left - 1);
    const el = document.getElementById('left');
    if (el) el.textContent = left;
    if (left === 10 || left === 5) announce(left + ' ' + unit);
  };

  bindClock();
  pollTimer = setInterval(poll, 2000);
  clockTimer = setInterval(tick, 1000);
})();
"""


def _state_signature(quiz: QuizModel) -> str:
    """Assinatura do que a tela do aluno mostra; a pagina so se troca quando muda."""
    return "|".join([
        quiz.status or "open",
        quiz.live_phase or "lobby",
        quiz.current_question_id or "",
    ])


def _live_head() -> str:
    """Recarregamento antigo, so para quem esta sem JavaScript."""
    return '<noscript><meta http-equiv="refresh" content="2"></noscript>'


def _live_block(*, quiz_id: str, language: str, signature: str) -> str:
    text = _PUBLIC_TEXT[language]
    return (
        '<div id="live-announce" class="sr-only" role="status" aria-live="polite"></div>\n'
        f'<script id="live-script" data-quiz="{escape(quiz_id)}" '
        f'data-signature="{escape(signature)}" data-lang="{language}" '
        f'data-unit="{escape(text["seconds_word"])}">{_LIVE_JS}</script>'
    )


_BCP47 = {"pt": "pt-BR", "es": "es", "en": "en"}


def _bcp47(language: Optional[str]) -> str:
    """Codigo de idioma para o atributo `lang` do HTML."""
    return _BCP47.get(language or "", "pt-BR")


def _public_language(
    request: Request,
    override: Optional[str],
    quiz_id: Optional[str] = None,
) -> str:
    """Idioma da tela do aluno: o que ele escolheu vence o do navegador.

    Ordem: `?lang=` (clique no seletor), o idioma escolhido ao entrar (cookie) e,
    so na primeira visita, o do navegador. Sem o cookie, o aluno que escolhia
    espanhol ao entrar voltava para o idioma do celular em qualquer link sem
    `?lang=`.
    """
    if override and override in _PUBLIC_LANGUAGES:
        return override
    if quiz_id:
        remembered = request.cookies.get(_language_cookie_name(quiz_id), "")
        if remembered in _PUBLIC_LANGUAGES:
            return remembered
    accept_lang = request.headers.get("accept-language", "").lower()
    for lang in _PUBLIC_LANGUAGES:
        if lang in accept_lang:
            return lang
    return "pt"


def _generate_quiz_page(
    *,
    quiz_id: str,
    question_id: str,
    question_index: int,
    total_questions: int,
    question_text: str,
    question_type: str,
    options: Optional[list] = None,
    language: str = "pt",
    status: Optional[str] = None,
    feedback: Optional[str] = None,
    student_name: str = "",
    time_limit_seconds: int = 0,
    seconds_remaining: Optional[int] = None,
    content_language: Optional[str] = None,
    signature: str = "",
) -> HTMLResponse:
    """Gera página HTML para responder questão do quiz.

    O relogio so aparece quando o professor definiu um prazo
    (`seconds_remaining` informado). No modo manual a pergunta nao tem fim
    marcado, e uma barra encolhendo sozinha era um prazo que nao existia.

    `content_language` e o idioma em que a pergunta e as alternativas
    **realmente** estao - diferente do idioma da interface quando a traducao
    falhou e o aluno le o original em portugues. Declarar isso (`lang`) e o que
    faz o leitor de tela usar a voz certa e o navegador oferecer a traducao
    dele sobre o trecho certo.
    """

    language = _normalize_public_language(language) or "pt"
    text = _PUBLIC_TEXT[language]
    content_lang = _bcp47(content_language or language)
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
                <label for="opt{idx}" lang="{content_lang}">{escape(option.get('texto', ''))}</label>
            </div>
            """
            options_html += option_html

    else:
        # Verdadeiro/falso (e qualquer tipo sem alternativas). O valor enviado
        # continua "verdadeiro"/"falso" em qualquer idioma: so o rotulo muda.
        options_html = f"""
        <div class="option">
            <input type="radio" id="opt_v" name="answer" value="verdadeiro" required>
            <label for="opt_v">{text["true_label"]}</label>
        </div>
        <div class="option">
            <input type="radio" id="opt_f" name="answer" value="falso" required>
            <label for="opt_f">{text["false_label"]}</label>
        </div>
        """

    button_text = text["submit"]

    # Cada idioma no proprio idioma ("lang" proprio) e o atual marcado: o leitor
    # de tela le "Español" em espanhol e diz qual esta selecionado.
    current = ' aria-current="true"'
    nav_html = "\n".join(
        f'<a href="?lang={code}" lang="{_bcp47(code)}"'
        f'{current if code == language else ""}>{label}</a>'
        for code, label in (("pt", "Português"), ("es", "Español"), ("en", "English"))
    )

    feedback_html = ""
    if feedback:
        feedback_html = f'<div class="feedback {status}">{escape(feedback)}</div>'

    timer_html = ""
    timer_css = ""
    if seconds_remaining is not None:
        remaining = max(0, int(seconds_remaining))
        window = max(int(time_limit_seconds or 0), remaining, 1)
        start_pct = round(remaining / window * 100, 1)
        # O numero muda a cada segundo, mas fora de qualquer regiao `aria-live`:
        # o leitor de tela anuncia o relogio so em marcos (10s e 5s), pelo
        # script compartilhado. A barra e decorativa.
        timer_html = (
            '<div class="timer" aria-hidden="true"><div></div></div>'
            f'<div class="timer-label"><span id="left" data-seconds="{remaining}">'
            f'{remaining}</span>{text["seconds_left"]}</div>'
        )
        timer_css = (
            ".timer{height:8px;background:#e5e7eb;border-radius:999px;"
            "overflow:hidden;margin:0 0 6px}"
            ".timer-label{text-align:right;font-size:13px;font-weight:700;"
            "color:#6b7280;margin:0 0 14px}"
            f".timer div{{width:{start_pct}%;height:100%;background:#22c55e;"
            f"animation:shrink {remaining}s linear forwards}}"
            f"@keyframes shrink{{from{{width:{start_pct}%}}to{{width:0}}}}"
        )

    return HTMLResponse(
        f"""<!doctype html>
<html lang="{text["html_lang"]}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{_live_head()}
<title>{text["page_prefix"]} - {escape(f'{text["question"]} {question_index + 1}')}</title>
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
width:{((question_index + 1) / total_questions) * 100}%;}}
h1{{font-size:20px;margin:20px 0 8px;color:#1f2937}}
.player{{font-size:13px;color:#e0e7ff;margin-top:6px}}
.question-info{{color:#6b7280;font-size:14px;margin-bottom:20px}}
fieldset.choices{{border:0;margin:0;padding:0;min-width:0}}
.question-text{{font-size:18px;font-weight:600;margin:20px 0;line-height:1.5;color:#1f2937;
padding:0;float:left;width:100%}}
.question-text + *{{clear:both}}
.option{{display:flex;align-items:center;padding:12px;margin:8px 0;border:2px solid #e5e7eb;
border-radius:8px;cursor:pointer;transition:all 0.3s}}
.option:hover{{border-color:#667eea;background:#f9fafb}}
.option:focus-within{{border-color:#4f46e5;outline:3px solid #4f46e5;outline-offset:2px}}
.btn-primary:focus-visible,.languages a:focus-visible{{outline:3px solid #facc15;outline-offset:2px}}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important;transition:none!important}}}}
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
{timer_css}
{_LIVE_CSS}
.languages{{display:flex;justify-content:center;gap:8px;margin-bottom:16px}}
.languages a{{color:white;text-decoration:none;border:1px solid rgba(255,255,255,0.5);
border-radius:5px;padding:6px 10px;font-size:12px;transition:all 0.3s}}
.languages a:hover{{border-color:white}}
</style></head><body><main>
<div class="header">
<div class="mark">{text["brand"]}</div>
<nav class="languages" aria-label="{text["language_label"]}">
{nav_html}
</nav>
<div class="player">{escape(student_name)}</div>
<h1 id="live-heading" tabindex="-1">{escape(f'{text["question"]} {question_index + 1}')}</h1>
<div class="progress">
<span>{question_index + 1} {text["of"]} {total_questions}</span>
<div class="progress-bar"><div class="progress-fill"></div></div>
</div>
</div>
{timer_html}
{feedback_html}
<form method="post" action="?lang={language}">
<input type="hidden" name="question_id" value="{escape(question_id)}">
<fieldset class="choices">
<legend class="question-text" lang="{content_lang}">{escape(question_text)}</legend>
{options_html}
</fieldset>
<div class="actions">
<button type="submit" class="btn-primary">{button_text}</button>
</div>
</form>
<small>{text["privacy"]}</small>
</main>
{_live_block(quiz_id=quiz_id, language=language, signature=signature)}
</body></html>""",
        headers={
            "Cache-Control": "no-store",
            "Content-Language": language,
            "Vary": "Accept-Language",
        },
    )


def _attempt_cookie_name(quiz_id: str) -> str:
    return f"intarq_quiz_attempt_{quiz_id.replace('-', '_')}"


def _attempt_id(request: Request, quiz_id: str) -> str:
    cookie_name = _attempt_cookie_name(quiz_id)
    existing = request.cookies.get(cookie_name, "")
    if re.fullmatch(r"[0-9a-f]{32}", existing):
        return existing
    if existing.startswith(f"{quiz_id}:"):
        legacy = existing.split(":", 1)[1]
        if re.fullmatch(r"[0-9a-f]{32}", legacy):
            return legacy
    return uuid.uuid4().hex


def _attach_attempt_cookie(
    response: HTMLResponse,
    *,
    quiz_id: str,
    attempt_id: str,
) -> HTMLResponse:
    response.set_cookie(
        _attempt_cookie_name(quiz_id),
        attempt_id,
        max_age=60 * 60 * 8,
        httponly=True,
        samesite="lax",
    )
    return response


def _attach_language_cookie(
    response: HTMLResponse,
    *,
    quiz_id: str,
    language: str,
) -> HTMLResponse:
    if language in _PUBLIC_LANGUAGES:
        response.set_cookie(
            _language_cookie_name(quiz_id),
            language,
            max_age=60 * 60 * 8,
            httponly=True,
            samesite="lax",
        )
    return response


def _student_cookie_name(quiz_id: str) -> str:
    return f"intarq_quiz_student_{quiz_id.replace('-', '_')}"


def _student_name(request: Request, quiz_id: str) -> str:
    return (request.cookies.get(_student_cookie_name(quiz_id), "") or "").strip()


def _attach_student_cookie(
    response: HTMLResponse,
    *,
    quiz_id: str,
    student_name: str,
) -> HTMLResponse:
    if student_name.strip():
        response.set_cookie(
            _student_cookie_name(quiz_id),
            student_name.strip()[:80],
            max_age=60 * 60 * 8,
            httponly=True,
            samesite="lax",
        )
    return response


#: Intervalo minimo entre gravacoes de "ainda esta aqui". A tela do aluno se
#: recarrega a cada 2s; gravar em toda recarga seria uma escrita por aluno por
#: segundo so para o contador do lobby.
PARTICIPANT_TOUCH_INTERVAL = timedelta(seconds=10)


async def _touch_participant(
    db: AsyncSession,
    *,
    quiz_id: str,
    attempt_id: str,
    student_name: str,
    force: bool = False,
    language: str = "",
) -> None:
    """Registra que o aluno entrou ou continua com a tela aberta."""
    name = (student_name or "").strip()[:80]
    if not name:
        return
    language = language if language in _PUBLIC_LANGUAGES else ""
    now = datetime.now(timezone.utc)
    participant = (await db.execute(
        select(QuizParticipantModel).where(
            QuizParticipantModel.quiz_id == quiz_id,
            QuizParticipantModel.attempt_id == attempt_id,
        )
    )).scalar_one_or_none()
    if participant is None:
        db.add(QuizParticipantModel(
            quiz_id=quiz_id,
            attempt_id=attempt_id,
            student_name=name,
            joined_at=now,
            last_seen_at=now,
            language=language or None,
        ))
    else:
        last_seen = _as_utc(participant.last_seen_at)
        mudou_idioma = bool(language) and participant.language != language
        if (
            not force
            and not mudou_idioma
            and last_seen
            and now - last_seen < PARTICIPANT_TOUCH_INTERVAL
            and participant.student_name == name
        ):
            return
        participant.student_name = name
        participant.last_seen_at = now
        if language:
            participant.language = language
    try:
        await db.commit()
    except IntegrityError:
        # Duas abas do mesmo aluno entrando juntas: a outra ja gravou.
        await db.rollback()
    except SQLAlchemyError as exc:
        # Qualquer outra falha aqui deixava o professor com "Participantes: 0"
        # sem explicacao nenhuma - o lobby mentia em silencio. Engolir para a
        # aula nao parar continua certo; engolir sem deixar rastro, nao.
        await db.rollback()
        logger.error(
            "Nao registrei o participante {} no quiz {}: {}",
            name, quiz_id, exc,
        )


def _play_redirect(
    *,
    quiz_id: str,
    attempt_id: str,
    student_name: str,
    language: str,
) -> RedirectResponse:
    """Depois de um POST, volta para a pagina por GET.

    A tela do aluno se atualiza sozinha. Pagina que veio de POST, ao recarregar,
    faz o navegador pedir confirmacao de reenvio do formulario - e a atualizacao
    simplesmente nao acontece: o aluno ficava parado em "Resposta registrada"
    enquanto o professor ja estava na pergunta seguinte.
    """
    response = RedirectResponse(url=f"play?lang={language}", status_code=303)
    _attach_attempt_cookie(response, quiz_id=quiz_id, attempt_id=attempt_id)
    _attach_student_cookie(response, quiz_id=quiz_id, student_name=student_name)
    _attach_language_cookie(response, quiz_id=quiz_id, language=language)
    return response


def _parse_options(question: QuestionModel) -> list:
    if question.tipo != "multipla_escolha" or not question.opcoes:
        return []
    try:
        decoded = json.loads(question.opcoes)
        return decoded if isinstance(decoded, list) else []
    except (TypeError, ValueError):
        return []


def _is_correct_answer(question: QuestionModel, answer: Optional[str]) -> Optional[bool]:
    if answer is None:
        return None
    expected = (question.resposta_correta or "").strip()
    received = answer.strip()
    if question.tipo == "aberta":
        return None
    if question.tipo == "verdadeiro_falso":
        truthy = {"verdadeiro", "v", "true", "sim", "s", "yes"}
        falsy = {"falso", "f", "false", "nao", "não", "n", "no"}
        expected_bool = expected.lower() in truthy
        if received.lower() in truthy:
            return expected_bool
        if received.lower() in falsy:
            return not expected_bool
        return False
    for option in _parse_options(question):
        if option.get("correta") is True:
            return received == str(option.get("label", "")).strip()
    return received == expected


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _response_time_ms(started_at: Optional[datetime]) -> Optional[int]:
    started = _as_utc(started_at)
    if started is None:
        return None
    elapsed = datetime.now(timezone.utc) - started
    return max(0, int(elapsed.total_seconds() * 1000))


def _score_answer(
    *,
    correta: Optional[bool],
    elapsed_ms: Optional[int],
    time_limit_seconds: Optional[int] = None,
) -> int:
    return quiz_live_service.score_answer(
        correta=correta,
        elapsed_ms=elapsed_ms,
        time_limit_seconds=time_limit_seconds,
    )


async def _answered_question_ids(
    *,
    db: AsyncSession,
    question_ids: list[str],
    attempt_id: str,
) -> set[str]:
    if not question_ids:
        return set()
    stmt = select(StudentAnswerModel).where(
        StudentAnswerModel.question_id.in_(question_ids),
        StudentAnswerModel.student_id == attempt_id,
    )
    answers = (await db.execute(stmt)).scalars().all()
    return {item.question_id for item in answers}


def _next_unanswered_question(
    questions: list[QuestionModel],
    answered_ids: set[str],
) -> tuple[int, Optional[QuestionModel]]:
    for index, question in enumerate(questions):
        if question.id not in answered_ids:
            return index, question
    return len(questions), None


def _question_by_id(
    questions: list[QuestionModel],
    question_id: Optional[str],
) -> Optional[QuestionModel]:
    if not question_id:
        return None
    return next((item for item in questions if item.id == question_id), None)


def _current_question_index(
    questions: list[QuestionModel],
    question_id: Optional[str],
) -> tuple[int, Optional[QuestionModel]]:
    if not question_id:
        return -1, None
    for index, question in enumerate(questions):
        if question.id == question_id:
            return index, question
    return -1, None


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


def _generate_empty_page(*, language: str = "pt") -> HTMLResponse:
    """Gera pagina para quiz salvo sem perguntas validas."""

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
h1{{font-size:24px;margin:0 0 10px;color:#dc2626}}
p{{color:#6b7280;font-size:15px;margin:0}}
</style></head><body><main>
<h1>{text["empty_title"]}</h1>
<p>{text["empty_message"]}</p>
</main></body></html>""",
        status_code=409,
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


def _generate_draft_page(*, language: str = "pt") -> HTMLResponse:
    """Gera pagina informando que o quiz ainda nao foi liberado."""

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
<h1>{text["draft_title"]}</h1>
<p>{text["draft_message"]}</p>
</main></body></html>""",
        status_code=403,
        headers={
            "Cache-Control": "no-store",
            "Content-Language": language,
        },
    )


_LANGUAGE_CHOICES = (("pt", "🇧🇷 Português"), ("es", "🇪🇸 Español"), ("en", "🇺🇸 English"))


def _generate_join_page(
    *,
    quiz_id: str,
    language: str = "pt",
    prefill_name: str = "",
    group_mode: bool = False,
    error: str = "",
) -> HTMLResponse:
    """Tela de entrada: o aluno informa o nome e escolhe o idioma do quiz.

    O idioma escolhido aqui vale para a interface e para a pergunta e as
    alternativas. Trocar o idioma recarrega a tela (para os textos mudarem na
    hora) sem perder o nome ja digitado.
    """
    language = _normalize_public_language(language) or "pt"
    text = _PUBLIC_TEXT[language]
    choices_html = "".join(
        f"""<label class="lang{' on' if code == language else ''}" lang="{_bcp47(code)}">
<input type="radio" name="language" value="{code}"{' checked' if code == language else ''}>
<span>{label}</span></label>"""
        for code, label in _LANGUAGE_CHOICES
    )
    if group_mode:
        # Quiz em grupo: a matricula leva ao grupo; o nome vem do cadastro.
        field_html = (
            f'<input name="enrollment" id="student_name" maxlength="40" required '
            f'autofocus autocomplete="off" aria-label="{text["enrollment"]}" '
            f'placeholder="{text["enrollment"]}" value="{escape(prefill_name)}">'
        )
        group_intro_html = f'<p class="intro">{text["group_intro"]}</p>'
    else:
        field_html = (
            f'<input name="student_name" id="student_name" maxlength="80" required '
            f'autofocus autocomplete="name" aria-label="{text["name"]}" '
            f'placeholder="{text["name"]}" value="{escape(prefill_name)}">'
        )
        group_intro_html = ""
    error_html = (
        f'<p class="error" role="alert">{escape(error)}</p>' if error else ""
    )
    return HTMLResponse(
        f"""<!doctype html>
<html lang="{text["html_lang"]}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{text["page_prefix"]}</title>
<style>
.intro{{margin:0 0 4px;color:#4b5563;font-size:14px}}
.error{{margin:10px 0 0;padding:10px 12px;border-radius:8px;background:#fef2f2;
color:#b91c1c;font-size:14px;font-weight:600}}
input[name=enrollment]:focus-visible{{outline:3px solid #4f46e5;outline-offset:2px}}
*{{box-sizing:border-box}}
body{{margin:0;background:linear-gradient(135deg,#2563eb,#7c3aed);color:#111827;
font:16px system-ui,-apple-system,Segoe UI,sans-serif;min-height:100vh;display:grid;
place-items:center;padding:20px}}
main{{width:min(460px,100%);background:white;border-radius:14px;padding:34px;
box-shadow:0 18px 45px #11182740;text-align:center}}
.brand{{font-size:12px;font-weight:900;letter-spacing:2px;color:#4f46e5}}
h1{{font-size:30px;margin:12px 0;color:#111827}}
input{{width:100%;padding:14px 16px;border:2px solid #d1d5db;border-radius:10px;
font-size:18px;margin:18px 0 14px}}
button{{width:100%;padding:14px;border:0;border-radius:10px;background:#4f46e5;
color:white;font-weight:900;letter-spacing:.8px;cursor:pointer}}
fieldset.langs{{margin:4px 0 18px;padding:0;border:0;min-width:0;text-align:left}}
.langs legend{{padding:0;margin:0 0 8px;font-size:13px;font-weight:700;color:#4b5563}}
.langs div{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}
.lang{{display:block;position:relative;border:2px solid #d1d5db;border-radius:10px;
padding:10px 4px;text-align:center;font-size:14px;font-weight:700;color:#374151;cursor:pointer}}
/* Escondido so da vista: continua focavel por teclado e lido pelo leitor de tela. */
.lang input{{position:absolute;opacity:0;inset:0;margin:0;cursor:pointer}}
.lang.on{{border-color:#4f46e5;background:#eef2ff;color:#3730a3}}
.lang:focus-within{{outline:3px solid #4f46e5;outline-offset:2px}}
input[name=student_name]:focus-visible,button:focus-visible{{outline:3px solid #4f46e5;outline-offset:2px}}
</style></head><body><main>
<div class="brand">{text["brand"]}</div>
<h1>{text["page_prefix"]}</h1>
<form method="post" action="?lang={language}" id="join">
{group_intro_html}{error_html}{field_html}
<fieldset class="langs"><legend>{text["join_language"]}</legend><div>{choices_html}</div></fieldset>
<button type="submit">{text["join"]}</button>
</form>
<script>
document.querySelectorAll('input[name=language]').forEach((radio) => {{
  radio.addEventListener('change', () => {{
    const name = document.getElementById('student_name').value;
    window.location.href = '?lang=' + radio.value + '&name=' + encodeURIComponent(name);
  }});
}});
</script>
</main></body></html>""",
        headers={"Cache-Control": "no-store", "Content-Language": language},
    )


def _generate_waiting_page(
    *,
    quiz_id: str,
    student_name: str,
    language: str = "pt",
    answered: bool = False,
    signature: str = "",
    notice: Optional[tuple[str, str]] = None,
) -> HTMLResponse:
    """Tela de espera. `notice` troca o titulo e a mensagem (quiz em grupo)."""
    language = _normalize_public_language(language) or "pt"
    text = _PUBLIC_TEXT[language]
    title = text["answer_saved"] if answered else text["waiting_title"]
    message = text["waiting_message"]
    if notice is not None:
        title, message = notice
    return HTMLResponse(
        f"""<!doctype html>
<html lang="{text["html_lang"]}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{_live_head()}
<title>{text["page_prefix"]}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#111827;color:white;font:16px system-ui,-apple-system,Segoe UI,sans-serif;
min-height:100vh;display:grid;place-items:center;padding:20px}}
main{{width:min(480px,100%);text-align:center}}
.pulse{{width:84px;height:84px;border:8px solid #38bdf8;border-top-color:transparent;
border-radius:50%;margin:0 auto 22px;animation:spin 1s linear infinite}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
h1{{font-size:28px;margin:0 0 10px}}
p{{color:#cbd5e1;margin:6px 0}}
.player{{font-weight:800;color:#93c5fd}}
@media (prefers-reduced-motion:reduce){{.pulse{{animation:none}}}}
{_LIVE_CSS}
</style></head><body><main>
<div class="pulse" aria-hidden="true"></div>
<p class="player">{escape(student_name)}</p>
<h1 id="live-heading" tabindex="-1">{escape(title)}</h1>
<p>{escape(message)}</p>
</main>
{_live_block(quiz_id=quiz_id, language=language, signature=signature)}
</body></html>""",
        headers={"Cache-Control": "no-store", "Content-Language": language},
    )


def _ranking_rows(
    answers: list[StudentAnswerModel],
    current_question_id: Optional[str] = None,
) -> list[dict]:
    return quiz_live_service.ranking_rows(answers, current_question_id)


async def _ranking_for_quiz(
    *,
    db: AsyncSession,
    quiz_id: str,
    question_id: Optional[str] = None,
) -> list[dict]:
    """Ranking do quiz inteiro, por pontos acumulados.

    `question_id` nao filtra: so diz qual pergunta alimenta o `round_score`. O
    ranking da rodada mostrava apenas os pontos da ultima pergunta e escondia o
    acumulado que decide a classificacao.
    """
    question_stmt = select(QuestionModel.id).where(QuestionModel.quiz_id == quiz_id)
    question_ids = [row[0] for row in (await db.execute(question_stmt)).all()]
    if not question_ids:
        return []
    stmt = select(StudentAnswerModel).where(
        StudentAnswerModel.question_id.in_(question_ids)
    )
    answers = list((await db.execute(stmt)).scalars().all())
    # Quiz em grupo: a turma ve o ranking dos grupos, no mesmo formato.
    group_config = await quiz_group_service.get_config(db, quiz_id)
    if group_config is not None:
        ctx = await quiz_group_service.load_context(db, group_config)
        return quiz_group_service.group_ranking_rows(answers, question_id, ctx)
    return _ranking_rows(answers, question_id)


def _generate_ranking_page(
    *,
    quiz_id: str,
    student_id: str,
    student_name: str,
    rows: list[dict],
    current_question_text: str = "",
    language: str = "pt",
    final: bool = False,
    round_active: bool = False,
    current_question_language: Optional[str] = None,
    signature: str = "",
) -> HTMLResponse:
    """Ranking da turma com pontos acumulados e o que cada um fez na pergunta.

    `round_active` e verdadeiro entre perguntas, quando a rodada que acabou ainda
    esta na tela: so ai faz sentido o "+N nesta pergunta" ao lado do total.
    """
    language = _normalize_public_language(language) or "pt"
    text = _PUBLIC_TEXT[language]
    top_rows = rows[:10]
    own = next((row for row in rows if row["student_id"] == student_id), None)

    def round_badge(row: dict) -> str:
        if not round_active:
            return ""
        points = int(row.get("round_score") or 0)
        return (
            f'<small class="{"gain" if points else "none"}">'
            f'+{points} {text["round_points"]}</small>'
        )

    rows_html = "".join(
        f"""<li{' class="me"' if row["student_id"] == student_id else ""}>
<strong>#{row["position"]}</strong>
<span>{escape(row["student_name"])}{round_badge(row)}</span>
<em>{row["score"]} {text["score"]}</em></li>"""
        for row in top_rows
    ) or f"<li><span>{text['waiting_ranking']}</span></li>"

    if own is None:
        own_html = (
            f"""<div class="own">{text["your_position"]}: {text["waiting_for_answer"]}</div>"""
        )
    else:
        verdict = ""
        if round_active:
            if own.get("round_correct") is True:
                verdict = f'<div class="verdict ok">{text["you_got_it"]} · +{own["round_score"]} {text["round_points"]}</div>'
            elif own.get("round_correct") is False:
                verdict = f'<div class="verdict bad">{text["you_missed"]}</div>'
            else:
                verdict = f'<div class="verdict bad">{text["no_answer"]}</div>'
        own_html = (
            f"""<div class="own">{verdict}{text["your_position"]}: <strong>#{own["position"]}</strong>
 - {own["score"]} {text["score"]} {text["total_points"]}</div>"""
        )
    waiting_html = (
        f'<p class="next">{text["ranking_next"]}</p>' if round_active else ""
    )
    # Ranking final nao muda mais: sem consulta nem recarregamento.
    live_head = "" if final else _live_head()
    live_block = (
        ""
        if final
        else _live_block(quiz_id=quiz_id, language=language, signature=signature)
    )
    return HTMLResponse(
        f"""<!doctype html>
<html lang="{text["html_lang"]}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{live_head}
<title>{text["ranking"]}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:linear-gradient(135deg,#0f172a,#581c87);color:white;
font:16px system-ui,-apple-system,Segoe UI,sans-serif;min-height:100vh;padding:20px;
display:grid;place-items:center}}
main{{width:min(620px,100%)}}
.player{{color:#c4b5fd;font-weight:800;text-align:center}}
h1{{font-size:36px;text-align:center;margin:8px 0 18px}}
.question{{background:#ffffff14;border:1px solid #ffffff25;border-radius:12px;
padding:14px;margin-bottom:16px;color:#e0e7ff}}
ol{{list-style:none;padding:0;margin:0;display:grid;gap:8px}}
li{{display:grid;grid-template-columns:64px 1fr auto;gap:10px;align-items:center;
background:white;color:#111827;border-radius:10px;padding:12px 14px}}
li.me{{outline:3px solid #facc15}}
li strong{{font-size:20px;color:#7c3aed}}
li span small{{display:block;font-size:12px;font-weight:700;margin-top:2px}}
li span small.gain{{color:#15803d}}
li span small.none{{color:#6b7280}}
li em{{font-style:normal;font-weight:900;color:#0f766e}}
.own{{margin-top:18px;background:#facc15;color:#422006;border-radius:12px;
padding:16px;text-align:center;font-size:20px;font-weight:800}}
.verdict{{font-size:16px;margin-bottom:6px}}
.verdict.ok{{color:#14532d}}
.verdict.bad{{color:#7f1d1d}}
.next{{text-align:center;color:#cbd5e1;margin:14px 0 0;font-size:14px}}
.own{{margin:0 0 16px}}
{_LIVE_CSS}
</style></head><body><main>
<p class="player">{escape(student_name)}</p>
<h1 id="live-heading" tabindex="-1">{text["ranking"]}</h1>
{f'<div class="question" lang="{_bcp47(current_question_language or language)}">{escape(current_question_text)}</div>' if current_question_text else ''}
{own_html}
<ol>{rows_html}</ol>
{waiting_html}
</main>
{live_block}
</body></html>""",
        headers={"Cache-Control": "no-store", "Content-Language": language},
    )


async def _render_live_quiz_page(
    *,
    quiz: QuizModel,
    questions: list[QuestionModel],
    request: Request,
    language: str,
    student_name: str,
    db: AsyncSession,
    answered: bool = False,
) -> HTMLResponse:
    attempt_id = _attempt_id(request, quiz.id)
    response: HTMLResponse

    # Quiz em grupo: o ranking mostrado e o dos grupos, e "voce" e o seu grupo.
    group_config = await quiz_group_service.get_config(db, quiz.id)
    group_ctx = (
        await quiz_group_service.load_context(db, group_config)
        if group_config is not None
        else None
    )
    viewer_id = attempt_id
    if group_ctx is not None:
        viewer_id = group_ctx.group_of_attempt(attempt_id) or attempt_id

    # Prazo vencido vira ranking aqui mesmo: o aluno nao depende de o painel do
    # professor estar aberto para a pergunta encerrar.
    await quiz_live_service.expire_question_if_due(db, quiz)
    # O que a tela mostra agora: a pagina so se troca quando isto muda.
    signature = _state_signature(quiz)

    if quiz.live_phase in {"results", "finished"} or quiz.status == "closed":
        current_question = _question_by_id(questions, quiz.current_question_id)
        round_active = quiz.live_phase == "results" and quiz.status != "closed"
        rows = await _ranking_for_quiz(
            db=db,
            quiz_id=quiz.id,
            question_id=quiz.current_question_id if round_active else None,
        )
        question_text = current_question.enunciado if current_question else ""
        question_language = "pt"
        if current_question is not None:
            # So o que ja esta traduzido: o ranking nao espera o modelo.
            translated = (await quiz_translation_service.cached_translations(
                db, [current_question.id], language
            )).get(current_question.id)
            if translated:
                question_text = translated["enunciado"]
                question_language = language
        response = _generate_ranking_page(
            quiz_id=quiz.id,
            student_id=viewer_id,
            student_name=student_name,
            rows=rows,
            current_question_text=question_text,
            current_question_language=question_language,
            language=language,
            final=quiz.live_phase == "finished" or quiz.status == "closed",
            round_active=round_active,
            signature=signature,
        )
    elif quiz.live_phase != "question" or not quiz.current_question_id:
        response = _generate_waiting_page(
            quiz_id=quiz.id,
            student_name=student_name,
            language=language,
            answered=answered,
            signature=signature,
        )
    else:
        question_index, question = _current_question_index(
            questions,
            quiz.current_question_id,
        )
        if question is None:
            response = _generate_waiting_page(
                quiz_id=quiz.id,
                student_name=student_name,
                language=language,
                signature=signature,
            )
        elif group_ctx is not None and not group_ctx.may_answer(attempt_id):
            # Modo representante: este integrante acompanha, nao responde.
            text = _PUBLIC_TEXT[language]
            grupo = group_ctx.group_of_attempt(attempt_id) or ""
            nome_grupo = group_ctx.group_names.get(grupo, text["group"])
            rep = group_ctx.representatives.get(grupo)
            if rep:
                notice = (
                    text["rep_only_title"],
                    text["rep_only_message"].format(
                        group=nome_grupo, name=group_ctx.member_names.get(rep, "")
                    ),
                )
            else:
                notice = (
                    text["rep_only_title"],
                    text["rep_missing_message"].format(group=nome_grupo),
                )
            response = _generate_waiting_page(
                quiz_id=quiz.id,
                student_name=student_name,
                language=language,
                signature=signature,
                notice=notice,
            )
        else:
            answered_ids = await _answered_question_ids(
                db=db,
                question_ids=[question.id],
                attempt_id=attempt_id,
            )
            if question.id in answered_ids or answered:
                response = _generate_waiting_page(
                    quiz_id=quiz.id,
                    student_name=student_name,
                    language=language,
                    answered=True,
                    signature=signature,
                )
            else:
                question_text = question.enunciado
                options = _parse_options(question)
                # Idioma em que o texto esta de verdade: o original e sempre
                # portugues, mesmo com a interface em outro idioma.
                content_language = "pt"
                # Pergunta e alternativas no idioma escolhido. Sem traducao
                # (modelo fora do ar, sem provedor), o aluno le o original.
                translated = await quiz_translation_service.ensure_for_question(
                    db,
                    quiz_id=quiz.id,
                    tutor_id=quiz.tutor_id,
                    question_ids=[item.id for item in questions],
                    current_question_id=question.id,
                    language=language,
                )
                if translated:
                    question_text = translated["enunciado"]
                    options = _translated_options(options, translated["opcoes"])
                    content_language = language
                response = _generate_quiz_page(
                    quiz_id=quiz.id,
                    question_id=question.id,
                    question_index=question_index,
                    total_questions=len(questions),
                    question_text=question_text,
                    question_type=question.tipo,
                    options=options,
                    language=language,
                    student_name=student_name,
                    time_limit_seconds=quiz.time_limit_seconds or 0,
                    seconds_remaining=quiz_live_service.seconds_remaining(quiz),
                    content_language=content_language,
                    signature=signature,
                )

    _attach_attempt_cookie(response, quiz_id=quiz.id, attempt_id=attempt_id)
    _attach_student_cookie(response, quiz_id=quiz.id, student_name=student_name)
    _attach_language_cookie(response, quiz_id=quiz.id, language=language)
    return response


def _translated_options(original: list, translated: list) -> list:
    """Alternativas com o texto traduzido, na ordem e com as letras originais.

    A letra e o que o aluno envia e o que corrige a resposta; so o texto muda.
    Alternativa sem traducao correspondente mantem o texto original.
    """
    by_label = {
        str(item.get("label", "")).strip().upper(): item.get("texto", "")
        for item in translated
        if isinstance(item, dict)
    }
    return [
        {
            **option,
            "texto": by_label.get(str(option.get("label", "")).strip().upper())
            or option.get("texto", ""),
        }
        for option in original
    ]


@router.get("/{quiz_token}/state")
async def quiz_public_state(
    quiz_token: str,
    request: Request,
    lang: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Estado publico minimo para sincronizar a tela do aluno.

    Tambem e o sinal de vida do aluno. A tela se recarregava a cada 2s e era o
    recarregamento que marcava presenca; agora ela so consulta o estado, e e esta
    consulta que mantem o aluno "online" no lobby do professor. So conta quem ja
    entrou (tem o cookie de tentativa e o nome): consulta anonima nao cria
    participante.
    """

    stmt = select(QuizModel).where(QuizModel.id == quiz_token)
    quiz = (await db.execute(stmt)).scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")

    student_name = _student_name(request, quiz_token)
    if (
        quiz.status == "open"
        and student_name
        and request.cookies.get(_attempt_cookie_name(quiz_token))
    ):
        await _touch_participant(
            db,
            quiz_id=quiz.id,
            attempt_id=_attempt_id(request, quiz_token),
            student_name=student_name,
            language=_public_language(request, lang, quiz_token),
        )
    # A tela do aluno consulta isto a cada 2s para saber se deve recarregar:
    # e o lugar certo para o prazo da pergunta virar "encerrada".
    await quiz_live_service.expire_question_if_due(db, quiz)
    return {
        "quiz_id": quiz.id,
        "status": quiz.status or "open",
        "live_phase": quiz.live_phase or "lobby",
        "current_question_id": quiz.current_question_id,
        "seconds_remaining": quiz_live_service.seconds_remaining(quiz),
    }


@router.get("/{quiz_token}/play", response_class=HTMLResponse)
async def quiz_play_page(
    quiz_token: str,
    request: Request,
    lang: Optional[str] = Query(default=None),
    name: Optional[str] = Query(default=None, max_length=80),
    db: AsyncSession = Depends(get_db),
):
    """Exibe questão do quiz para responder."""

    language = _public_language(request, lang, quiz_token)

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

    if quiz.status not in {"open", "closed"}:
        return _generate_draft_page(language=language)

    attempt_id = _attempt_id(request, quiz_token)

    # Busca questões
    stmt = select(QuestionModel).where(
        QuestionModel.quiz_id == quiz_token
    ).order_by(QuestionModel.created_at, QuestionModel.id)
    questions = (await db.execute(stmt)).scalars().all()

    if not questions:
        return _generate_empty_page(language=language)

    student_name = _student_name(request, quiz_token)
    group_config = await quiz_group_service.get_config(db, quiz.id)
    if group_config is not None:
        # Quiz em grupo: quem vale e o vinculo gravado pela matricula, nao o
        # nome que estiver no cookie. Sem vinculo, volta para a entrada.
        group_link = await quiz_group_service.get_link(db, quiz.id, attempt_id)
        student_name = group_link.member_name if group_link else ""
    if not student_name:
        if quiz.status == "closed":
            return _generate_closed_page(language=language)
        return _attach_attempt_cookie(
            _generate_join_page(
                quiz_id=quiz_token,
                language=language,
                prefill_name=(name or "").strip(),
                group_mode=group_config is not None,
            ),
            quiz_id=quiz_token,
            attempt_id=attempt_id,
        )

    if quiz.status == "open":
        await _touch_participant(
            db,
            quiz_id=quiz.id,
            attempt_id=attempt_id,
            student_name=student_name,
            language=language,
        )
        # Aluno em ingles ou espanhol: comeca a traduzir o quiz agora, para a
        # pergunta ja estar pronta quando o professor abrir.
        await quiz_translation_service.warm_if_missing(
            db,
            quiz_id=quiz.id,
            tutor_id=quiz.tutor_id,
            question_ids=[question.id for question in questions],
            language=language,
        )

    return await _render_live_quiz_page(
        quiz=quiz,
        questions=questions,
        request=request,
        language=language,
        student_name=student_name,
        db=db,
    )


@router.post("/{quiz_token}/play", response_class=HTMLResponse)
async def quiz_submit_answer(
    quiz_token: str,
    request: Request,
    lang: Optional[str] = Query(default=None),
    answer: Optional[str] = Form(default=None),
    question_id: Optional[str] = Form(default=None),
    student_name: Optional[str] = Form(default=None),
    enrollment: Optional[str] = Form(default=None, max_length=40),
    skip: Optional[str] = Form(default=None),
    language_choice: Optional[str] = Form(default=None, alias="language"),
    db: AsyncSession = Depends(get_db),
):
    """Processa resposta e exibe próxima questão.

    Na entrada, o idioma escolhido junto do nome vence o da URL e o do navegador.
    """

    language = _normalize_public_language(language_choice) or _public_language(
        request, lang, quiz_token
    )

    # Busca quiz
    stmt = select(QuizModel).where(QuizModel.id == quiz_token)
    quiz = (await db.execute(stmt)).scalar_one_or_none()

    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")
    if quiz.status not in {"open", "closed"}:
        return _generate_draft_page(language=language)

    attempt_id = _attempt_id(request, quiz_token)

    # Busca todas as questões
    stmt = select(QuestionModel).where(
        QuestionModel.quiz_id == quiz_token
    ).order_by(QuestionModel.created_at, QuestionModel.id)
    all_questions = (await db.execute(stmt)).scalars().all()

    if not all_questions:
        return _generate_empty_page(language=language)

    display_name = (student_name or _student_name(request, quiz_token)).strip()[:80]
    group_config = await quiz_group_service.get_config(db, quiz.id)
    group_ctx = None
    if group_config is not None:
        group_link = await quiz_group_service.get_link(db, quiz.id, attempt_id)
        if enrollment is not None and quiz.status == "open":
            # Entrada pela matricula: o servidor acha o grupo, o aluno nao escolhe.
            try:
                resolved = await quiz_group_service.resolve_enrollment(
                    db, group_config, enrollment
                )
            except quiz_group_service.EnrollmentError as exc:
                text = _PUBLIC_TEXT[language]
                key = {
                    "invalid": "enrollment_invalid",
                    "no_group": "enrollment_no_group",
                }.get(exc.code, "enrollment_unknown")
                return _attach_attempt_cookie(
                    _generate_join_page(
                        quiz_id=quiz_token,
                        language=language,
                        prefill_name=enrollment.strip(),
                        group_mode=True,
                        error=text[key],
                    ),
                    quiz_id=quiz_token,
                    attempt_id=attempt_id,
                )
            group_link = await quiz_group_service.link_attempt(
                db, quiz.id, attempt_id, resolved
            )
        display_name = group_link.member_name if group_link else ""
        if group_link is not None:
            group_ctx = await quiz_group_service.load_context(db, group_config)
    if not display_name:
        if quiz.status == "closed":
            return _generate_closed_page(language=language)
        return _attach_attempt_cookie(
            _generate_join_page(
                quiz_id=quiz_token,
                language=language,
                group_mode=group_config is not None,
            ),
            quiz_id=quiz_token,
            attempt_id=attempt_id,
        )

    if quiz.status == "open":
        await _touch_participant(
            db,
            quiz_id=quiz.id,
            attempt_id=attempt_id,
            student_name=display_name,
            force=True,
            language=language,
        )
        await quiz_translation_service.warm_if_missing(
            db,
            quiz_id=quiz.id,
            tutor_id=quiz.tutor_id,
            question_ids=[question.id for question in all_questions],
            language=language,
        )

    # Resposta que chega depois do prazo (e da folga de rede) nao conta: o
    # prazo fecha a pergunta aqui, antes de decidir se a resposta ainda vale.
    await quiz_live_service.expire_question_if_due(db, quiz)

    submitted_question = _question_by_id(all_questions, question_id)
    # No modo representante so ele responde: a resposta dos outros integrantes
    # nao e gravada, e a tela deles ja avisa quem responde pelo grupo.
    may_answer = group_ctx is None or group_ctx.may_answer(attempt_id)
    if (
        may_answer
        and quiz.live_phase == "question"
        and submitted_question is not None
        and submitted_question.id == quiz.current_question_id
    ):
        answered_ids = await _answered_question_ids(
            db=db,
            question_ids=[submitted_question.id],
            attempt_id=attempt_id,
        )
        if submitted_question.id not in answered_ids:
            response_text = "" if skip == "true" else answer
            elapsed_ms = _response_time_ms(quiz.question_started_at)
            correta = None if skip == "true" else _is_correct_answer(
                submitted_question,
                response_text,
            )
            db.add(StudentAnswerModel(
                id=str(uuid.uuid4()),
                question_id=submitted_question.id,
                student_id=attempt_id,
                student_name=display_name,
                resposta=response_text,
                correta=correta,
                tempo_resposta=elapsed_ms,
                pontuacao=_score_answer(
                    correta=correta,
                    elapsed_ms=elapsed_ms,
                    time_limit_seconds=quiz.time_limit_seconds,
                ),
            ))
            await db.commit()

    # O GET decide o que mostrar a partir do banco: com a resposta gravada, a
    # pergunta atual aparece como "Resposta registrada" ate o professor avancar.
    return _play_redirect(
        quiz_id=quiz.id,
        attempt_id=attempt_id,
        student_name=display_name,
        language=language,
    )
