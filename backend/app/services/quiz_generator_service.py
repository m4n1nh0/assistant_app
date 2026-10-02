"""Serviço de geração automática de exercícios e quizzes baseado em resumos de aula.

A regra desta versão: pergunta de quiz é escrita pela IA. Não existe gerador por
template aqui — quando o modelo não entrega, o quiz falha e diz por quê, em vez
de devolver frase recortada da aula com cara de pergunta. Para o modelo ter
chance real de entregar, a geração vai em lotes pequenos (JSON curto não volta
cortado) e roda fora do ciclo da requisição, sem pressa de responder rápido.
"""

import json
import random
import re
from typing import Any, Callable, Dict, List, Optional, Sequence

from langgraph.graph import END, START, StateGraph
from loguru import logger

from .llm_routing_service import pick_auto_llm, rank_auto_llms
from .text_sampling import sample_evenly
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

#: Provedores que a validacao tenta por lote antes de desistir dele.
MAX_VALIDATION_PROVIDERS = 2

#: Gera-se um pouco alem do pedido e corta-se no fim. Repeticao e reprovacao na
#: validacao sao perdas esperadas; sem folga, pedir 20 entregava 15 e o professor
#: ficava sem as 5 que faltavam.
OVERSAMPLE_RATIO = 0.25
MIN_OVERSAMPLE = 2
MAX_OVERSAMPLE = 8

#: Alternativas diferentes entre si que uma pergunta precisa ter para valer: com
#: menos de tres o aluno acerta no chute, ou nao ha o que escolher.
MIN_DISTINCT_OPTIONS = 3

#: Quantas vezes um objetivo do plano e oferecido ao modelo antes de desistir
#: dele (o conteudo pode nao sustentar aquela pergunta).
MAX_SLOT_OFFERS = 2

# Templates de prompts para diferentes tipos de quiz
QUIZ_GENERATION_PROMPT = """Você é um especialista em geração de questões educacionais.

Baseado no conteúdo da aula abaixo, gere {quantidade_questoes} questões de forma estruturada.

**Conteúdo selecionado (uma ou mais aulas e materiais da disciplina):**
{resumo}

**Disciplina:** {disciplina}
**Tipo de Quiz:** {tipo_quiz}
**Tipos de Questão:** multipla_escolha
**Dificuldade:** {dificuldade}

**Instruções:**
1. Cada questão deve derivar diretamente do conteúdo acima (não invente conteúdo)
2. Inclua justificativas que citam o trecho de onde a questão saiu
3. Quando houver mais de uma fonte, distribua as questões entre elas
4. Gere somente questões objetivas de múltipla escolha
5. Distribua dificuldade equitativamente
6. Cubra os tópicos principais do conteúdo, priorizando os que ainda não
   aparecem nas perguntas já geradas
7. Para "multipla_escolha", gere exatamente 4 opções com labels A, B, C e D,
   todas diferentes entre si, plausíveis e do mesmo tipo da correta — nunca
   "todas as anteriores" nem "nenhuma das anteriores"
8. Marque exatamente uma opção como correta, e varie a posição dela de uma
   questão para outra (A, B, C ou D): não deixe a correta sempre na A
9. Alternativa curta: no máximo {max_palavras} palavras e {max_caracteres}
   caracteres cada, sem frase completa e sem ponto final. O quiz é respondido
   no celular com o enunciado projetado: alternativa longa não cabe na tela nem
   dá para ler no tempo da pergunta. Escreva o termo, o número ou a expressão
   que responde — nunca a explicação inteira, que é o lugar da justificativa
10. Enunciado direto, em uma linha
11. Use "resposta_correta" com o label da alternativa correta
12. Responda somente com JSON válido, sem markdown e sem comentários fora do JSON
{plano}{evitar}
**Formato de resposta (JSON):**
{{
  "questoes": [
    {{
      "objetivo": 1,
      "tipo": "multipla_escolha",
      "dificuldade": "facil|medio|dificil",
      "enunciado": "Texto da questão",
      "opcoes": [
        {{"label": "A", "texto": "Chave estrangeira", "correta": false}},
        {{"label": "B", "texto": "Índice composto", "correta": false}},
        {{"label": "C", "texto": "Terceira forma normal", "correta": true}},
        {{"label": "D", "texto": "Gatilho", "correta": false}}
      ],
      "resposta_correta": "C",
      "justificativa": "Explicação com referência ao resumo",
      "conceitos": ["conceito1", "conceito2"],
      "topico_origem": "Título do tópico do resumo"
    }}
  ],
  "tempo_estimado": 15
}}
"""

#: Planejar antes de escrever e o que da variedade ao quiz. Sem plano, cada lote
#: so sabia a lista do que ja saiu e voltava as mesmas perguntas com outras
#: palavras; com plano, cada pergunta nasce de um conceito e de um angulo
#: escolhidos antes. Nao contem "gere N questoes" de proposito: esse trecho e o
#: que identifica o pedido de geracao.
PLAN_PROMPT = """Você é um professor planejando um quiz de múltipla escolha.

Leia o conteúdo e planeje {quantidade} perguntas **diferentes entre si**. Ainda
não escreva as perguntas: liste os objetivos.

**Conteúdo selecionado (uma ou mais aulas e materiais da disciplina):**
{resumo}

**Disciplina:** {disciplina}
**Tipo de Quiz:** {tipo_quiz}
**Dificuldade:** {dificuldade}

Regras:
1. Cada objetivo testa um conceito ou fato **distinto** do conteúdo. Dois objetivos
   nunca podem ter a mesma resposta.
2. Varie o ângulo entre os objetivos: definição, aplicação a um caso, comparação
   entre dois conceitos, causa e consequência, identificação de erro, ordem de
   etapas, exemplo concreto.
3. Cubra o conteúdo todo, distribuindo entre as fontes e os tópicos.
4. Use somente o que está no conteúdo. Se ele não sustenta {quantidade} objetivos
   realmente distintos, devolva menos — nunca repita nem invente.
5. Responda somente com JSON válido, sem markdown.
{evitar}
**Formato de resposta (JSON):**
{{
  "objetivos": [
    {{"topico": "Título do tópico", "conceito": "Conceito ou fato testado", "angulo": "aplicacao"}}
  ]
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

    #: Questoes de quizzes anteriores das mesmas fontes. Entram na lista de "ja
    #: geradas" do prompt e na deteccao de repeticao, mas nao no quiz novo: sao
    #: o que faz o segundo quiz da mesma aula nao sair igual ao primeiro.
    previas: List[Dict[str, Any]]

    #: Chamado a cada lote com (questoes prontas, total pedido). Existe para a
    #: geracao em segundo plano poder dizer na tela em que ponto esta.
    on_progress: Optional[Callable[[int, int], None]]

    #: O que foi descartado e por que (repetidas, invalidas, reprovadas na
    #: validacao, excedentes) e quantos objetivos o plano conseguiu. E o que
    #: explica ao professor por que vieram menos perguntas do que o pedido.
    descartes: Optional[Dict[str, int]] = None

    #: Provedores que funcionaram, o melhor primeiro, e o teto de fonte de cada um.
    provedores: Optional[List[str]] = None
    limites: Optional[Dict[str, int]] = None

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
    disponiveis = settings.active_llms
    if not disponiveis:
        # Sem provedor configurado nao ha o que tentar. Devolver um nome fixo
        # aqui so adiaria a falha para dentro da chamada, com mensagem pior.
        return []
    if not ranked:
        ranked = await rank_auto_llms(disponiveis, task="code")
    fallback = [await pick_auto_llm(disponiveis) or disponiveis[0]]
    # Sem teto: antes so os tres primeiros da fila eram tentados, entao dois
    # provedores quebrados (modelo retirado do ar, chave vencida) consumiam a
    # fila inteira e o quiz falhava com as demais contas do professor intactas
    # e nunca chamadas. Provedor que falha sai da fila em `_drop_provider`, o
    # que ja limita quantas chamadas cada geracao faz.
    return ranked or fallback


async def _resolve_llm_for_quiz(preferred: Optional[str] = None) -> str:
    """Resolve qual LLM usar para geração de quiz."""
    candidatos = await _candidate_llms_for_quiz(preferred)
    return candidatos[0] if candidatos else ""


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


#: Mesma extracao, para quem le resposta de modelo fora deste modulo (revisao
#: das perguntas por agentes especialistas).
json_from_content = _json_from_content


async def candidate_llms(preferred: Optional[str] = None) -> List[str]:
    """Modelos a tentar, em ordem; vazio quando nao ha provedor configurado."""
    return await _candidate_llms_for_quiz(preferred)


def token_budget(quantidade_questoes: int) -> int:
    """Teto de saida proporcional ao tamanho do lote pedido."""
    return _token_budget(quantidade_questoes)


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

    try:
        objetivo = int(item.get("objetivo"))
    except (TypeError, ValueError):
        objetivo = None

    return {
        "objetivo": objetivo,
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


#: Quantas perguntas prontas entram no prompt do lote seguinte. Tem de ser o que a
#: checagem de repeticao tambem enxerga: com 30 aqui e 60 la, as 30 mais antigas
#: rejeitavam a resposta do modelo sem que ele soubesse que devia evitá-las, e o
#: lote voltava "todas repetiam as ja geradas". As mais antigas entram em forma
#: compacta (sem a resposta) para a lista nao comer o contexto da aula.
MAX_AVOID_QUESTIONS = 80
MAX_AVOID_CONCEPTS = 40

#: Das perguntas a evitar, quantas mais recentes levam a resposta junto.
AVOID_WITH_ANSWER = 20
#: Parecenca de palavras a partir da qual uma pergunta conta como reformulacao
#: de outra ja pronta ("O que e 3FN?" x "O que e a 3FN na normalizacao?").
REPHRASE_SIMILARITY = 0.8


def _dedupe_key(enunciado: str) -> str:
    return re.sub(r"[^0-9a-zà-ÿ ]", "", (enunciado or "").lower()).strip()


def _stem(word: str) -> str:
    """Tira o plural simples: "dependencias" e "dependencia" sao a mesma palavra.

    Sem isso, a mesma pergunta reescrita no plural passava pela checagem de
    repeticao com palavras "diferentes".
    """
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _key_words(enunciado: str) -> frozenset:
    # Numero fica mesmo curto: "1FN" e "2FN", ou "1 byte" e "2 bytes", sao
    # perguntas diferentes que so se distinguem por ele.
    return frozenset(
        _stem(word)
        for word in _dedupe_key(enunciado).split()
        if len(word) > 2 or any(char.isdigit() for char in word)
    )


def _is_repeat(enunciado: str, vistos: Sequence[frozenset], chaves: set) -> bool:
    """Diz se a pergunta ja existe, igual ou so com as palavras trocadas de lugar.

    Comparar so o texto normalizado deixava passar a mesma pergunta com uma
    palavra a mais - e o quiz saia com duas questoes sobre a mesma coisa.
    """
    chave = _dedupe_key(enunciado)
    if not chave or chave in chaves:
        return True
    palavras = _key_words(enunciado)
    if not palavras:
        return False
    for outras in vistos:
        if not outras:
            continue
        comuns = len(palavras & outras) / len(palavras | outras)
        if comuns >= REPHRASE_SIMILARITY:
            return True
    return False


def _correct_option_text(questao: Dict[str, Any]) -> str:
    for opcao in questao.get("opcoes") or []:
        if isinstance(opcao, dict) and opcao.get("correta"):
            return str(opcao.get("texto") or "").strip()
    return ""


#: Parecenca de palavras a partir da qual duas perguntas com a **mesma resposta**
#: contam como a mesma pergunta. Mais baixa que `REPHRASE_SIMILARITY` de
#: proposito: resposta igual ja e um sinal forte, e e o que pega a reformulacao
#: ("elimina dependencia transitiva" x "remove dependencias transitivas").
SAME_ANSWER_SIMILARITY = 0.3


def _answer_key(questao: Dict[str, Any]) -> str:
    return _dedupe_key(_correct_option_text(questao))


def _is_same_fact(
    questao: Dict[str, Any],
    vistas: Sequence[tuple],
) -> bool:
    """Mesma resposta e enunciado minimamente parecido: e o mesmo fato.

    Comparar so o enunciado deixava passar a pergunta reescrita. Duas perguntas
    podem ter a mesma resposta e serem diferentes ("qual forma normal exige 2FN?"
    x "qual elimina dependencia transitiva?"), por isso a resposta sozinha nao
    basta - tem de vir junto com enunciado parecido.

    Args:
        vistas: pares `(palavras do enunciado, chave da resposta)` ja aceitos.
    """
    resposta = _answer_key(questao)
    if not resposta:
        return False
    palavras = _key_words(questao.get("enunciado", ""))
    if not palavras:
        return False
    for outras, resposta_outra in vistas:
        if resposta_outra != resposta or not outras:
            continue
        if len(palavras & outras) / len(palavras | outras) >= SAME_ANSWER_SIMILARITY:
            return True
    return False


# --- Alternativas: distintas, em ordem equilibrada --------------------------

_ORDER_DEPENDENT = re.compile(
    r"\b(todas|todos|nenhuma|nenhum|ambas|ambos)\b[^.]*\b(anteriores?|acima|alternativas?|itens?)\b"
    r"|\b(alternativas?|itens?|op[cç][aã]o|op[cç][oõ]es)\s+[A-E]\b",
    re.IGNORECASE,
)


def _dedupe_options(opcoes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Tira alternativas com o mesmo texto, mantendo a marca de correta."""
    vistas: Dict[str, Dict[str, Any]] = {}
    resultado: List[Dict[str, Any]] = []
    for opcao in opcoes:
        chave = _dedupe_key(str(opcao.get("texto", "")))
        if not chave:
            continue
        if chave in vistas:
            # Duas iguais e a segunda era a correta: a correta e a que fica.
            if opcao.get("correta"):
                vistas[chave]["correta"] = True
            continue
        vistas[chave] = opcao
        resultado.append(opcao)
    return resultado


def _is_answerable(questao: Dict[str, Any]) -> bool:
    """Multipla escolha com alternativas suficientes para haver o que escolher."""
    if questao.get("tipo") != "multipla_escolha":
        return True
    return len(questao.get("opcoes") or []) >= MIN_DISTINCT_OPTIONS


def _correct_index(opcoes: Sequence[Dict[str, Any]]) -> Optional[int]:
    indices = [i for i, opcao in enumerate(opcoes) if opcao.get("correta")]
    return indices[0] if len(indices) == 1 else None


def _relabel(questao: Dict[str, Any]) -> None:
    """Letras sequenciais (A, B, C...) na ordem atual, e `resposta_correta` coerente.

    O modelo as vezes devolve letras repetidas ou fora de ordem; a letra e o que
    o aluno envia e o que corrige a resposta, entao ela tem de ser unica e bater
    com a posicao.
    """
    for indice, opcao in enumerate(questao.get("opcoes") or []):
        opcao["label"] = chr(ord("A") + indice)
    posicao = _correct_index(questao.get("opcoes") or [])
    if posicao is not None:
        questao["resposta_correta"] = questao["opcoes"][posicao]["label"]


def _balance_correct_positions(
    questoes: List[Dict[str, Any]],
    rng: random.Random,
) -> None:
    """Espalha a posicao da alternativa correta pelo quiz inteiro.

    Os modelos colocam a correta quase sempre na A (o exemplo do prompt fazia
    isso), e o aluno que percebe o padrao acerta sem ler. Reordenar no codigo e a
    unica garantia: pedir "varie a posicao" no prompt so ajuda um pouco.

    A posicao de cada questao e escolhida entre as menos usadas ate ali, com
    desempate aleatorio, entao o quiz sai equilibrado, nao so sorteado. Pergunta
    cujas alternativas dependem da ordem ("todas as anteriores", "A e B") nao e
    reordenada.
    """
    usos: Dict[int, int] = {}
    for questao in questoes:
        if questao.get("tipo") != "multipla_escolha":
            continue
        opcoes = questao.get("opcoes") or []
        posicao_atual = _correct_index(opcoes)
        if posicao_atual is None or len(opcoes) < 2:
            _relabel(questao)
            continue
        if any(_ORDER_DEPENDENT.search(str(o.get("texto", ""))) for o in opcoes):
            _relabel(questao)
            usos[posicao_atual] = usos.get(posicao_atual, 0) + 1
            continue

        menos = min(usos.get(i, 0) for i in range(len(opcoes)))
        alvo = rng.choice([i for i in range(len(opcoes)) if usos.get(i, 0) == menos])
        correta = opcoes[posicao_atual]
        outras = [o for i, o in enumerate(opcoes) if i != posicao_atual]
        rng.shuffle(outras)
        questao["opcoes"] = outras[:alvo] + [correta] + outras[alvo:]
        _relabel(questao)
        usos[alvo] = usos.get(alvo, 0) + 1


def _new_rng() -> random.Random:
    return random.Random()


def _avoid_block(
    ja_gerados: Sequence[Dict[str, Any]],
    *,
    tentativa_repetiu: bool = False,
) -> str:
    """O que o lote seguinte precisa saber para nao repetir o que ja saiu.

    Mandar so o enunciado nao bastava: com uma aula curta, o modelo relia a
    instrucao de cobrir os topicos principais e voltava as mesmas perguntas -
    varios provedores seguidos devolviam as quatro de antes. Aqui vao tambem a
    resposta e os conceitos ja usados, e um caminho para variar quando os
    conceitos acabam.

    Args:
        ja_gerados: perguntas aceitas ate agora.
        tentativa_repetiu: o provedor anterior deste mesmo lote so devolveu
            repeticao; o seguinte recebe isso escrito.
    """
    if not ja_gerados:
        return ""

    recentes = list(ja_gerados)[-MAX_AVOID_QUESTIONS:]
    linhas = []
    limite_com_resposta = len(recentes) - AVOID_WITH_ANSWER
    for posicao, questao in enumerate(recentes):
        recente = posicao >= limite_com_resposta
        resposta = _correct_option_text(questao) if recente else ""
        sufixo = f" (resposta: {_compact_text(resposta, limit=60)})" if resposta else ""
        limite = 160 if recente else 100
        linhas.append(
            f"- {_compact_text(questao.get('enunciado', ''), limit=limite)}{sufixo}"
        )

    conceitos: List[str] = []
    for questao in recentes:
        for item in [*(questao.get("conceitos") or []), questao.get("topico_origem")]:
            texto = str(item or "").strip()
            if texto and texto.lower() not in {c.lower() for c in conceitos}:
                conceitos.append(texto)

    bloco = [
        "\n**Perguntas já geradas — não repita, não reformule e não pergunte a "
        "mesma coisa com outras palavras:**",
        *linhas,
    ]
    if conceitos:
        bloco.append(
            "\n**Conceitos já cobertos:** "
            + ", ".join(conceitos[:MAX_AVOID_CONCEPTS])
        )
    bloco.append(
        "\n**Como variar:** cada questão nova precisa testar um conceito que ainda "
        "não foi cobrido ou um ângulo novo de um conceito já usado — aplicação "
        "prática, comparação entre dois conceitos, causa e consequência, exemplo "
        "concreto, identificação de erro ou ordem de etapas. Trocar sinônimos ou a "
        "ordem das palavras de uma pergunta existente não conta como pergunta nova."
    )
    if tentativa_repetiu:
        bloco.append(
            "\n**Atenção:** a tentativa anterior devolveu apenas perguntas que já "
            "existiam. Não use nenhum enunciado acima como ponto de partida."
        )
    return "\n".join(bloco) + "\n"


def _attempts_error(attempts: Sequence[Dict[str, Any]]) -> str:
    """Resume o que cada modelo respondeu quando nenhum gerou questao.

    Antes so o erro do ultimo candidato chegava a tela, e o ultimo da fila e
    justamente o provedor local - o professor lia "Servico local indisponivel"
    sem saber que o modelo de nuvem tinha falhado antes, e por qual motivo.
    """
    motivos: Dict[str, str] = {}
    for attempt in attempts:
        nome = str(attempt.get("llm") or "")
        if attempt.get("success") or not nome or nome in motivos:
            continue
        motivos[nome] = _compact_text(
            str(attempt.get("error") or "nao devolveu perguntas"), limit=160
        )
    if not motivos:
        return ""
    detalhes = "; ".join(f"{nome}: {motivo}" for nome, motivo in motivos.items())
    return f"Nenhum modelo gerou o quiz. {detalhes}"


#: Erros que nao mudam entre um lote e o seguinte: chave, permissao, modelo
#: inexistente ou credito acabado. Insistir so gasta os lotes que restam.
_PERMANENT_FAILURE_MARKS = (
    "credencial",
    "not found",
    "nao configurada",
    "não configurada",
    "is not supported",
    "unauthorized",
    "forbidden",
    "invalid api key",
    "invalid_api_key",
    "incorrect api key",
    "authentication",
    "quota",
    "insufficient",
    "billing",
    "credit",
    "401",
    "403",
    "404",
)


def _is_permanent_failure(error: str) -> bool:
    """Diz se repetir a chamada neste provedor daria o mesmo erro."""
    texto = (error or "").lower()
    return any(marca in texto for marca in _PERMANENT_FAILURE_MARKS)


def _drop_provider(candidatos: List[str], llm_name: str, error: str) -> None:
    """Tira da fila o provedor cujo erro nao vai mudar no proximo lote.

    Sem isso, um provedor com modelo retirado do ar era chamado de novo a cada
    lote, devolvia a mesma mensagem e queimava as tentativas que o provedor
    seguinte usaria para entregar as perguntas que faltavam.
    """
    if not _is_permanent_failure(error) or llm_name not in candidatos:
        return
    if len(candidatos) == 1:
        # Ultimo da fila fica: e melhor tentar de novo e falhar com a mensagem
        # dele do que terminar sem provedor algum e sem explicacao.
        return
    candidatos.remove(llm_name)
    logger.info(
        f"{llm_name} fora da fila do quiz: erro nao muda no proximo lote "
        f"({_compact_text(error, limit=120)})"
    )


# --- Fonte grande demais para o provedor ----------------------------------------
#
# O contexto da geracao leva ate 60 mil caracteres (~15 mil tokens). Provedor de
# plano gratuito ou de modelo pequeno recusa isso ("Request too large ... Limit
# 7000, Requested 14940"), e o erro nao e passageiro nem de credencial: o mesmo
# pedido falha sempre. Tirar o provedor da fila desperdicava justamente os modelos
# que cabem com a fonte menor; agora a fonte encolhe para ele e a chamada se repete.

#: Menos que isso de fonte nao sustenta pergunta ancorada; encolher alem disso
#: seria entregar pergunta inventada.
MIN_SOURCE_CHARS = 2_500

#: Folga sobre a razao devolvida pelo provedor: o limite conta tambem as
#: instrucoes do prompt e a resposta pedida, nao so a fonte.
SHRINK_SAFETY = 0.7

_TOO_LARGE_MARKS = (
    "request too large",
    "too large",
    "context length",
    "context_length",
    "maximum context",
    "prompt is too long",
    "reduce your message",
    "reduce the length",
)

_LIMIT_REQUESTED = re.compile(r"limit\s+(\d+)\s*,\s*requested\s+(\d+)", re.IGNORECASE)


def _size_ratio(error: str) -> Optional[float]:
    """Quanto da fonte cabe, a partir da recusa do provedor; `None` se nao e de tamanho.

    "Limit 7000, Requested 14940" diz a razao exata. Sem os numeros, a recusa por
    tamanho (`context length`, `too large`) pede metade. `Limit` maior que
    `Requested` e limite de taxa passageiro, nao de tamanho: encolher nao ajuda.
    """
    texto = error or ""
    achado = _LIMIT_REQUESTED.search(texto)
    if achado:
        limite, pedido = int(achado.group(1)), int(achado.group(2))
        return limite / pedido if pedido > limite else None
    lower = texto.lower()
    return 0.5 if any(marca in lower for marca in _TOO_LARGE_MARKS) else None


def _next_limit(current_chars: int, error: str) -> Optional[int]:
    """Novo teto de caracteres da fonte, ou `None` se nao da para encolher mais."""
    ratio = _size_ratio(error)
    if ratio is None:
        return None
    novo = int(current_chars * ratio * SHRINK_SAFETY)
    if novo < MIN_SOURCE_CHARS or novo >= current_chars:
        return None
    return novo


_SOURCE_BLOCK = re.compile(r"(?m)^(?==== )")


def _cut_at_boundary(text: str, limit: int) -> str:
    """Corta em fim de paragrafo ou de frase, nao no meio de uma palavra."""
    if len(text) <= limit:
        return text
    corte = text[:limit]
    for marca in ("\n\n", ". ", "\n", "; "):
        posicao = corte.rfind(marca)
        if posicao >= limit * 0.6:
            return corte[: posicao + len(marca.rstrip())].rstrip() + " …"
    return corte.rstrip() + " …"


def _shrink_source(resumo: str, max_chars: Optional[int]) -> str:
    """Encolhe a fonte repartindo o espaco entre as aulas e materiais.

    Cortar so o fim tiraria a ultima aula inteira. Cada bloco (`=== AULA: ...`)
    recebe sua parte; dentro de um bloco o resumo vem primeiro e a transcricao
    depois, entao e a transcricao que perde.
    """
    if not max_chars or len(resumo) <= max_chars:
        return resumo
    blocos = [bloco for bloco in _SOURCE_BLOCK.split(resumo) if bloco.strip()]
    if len(blocos) <= 1:
        return _cut_block(resumo, max_chars)
    parte = max(max_chars // len(blocos), 800)
    return "\n\n".join(_cut_block(bloco.rstrip(), parte) for bloco in blocos)


def _cut_block(bloco: str, limite: int) -> str:
    """Corta um bloco da fonte conforme o que ele e.

    Material (PDF, apostila) e amostrado do comeco ao fim: o inicio sozinho deixava
    o resto do documento sem pergunta. Aula corta pelo fim - o resumo validado vem
    primeiro e ja cobre a aula inteira, e a transcricao, que e a parte que cresce,
    e a que perde.
    """
    if bloco.lstrip().startswith("=== MATERIAL"):
        return sample_evenly(bloco, limite)
    return _cut_at_boundary(bloco, limite)


async def _dispatch_fitting(
    llm_name: str,
    resumo: str,
    make_prompt: Callable[[str], str],
    system: str,
    max_tokens: int,
    limits: Dict[str, int],
):
    """Chama o provedor com a fonte no tamanho que ele aguenta.

    Usa o teto ja aprendido para este provedor e, se ele recusar por tamanho,
    encolhe e repete uma vez. O teto fica em `limits` para os proximos lotes.
    Erro que nao e de tamanho segue para quem chamou.
    """
    resposta = None
    for _ in range(2):
        fonte = _shrink_source(resumo, limits.get(llm_name))
        try:
            resposta = await dispatch_single(
                llm_name, make_prompt(fonte), [], system, max_tokens=max_tokens
            )
        except Exception as erro:
            novo = _next_limit(len(fonte), str(erro))
            if novo is None:
                raise
            limits[llm_name] = novo
            logger.info(f"{llm_name} recusou por tamanho; fonte limitada a {novo} caracteres")
            continue
        if resposta.is_error:
            novo = _next_limit(len(fonte), resposta.content)
            if novo is not None:
                limits[llm_name] = novo
                logger.info(f"{llm_name} recusou por tamanho; fonte limitada a {novo} caracteres")
                continue
        return resposta
    return resposta


def _empty_batch_reason(
    content: str,
    questoes_lidas: Sequence[Dict[str, Any]],
    descartes: Optional[Dict[str, int]] = None,
) -> str:
    """Diz por que o lote nao rendeu pergunta nenhuma.

    Sao casos distintos com consequencias distintas: o modelo escreveu fora do
    JSON (prompt ou modelo inadequado), devolveu JSON valido mas so repetiu o que
    ja havia (pedir mais perguntas nao vai adiantar), devolveu perguntas sem
    alternativas suficientes (modelo fraco, e gerar de novo pode resolver) ou nao
    devolveu nada (resposta vazia ou cortada). Dizer "todas repetiam" para os
    dois casos do meio mandava o professor atras da causa errada.

    Args:
        descartes: `repetidas` e `invalidas` deste lote. Sem eles, vale o texto
            antigo, que so conhece o caso da repeticao.
    """
    texto = (content or "").strip()
    if not texto:
        return "Resposta vazia do modelo."
    if questoes_lidas:
        descartes = descartes or {}
        repetidas = descartes.get("repetidas", 0)
        invalidas = descartes.get("invalidas", 0)
        if invalidas and not repetidas:
            return (
                f"O modelo devolveu {len(questoes_lidas)} pergunta(s), mas nenhuma "
                "serve: faltaram alternativas diferentes entre si (precisa de ao "
                f"menos {MIN_DISTINCT_OPTIONS})."
            )
        if invalidas and repetidas:
            return (
                f"O modelo devolveu {len(questoes_lidas)} pergunta(s): {repetidas} "
                f"repetiam as já geradas e {invalidas} tinham alternativas "
                "insuficientes."
            )
        return (
            f"O modelo devolveu {len(questoes_lidas)} pergunta(s), mas todas "
            "repetiam as já geradas."
        )
    return f"Resposta sem JSON de perguntas: “{_compact_text(texto, limit=160)}”"


def _report_progress(state: QuizGraphState, prontas: int, total: int) -> None:
    callback = state.get("on_progress")
    if not callable(callback):
        return
    try:
        callback(prontas, total)
    except Exception as error:  # progresso e informativo: nao derruba a geracao
        logger.debug(f"Callback de progresso do quiz falhou: {error}")


def _plan_block(slots: Sequence[tuple]) -> str:
    """Os objetivos do plano que esta rodada precisa transformar em pergunta."""
    if not slots:
        return ""
    linhas = [
        f"{numero}. [{slot.get('topico') or '-'}] {slot['conceito']}"
        f" — ângulo: {slot.get('angulo') or 'livre'}"
        for numero, slot in slots
    ]
    return (
        "\n**Objetivos desta rodada — escreva exatamente uma pergunta para cada "
        "objetivo, na ordem, e copie o número do objetivo no campo `objetivo`. "
        "Cada pergunta testa só o conceito do seu objetivo:**\n"
        + "\n".join(linhas)
        + "\n"
    )


def _parse_plan(content: str, limite: int) -> List[Dict[str, Any]]:
    """Objetivos do plano, sem os que repetem outro objetivo."""
    data = _json_from_content(content)
    itens = data.get("objetivos") or data.get("plano") or data.get("objectives")
    if not isinstance(itens, list):
        return []

    slots: List[Dict[str, Any]] = []
    vistos: List[frozenset] = []
    for item in itens:
        if not isinstance(item, dict):
            continue
        conceito = " ".join(
            str(item.get("conceito") or item.get("objetivo") or "").split()
        )
        if not conceito:
            continue
        palavras = _key_words(conceito)
        if palavras and any(
            outras and len(palavras & outras) / len(palavras | outras) >= REPHRASE_SIMILARITY
            for outras in vistos
        ):
            continue
        vistos.append(palavras)
        slots.append({
            "topico": " ".join(str(item.get("topico") or "").split()),
            "conceito": conceito,
            "angulo": " ".join(str(item.get("angulo") or "").split()),
        })
        if len(slots) >= limite:
            break
    return slots


def _record_failure(
    attempts: Optional[List[Dict[str, Any]]],
    llm_name: str,
    error: str,
) -> None:
    """Registra a falha de um provedor uma vez so, para a tela mostrar o motivo.

    O plano tira da fila quem falha por credencial; sem este registro, a lista de
    tentativas que o professor le deixava de citar justamente os provedores que
    ja tinham falhado ali.
    """
    if attempts is None or any(
        item.get("llm") == llm_name and not item.get("success") and item.get("error") == error
        for item in attempts
    ):
        return
    attempts.append({
        "llm": llm_name,
        "success": False,
        "error": error,
        "question_count": 0,
    })


#: Quantos provedores o plano tenta antes de seguir sem plano. Cada tentativa e
#: uma chamada longa: quatro cobrem uma fila com um ou dois provedores mortos
#: sem fazer o professor esperar o plano por minutos.
MAX_PLAN_ATTEMPTS = 4


async def _plan_questions(
    state: QuizGraphState,
    quantidade: int,
    candidatos: List[str],
    limits: Optional[Dict[str, int]] = None,
    attempts: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Planeja conceitos e angulos distintos antes de escrever as perguntas.

    Falha aqui nao derruba o quiz: sem plano, a geracao segue como antes, so com a
    lista do que ja saiu para nao repetir. O plano pode vir menor que o pedido, e
    isso e informacao - o conteudo nao sustenta mais perguntas distintas.

    Percorre a fila inteira, e nao so os dois primeiros: os dois primeiros sao
    justamente os melhores ranqueados, e quando estao sem credito o plano nunca
    saia - e sem plano os modelos menores repetem a mesma pergunta. Quem falha por
    credencial sai da fila (a mesma lista que a geracao usa), e quem entrega o
    plano passa para a frente dela.
    """
    limits = limits if limits is not None else {}
    avoid = _avoid_block(list(state.get("previas") or []))

    def make_prompt(fonte: str) -> str:
        return PLAN_PROMPT.format(
            quantidade=quantidade,
            resumo=fonte,
            disciplina=state["disciplina"],
            tipo_quiz=state["tipo_quiz"],
            dificuldade=state["dificuldade"],
            evitar=avoid,
        )

    tentativas = 0
    # Copia: `_drop_provider` altera a fila original.
    for llm_name in list(candidatos):
        if tentativas >= MAX_PLAN_ATTEMPTS:
            break
        tentativas += 1
        try:
            response = await _dispatch_fitting(
                llm_name,
                state["resumo"],
                make_prompt,
                "Planeje as perguntas e responda somente com JSON válido.",
                _token_budget(max(quantidade // 3, 1)),
                limits,
            )
        except Exception as error:
            logger.warning(f"Plano do quiz falhou em {llm_name}: {error}")
            _record_failure(attempts, llm_name, str(error))
            _drop_provider(candidatos, llm_name, str(error))
            continue
        if response.is_error:
            logger.warning(f"Plano do quiz recusado por {llm_name}: {response.content}")
            _record_failure(attempts, llm_name, response.content)
            _drop_provider(candidatos, llm_name, response.content)
            continue
        slots = _parse_plan(response.content, quantidade)
        if slots:
            if candidatos and candidatos[0] != llm_name and llm_name in candidatos:
                candidatos[:] = [llm_name] + [n for n in candidatos if n != llm_name]
            return slots
        logger.warning(f"Plano do quiz sem objetivos aproveitaveis em {llm_name}")
    return []


def _oversample(pedido: int) -> int:
    """Quantas perguntas gerar para entregar `pedido` depois das perdas."""
    margem = min(max(round(pedido * OVERSAMPLE_RATIO), MIN_OVERSAMPLE), MAX_OVERSAMPLE)
    return pedido + margem


async def _generate_batch(
    state: QuizGraphState,
    quantidade: int,
    ja_gerados: List[Dict[str, Any]],
    candidatos: List[str],
    attempts: List[Dict[str, Any]],
    slots: Sequence[tuple] = (),
    limits: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Pede um lote de questoes, tentando cada modelo candidato em ordem.

    `slots` sao os objetivos do plano a cobrir neste lote, como pares
    `(numero, objetivo)`. Sem plano, o lote so recebe a lista do que ja saiu.
    """

    # O que ja existe de quizzes anteriores vem antes: o corte do bloco guarda as
    # mais recentes, e as deste quiz sao as que mais importa nao repetir.
    referencia = list(state.get("previas") or []) + list(ja_gerados)

    limits = limits if limits is not None else {}

    def prompt_for(fonte: str, tentativa_repetiu: bool) -> str:
        return QUIZ_GENERATION_PROMPT.format(
            quantidade_questoes=quantidade,
            resumo=fonte,
            disciplina=state["disciplina"],
            tipo_quiz=state["tipo_quiz"],
            tipos_questao=", ".join(state["tipos_questao"]),
            dificuldade=state["dificuldade"],
            plano=_plan_block(slots),
            evitar=_avoid_block(referencia, tentativa_repetiu=tentativa_repetiu),
            max_palavras=MAX_OPTION_WORDS,
            max_caracteres=MAX_OPTION_CHARS,
        )

    chaves = {_dedupe_key(questao.get("enunciado", "")) for questao in referencia}
    vistos = [_key_words(questao.get("enunciado", "")) for questao in referencia]
    fatos = [
        (_key_words(questao.get("enunciado", "")), _answer_key(questao))
        for questao in referencia
    ]
    descartes = {"repetidas": 0, "invalidas": 0}
    tentativa_repetiu = False
    erro = "A IA não gerou perguntas aproveitáveis."

    # Copia: `_drop_provider` altera a fila original, e tirar item de lista
    # sendo percorrida pularia o candidato seguinte.
    for llm_name in list(candidatos):
        try:
            response = await _dispatch_fitting(
                llm_name,
                state["resumo"],
                lambda fonte: prompt_for(fonte, tentativa_repetiu),
                "Responda somente com JSON válido para geração de quiz.",
                _token_budget(quantidade),
                limits,
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
            _drop_provider(candidatos, llm_name, str(e))
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
            _drop_provider(candidatos, llm_name, response.content)
            continue

        quiz_data = _json_from_content(response.content)
        questoes = _normalize_questions(quiz_data, state["tipos_questao"])

        # Contagem por tentativa: vale a da resposta que foi aceita, ou a ultima
        # quando nenhuma serve. Somar as de varios provedores contaria a mesma
        # repeticao mais de uma vez.
        descartes = {
            "repetidas": 0,
            "invalidas": max(_raw_count(quiz_data) - len(questoes), 0),
        }

        novas = []
        for questao in questoes:
            enunciado = questao.get("enunciado", "")
            if questao.get("tipo") == "multipla_escolha":
                # Alternativas iguais e letras desencontradas entram aqui, antes
                # de qualquer outra etapa usar a letra como chave.
                questao["opcoes"] = _dedupe_options(questao.get("opcoes") or [])
                _relabel(questao)
            if not _is_answerable(questao):
                descartes["invalidas"] += 1
                continue
            if _is_repeat(enunciado, vistos, chaves) or _is_same_fact(questao, fatos):
                descartes["repetidas"] += 1
                continue
            chaves.add(_dedupe_key(enunciado))
            vistos.append(_key_words(enunciado))
            fatos.append((_key_words(enunciado), _answer_key(questao)))
            novas.append(questao)
            if len(novas) >= quantidade:
                break

        if not novas:
            # Sem motivo aqui, a revisao mostrava "sem detalhe" e o professor
            # nao tinha como saber se o modelo falou fora do JSON, repetiu as
            # perguntas do lote anterior ou devolveu resposta vazia.
            erro = _empty_batch_reason(response.content, questoes, descartes)
            # O proximo provedor deste lote precisa saber que "nao repita" nao
            # bastou - senao recebe o mesmo prompt e tende ao mesmo resultado.
            # So quando houve repeticao: pergunta descartada por alternativas
            # insuficientes nao e repeticao, e o aviso mandaria o modelo variar o
            # que ja estava variado.
            tentativa_repetiu = tentativa_repetiu or descartes["repetidas"] > 0
            attempts.append({
                "llm": llm_name,
                "success": False,
                "error": erro,
                "question_count": 0,
            })
            logger.warning(f"Quiz generation returned no questions from {llm_name}")
            continue

        attempts.append({
            "llm": llm_name,
            "success": True,
            "question_count": len(novas),
        })

        return {
            "questoes": novas,
            "tempo_estimado": int(quiz_data.get("tempo_estimado") or 0),
            "llm": llm_name,
            "descartes": descartes,
        }

    return {
        "questoes": [],
        "tempo_estimado": 0,
        "llm": "",
        "error": erro,
        "descartes": descartes,
    }


def _raw_count(data: Dict[str, Any]) -> int:
    """Quantas questoes o modelo devolveu, antes de qualquer descarte."""
    brutas = (
        data.get("questoes")
        or data.get("perguntas")
        or data.get("questions")
        or data.get("items")
        or []
    )
    return len(brutas) if isinstance(brutas, list) else 0


def _baixar_objetivos(
    pendentes: List[tuple],
    oferecidos: Sequence[tuple],
    novas: Sequence[Dict[str, Any]],
) -> None:
    """Tira da fila os objetivos que o lote cobriu.

    O modelo devolve o numero do objetivo em cada pergunta. Quando ele nao
    devolve, vale a ordem: as primeiras perguntas cobrem os primeiros objetivos.
    """
    if not oferecidos:
        return
    ecoados = {
        questao.get("objetivo")
        for questao in novas
        if questao.get("objetivo") is not None
    }
    oferecidos_numeros = {numero for numero, _ in oferecidos}
    cobertos = (ecoados & oferecidos_numeros) or {
        numero for numero, _ in list(oferecidos)[: len(novas)]
    }
    pendentes[:] = [item for item in pendentes if item[0] not in cobertos]


def _desistir_de_objetivos(pendentes: List[tuple], ofertas: Dict[int, int]) -> None:
    """Abandona o objetivo que ja foi oferecido vezes demais sem render pergunta.

    O conteudo pode nao sustentar aquela pergunta; insistir nela travaria o
    lote seguinte numa pergunta impossivel.
    """
    pendentes[:] = [
        item for item in pendentes if ofertas.get(item[0], 0) < MAX_SLOT_OFFERS
    ]


async def _quiz_generate_node(state: QuizGraphState) -> Dict[str, Any]:
    """Nó que gera questões usando LLM, em lotes pequenos.

    Sem rede de template: o que sai daqui foi escrito pelo modelo. Lote vazio e
    tentado de novo, com o modelo candidato seguinte; se nem assim vier nada, o
    quiz falha dizendo o motivo, em vez de entregar frase recortada da aula com
    cara de pergunta.
    """

    total = max(int(state["quantidade_questoes"]), 1)
    candidatos = list(await _candidate_llms_for_quiz(state.get("requested_llm")))
    if not candidatos:
        return {
            "attempts": [],
            "outcome": {
                "error": (
                    "Nenhum provedor de IA configurado para gerar o quiz. "
                    "Cadastre uma chave de API ou o endereco de um modelo local."
                ),
                "questoes": [],
                "attempts": [],
            },
        }

    questoes: List[Dict[str, Any]] = []
    attempts: List[Dict[str, Any]] = []
    tempo_estimado = 0
    lotes_vazios = 0
    erro = "A IA não gerou perguntas aproveitáveis."
    previas = list(state.get("previas") or [])
    descartes = {
        "repetidas": 0,
        "invalidas": 0,
        # O que explica um quiz curto: pouca fonte e perguntas de quizzes
        # anteriores da mesma fonte, que as novas nao repetem.
        "conteudo_caracteres": len(state["resumo"]),
        "ja_existentes": len(previas),
    }
    # Teto de fonte aprendido por provedor (quem recusa por tamanho).
    limits: Dict[str, int] = {}

    # Gera alem do pedido: repeticao e reprovacao na validacao sao perdas
    # esperadas, e o corte para `total` vem no fim.
    alvo = _oversample(total)

    _report_progress(state, 0, total)

    # Plano antes das perguntas: cada uma nasce de um conceito e de um angulo
    # distintos. O plano pode vir menor que o pedido; sem plano, segue sem ele.
    plano = await _plan_questions(state, alvo, candidatos, limits, attempts)
    pendentes: List[tuple] = list(enumerate(plano, start=1))
    ofertas: Dict[int, int] = {}

    while len(questoes) < alvo:
        pedido = min(QUESTIONS_PER_BATCH, alvo - len(questoes))
        lote_slots = pendentes[:pedido]
        for numero, _ in lote_slots:
            ofertas[numero] = ofertas.get(numero, 0) + 1
        lote = await _generate_batch(
            state, pedido, questoes, candidatos, attempts, slots=lote_slots,
            limits=limits,
        )
        for chave, valor in (lote.get("descartes") or {}).items():
            descartes[chave] = descartes.get(chave, 0) + valor

        if not lote["questoes"]:
            erro = lote.get("error") or erro
            lotes_vazios += 1
            _desistir_de_objetivos(pendentes, ofertas)
            if lotes_vazios >= MAX_EMPTY_BATCHES:
                break
            continue

        lotes_vazios = 0
        # Quem entregou o lote comeca o proximo. Sem isso, um quiz de cinquenta
        # perguntas repete a chamada perdida no modelo que falhou, lote a lote.
        vencedor = lote.get("llm")
        if vencedor and candidatos and candidatos[0] != vencedor:
            candidatos[:] = [vencedor] + [
                nome for nome in candidatos if nome != vencedor
            ]

        _baixar_objetivos(pendentes, lote_slots, lote["questoes"])
        _desistir_de_objetivos(pendentes, ofertas)
        questoes.extend(lote["questoes"])
        tempo_estimado = max(tempo_estimado, lote["tempo_estimado"])
        _report_progress(state, min(len(questoes), total), total)

    # Quantos objetivos distintos o plano achou: se for menos que o pedido, o
    # conteudo nao sustenta mais perguntas diferentes - e e isso que o professor
    # precisa ouvir, em vez de so ver um numero menor.
    descartes["objetivos_planejados"] = len(plano)
    descartes["objetivos_pedidos"] = alvo

    if not questoes:
        # `attempts` tambem no topo do estado: e de la que `generate_quiz` le a
        # lista para a revisao mostrar qual modelo falhou e com que erro.
        return {
            "attempts": attempts,
            "outcome": {
                "error": _attempts_error(attempts) or erro,
                "questoes": [],
                "attempts": attempts,
            },
        }

    questoes = await _shorten_long_options(questoes, candidatos)
    # Por ultimo, depois de encurtar (que casa as alternativas pela letra): a
    # posicao da correta vira equilibrada no quiz inteiro, e as letras
    # sequenciais com o gabarito acompanhando.
    _balance_correct_positions(questoes, _new_rng())

    return {
        "questoes_brutas": questoes,
        "tempo_estimado": tempo_estimado or 15,
        "attempts": attempts,
        "descartes": descartes,
        # A fila ja sem os provedores mortos e com o que funcionou na frente: e
        # com ela que a validacao fala, e nao com o ranking de antes da geracao.
        "provedores": list(candidatos),
        "limites": limits,
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

    # Os provedores que funcionaram na geracao, o melhor primeiro. Perguntar ao
    # ranking de antes da geracao mandava a validacao ao primeiro da fila - o
    # mesmo que acabara de falhar por falta de credito -, e todo quiz saia com
    # "validacao automatica indisponivel".
    provedores = list(state.get("provedores") or []) or [await _resolve_llm_for_quiz()]
    limits: Dict[str, int] = dict(state.get("limites") or {})
    validacoes: List[Dict[str, Any]] = []
    falhas = 0

    # Em lotes pelo mesmo motivo da geracao: a validacao de vinte questoes de
    # uma vez volta cortada, e ai nenhuma questao fica marcada como verificada.
    for inicio in range(0, len(questoes_brutas), VALIDATION_BATCH):
        lote = questoes_brutas[inicio:inicio + VALIDATION_BATCH]
        questoes_json = json.dumps(lote, ensure_ascii=False, indent=2)

        dados: Optional[Dict[str, Any]] = None
        for llm_name in provedores[:MAX_VALIDATION_PROVIDERS]:
            try:
                response = await _dispatch_fitting(
                    llm_name,
                    state["resumo"],
                    lambda fonte: VALIDATION_PROMPT.format(
                        resumo=fonte, questoes_json=questoes_json
                    ),
                    "Valide as questões e responda somente com JSON válido.",
                    _token_budget(len(lote)),
                    limits,
                )
                if response.is_error:
                    raise RuntimeError(response.content)
                dados = _json_from_content(response.content)
                break
            except Exception as e:
                logger.warning(f"Validation error (non-blocking) em {llm_name}: {e}")
        if dados is None:
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

    # Reprovadas na validacao contam antes do corte: sao perda, nao sobra.
    descartes = dict(state.get("descartes") or {})
    descartes["reprovadas"] = len(questoes_brutas) - len(questoes_filtradas)

    # A geracao passou do pedido de proposito (folga para as perdas). Aqui
    # sobram as melhores: verificadas primeiro, depois maior grounding, mantida
    # a ordem do plano entre as que ficam.
    pedido = max(int(state.get("quantidade_questoes") or 1), 1)
    descartes["excedentes"] = max(len(questoes_filtradas) - pedido, 0)
    if len(questoes_filtradas) > pedido:
        ranking = sorted(
            range(len(questoes_filtradas)),
            key=lambda i: (
                not questoes_filtradas[i].get("verificado", True),
                -float(questoes_filtradas[i].get("grounding_score") or 0.0),
                i,
            ),
        )
        ficam = set(ranking[:pedido])
        questoes_filtradas = [
            questao for i, questao in enumerate(questoes_filtradas) if i in ficam
        ]

    return {
        "questoes_brutas": questoes_filtradas,
        "outcome": {
            "questoes": questoes_filtradas,
            "descartes": descartes,
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
    questoes_existentes: Optional[Sequence[Dict[str, Any]]] = None,
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
        questoes_existentes: questões de quizzes anteriores das mesmas fontes,
            para a IA não repeti-las

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
        "previas": list(questoes_existentes or []),
    })

    outcome = dict(result.get("outcome", {}))
    outcome["attempts"] = result.get("attempts", [])

    return outcome
