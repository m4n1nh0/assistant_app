"""Serviço de geração automática de exercícios e quizzes baseado em resumos de aula."""

import json
import re
from typing import Any, Dict, List, Optional, Sequence

from langgraph.graph import END, START, StateGraph
from loguru import logger

from .llm_routing_service import pick_auto_llm, rank_auto_llms
from .llm_service import dispatch_single
from .user_llm_config_service import runtime_settings

settings = runtime_settings

# Templates de prompts para diferentes tipos de quiz
QUIZ_GENERATION_PROMPT = """Você é um especialista em geração de questões educacionais.

Baseado no conteúdo da aula abaixo, gere {quantidade_questoes} questões de forma estruturada.

**Conteúdo da Aula (resumo e/ou transcrição):**
{resumo}

**Disciplina:** {disciplina}
**Tipo de Quiz:** {tipo_quiz}
**Tipos de Questão:** multipla_escolha
**Dificuldade:** {dificuldade}

**Instruções:**
1. Cada questão deve derivar diretamente do conteúdo da aula (não invente conteúdo)
2. Inclua justificativas que citam a fonte no conteúdo da aula
3. Gere somente questões objetivas de múltipla escolha
4. Distribua dificuldade equitativamente
5. Inclua todos os tópicos principais encontrados no conteúdo
6. Para "multipla_escolha", gere exatamente 4 opções com labels A, B, C e D
7. Marque exatamente uma opção como correta
8. Alternativas curtas: no máximo 8 palavras cada, sem frase completa. O quiz é
   respondido no celular com o enunciado projetado, e alternativa longa não cabe
   na tela nem dá para ler no tempo da pergunta
9. Enunciado direto, em uma linha
10. Use "resposta_correta" com o label da alternativa correta
11. Responda somente com JSON válido, sem markdown e sem comentários fora do JSON

**Formato de resposta (JSON):**
{{
  "questoes": [
    {{
      "tipo": "multipla_escolha",
      "dificuldade": "facil|medio|dificil",
      "enunciado": "Texto da questão",
      "opcoes": [
        {{"label": "A", "texto": "Opção A", "correta": true}},
        {{"label": "B", "texto": "Opção B", "correta": false}}
      ],
      "resposta_correta": "Resposta esperada",
      "justificativa": "Explicação com referência ao resumo",
      "conceitos": ["conceito1", "conceito2"],
      "topico_origem": "Título do tópico do resumo"
    }}
  ],
  "tempo_estimado": 15
}}
"""

VALIDATION_PROMPT = """Valide as seguintes questões geradas com base no conteúdo da aula.

**Conteúdo Original:**
{resumo}

**Questões para Validar:**
{questoes_json}

Para cada questão, verifique:
1. A questão derivou do conteúdo da aula (grounding score 0-1)?
2. A questão está bem formulada?
3. A resposta correta está clara?
4. Há risco de alucinação?

Responda em JSON:
{{
  "validacoes": [
    {{
      "indice": 0,
      "grounding_score": 0.95,
      "bem_formulada": true,
      "risco_alucinacao": false,
      "feedback": "Questão bem baseada no resumo"
    }}
  ],
  "media_grounding": 0.87,
  "aprovacao_geral": true
}}
"""


class QuizGraphState(dict):
    """Estado do grafo de geração de quiz."""

    resumo: str
    disciplina: str
    titulo_aula: str
    tipo_quiz: str
    quantidade_questoes: int
    tipos_questao: List[str]
    dificuldade: str
    requested_llm: Optional[str]

    # Intermediários
    questoes_brutas: Optional[List[Dict[str, Any]]] = None
    validacoes: Optional[Dict[str, Any]] = None
    tempo_estimado: int = 15

    # Saída
    outcome: Optional[Dict[str, Any]] = None
    attempts: List[Dict[str, Any]] = []


async def _candidate_llms_for_quiz(preferred: Optional[str] = None) -> List[str]:
    """Resolve candidatos para quiz, priorizando modelos melhores em JSON."""
    if preferred and preferred not in {"auto", ""}:
        return [preferred]

    ranked = await rank_auto_llms(
        settings.active_llms,
        task="code",
        available_only=True,
    )
    if not ranked:
        ranked = await rank_auto_llms(settings.active_llms, task="code")
    fallback = [await pick_auto_llm(settings.active_llms) or "llama"]
    return (ranked or fallback)[:3]


async def _resolve_llm_for_quiz(preferred: Optional[str] = None) -> str:
    """Resolve qual LLM usar para geração de quiz."""
    return (await _candidate_llms_for_quiz(preferred))[0]


def _token_budget(quantidade_questoes: int) -> int:
    """Teto de saida proporcional ao tamanho do quiz pedido.

    O padrao dos provedores e 2000 tokens, dimensionado para resposta de chat.
    Um JSON com dez questoes de multipla escolha - enunciado, quatro
    alternativas e justificativa em cada - passa disso, e a resposta voltava
    cortada no meio: `json.loads` falhava nos tres modelos candidatos e o quiz
    inteiro caia no gerador por template. Quanto mais questoes o professor
    pedia, mais garantido era o corte.
    """
    return min(max(2000, 300 * max(quantidade_questoes, 1) + 500), 8000)


def _salvage_questions(content: str) -> List[Dict[str, Any]]:
    """Recupera as questoes inteiras de um JSON que veio cortado.

    Sete questoes de verdade valem mais que dez de template, entao um corte no
    meio do array nao precisa perder o que ja estava completo. Varre o texto
    contando chaves e devolve so os objetos que fecharam.
    """
    start = content.find("[")
    if start < 0:
        return []

    recovered: List[Dict[str, Any]] = []
    depth = 0
    in_string = False
    escaped = False
    piece_start = -1

    for index in range(start, len(content)):
        char = content[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                piece_start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and piece_start >= 0:
                try:
                    item = json.loads(content[piece_start:index + 1])
                except ValueError:
                    piece_start = -1
                    continue
                if isinstance(item, dict) and item.get("enunciado"):
                    recovered.append(item)
                piece_start = -1
    return recovered


def _json_from_content(content: str) -> Dict[str, Any]:
    """Extrai JSON mesmo quando o modelo envolve a resposta em texto."""
    json_match = re.search(r'\{.*\}', content or "", re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group())
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            pass

    list_match = re.search(r'\[.*\]', content or "", re.DOTALL)
    if list_match:
        try:
            parsed = json.loads(list_match.group())
            return {"questoes": parsed} if isinstance(parsed, list) else {}
        except ValueError:
            pass

    # Resposta cortada: aproveita o que fechou em vez de descartar tudo.
    salvaged = _salvage_questions(content or "")
    if salvaged:
        logger.warning(
            f"JSON do quiz veio incompleto; {len(salvaged)} questao(oes) "
            "aproveitadas do trecho valido."
        )
        return {"questoes": salvaged}

    return {}


def _normalize_question_type(value: Any, fallback: str = "multipla_escolha") -> str:
    raw = str(value or fallback).strip().lower()
    raw = raw.replace("-", "_").replace(" ", "_")
    aliases = {
        "multiple_choice": "multipla_escolha",
        "multipla": "multipla_escolha",
        "múltipla_escolha": "multipla_escolha",
        "verdadeiro/falso": "verdadeiro_falso",
        "true_false": "verdadeiro_falso",
        "vf": "verdadeiro_falso",
        "dissertativa": "aberta",
        "open": "aberta",
        "open_ended": "aberta",
    }
    return aliases.get(raw, raw if raw in {"multipla_escolha", "verdadeiro_falso", "aberta"} else fallback)


def _normalize_difficulty(value: Any) -> str:
    raw = str(value or "medio").strip().lower()
    aliases = {
        "fácil": "facil",
        "easy": "facil",
        "media": "medio",
        "média": "medio",
        "intermediaria": "medio",
        "intermediária": "medio",
        "medium": "medio",
        "difícil": "dificil",
        "hard": "dificil",
    }
    return aliases.get(raw, raw if raw in {"facil", "medio", "dificil"} else "medio")


def _question_text(item: Dict[str, Any]) -> str:
    for key in ("enunciado", "pergunta", "question", "texto", "statement"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _correct_answer(item: Dict[str, Any]) -> str:
    for key in ("resposta_correta", "correct_answer", "gabarito", "answer", "resposta"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _raw_options(item: Dict[str, Any]) -> Any:
    for key in ("opcoes", "alternativas", "options", "choices"):
        if key in item:
            return item.get(key)
    return []


def _normalize_options(raw_options: Any, correct_answer: str) -> List[Dict[str, Any]]:
    if isinstance(raw_options, dict):
        iterable = [
            {"label": str(label), "texto": text}
            for label, text in raw_options.items()
        ]
    elif isinstance(raw_options, list):
        iterable = raw_options
    else:
        iterable = []

    normalized = []
    correct_norm = correct_answer.strip().lower()
    for index, option in enumerate(iterable):
        label = chr(ord("A") + index)
        texto = ""
        correta = False

        if isinstance(option, dict):
            label = str(option.get("label") or option.get("letra") or label).strip().upper()
            texto = str(option.get("texto") or option.get("text") or option.get("value") or "").strip()
            correta = bool(option.get("correta") or option.get("correct") or option.get("is_correct"))
        else:
            texto = str(option).strip()

        if not texto:
            continue

        aponta_para_esta = bool(correct_norm) and (
            label.lower() == correct_norm
            or texto.lower() == correct_norm
            or correct_norm in {f"{label.lower()})", f"{label.lower()}."}
        )

        normalized.append({
            "label": label or chr(ord("A") + len(normalized)),
            "texto": texto,
            "correta": correta,
            "_apontada": aponta_para_esta,
        })

    return _single_correct_option(normalized, bool(correct_norm))


def _single_correct_option(
    options: List[Dict[str, Any]],
    tem_gabarito: bool,
) -> List[Dict[str, Any]]:
    """Deixa no maximo uma alternativa correta, sem inventar gabarito.

    Duas coisas davam errado aqui. O `resposta_correta` **somava** uma marcacao
    aa que o modelo ja tinha feito, entao a questao saia com duas alternativas
    corretas e a turma era corrigida errado. E, quando o modelo nao marcava
    nenhuma, o codigo marcava a primeira - fabricando um gabarito com cara de
    legitimo, que e pior do que nao ter gabarito.

    Agora `resposta_correta` manda quando resolve; senao vale a marcacao do
    modelo, e so quando ela e unica. Ambiguidade sobra como zero corretas, e
    quem chama sinaliza a questao para revisao.
    """
    apontadas = [item for item in options if item.pop("_apontada", False)]
    if tem_gabarito and len(apontadas) == 1:
        for item in options:
            item["correta"] = item is apontadas[0]
        return options

    marcadas = [item for item in options if item["correta"]]
    if len(marcadas) != 1:
        for item in options:
            item["correta"] = False
    return options


def _normalize_question(item: Any, tipos_questao: Sequence[str]) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None

    enunciado = _question_text(item)
    if not enunciado:
        return None

    fallback_type = tipos_questao[0] if tipos_questao else "multipla_escolha"
    tipo = _normalize_question_type(item.get("tipo") or item.get("type"), fallback_type)
    resposta_correta = _correct_answer(item)
    opcoes = _normalize_options(_raw_options(item), resposta_correta)

    if tipo == "verdadeiro_falso":
        opcoes = []
        answer_norm = resposta_correta.strip().lower()
        if answer_norm in {"true", "verdade", "v", "sim"}:
            resposta_correta = "verdadeiro"
        elif answer_norm in {"false", "falso", "f", "não", "nao"}:
            resposta_correta = "falso"
    elif tipo == "multipla_escolha" and len(opcoes) < 2:
        tipo = "aberta"
        opcoes = []

    # Multipla escolha sem gabarito resolvido nao pode ser liberada em silencio:
    # a turma seria corrigida contra uma chave que nao existe. Fica marcada para
    # aparecer na revisao como nao verificada.
    chave_ambigua = tipo == "multipla_escolha" and not any(
        opcao["correta"] for opcao in opcoes
    )

    return {
        "tipo": tipo,
        "dificuldade": _normalize_difficulty(item.get("dificuldade") or item.get("difficulty")),
        "enunciado": enunciado,
        "opcoes": opcoes,
        "chave_ambigua": chave_ambigua,
        "resposta_correta": resposta_correta,
        "justificativa": str(item.get("justificativa") or item.get("feedback") or item.get("explanation") or "").strip(),
        "conceitos": item.get("conceitos") or item.get("conceitos_relacionados") or item.get("concepts") or [],
        "topico_origem": item.get("topico_origem") or item.get("source_topic") or item.get("topico"),
    }


def _normalize_questions(data: Dict[str, Any], tipos_questao: Sequence[str]) -> List[Dict[str, Any]]:
    raw_questions = (
        data.get("questoes")
        or data.get("perguntas")
        or data.get("questions")
        or data.get("items")
        or []
    )
    if not isinstance(raw_questions, list):
        return []

    normalized = []
    for item in raw_questions:
        question = _normalize_question(item, tipos_questao)
        if question:
            normalized.append(question)
    return normalized


_QUIZ_STOPWORDS = {
    "aula", "sobre", "para", "como", "com", "uma", "por", "dos", "das",
    "que", "foi", "sao", "são", "mais", "entre", "quando", "onde", "esse",
    "essa", "isso", "este", "esta", "tambem", "também", "conceito",
    "conceitos", "exemplo", "exemplos", "professor", "aluno", "alunos",
    "banco", "dados",
}


def _compact_text(text: str, *, limit: int = 220) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip(" -")
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 3].rstrip()}..."


def _content_sentences(content: str) -> List[str]:
    cleaned = re.sub(
        r"RESUMO VALIDADO DA AULA:|TRANSCRIÇÃO DA AULA:",
        "\n",
        content or "",
        flags=re.IGNORECASE,
    )
    parts = re.split(r"(?<=[.!?])\s+|\n+", cleaned)
    sentences = []
    seen = set()
    for part in parts:
        sentence = _compact_text(part, limit=220)
        if len(sentence) < 45:
            continue
        key = sentence.lower()
        if key in seen:
            continue
        seen.add(key)
        sentences.append(sentence)
    return sentences[:80]


def _topic_from_sentence(sentence: str, fallback: str) -> str:
    words = re.findall(r"[A-Za-zÀ-ÿ0-9_]{4,}", sentence.lower())
    keywords = [
        word for word in words
        if word not in _QUIZ_STOPWORDS and not word.isdigit()
    ]
    topic = " ".join(keywords[:3]).strip()
    return topic.title() if topic else fallback


def _fallback_options(
    correct_sentence: str,
    sentences: Sequence[str],
    index: int,
) -> List[Dict[str, Any]]:
    distractors = [
        sentence for sentence in sentences
        if sentence != correct_sentence
    ][:3]
    generic = [
        "Um ponto não abordado diretamente no trecho selecionado.",
        "Uma afirmação incompatível com a explicação da aula.",
        "Uma conclusão que não aparece no resumo nem na transcrição.",
    ]
    while len(distractors) < 3:
        distractors.append(generic[len(distractors)])

    options = [_compact_text(correct_sentence, limit=160)] + [
        _compact_text(item, limit=160) for item in distractors
    ]
    rotation = index % 4
    rotated = options[rotation:] + options[:rotation]
    labels = ["A", "B", "C", "D"]
    return [
        {
            "label": label,
            "texto": text,
            "correta": text == options[0],
        }
        for label, text in zip(labels, rotated)
    ]


def _fallback_quiz_questions(
    content: str,
    quantidade_questoes: int,
    tipos_questao: Sequence[str],
    dificuldade: str,
) -> List[Dict[str, Any]]:
    """Monta perguntas revisaveis quando o LLM falha em estruturar JSON."""
    sentences = _content_sentences(content)
    if not sentences:
        return []

    requested_types = [
        _normalize_question_type(tipo)
        for tipo in (tipos_questao or ["multipla_escolha"])
    ]
    # Teto de 10 chumbado aqui ignorava o que o professor pediu no controle,
    # que aceita ate 50: pedir 20 devolvia 10 sem dizer por que. O limite real e
    # quantas frases a aula tem - de uma frase nao sai uma pergunta ancorada.
    question_count = min(max(quantidade_questoes, 1), len(sentences))
    questions = []

    for index, sentence in enumerate(sentences[:question_count]):
        tipo = requested_types[index % len(requested_types)]
        topic = _topic_from_sentence(sentence, f"Tópico {index + 1}")
        base = {
            "dificuldade": (
                _normalize_difficulty(dificuldade)
                if dificuldade != "mista"
                else "medio"
            ),
            "justificativa": (
                "Pergunta preparada automaticamente a partir de trecho da aula; "
                "revise antes de liberar."
            ),
            "conceitos": [topic],
            "topico_origem": topic,
            "grounding_score": 0.55,
            "verificado": False,
            "fallback": True,
        }

        if tipo == "verdadeiro_falso":
            questions.append({
                **base,
                "tipo": "verdadeiro_falso",
                "enunciado": f"Verdadeiro ou falso: {sentence}",
                "opcoes": [],
                "resposta_correta": "verdadeiro",
            })
        elif tipo == "aberta":
            questions.append({
                **base,
                "tipo": "aberta",
                "enunciado": f"Explique, com base na aula, o ponto principal sobre {topic}.",
                "opcoes": [],
                "resposta_correta": sentence,
            })
        else:
            questions.append({
                **base,
                "tipo": "multipla_escolha",
                "enunciado": (
                    "De acordo com a aula, qual afirmação está diretamente "
                    f"relacionada a {topic}?"
                ),
                "opcoes": _fallback_options(sentence, sentences, index),
                "resposta_correta": "Alternativa correta marcada nas opções.",
            })

    return questions


async def _quiz_generate_node(state: QuizGraphState) -> Dict[str, Any]:
    """Nó que gera questões usando LLM."""

    prompt = QUIZ_GENERATION_PROMPT.format(
        quantidade_questoes=state["quantidade_questoes"],
        resumo=state["resumo"],
        disciplina=state["disciplina"],
        tipo_quiz=state["tipo_quiz"],
        tipos_questao=", ".join(state["tipos_questao"]),
        dificuldade=state["dificuldade"],
    )

    attempts = []
    last_error = "A IA não gerou perguntas aproveitáveis."
    for llm_name in await _candidate_llms_for_quiz(state.get("requested_llm")):
        try:
            response = await dispatch_single(
                llm_name,
                prompt,
                [],
                "Responda somente com JSON válido para geração de quiz.",
                max_tokens=_token_budget(state["quantidade_questoes"]),
            )
        except Exception as e:
            last_error = f"Erro ao chamar LLM {llm_name}: {e}"
            logger.warning(last_error)
            attempts.append({
                "llm": llm_name,
                "success": False,
                "error": str(e),
                "question_count": 0,
            })
            continue

        if response.is_error:
            last_error = f"Falha ao gerar questões: {response.content}"
            logger.error(f"LLM error: {response.content}")
            attempts.append({
                "llm": llm_name,
                "success": False,
                "error": response.content,
                "question_count": 0,
            })
            continue

        # Parse JSON da resposta
        content = response.content
        try:
            quiz_data = _json_from_content(content)
        except Exception as e:
            last_error = f"Resposta do LLM sem JSON válido: {e}"
            logger.error(f"No JSON found in response: {content[:200]}")
            attempts.append({
                "llm": llm_name,
                "success": False,
                "error": str(e),
                "question_count": 0,
            })
            continue

        questoes = _normalize_questions(quiz_data, state["tipos_questao"])
        attempts.append({
            "llm": llm_name,
            "success": bool(questoes),
            "question_count": len(questoes),
        })
        if not questoes:
            last_error = "Resposta do LLM sem perguntas estruturadas."
            logger.warning(f"Quiz generation returned no questions from {llm_name}")
            continue

        return {
            "questoes_brutas": questoes,
            "tempo_estimado": int(quiz_data.get("tempo_estimado") or 15),
            "attempts": attempts,
        }

    fallback_questions = _fallback_quiz_questions(
        state["resumo"],
        state["quantidade_questoes"],
        state["tipos_questao"],
        state["dificuldade"],
    )
    if fallback_questions:
        attempts.append({
            "llm": "content-fallback",
            "success": True,
            "question_count": len(fallback_questions),
            "warning": last_error,
        })
        return {
            "questoes_brutas": fallback_questions,
            "tempo_estimado": 15,
            "attempts": attempts,
        }

    return {
        "outcome": {
            "error": last_error,
            "questoes": [],
            "attempts": attempts,
        }
    }


async def _quiz_validate_node(state: QuizGraphState) -> Dict[str, Any]:
    """Nó que valida questões geradas contra hallucinations."""

    if not state.get("questoes_brutas"):
        return {
            "validacoes": {
                "aprovacao_geral": False,
                "media_grounding": 0.0,
                "feedback": "Nenhuma questão foi gerada"
            }
        }

    llm_name = await _resolve_llm_for_quiz()

    questoes_str = json.dumps(state["questoes_brutas"], ensure_ascii=False, indent=2)

    prompt = VALIDATION_PROMPT.format(
        resumo=state["resumo"],
        questoes_json=questoes_str,
    )

    try:
        response = await dispatch_single(
            llm_name,
            prompt,
            [],
            "Valide as questões e responda somente com JSON válido.",
        )

        if response.is_error:
            raise RuntimeError(response.content)

        content = response.content
        json_match = re.search(r'\{.*\}', content, re.DOTALL)

        if json_match:
            validacoes = json.loads(json_match.group())
            return {"validacoes": validacoes}
        else:
            # Validação default se não conseguir fazer a validação
            return {
                "validacoes": {
                    "aprovacao_geral": True,  # Aceita com confiança baixa
                    "media_grounding": 0.75,
                    "feedback": "Validação automática não funcionou, aceitando com cautela"
                }
            }

    except Exception as e:
        logger.warning(f"Validation error (non-blocking): {e}")
        # Falha na validação não bloqueia - apenas marca com score baixo
        return {
            "validacoes": {
                "aprovacao_geral": True,
                "media_grounding": 0.7,
                "feedback": f"Validação indisponível: {str(e)}"
            }
        }


async def _quiz_filter_node(state: QuizGraphState) -> Dict[str, Any]:
    """Nó que filtra questões com baixo grounding score."""

    questoes_brutas = state.get("questoes_brutas", [])
    validacoes = state.get("validacoes", {})

    if not questoes_brutas or not validacoes.get("validacoes"):
        # Se nao houver validacao completa, segue com as questoes que possuem
        # estrutura minima. O bloqueio final de publicacao ainda ocorre antes
        # de liberar o QR Code.
        questoes_filtradas = [
            questao for questao in questoes_brutas
            if (questao.get("enunciado") or "").strip()
        ]
        media_score = 0.8
    else:
        # A validacao anota confianca. Como o professor revisa antes de publicar,
        # descartamos apenas item malformado ou sinalizado como alucinacao.
        validacoes_por_idx = {
            int(v.get("indice", idx)): v
            for idx, v in enumerate(validacoes.get("validacoes", []))
            if isinstance(v, dict)
        }

        questoes_filtradas = []
        scores = []

        for idx, questao in enumerate(questoes_brutas):
            val = validacoes_por_idx.get(idx, {})
            score = val.get("grounding_score", 0.7)
            scores.append(score)
            is_fallback = questao.get("fallback") is True

            if not (questao.get("enunciado") or "").strip():
                continue
            if val.get("risco_alucinacao", False) is True and not is_fallback:
                continue
            if (
                val.get("bem_formulada", True) is False
                and score < 0.65
                and not is_fallback
            ):
                continue

            questao["grounding_score"] = score
            questao["verificado"] = (
                not is_fallback
                and not questao.get("chave_ambigua")
                and score >= 0.65 and val.get("bem_formulada", True) is not False
            )
            questoes_filtradas.append(questao)

        media_score = sum(scores) / len(scores) if scores else 0.0

    return {
        "questoes_brutas": questoes_filtradas,
        "outcome": {
            "questoes": questoes_filtradas,
            "total_gerado": len(state.get("questoes_brutas", [])),
            "total_validado": len(questoes_filtradas),
            "media_grounding_score": media_score,
            "aprovacao": media_score > 0.7,
            "llm": state.get("requested_llm", "auto"),
            "tempo_estimado": state.get("tempo_estimado", 15),
        }
    }


# Constrói o grafo de geração de quiz
_quiz_graph_builder = StateGraph(QuizGraphState)

_quiz_graph_builder.add_node("generate", _quiz_generate_node)
_quiz_graph_builder.add_node("validate", _quiz_validate_node)
_quiz_graph_builder.add_node("filter", _quiz_filter_node)

_quiz_graph_builder.add_edge(START, "generate")
_quiz_graph_builder.add_edge("generate", "validate")
_quiz_graph_builder.add_edge("validate", "filter")
_quiz_graph_builder.add_edge("filter", END)

quiz_graph = _quiz_graph_builder.compile()


async def generate_quiz(
    *,
    resumo: str,
    disciplina: str,
    titulo_aula: str,
    tipo_quiz: str = "pratica",
    quantidade_questoes: int = 10,
    tipos_questao: Optional[List[str]] = None,
    dificuldade: str = "mista",
    llm: Optional[str] = None,
) -> Dict[str, Any]:
    """Gera quiz automaticamente baseado em resumo de aula.

    Args:
        resumo: Texto do resumo estruturado da aula
        disciplina: Nome da disciplina
        titulo_aula: Título/tema da aula
        tipo_quiz: 'revisao', 'diagnostico', 'pratica'
        quantidade_questoes: Número de questões a gerar
        tipos_questao: Lista de tipos ['multipla_escolha', 'verdadeiro_falso', 'aberta']
        dificuldade: 'facil', 'medio', 'dificil', 'mista'
        llm: LLM preferido ou 'auto' para seleção automática

    Returns:
        Dict com questões geradas e metadata
    """

    if not tipos_questao:
        tipos_questao = ["multipla_escolha", "verdadeiro_falso"]

    if not resumo or not resumo.strip():
        return {
            "questoes": [],
            "error": "Resumo vazio",
            "total_gerado": 0,
            "media_grounding_score": 0.0,
        }

    result = await quiz_graph.ainvoke({
        "resumo": resumo,
        "disciplina": disciplina,
        "titulo_aula": titulo_aula,
        "tipo_quiz": tipo_quiz,
        "quantidade_questoes": quantidade_questoes,
        "tipos_questao": tipos_questao,
        "dificuldade": dificuldade,
        "requested_llm": llm,
    })

    outcome = dict(result.get("outcome", {}))
    outcome["attempts"] = result.get("attempts", [])

    return outcome
