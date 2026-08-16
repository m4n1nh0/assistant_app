"""Regras do modo educacao: resumo da aula e pontuacao extra de alunos.

A interface envia blocos de audio ao longo da aula. Cada bloco vira um trecho
de transcricao, e sobre esse texto rodamos duas coisas independentes: a
indexacao no Qdrant (para o resumo depois recuperar contexto) e a extracao de
pontuacoes extras citadas pelo professor.
"""

import asyncio
import json
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Sequence, TypedDict

from langgraph.graph import END, START, StateGraph
from loguru import logger

from ..core.config import get_settings
from .llm_routing_service import FREE_LOCAL_LLMS, pick_auto_llm, rank_auto_llms
from .llm_service import dispatch_single

settings = get_settings()

# Abaixo disso o nome ouvido e diferente demais do cadastro para ser a mesma
# pessoa; o registro fica sem student_id e aparece como pendente de revisao.
_NAME_MATCH_THRESHOLD = 0.82
_MAX_POINTS_PER_ENTRY = 100.0

# Sem uma dessas palavras no trecho o professor nao concedeu nada, entao nem
# chamamos o LLM: menos chamada por aula e, sobretudo, menos chance de o modelo
# inventar uma concessao a partir da lista de alunos que vai no prompt.
_POINTS_TRIGGERS = (
    "ponto",
    "pontos",
    "pontinho",
    "pontuacao",
    "decimo",
    "decimos",
    "bonus",
    "extra",
)

# O trecho citado pelo modelo precisa existir mesmo na transcricao. Abaixo
# desse grau de semelhanca tratamos como alucinacao e descartamos.
_QUOTE_MATCH_THRESHOLD = 0.75


def normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (value or "").lower())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", stripped).split())


async def resolve_llm(preferred: Optional[str] = None) -> str:
    if preferred and preferred not in {"auto", ""}:
        return preferred
    return await pick_auto_llm(settings.active_llms) or "llama"


# --- Casamento de nomes contra a turma ------------------------------------


def _roster_keys(student: Dict[str, Any]) -> List[str]:
    keys = [normalize_name(student.get("name", ""))]
    for alias in student.get("aliases") or []:
        normalized = normalize_name(str(alias))
        if normalized:
            keys.append(normalized)
    return [key for key in keys if key]


def match_student(
    heard_name: str,
    roster: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Casa o nome ouvido no audio com o cadastro da turma.

    O Whisper erra nomes proprios com frequencia ("Tiago"/"Thiago",
    "Wesley"/"Uesley"), entao alem do nome cheio aceitamos apelidos, primeiro
    nome unico na turma e similaridade textual.
    """
    heard = normalize_name(heard_name)
    result: Dict[str, Any] = {
        "student_id": None,
        "student_name": (heard_name or "").strip(),
        "confidence": 0.0,
    }
    if not heard or not roster:
        return result

    for student in roster:
        if heard in _roster_keys(student):
            return {
                "student_id": student.get("id"),
                "student_name": student.get("name", heard_name),
                "confidence": 1.0,
            }

    # Professor costuma citar so o primeiro nome. So aceitamos quando ele
    # identifica uma unica pessoa da turma — havendo duas Marias, fica pendente.
    first = heard.split()[0]
    by_first = [
        student
        for student in roster
        if any(key.split()[0] == first for key in _roster_keys(student))
    ]
    if len(by_first) == 1:
        return {
            "student_id": by_first[0].get("id"),
            "student_name": by_first[0].get("name", heard_name),
            "confidence": 0.9,
        }

    # Primeiro nome mal transcrito ("Tiago" por "Thiago"): comparar o token
    # ouvido com o nome completo derruba a similaridade, entao comparamos
    # primeiro nome contra primeiro nome.
    if not by_first:
        near_first = []
        for student in roster:
            score = max(
                (
                    SequenceMatcher(None, first, key.split()[0]).ratio()
                    for key in _roster_keys(student)
                ),
                default=0.0,
            )
            if score >= _NAME_MATCH_THRESHOLD:
                near_first.append((score, student))
        if len(near_first) == 1:
            score, student = near_first[0]
            return {
                "student_id": student.get("id"),
                "student_name": student.get("name", heard_name),
                "confidence": round(score * 0.9, 3),
            }

    best_score = 0.0
    best_student: Optional[Dict[str, Any]] = None
    for student in roster:
        for key in _roster_keys(student):
            score = SequenceMatcher(None, heard, key).ratio()
            if score > best_score:
                best_score = score
                best_student = student

    if best_student is not None and best_score >= _NAME_MATCH_THRESHOLD:
        return {
            "student_id": best_student.get("id"),
            "student_name": best_student.get("name", heard_name),
            "confidence": round(best_score, 3),
        }

    result["confidence"] = round(best_score, 3)
    return result


# --- Extracao de pontuacao extra ------------------------------------------


_POINTS_SYSTEM_PROMPT = (
    "Voce extrai pontuacoes extras concedidas por um professor durante a aula. "
    "Responda SEMPRE com JSON valido, sem markdown e sem texto fora do JSON."
)


def _points_prompt(text: str, roster: Sequence[Dict[str, Any]]) -> str:
    names = [str(student.get("name", "")) for student in roster if student.get("name")]
    roster_block = (
        "Alunos da turma (use exatamente estes nomes quando reconhecer o aluno):\n"
        + "\n".join(f"- {name}" for name in names)
        if names
        else "Nao ha cadastro de turma; transcreva o nome como foi falado."
    )

    return (
        f"{roster_block}\n\n"
        "Trecho da transcricao da aula:\n"
        f'"""\n{text}\n"""\n\n'
        "Liste apenas pontuacoes extras que o professor concedeu explicitamente "
        "a um aluno neste trecho. Ignore notas de prova, medias, chamadas, "
        "combinados futuros e hipoteses (\"quem responder ganha ponto\" sem "
        "alguem receber). Se nada foi concedido, devolva a lista vazia.\n"
        "A lista de alunos serve so para corrigir a grafia do nome: nunca "
        "premie quem nao foi citado na fala. O campo \"trecho\" tem de ser "
        "copia literal da transcricao acima, e o valor em \"pontos\" tem de "
        "ter sido dito pelo professor.\n\n"
        "Formato exato:\n"
        '{"pontuacoes": [{"aluno": "nome", "pontos": 0.5, '
        '"motivo": "por que recebeu", "trecho": "frase do professor"}]}'
    )


def _parse_json_object(raw: str) -> Dict[str, Any]:
    """Extrai o objeto JSON mesmo com cercas de markdown ou texto em volta."""
    content = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", content, re.DOTALL)
    if fenced:
        content = fenced.group(1).strip()

    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        parsed = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _coerce_points(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        points = float(value)
    else:
        text = str(value or "").strip().replace(",", ".")
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        if not match:
            return None
        points = float(match.group())
    if points <= 0 or points > _MAX_POINTS_PER_ENTRY:
        return None
    return round(points, 3)


def mentions_points(text: str) -> bool:
    """O trecho fala em pontuacao? Serve de porta para a extracao."""
    words = set(normalize_name(text).split())
    return any(trigger in words for trigger in _POINTS_TRIGGERS)


def quote_supported(quote: str, text: str) -> bool:
    """A frase que o modelo diz ter ouvido existe mesmo na transcricao?

    Comparamos normalizado e aceitamos quase-igual, porque o modelo costuma
    reescrever pontuacao e concordancia ao repetir a fala.
    """
    needle = normalize_name(quote)
    haystack = normalize_name(text)
    if not needle or not haystack:
        return False
    if needle in haystack:
        return True
    match = SequenceMatcher(None, needle, haystack).find_longest_match(
        0, len(needle), 0, len(haystack)
    )
    return match.size >= len(needle) * _QUOTE_MATCH_THRESHOLD


def name_spoken(heard_name: str, text: str) -> bool:
    """O nome premiado foi dito no trecho?

    O prompt leva a lista da turma, entao um modelo local as vezes premia
    alguem que so aparece nessa lista. Sem o nome na fala, descartamos.
    """
    words = set(normalize_name(text).split())
    tokens = [token for token in normalize_name(heard_name).split() if len(token) > 2]
    return any(token in words for token in tokens)


async def extract_points(
    *,
    text: str,
    roster: Sequence[Dict[str, Any]],
    llm: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Devolve as pontuacoes extras citadas no trecho, ja casadas com a turma.

    Toda entrada precisa passar por tres portas: o trecho falar em pontuacao, a
    citacao existir na transcricao e o nome premiado ter sido dito. O modelo
    sozinho premia aluno que nunca foi citado.
    """
    if not text.strip() or not mentions_points(text):
        return []

    provider = await resolve_llm(llm)
    response = await dispatch_single(
        provider,
        _points_prompt(text, roster),
        [],
        _POINTS_SYSTEM_PROMPT,
    )
    if response.is_error:
        logger.warning(f"Extracao de pontos falhou ({provider}): {response.content}")
        return []

    payload = _parse_json_object(response.content)
    raw_entries = payload.get("pontuacoes")
    if not isinstance(raw_entries, list):
        return []

    entries: List[Dict[str, Any]] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        heard_name = str(item.get("aluno") or "").strip()
        points = _coerce_points(item.get("pontos"))
        if not heard_name or points is None:
            continue

        quote = str(item.get("trecho") or "").strip()
        if not quote_supported(quote, text):
            logger.info(
                "Pontuacao descartada: citacao ausente na transcricao "
                f"(aluno={heard_name!r}, trecho={quote!r})"
            )
            continue
        if not name_spoken(heard_name, text):
            logger.info(
                f"Pontuacao descartada: nome nao foi dito no trecho ({heard_name!r})"
            )
            continue

        match = match_student(heard_name, roster)
        entries.append({
            "student_id": match["student_id"],
            "student_name": match["student_name"],
            "heard_name": heard_name,
            "points": points,
            "reason": str(item.get("motivo") or "").strip() or None,
            "quote": quote or None,
            "confidence": match["confidence"],
        })
    return entries


def is_duplicate_point(
    entry: Dict[str, Any],
    existing: Sequence[Dict[str, Any]],
) -> bool:
    """Evita gravar duas vezes a mesma concessao.

    Blocos de audio consecutivos podem repetir a mesma frase quando o corte cai
    no meio dela, e o LLM entao extrai a concessao duas vezes.
    """
    name = normalize_name(entry.get("student_name", ""))
    points = float(entry.get("points") or 0)
    quote = normalize_name(entry.get("quote") or "")
    reason = normalize_name(entry.get("reason") or "")

    for item in existing:
        if normalize_name(item.get("student_name", "")) != name:
            continue
        if float(item.get("points") or 0) != points:
            continue
        other_quote = normalize_name(item.get("quote") or "")
        other_reason = normalize_name(item.get("reason") or "")
        if quote and other_quote and quote == other_quote:
            return True
        if reason and other_reason and reason == other_reason:
            return True
        if not quote and not reason and not other_quote and not other_reason:
            return True
    return False


# --- Resumo da aula --------------------------------------------------------


_SUMMARY_SYSTEM_PROMPT = (
    "Voce resume aulas a partir da transcricao do audio. Escreva em portugues "
    "brasileiro, de forma objetiva e fiel ao que foi dito. Corrija "
    "silenciosamente erros evidentes de reconhecimento de fala quando a "
    "disciplina, o tema e o restante da frase tornarem a correcao inequivoca. "
    "Nunca invente conteudo para completar um trecho sem sentido; quando nao "
    "for possivel recuperar o significado com seguranca, omita o detalhe ou "
    "marque-o como incerto."
)


def _summary_prompt(
    *,
    discipline: str,
    title: str,
    transcript: str,
    focus: str,
    partial: bool = False,
) -> str:
    header = f"Disciplina: {discipline}"
    if title:
        header += f"\nAula: {title}"
    extra = f"\nDe atencao especial a: {focus}" if focus.strip() else ""

    if partial:
        return (
            f"{header}{extra}\n\n"
            "Este e um trecho de uma aula longa. Resuma o trecho preservando "
            "termos tecnicos, definicoes, exemplos e qualquer tarefa ou data "
            "citada. Normalize frases quebradas e corrija palavras claramente "
            "transcritas de forma errada usando o contexto da disciplina, sem "
            "criar fatos nem completar passagens ambiguas. Nao escreva "
            "introducao nem conclusao. Responda em no "
            "maximo 8 linhas: os parciais sao juntados depois e precisam caber "
            "na janela do modelo.\n\n"
            f'Trecho:\n"""\n{transcript}\n"""'
        )

    return (
        f"{header}{extra}\n\n"
        "Monte o resumo da aula a partir da transcricao, nesta estrutura:\n"
        "## Resumo\n(2 a 4 paragrafos com o fio condutor da aula)\n"
        "## Principais topicos\n(lista com os conceitos trabalhados)\n"
        "## Definicoes e formulas\n(o que foi enunciado literalmente; omita a "
        "secao se nao houver)\n"
        "## Tarefas e avisos\n(trabalhos, prazos, datas de prova; omita se nao "
        "houver)\n"
        "## Duvidas levantadas\n(perguntas da turma e as respostas; omita se "
        "nao houver)\n\n"
        "Antes de redigir, ajuste mentalmente frases quebradas e erros evidentes "
        "de reconhecimento de fala usando a disciplina, o tema e as frases "
        "vizinhas. Use no resumo a forma corrigida quando ela for inequivoca. "
        "Se a transcricao continuar truncada ou ambigua, omita o detalhe ou "
        "declare a incerteza em vez de preencher com suposicao.\n\n"
        f'Transcricao:\n"""\n{transcript}\n"""'
    )


# A janela do modelo e contada em tokens e a transcricao em caracteres. Tres
# caracteres por token e um cambio pessimista de proposito: estourar a janela
# custa a chamada inteira, sobrar espaco custa uma frase a menos por bloco.
_CHARS_PER_TOKEN = 3.0
# O que ocupa a janela alem da transcricao: as instrucoes do prompt e a
# resposta que o modelo ainda precisa escrever.
_PROMPT_TOKENS = 350
_ANSWER_TOKENS = 700
_LOCAL_PROVIDERS = frozenset({"localai", "llama"})
# Rodadas de condensacao antes de aceitar o que ja foi resumido.
_MAX_CONDENSE_ROUNDS = 4
_PARTIAL_SUMMARY_MAX_TOKENS = 192
_FINAL_SUMMARY_MAX_TOKENS = 512

# Servidores compativeis com a API da OpenAI reclamam de contexto cheio de
# formas diferentes; todos, porem, dizem o tamanho da janela na mensagem.
_CONTEXT_LIMIT_PATTERNS = (
    r"available context size \((\d+) tokens\)",
    r"maximum context length is (\d+) tokens",
    r"context length of (\d+) tokens",
    r"n_ctx[^\d]{0,10}(\d+)",
)


def _budget_from_tokens(context_tokens: int) -> int:
    usable = int(context_tokens) - _PROMPT_TOKENS - _ANSWER_TOKENS
    return max(800, int(usable * _CHARS_PER_TOKEN))


def summary_budget_chars(provider: str) -> int:
    """Quantos caracteres de transcricao cabem em uma chamada ao modelo."""
    ceiling = max(2000, settings.education_summary_max_chars)
    if provider not in _LOCAL_PROVIDERS:
        return ceiling
    return min(ceiling, _budget_from_tokens(settings.local_llm_context_tokens))


def context_limit_from_error(message: str) -> Optional[int]:
    """Le na mensagem de erro a janela real do modelo, quando ele a informa.

    Evita depender do que esta configurado: o servidor local pode ter sido
    subido com outra janela, e a primeira falha ja diz qual e.
    """
    for pattern in _CONTEXT_LIMIT_PATTERNS:
        found = re.search(pattern, message or "", re.IGNORECASE)
        if found:
            return int(found.group(1))
    return None


def _split_piece(piece: str, max_chars: int) -> List[str]:
    """Parte um trecho maior que a janela, de preferencia no fim de uma frase."""
    if len(piece) <= max_chars:
        return [piece]

    parts: List[str] = []
    rest = piece
    while len(rest) > max_chars:
        window = rest[:max_chars]
        cut = max(window.rfind(". "), window.rfind("? "), window.rfind("! "))
        if cut < max_chars // 2:
            cut = window.rfind(" ")
        cut = max_chars if cut <= 0 else cut + 1
        parts.append(rest[:cut].strip())
        rest = rest[cut:].lstrip()
    if rest:
        parts.append(rest)
    return parts


def _windows(texts: Sequence[str], max_chars: int) -> List[str]:
    windows: List[str] = []
    current: List[str] = []
    size = 0
    for text in texts:
        for piece in _split_piece(text.strip(), max_chars):
            if not piece:
                continue
            if size + len(piece) > max_chars and current:
                windows.append("\n".join(current))
                current = []
                size = 0
            current.append(piece)
            size += len(piece) + 1
    if current:
        windows.append("\n".join(current))
    return windows


async def build_study_context(
    *,
    tutor_id: str,
    message: str,
    limit: int = 6,
    min_score: float = 0.25,
) -> str:
    """Recupera trechos de aula relevantes para injetar no prompt do chat.

    Chamado apenas quando o roteador classifica o pedido como estudo, para nao
    pagar uma busca vetorial em toda conversa. O corte por score evita colar
    trecho aleatorio quando a aula nao fala do assunto perguntado.
    """
    from . import lesson_index_service, qdrant_service

    async def _search() -> List[Dict[str, Any]]:
        try:
            hits = await qdrant_service.search_lesson_transcripts(
                tutor_id=tutor_id,
                query=message,
                limit=limit,
            )
        except Exception as e:
            logger.warning(f"Busca de contexto de aula falhou: {e}")
            return []
        return [hit for hit in hits if hit.get("score", 0.0) >= min_score]

    relevant = await _search()
    if not relevant:
        # A aula pode existir no MySQL e faltar no indice: o Qdrant estava fora
        # do ar na gravacao, ou o modelo de embedding mudou. Reconstroi o que
        # falta e pergunta de novo - uma vez, com intervalo minimo entre
        # tentativas, para pergunta sem resposta nao virar reindexacao em loop.
        outcome = await lesson_index_service.catch_up(
            tutor_id=tutor_id, reason="busca de aula sem resultado"
        )
        if outcome.get("indexed"):
            relevant = await _search()

    if not relevant:
        return ""

    lines = []
    for hit in relevant:
        header = hit.get("discipline") or "aula"
        date = hit.get("lesson_date") or ""
        if date:
            header = f"{header}, {date}"
        lines.append(f"[{header}] {hit.get('content', '').strip()}")

    return (
        "\n\nTrechos das aulas gravadas pelo usuario que podem responder a "
        "pergunta. Use-os como fonte e cite a disciplina e a data quando "
        "responder. Se nao responderem o que foi perguntado, diga isso em vez "
        "de completar com suposicao.\n"
        + "\n".join(lines)
    )


async def _dispatch_summary(
    provider: str,
    prompt: str,
    *,
    max_tokens: int,
):
    """Chama o modelo com opcoes adequadas a uma tarefa de resumo.

    Modelos LocalAI de raciocinio podem gastar toda a saida em ``reasoning`` e
    nunca preencher ``content``. Resumo e uma tarefa de extracao/condensacao,
    por isso desativamos thinking apenas aqui; o chat continua inalterado.
    """
    return await dispatch_single(
        provider,
        prompt,
        [],
        _SUMMARY_SYSTEM_PROMPT,
        max_tokens=max_tokens,
        reasoning_effort="none" if provider == "localai" else None,
    )


async def _summarise_within(
    *,
    provider: str,
    discipline: str,
    title: str,
    texts: Sequence[str],
    focus: str,
    budget: int,
) -> Dict[str, Any]:
    """Condensa a aula em rodadas ate ela caber em uma unica chamada."""
    chunks = _windows(texts, budget)
    error = ""
    truncated = False

    rounds = 0
    while len(chunks) > 1 and rounds < _MAX_CONDENSE_ROUNDS:
        rounds += 1
        partials: List[str] = []
        logger.info(
            f"Resumo ({provider}): condensando {len(chunks)} blocos, "
            f"rodada {rounds}/{_MAX_CONDENSE_ROUNDS}"
        )
        for index, chunk in enumerate(chunks, start=1):
            response = await _dispatch_summary(
                provider,
                _summary_prompt(
                    discipline=discipline,
                    title=title,
                    transcript=chunk,
                    focus=focus,
                    partial=True,
                ),
                max_tokens=_PARTIAL_SUMMARY_MAX_TOKENS,
            )
            if response.is_error:
                error = response.content
                logger.warning(
                    f"Resumo parcial falhou ({provider}, bloco "
                    f"{index}/{len(chunks)}): {error}"
                )
                # Todos os blocos usam o mesmo provedor. Repetir uma chamada
                # que acabou de falhar (especialmente por timeout) fazia a
                # requisicao ficar presa por varios minutos e ocultava a causa.
                return {
                    "summary": "",
                    "llm": provider,
                    "used_segments": 0,
                    "error": error,
                }
            partial = response.content.strip()
            if not partial:
                error = "O modelo retornou um resumo parcial vazio"
                logger.warning(
                    f"Resumo parcial falhou ({provider}, bloco "
                    f"{index}/{len(chunks)}): {error}"
                )
                return {
                    "summary": "",
                    "llm": provider,
                    "used_segments": 0,
                    "error": error,
                }
            partials.append(partial)

        if not partials:
            return {"summary": "", "llm": provider, "used_segments": 0, "error": error}

        condensed = _windows(partials, budget)
        if len(condensed) >= len(chunks):
            # Os parciais pararam de encolher; mais uma rodada so gastaria
            # chamada. Fica o que ja coube, e o prompt final pede ao modelo que
            # avise que a transcricao esta truncada.
            logger.warning(
                f"Resumo: condensacao estagnou em {len(condensed)} blocos, "
                "usando o primeiro"
            )
            chunks = condensed[:1]
            truncated = True
            break
        chunks = condensed

    if len(chunks) > 1:
        chunks = chunks[:1]
        truncated = True

    response = await _dispatch_summary(
        provider,
        _summary_prompt(
            discipline=discipline,
            title=title,
            transcript=chunks[0],
            focus=focus,
        ),
        max_tokens=_FINAL_SUMMARY_MAX_TOKENS,
    )
    if response.is_error:
        logger.warning(f"Resumo falhou ({provider}): {response.content}")
        return {
            "summary": "",
            "llm": provider,
            "used_segments": 0,
            "error": response.content,
        }

    summary = response.content.strip()
    if not summary:
        error = "O modelo retornou um resumo vazio"
        logger.warning(f"Resumo falhou ({provider}): {error}")
        return {
            "summary": "",
            "llm": provider,
            "used_segments": 0,
            "error": error,
        }

    return {
        "summary": summary,
        "llm": provider,
        "used_segments": len(texts),
        "truncated": truncated,
    }


async def _summarise_provider(
    *,
    provider: str,
    discipline: str,
    title: str,
    texts: Sequence[str],
    focus: str,
) -> Dict[str, Any]:
    """Executa um provedor e adapta uma vez a janela informada por ele."""
    budget = summary_budget_chars(provider)
    outcome = await _summarise_within(
        provider=provider,
        discipline=discipline,
        title=title,
        texts=texts,
        focus=focus,
        budget=budget,
    )
    if outcome["summary"]:
        return outcome

    # O modelo recusou por contexto cheio e disse o tamanho real da janela:
    # refaz uma vez com a medida dele em vez da configurada.
    limit = context_limit_from_error(str(outcome.get("error") or ""))
    if limit is None:
        return outcome

    corrected = _budget_from_tokens(limit)
    if corrected >= budget:
        return outcome

    logger.info(
        f"Resumo refeito com a janela informada pelo modelo: {limit} tokens"
    )
    return await _summarise_within(
        provider=provider,
        discipline=discipline,
        title=title,
        texts=texts,
        focus=focus,
        budget=corrected,
    )


async def _summary_provider_candidates(preferred: Optional[str]) -> List[str]:
    """Monta a fila free-first usada pelo workflow de resumo."""
    if preferred:
        return [await resolve_llm(preferred)]

    configured = list(getattr(settings, "active_llms", []) or [])
    if not configured:
        return [await resolve_llm(None)]

    ranked = await rank_auto_llms(
        configured,
        "study",
        available_only=True,
    )
    allow_paid = bool(
        getattr(settings, "education_summary_allow_paid_fallback", True)
    )
    if not allow_paid:
        ranked = [provider for provider in ranked if provider in FREE_LOCAL_LLMS]

    if not ranked:
        # Mantem uma tentativa para devolver ao usuario o erro concreto do
        # provedor configurado, em vez de um generico "nenhum disponivel".
        ranked = [await resolve_llm(None)]

    maximum = max(1, int(getattr(settings, "education_summary_max_providers", 3)))
    return ranked[:maximum]


class SummaryGraphState(TypedDict, total=False):
    discipline: str
    title: str
    texts: List[str]
    focus: str
    requested_llm: Optional[str]
    providers: List[str]
    provider_index: int
    outcome: Dict[str, Any]
    attempts: List[Dict[str, Any]]


async def _summary_resolve_node(state: SummaryGraphState) -> Dict[str, Any]:
    providers = await _summary_provider_candidates(state.get("requested_llm"))
    logger.info(f"Resumo LangGraph: fila de provedores {providers}")
    return {"providers": providers, "provider_index": 0, "attempts": []}


async def _summary_run_node(state: SummaryGraphState) -> Dict[str, Any]:
    provider = state["providers"][state["provider_index"]]
    timeout = max(
        10,
        int(getattr(settings, "education_summary_provider_timeout_seconds", 180)),
    )
    started = asyncio.get_running_loop().time()
    try:
        outcome = await asyncio.wait_for(
            _summarise_provider(
                provider=provider,
                discipline=state["discipline"],
                title=state["title"],
                texts=state["texts"],
                focus=state["focus"],
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        outcome = {
            "summary": "",
            "llm": provider,
            "used_segments": 0,
            "error": f"Tempo limite de {timeout}s excedido ao gerar o resumo",
        }
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        logger.exception(f"Resumo LangGraph falhou em {provider}: {detail}")
        outcome = {
            "summary": "",
            "llm": provider,
            "used_segments": 0,
            "error": detail,
        }

    elapsed_ms = int((asyncio.get_running_loop().time() - started) * 1000)
    attempt = {
        "provider": provider,
        "duration_ms": elapsed_ms,
        "success": bool(outcome.get("summary")),
        "error": outcome.get("error"),
    }
    return {
        "outcome": outcome,
        "attempts": [*state.get("attempts", []), attempt],
    }


def _summary_route_after_attempt(state: SummaryGraphState) -> str:
    if state["outcome"].get("summary"):
        return "done"
    if state["provider_index"] + 1 >= len(state["providers"]):
        return "done"
    return "fallback"


async def _summary_fallback_node(state: SummaryGraphState) -> Dict[str, Any]:
    current = state["providers"][state["provider_index"]]
    next_index = state["provider_index"] + 1
    following = state["providers"][next_index]
    logger.warning(
        f"Resumo LangGraph: {current} falhou; tentando fallback {following}"
    )
    return {"provider_index": next_index}


def _build_summary_graph():
    workflow = StateGraph(SummaryGraphState)
    workflow.add_node("resolve_providers", _summary_resolve_node)
    workflow.add_node("run_provider", _summary_run_node)
    workflow.add_node("fallback", _summary_fallback_node)
    workflow.add_edge(START, "resolve_providers")
    workflow.add_edge("resolve_providers", "run_provider")
    workflow.add_conditional_edges(
        "run_provider",
        _summary_route_after_attempt,
        {"fallback": "fallback", "done": END},
    )
    workflow.add_edge("fallback", "run_provider")
    return workflow.compile()


summary_graph = _build_summary_graph()


async def generate_summary(
    *,
    discipline: str,
    title: str,
    segments: Sequence[str],
    llm: Optional[str] = None,
    focus: str = "",
) -> Dict[str, Any]:
    """Resume a aula com LangGraph, janela adaptativa e fallback free-first."""
    texts = [text for text in segments if text and text.strip()]
    if not texts:
        return {"summary": "", "llm": "", "used_segments": 0}

    result = await summary_graph.ainvoke({
        "discipline": discipline,
        "title": title,
        "texts": texts,
        "focus": focus,
        "requested_llm": llm,
    })
    outcome = dict(result["outcome"])
    outcome["attempts"] = result.get("attempts", [])
    return outcome
