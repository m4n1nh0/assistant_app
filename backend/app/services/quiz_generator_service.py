"""Serviço de geração automática de exercícios e quizzes baseado em resumos de aula.

A regra desta versão: pergunta de quiz é escrita pela IA. Não existe gerador por
template aqui — quando o modelo não entrega, o quiz falha e diz por quê, em vez
de devolver frase recortada da aula com cara de pergunta. Para o modelo ter
chance real de entregar, a geração vai em lotes pequenos (JSON curto não volta
cortado) e roda fora do ciclo da requisição, sem pressa de responder rápido.
"""

import json
import re
from typing import Any, Callable, Dict, List, Optional, Sequence

from langgraph.graph import END, START, StateGraph
from loguru import logger

from .llm_routing_service import pick_auto_llm, rank_auto_llms
from .llm_service import dispatch_single
from .user_llm_config_service import runtime_settings

settings = runtime_settings

#: Alternativa e lida no celular com o enunciado projetado. Passando disso, o
#: aluno nao termina de ler no tempo da pergunta.
MAX_OPTION_WORDS = 8
MAX_OPTION_CHARS = 60

#: Questoes por chamada. Dez questoes em um JSON so estouravam o teto de saida
#: e voltavam cortadas; em lotes de quatro cada resposta fecha com folga.
QUESTIONS_PER_BATCH = 4

#: Lotes seguidos sem nenhuma questao aproveitavel antes de desistir.
MAX_EMPTY_BATCHES = 2

#: Questoes por chamada de validacao, pelo mesmo motivo do lote de geracao.
VALIDATION_BATCH = 6

# Templates de prompts para diferentes tipos de quiz
QUIZ_GENERATION_PROMPT = """Você é um especialista em geração de questões educacionais.

Baseado no conteúdo da aula abaixo, gere {quantidade_questoes} questões de forma estruturada.

**Conteúdo selecionado (uma ou mais aulas e materiais da disciplina):**
{resumo}

**Disciplina:** {disciplina}
**Tipo de Quiz:** {tipo_quiz}
**Tipos de Questão:** multipla_escolha
**Dificuldade:** {dificuldade}
{evitar}
**Instruções:**
1. Cada questão deve derivar diretamente do conteúdo acima (não invente conteúdo)
2. Inclua justificativas que citam o trecho de onde a questão saiu
3. Quando houver mais de uma fonte, distribua as questões entre elas
4. Gere somente questões objetivas de múltipla escolha
5. Distribua dificuldade equitativamente
6. Inclua todos os tópicos principais encontrados no conteúdo
7. Para "multipla_escolha", gere exatamente 4 opções com labels A, B, C e D
8. Marque exatamente uma opção como correta
9. Alternativa curta: no máximo {max_palavras} palavras e {max_caracteres}
   caracteres cada, sem frase completa e sem ponto final. O quiz é respondido
   no celular com o enunciado projetado: alternativa longa não cabe na tela nem
   dá para ler no tempo da pergunta. Escreva o termo, o número ou a expressão
   que responde — nunca a explicação inteira, que é o lugar da justificativa
10. Enunciado direto, em uma linha
11. Use "resposta_correta" com o label da alternativa correta
12. Responda somente com JSON válido, sem markdown e sem comentários fora do JSON

**Formato de resposta (JSON):**
{{
  "questoes": [
    {{
      "tipo": "multipla_escolha",
      "dificuldade": "facil|medio|dificil",
      "enunciado": "Texto da questão",
      "opcoes": [
        {{"label": "A", "texto": "Terceira forma normal", "correta": true}},
        {{"label": "B", "texto": "Chave estrangeira", "correta": false}}
      ],
      "resposta_correta": "A",
      "justificativa": "Explicação com referência ao resumo",
      "conceitos": ["conceito1", "conceito2"],
      "topico_origem": "Título do tópico do resumo"
    }}
  ],
  "tempo_estimado": 15
}}
"""

SHORTEN_PROMPT = """As alternativas abaixo ficaram longas demais para um quiz respondido no celular.

Reescreva cada alternativa com no máximo {max_palavras} palavras e {max_caracteres} caracteres, mantendo exatamente o mesmo sentido. Não mude a ordem, não mude os labels, não crie nem remova alternativa, e não altere qual delas responde a pergunta.

**Questões:**
{questoes_json}

Responda somente com JSON válido:
{{
  "questoes": [
    {{
      "indice": 0,
      "opcoes": [
        {{"label": "A", "texto": "versão curta"}},
        {{"label": "B", "texto": "versão curta"}}
      ]
    }}
  ]
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

    #: Chamado a cada lote com (questoes prontas, total pedido). Existe para a
    #: geracao em segundo plano poder dizer na tela em que ponto esta.
    on_progress: Optional[Callable[[int, int], None]]

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
    """Teto de saida proporcional ao tamanho do lote pedido.

    O padrao dos provedores e 2000 tokens, dimensionado para resposta de chat.
    Um JSON com dez questoes de multipla escolha - enunciado, quatro
    alternativas e justificativa em cada - passa disso, e a resposta voltava
    cortada no meio: `json.loads` falhava nos tres modelos candidatos e o quiz
    inteiro nao saia. Quanto mais questoes o professor pedia, mais garantido
    era o corte.
    """
    return min(max(2000, 300 * max(quantidade_questoes, 1) + 500), 8000)


def _salvage_questions(content: str) -> List[Dict[str, Any]]:
    """Recupera as questoes inteiras de um JSON que veio cortado.

    Sete questoes de verdade valem mais que dez perdidas por um corte no meio
    do array. Varre o texto contando chaves e devolve so os objetos que
    fecharam.
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
        "enunciado": re.sub(r"\s+", " ", enunciado).strip(),
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


# --- Alternativas que cabem na tela ---------------------------------------

#: Palavra solta no fim de uma alternativa aparada nao diz nada e ainda sugere
#: que falta texto.
_TRAILING_WORDS = {
    "de", "da", "do", "das", "dos", "e", "ou", "que", "com", "para", "por",
    "em", "no", "na", "nos", "nas", "a", "o", "as", "os", "um", "uma", "ao",
    "aos", "à", "às", "pelo", "pela", "sobre", "como", "quando", "se",
}


def _compact_text(text: str, *, limit: int = 220) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip(" -")
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 3].rstrip()}..."


def _option_is_long(texto: str) -> bool:
    """Alternativa que nao cabe na tela do aluno."""
    limpo = re.sub(r"\s+", " ", texto or "").strip()
    return len(limpo) > MAX_OPTION_CHARS or len(limpo.split()) > MAX_OPTION_WORDS


def _trim_option(texto: str) -> str:
    """Encurta a alternativa mecanicamente, como ultimo recurso.

    So roda depois de o modelo ja ter tido a chance de reescrever. Corta
    primeiro a explicacao pendurada depois de travessao, ponto e virgula ou
    parenteses - que e onde o modelo alonga - e so entao pelo numero de
    palavras.
    """
    limpo = re.sub(r"\s+", " ", texto or "").strip()
    if not _option_is_long(limpo):
        return limpo

    for separador in (" — ", " – ", " - ", "; ", ": ", " (", ", pois", ", que"):
        cabeca = limpo.split(separador)[0].strip(" ,;:.")
        if cabeca and not _option_is_long(cabeca):
            return cabeca

    palavras = limpo.split()[:MAX_OPTION_WORDS]
    while len(palavras) > 1 and (
        len(" ".join(palavras)) > MAX_OPTION_CHARS
        or palavras[-1].lower().strip(",.;:") in _TRAILING_WORDS
    ):
        palavras.pop()

    resultado = " ".join(palavras).strip(" ,;:.")
    return resultado or limpo[:MAX_OPTION_CHARS].strip()


def _questions_with_long_options(questoes: Sequence[Dict[str, Any]]) -> List[int]:
    return [
        indice for indice, questao in enumerate(questoes)
        if any(
            _option_is_long(opcao.get("texto", ""))
            for opcao in questao.get("opcoes") or []
        )
    ]


def _apply_shortened_options(
    questoes: List[Dict[str, Any]],
    data: Dict[str, Any],
) -> int:
    """Aplica a reescrita do modelo, aceitando so o que ficou realmente curto.

    A marcacao de correta continua sendo a original, casada por label: o passo
    e de encurtar texto, e trocar gabarito aqui seria mudar a pergunta.
    """
    itens = data.get("questoes")
    if not isinstance(itens, list):
        return 0

    aplicadas = 0
    for item in itens:
        if not isinstance(item, dict):
            continue
        try:
            indice = int(item.get("indice"))
        except (TypeError, ValueError):
            continue
        if not 0 <= indice < len(questoes):
            continue

        novas = item.get("opcoes")
        if not isinstance(novas, list):
            continue

        por_label: Dict[str, str] = {}
        for nova in novas:
            if not isinstance(nova, dict):
                continue
            label = str(nova.get("label") or "").strip().upper()
            texto = re.sub(r"\s+", " ", str(nova.get("texto") or "")).strip()
            if label and texto and not _option_is_long(texto):
                por_label[label] = texto

        alterou = False
        for opcao in questoes[indice].get("opcoes") or []:
            curto = por_label.get(str(opcao.get("label", "")).strip().upper())
            if curto and curto != opcao.get("texto"):
                opcao["texto"] = curto
                alterou = True
        if alterou:
            aplicadas += 1

    return aplicadas


async def _shorten_long_options(
    questoes: List[Dict[str, Any]],
    candidatos: Sequence[str],
) -> List[Dict[str, Any]]:
    """Devolve as questoes com alternativas que cabem na tela do aluno.

    Primeiro pede ao modelo que reescreva: encurtar mantendo o sentido e
    trabalho de quem escreveu a alternativa. So o que sobrar longo e aparado no
    braco, porque alternativa que o aluno nao le no tempo da pergunta e pior do
    que alternativa aparada.
    """
    alvos = _questions_with_long_options(questoes)
    if not alvos:
        return questoes

    payload = json.dumps(
        [
            {
                "indice": indice,
                "enunciado": questoes[indice].get("enunciado", ""),
                "opcoes": [
                    {"label": opcao.get("label"), "texto": opcao.get("texto")}
                    for opcao in questoes[indice].get("opcoes") or []
                ],
            }
            for indice in alvos
        ],
        ensure_ascii=False,
        indent=2,
    )
    prompt = SHORTEN_PROMPT.format(
        max_palavras=MAX_OPTION_WORDS,
        max_caracteres=MAX_OPTION_CHARS,
        questoes_json=payload,
    )

    for llm_name in list(candidatos)[:2]:
        try:
            response = await dispatch_single(
                llm_name,
                prompt,
                [],
                "Encurte alternativas de quiz e responda somente com JSON válido.",
                max_tokens=_token_budget(len(alvos)),
            )
        except Exception as error:
            logger.warning(f"Falha ao encurtar alternativas com {llm_name}: {error}")
            continue

        if response.is_error:
            logger.warning(f"Encurtamento recusado por {llm_name}: {response.content}")
            continue

        if _apply_shortened_options(questoes, _json_from_content(response.content)):
            break

    aparadas = 0
    for questao in questoes:
        for opcao in questao.get("opcoes") or []:
            if _option_is_long(opcao.get("texto", "")):
                opcao["texto"] = _trim_option(opcao["texto"])
                aparadas += 1
    if aparadas:
        logger.info(f"{aparadas} alternativa(s) aparadas localmente.")

    return questoes


# --- Geracao em lotes ------------------------------------------------------


def _dedupe_key(enunciado: str) -> str:
    return re.sub(r"[^0-9a-zà-ÿ ]", "", (enunciado or "").lower()).strip()


def _avoid_block(ja_gerados: Sequence[Dict[str, Any]]) -> str:
    """Lista os enunciados ja prontos, para o lote seguinte nao repetir."""
    if not ja_gerados:
        return ""
    enunciados = "\n".join(
        f"- {_compact_text(questao.get('enunciado', ''), limit=120)}"
        for questao in list(ja_gerados)[-12:]
    )
    return (
        "\n**Perguntas já geradas (não repita nem reformule estas):**\n"
        f"{enunciados}\n"
    )


def _report_progress(state: QuizGraphState, prontas: int, total: int) -> None:
    callback = state.get("on_progress")
    if not callable(callback):
        return
    try:
        callback(prontas, total)
    except Exception as error:  # progresso e informativo: nao derruba a geracao
        logger.debug(f"Callback de progresso do quiz falhou: {error}")


async def _generate_batch(
    state: QuizGraphState,
    quantidade: int,
    ja_gerados: List[Dict[str, Any]],
    candidatos: Sequence[str],
    attempts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Pede um lote de questoes, tentando cada modelo candidato em ordem."""

    prompt = QUIZ_GENERATION_PROMPT.format(
        quantidade_questoes=quantidade,
        resumo=state["resumo"],
        disciplina=state["disciplina"],
        tipo_quiz=state["tipo_quiz"],
        tipos_questao=", ".join(state["tipos_questao"]),
        dificuldade=state["dificuldade"],
        evitar=_avoid_block(ja_gerados),
        max_palavras=MAX_OPTION_WORDS,
        max_caracteres=MAX_OPTION_CHARS,
    )
    vistos = {_dedupe_key(questao.get("enunciado", "")) for questao in ja_gerados}
    erro = "A IA não gerou perguntas aproveitáveis."

    for llm_name in candidatos:
        try:
            response = await dispatch_single(
                llm_name,
                prompt,
                [],
                "Responda somente com JSON válido para geração de quiz.",
                max_tokens=_token_budget(quantidade),
            )
        except Exception as e:
            erro = f"Erro ao chamar LLM {llm_name}: {e}"
            logger.warning(erro)
            attempts.append({
                "llm": llm_name,
                "success": False,
                "error": str(e),
                "question_count": 0,
            })
            continue

        if response.is_error:
            erro = f"Falha ao gerar questões: {response.content}"
            logger.error(f"LLM error: {response.content}")
            attempts.append({
                "llm": llm_name,
                "success": False,
                "error": response.content,
                "question_count": 0,
            })
            continue

        quiz_data = _json_from_content(response.content)
        questoes = _normalize_questions(quiz_data, state["tipos_questao"])

        novas = []
        for questao in questoes:
            chave = _dedupe_key(questao.get("enunciado", ""))
            if not chave or chave in vistos:
                continue
            vistos.add(chave)
            novas.append(questao)
            if len(novas) >= quantidade:
                break

        attempts.append({
            "llm": llm_name,
            "success": bool(novas),
            "question_count": len(novas),
        })
        if not novas:
            erro = "Resposta do LLM sem perguntas estruturadas."
            logger.warning(f"Quiz generation returned no questions from {llm_name}")
            continue

        return {
            "questoes": novas,
            "tempo_estimado": int(quiz_data.get("tempo_estimado") or 0),
            "llm": llm_name,
        }

    return {"questoes": [], "tempo_estimado": 0, "llm": "", "error": erro}


async def _quiz_generate_node(state: QuizGraphState) -> Dict[str, Any]:
    """Nó que gera questões usando LLM, em lotes pequenos.

    Sem rede de template: o que sai daqui foi escrito pelo modelo. Lote vazio e
    tentado de novo, com o modelo candidato seguinte; se nem assim vier nada, o
    quiz falha dizendo o motivo, em vez de entregar frase recortada da aula com
    cara de pergunta.
    """

    total = max(int(state["quantidade_questoes"]), 1)
    candidatos = await _candidate_llms_for_quiz(state.get("requested_llm"))

    questoes: List[Dict[str, Any]] = []
    attempts: List[Dict[str, Any]] = []
    tempo_estimado = 0
    lotes_vazios = 0
    erro = "A IA não gerou perguntas aproveitáveis."

    _report_progress(state, 0, total)

    while len(questoes) < total:
        pedido = min(QUESTIONS_PER_BATCH, total - len(questoes))
        lote = await _generate_batch(state, pedido, questoes, candidatos, attempts)

        if not lote["questoes"]:
            erro = lote.get("error") or erro
            lotes_vazios += 1
            if lotes_vazios >= MAX_EMPTY_BATCHES:
                break
            continue

        lotes_vazios = 0
        # Quem entregou o lote comeca o proximo. Sem isso, um quiz de cinquenta
        # perguntas repete a chamada perdida no modelo que falhou, lote a lote.
        vencedor = lote.get("llm")
        if vencedor and candidatos and candidatos[0] != vencedor:
            candidatos = [vencedor] + [
                nome for nome in candidatos if nome != vencedor
            ]

        questoes.extend(lote["questoes"])
        tempo_estimado = max(tempo_estimado, lote["tempo_estimado"])
        _report_progress(state, len(questoes), total)

    if not questoes:
        # `attempts` tambem no topo do estado: e de la que `generate_quiz` le a
        # lista para a revisao mostrar qual modelo falhou e com que erro.
        return {
            "attempts": attempts,
            "outcome": {
                "error": erro,
                "questoes": [],
                "attempts": attempts,
            },
        }

    questoes = await _shorten_long_options(questoes, candidatos)

    return {
        "questoes_brutas": questoes,
        "tempo_estimado": tempo_estimado or 15,
        "attempts": attempts,
    }


async def _quiz_validate_node(state: QuizGraphState) -> Dict[str, Any]:
    """Nó que valida questões geradas contra hallucinations."""

    questoes_brutas = state.get("questoes_brutas") or []
    if not questoes_brutas:
        return {
            "validacoes": {
                "aprovacao_geral": False,
                "media_grounding": 0.0,
                "feedback": "Nenhuma questão foi gerada"
            }
        }

    llm_name = await _resolve_llm_for_quiz()
    validacoes: List[Dict[str, Any]] = []
    falhas = 0

    # Em lotes pelo mesmo motivo da geracao: a validacao de vinte questoes de
    # uma vez volta cortada, e ai nenhuma questao fica marcada como verificada.
    for inicio in range(0, len(questoes_brutas), VALIDATION_BATCH):
        lote = questoes_brutas[inicio:inicio + VALIDATION_BATCH]
        prompt = VALIDATION_PROMPT.format(
            resumo=state["resumo"],
            questoes_json=json.dumps(lote, ensure_ascii=False, indent=2),
        )

        try:
            response = await dispatch_single(
                llm_name,
                prompt,
                [],
                "Valide as questões e responda somente com JSON válido.",
                max_tokens=_token_budget(len(lote)),
            )
            if response.is_error:
                raise RuntimeError(response.content)
            dados = _json_from_content(response.content)
        except Exception as e:
            logger.warning(f"Validation error (non-blocking): {e}")
            falhas += 1
            continue

        itens = dados.get("validacoes")
        if not isinstance(itens, list):
            falhas += 1
            continue

        for posicao, item in enumerate(itens):
            if not isinstance(item, dict):
                continue
            try:
                relativo = int(item.get("indice", posicao))
            except (TypeError, ValueError):
                relativo = posicao
            ajustado = dict(item)
            ajustado["indice"] = inicio + relativo
            validacoes.append(ajustado)

    if not validacoes:
        # Falha na validacao nao bloqueia: as questoes seguem para a revisao com
        # confianca baixa, e o professor decide.
        return {
            "validacoes": {
                "aprovacao_geral": True,
                "media_grounding": 0.7,
                "feedback": "Validação automática indisponível; revise as perguntas.",
            }
        }

    scores = [float(item.get("grounding_score", 0.7) or 0.0) for item in validacoes]
    media = sum(scores) / len(scores) if scores else 0.0
    return {
        "validacoes": {
            "validacoes": validacoes,
            "media_grounding": media,
            "aprovacao_geral": media > 0.7,
            "lotes_sem_validacao": falhas,
        }
    }


async def _quiz_filter_node(state: QuizGraphState) -> Dict[str, Any]:
    """Nó que filtra questões com baixo grounding score."""

    # Geracao que falhou ja escreveu o motivo. Reescrever o outcome aqui trocava
    # a frase do modelo por um resultado vazio, e a tela dizia so "nenhuma
    # pergunta válida" - sem dizer qual modelo falhou nem por que.
    erro_da_geracao = (state.get("outcome") or {}).get("error")
    if erro_da_geracao:
        return {"outcome": state["outcome"]}

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

            if not (questao.get("enunciado") or "").strip():
                continue
            if val.get("risco_alucinacao", False) is True:
                continue
            if val.get("bem_formulada", True) is False and score < 0.65:
                continue

            questao["grounding_score"] = score
            questao["verificado"] = (
                not questao.get("chave_ambigua")
                and score >= 0.65
                and val.get("bem_formulada", True) is not False
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
    on_progress: Optional[Callable[[int, int], None]] = None,
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
        on_progress: Chamado a cada lote com (questões prontas, total pedido)

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
        "on_progress": on_progress,
    })

    outcome = dict(result.get("outcome", {}))
    outcome["attempts"] = result.get("attempts", [])

    return outcome
