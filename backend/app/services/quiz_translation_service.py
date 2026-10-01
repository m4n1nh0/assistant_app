"""Traducao da pergunta e das alternativas do quiz para o idioma do aluno.

A tela do aluno ja trocava os textos da interface (botoes, avisos), mas a
pergunta e as alternativas continuavam em portugues: quem escolhia ingles ou
espanhol lia a interface num idioma e a pergunta em outro. Aqui a traducao e
feita pelo modelo do professor, uma vez por (pergunta, idioma), e gravada: a
turma inteira le a mesma traducao, e abrir a pergunta nao espera o modelo
depois da primeira vez.

Regras que mantem o quiz correto:

- as alternativas sao identificadas pela **letra**, nao pelo texto, entao o
  gabarito nao muda com a traducao;
- traducao que nao fecha com a pergunta original (outra quantidade de
  alternativas, letra trocada, texto vazio) e descartada, e o aluno le o
  original - pergunta em portugues e melhor do que pergunta traduzida errada;
- falha do modelo nunca derruba a tela do aluno.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    AsyncSessionLocal,
    QuestionModel,
    QuestionTranslationModel,
)
from . import quiz_generator_service
from .llm_service import dispatch_single
from .user_llm_config_service import (
    activate_user_llms,
    load_user_llm_runtime,
    reset_user_llms,
)

#: Idioma em que as perguntas nascem; nao ha o que traduzir.
SOURCE_LANGUAGE = "pt"

LANGUAGE_NAMES = {
    "pt": "português do Brasil",
    "es": "espanhol",
    "en": "inglês",
}

#: Questoes por chamada: JSON curto nao volta cortado.
BATCH_SIZE = 5

#: Quanto a tela do aluno espera a traducao da pergunta que acabou de abrir.
ON_DEMAND_TIMEOUT_SECONDS = 12

TRANSLATION_PROMPT = """Traduza as perguntas de quiz abaixo para {idioma}.

Regras:
1. Traduza o enunciado e o texto de cada alternativa, mantendo o sentido exato.
2. Mantenha as letras (labels) das alternativas, a ordem e a quantidade.
3. Não traduza nomes próprios, siglas, código nem comandos (por exemplo SQL,
   3FN, SELECT); termos comuns da área devem ser traduzidos normalmente.
4. Não explique, não acrescente nem remova conteúdo, e não indique a resposta correta.

**Perguntas:**
{perguntas_json}

Responda somente com JSON válido, sem markdown:
{{
  "traducoes": [
    {{
      "id": "o id da pergunta, copiado",
      "enunciado": "pergunta traduzida",
      "opcoes": [
        {{"label": "A", "texto": "alternativa traduzida"}}
      ]
    }}
  ]
}}
"""

#: Traducoes em andamento por (quiz, idioma), para a turma inteira pedindo o
#: mesmo idioma ao mesmo tempo gerar uma chamada ao modelo, nao trinta.
_in_flight: Dict[tuple, "asyncio.Task[None]"] = {}

#: Depois de uma tentativa que nao traduziu tudo (sem provedor, modelo fora do
#: ar), espera antes de tentar de novo. Sem isso, cada recarga da tela de cada
#: aluno - a cada 2s - dispararia outra chamada que falha do mesmo jeito.
RETRY_COOLDOWN_SECONDS = 60
_cooldown_until: Dict[tuple, float] = {}


def is_translatable(language: Optional[str]) -> bool:
    return bool(language) and language in LANGUAGE_NAMES and language != SOURCE_LANGUAGE


def _options_of(question: QuestionModel) -> List[Dict[str, str]]:
    if question.tipo != "multipla_escolha" or not question.opcoes:
        return []
    try:
        decoded = json.loads(question.opcoes)
    except (TypeError, ValueError):
        return []
    if not isinstance(decoded, list):
        return []
    return [
        {"label": str(item.get("label", "")), "texto": str(item.get("texto", ""))}
        for item in decoded
        if isinstance(item, dict)
    ]


def parse_translations(
    content: str,
    originals: Sequence[QuestionModel],
) -> Dict[str, Dict[str, Any]]:
    """Le a resposta do modelo e devolve so as traducoes que fecham com o original."""
    data = quiz_generator_service.json_from_content(content or "")
    items = data.get("traducoes") or data.get("translations")
    if not isinstance(items, list):
        return {}

    by_id = {question.id: question for question in originals}
    result: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        question = by_id.get(str(item.get("id") or "").strip())
        if question is None:
            continue

        enunciado = " ".join(str(item.get("enunciado") or "").split())
        if not enunciado:
            continue

        original_options = _options_of(question)
        translated: List[Dict[str, str]] = []
        if original_options:
            raw = item.get("opcoes")
            if not isinstance(raw, list) or len(raw) != len(original_options):
                continue
            by_label = {
                str(option.get("label", "")).strip().upper(): " ".join(
                    str(option.get("texto") or "").split()
                )
                for option in raw
                if isinstance(option, dict)
            }
            ok = True
            for original in original_options:
                texto = by_label.get(original["label"].strip().upper(), "")
                if not texto:
                    ok = False
                    break
                translated.append({"label": original["label"], "texto": texto})
            if not ok:
                continue

        result[question.id] = {"enunciado": enunciado, "opcoes": translated}
    return result


async def cached_translations(
    db: AsyncSession,
    question_ids: Iterable[str],
    language: str,
) -> Dict[str, Dict[str, Any]]:
    """Traducoes ja gravadas para o idioma, por id de pergunta."""
    ids = list(question_ids)
    if not ids or not is_translatable(language):
        return {}
    rows = (await db.execute(
        select(QuestionTranslationModel).where(
            QuestionTranslationModel.question_id.in_(ids),
            QuestionTranslationModel.language == language,
        )
    )).scalars().all()

    result: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        try:
            options = json.loads(row.opcoes) if row.opcoes else []
        except (TypeError, ValueError):
            options = []
        result[row.question_id] = {
            "enunciado": row.enunciado,
            "opcoes": options if isinstance(options, list) else [],
        }
    return result


SYSTEM_PROMPT = "Traduza perguntas de quiz e responda somente com JSON válido."


def build_translation_prompt(
    batch: Sequence[QuestionModel],
    language: str,
) -> Dict[str, Any]:
    """Prompt de traducao de um lote de perguntas.

    Usado pelo servidor e tambem entregue ao app do professor, que traduz com
    Codex ou Claude quando o servidor nao tem provedor de IA: a mesma redacao e o
    mesmo formato de resposta nos dois caminhos.
    """
    payload = json.dumps(
        [
            {
                "id": question.id,
                "enunciado": question.enunciado,
                "opcoes": _options_of(question),
            }
            for question in batch
        ],
        ensure_ascii=False,
        indent=2,
    )
    return {
        "system_prompt": SYSTEM_PROMPT,
        "prompt": TRANSLATION_PROMPT.format(
            idioma=LANGUAGE_NAMES[language], perguntas_json=payload
        ),
        "question_ids": [question.id for question in batch],
    }


async def missing_question_ids(
    db: AsyncSession,
    question_ids: Sequence[str],
    language: str,
) -> List[str]:
    """Perguntas ainda sem traducao no idioma, na ordem do quiz."""
    have = await cached_translations(db, question_ids, language)
    return [qid for qid in question_ids if qid not in have]


def backend_gave_up(question_ids: Sequence[str], language: str) -> bool:
    """O servidor tentou traduzir e nao conseguiu (sem provedor, modelo fora)."""
    key = (tuple(sorted(question_ids)), language)
    return _cooldown_until.get(key, 0) > time.monotonic()


def backend_translating(quiz_id: str, language: str) -> bool:
    running = _in_flight.get((quiz_id, language))
    return running is not None and not running.done()


async def store_external(
    db: AsyncSession,
    *,
    content: str,
    language: str,
    questions: Sequence[QuestionModel],
) -> int:
    """Grava a traducao feita por um agente do app do professor.

    Passa pela mesma validacao da traducao do servidor: o que nao fecha com a
    pergunta original e descartado, em vez de gravado.
    """
    if not is_translatable(language):
        return 0
    already = await cached_translations(db, [q.id for q in questions], language)
    translated = {
        question_id: value
        for question_id, value in parse_translations(content, questions).items()
        if question_id not in already
    }
    await _store(db, translated, language)
    return len(translated)


async def _translate_batch(
    batch: Sequence[QuestionModel],
    language: str,
    candidates: List[str],
) -> Dict[str, Dict[str, Any]]:
    prompt = build_translation_prompt(batch, language)["prompt"]

    for llm_name in list(candidates):
        try:
            response = await dispatch_single(
                llm_name,
                prompt,
                [],
                SYSTEM_PROMPT,
                max_tokens=quiz_generator_service.token_budget(len(batch)),
            )
        except Exception as error:
            logger.warning(f"Traducao do quiz falhou em {llm_name}: {error}")
            continue
        if response.is_error:
            logger.warning(f"Traducao do quiz recusada por {llm_name}: {response.content}")
            continue
        translated = parse_translations(response.content, batch)
        if translated:
            return translated
        logger.warning(f"Traducao do quiz sem resultado aproveitavel em {llm_name}")
    return {}


async def _store(
    session: AsyncSession,
    translations: Dict[str, Dict[str, Any]],
    language: str,
) -> None:
    for question_id, value in translations.items():
        session.add(QuestionTranslationModel(
            question_id=question_id,
            language=language,
            enunciado=value["enunciado"],
            opcoes=json.dumps(value["opcoes"], ensure_ascii=False),
        ))
        try:
            await session.commit()
        except IntegrityError:
            # Outra requisicao gravou a mesma traducao primeiro: vale a dela.
            await session.rollback()


async def translate_questions(
    *,
    tutor_id: str,
    question_ids: Sequence[str],
    language: str,
    session_factory=None,
) -> None:
    """Traduz e grava as perguntas que ainda nao tem traducao no idioma.

    Roda fora da requisicao do aluno, com as chaves de provedor do professor
    carregadas do banco: o aluno e anonimo e nao tem provedor nenhum.
    """
    if not is_translatable(language) or not question_ids:
        return

    factory = session_factory or AsyncSessionLocal
    runtime = await load_user_llm_runtime(tutor_id)
    token = activate_user_llms(runtime)
    key = (tuple(sorted(question_ids)), language)
    try:
        candidates = await quiz_generator_service.candidate_llms(None)
        if not candidates:
            logger.warning("Quiz sem provedor de IA para traduzir as perguntas.")
            _cooldown_until[key] = time.monotonic() + RETRY_COOLDOWN_SECONDS
            return

        async with factory() as session:
            have = await cached_translations(session, question_ids, language)
            pending = [
                question
                for question in (await session.execute(
                    select(QuestionModel).where(QuestionModel.id.in_(list(question_ids)))
                )).scalars().all()
                if question.id not in have
            ]
            # Na ordem em que o quiz avanca: a pergunta que a turma vai ver
            # primeiro e a primeira a ficar pronta.
            order = {qid: index for index, qid in enumerate(question_ids)}
            pending.sort(key=lambda question: order.get(question.id, 0))

            stored = 0
            for start in range(0, len(pending), BATCH_SIZE):
                batch = pending[start:start + BATCH_SIZE]
                translated = await _translate_batch(batch, language, candidates)
                await _store(session, translated, language)
                stored += len(translated)
            if stored < len(pending):
                _cooldown_until[key] = time.monotonic() + RETRY_COOLDOWN_SECONDS
    except Exception as error:  # a traducao nunca pode derrubar o quiz
        logger.warning(f"Nao consegui traduzir o quiz para {language}: {error}")
        _cooldown_until[key] = time.monotonic() + RETRY_COOLDOWN_SECONDS
    finally:
        reset_user_llms(token)


def warm(
    *,
    quiz_id: str,
    tutor_id: str,
    question_ids: Sequence[str],
    language: str,
) -> Optional["asyncio.Task[None]"]:
    """Comeca a traduzir o quiz inteiro em segundo plano, sem esperar.

    Chamado quando o primeiro aluno entra num idioma: ate a pergunta abrir, a
    traducao ja esta pronta. Uma tarefa por (quiz, idioma).
    """
    if not is_translatable(language) or not question_ids:
        return None
    key = (quiz_id, language)
    running = _in_flight.get(key)
    if running is not None and not running.done():
        return running
    cooldown_key = (tuple(sorted(question_ids)), language)
    if _cooldown_until.get(cooldown_key, 0) > time.monotonic():
        return None

    task = asyncio.ensure_future(
        translate_questions(
            tutor_id=tutor_id, question_ids=list(question_ids), language=language
        )
    )
    _in_flight[key] = task
    task.add_done_callback(
        lambda finished, key=key: _in_flight.pop(key, None)
        if _in_flight.get(key) is finished
        else None
    )
    return task


async def warm_if_missing(
    db: AsyncSession,
    *,
    quiz_id: str,
    tutor_id: str,
    question_ids: Sequence[str],
    language: str,
) -> None:
    """Comeca a traduzir so se faltar alguma pergunta no idioma.

    A tela do aluno chama isto a cada recarga: a consulta e barata, e a chamada ao
    modelo so acontece enquanto a traducao nao estiver completa.
    """
    if not is_translatable(language) or not question_ids:
        return
    have = await cached_translations(db, question_ids, language)
    if len(have) >= len(set(question_ids)):
        return
    warm(
        quiz_id=quiz_id,
        tutor_id=tutor_id,
        question_ids=question_ids,
        language=language,
    )


async def ensure_for_question(
    db: AsyncSession,
    *,
    quiz_id: str,
    tutor_id: str,
    question_ids: Sequence[str],
    current_question_id: str,
    language: str,
    timeout: float = ON_DEMAND_TIMEOUT_SECONDS,
) -> Optional[Dict[str, Any]]:
    """Traducao da pergunta que esta no ar, esperando um pouco se for preciso.

    Devolve `None` quando nao deu tempo ou o modelo falhou: o aluno le o original.
    """
    if not is_translatable(language):
        return None
    found = await cached_translations(db, [current_question_id], language)
    if current_question_id in found:
        return found[current_question_id]

    task = warm(
        quiz_id=quiz_id,
        tutor_id=tutor_id,
        question_ids=_current_first(question_ids, current_question_id),
        language=language,
    )
    if task is None:
        return None
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout)
    except (asyncio.TimeoutError, Exception):
        return None
    # Sessao nova: a traducao foi gravada por outra sessao, e a da requisicao
    # ja tem um snapshot anterior a ela (o MySQL le em REPEATABLE READ). Nao da
    # para dar rollback aqui - expiraria o quiz e as perguntas que a requisicao
    # ainda vai ler.
    async with AsyncSessionLocal() as fresh:
        return (await cached_translations(fresh, [current_question_id], language)).get(
            current_question_id
        )


def _current_first(question_ids: Sequence[str], current: str) -> List[str]:
    return [current, *[qid for qid in question_ids if qid != current]]
