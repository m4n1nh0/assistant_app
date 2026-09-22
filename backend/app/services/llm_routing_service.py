"""Picks a default LLM for chat requests that don't specify one.

Priority: free/local providers first, then paid providers with confirmed
remaining credit, then paid providers with no balance signal. Providers
known to be out of credit never reach here (llm_status_service already
excludes them from "available").

Sobre a rota por tarefa: a regra de custo continua sendo a base. O tipo de
tarefa so entra para *rebaixar* provedores fracos em pedidos exigentes — mandar
uma tarefa de codigo para um modelo local de 3B economiza credito e devolve
resposta inutil, o que nao e economia.
"""

import re
import unicodedata

from .llm_status_service import get_llm_statuses

FREE_LOCAL_LLMS = {"llama", "localai"}

# Provedores que aguentam raciocinio longo, codigo e instrucao complexa.
STRONG_LLMS = {
    "claude",
    "gpt",
    "deepseek",
    "grok",
    "gemini",
    "together",
    "openrouter",
}

# Tarefas em que um modelo fraco costuma devolver resposta inaproveitavel.
DEMANDING_TASKS = {"code"}

# Pergunta que so se responde lendo o cadastro do Modo Aula. Exige mais do
# modelo do que parece: o tool-calling deste projeto e textual (o modelo escreve
# `{"tool": ..., "args": ...}` e nada mais), e depois ainda precisa responder a
# partir da tabela que voltou. Modelo pequeno erra os dois passos - responde em
# prosa sem chamar nada, ou chama e pede ao usuario o dado que acabou de ler.
#
# O recorte e de proposito mais estreito que a tarefa `study`: "resuma a ultima
# aula" o RAG resolve com qualquer modelo, e encarecer isso nao compraria
# qualidade nenhuma.
_REGISTRY_PATTERNS = (
    r"\bquiz\w*\b", r"\bquestao\b", r"\bquestoes\b", r"\bbanco\s+de\s+questoes\b",
    r"\balun\w+\b", r"\bturma\b", r"\bturmas\b", r"\bnota\b", r"\bnotas\b",
    r"\bgabarito\b", r"\bdesempenho\b", r"\branking\b", r"\bresultad\w+\b",
    r"\btempo\s+de\s+estudo\b", r"\bcadastrad\w+\b", r"\bmodo\s+aula\b",
)

TASK_KINDS = ("general", "code", "study", "calendar")

_CODE_PATTERNS = (
    r"\bcodig\w+", r"\bcod\w*\b", r"\bfuncao\b", r"\bfuncoes\b", r"\bclasse\b",
    r"\bbug\b", r"\berro\b", r"\bstack\s*trace\b", r"\bexception\b",
    r"\brefator\w+", r"\bimplement\w+", r"\bdebug\w*", r"\bcompil\w+",
    r"\btest\w*\s+unitari\w+", r"\bpython\b", r"\bjavascript\b", r"\btypescript\b",
    r"\bdart\b", r"\bflutter\b", r"\bsql\b", r"\bapi\b", r"\bendpoint\b",
    r"\bgit\b", r"\bdocker\b", r"\bscript\b", r"\brepositori\w+",
)

_STUDY_PATTERNS = (
    r"\baula\b", r"\baulas\b", r"\bprofessor\w*\b", r"\bmateria\b",
    r"\bdisciplina\b", r"\bexplic\w+\s+(?:sobre|que|o)\b", r"\bfalou\s+sobre\b",
    r"\bconteud\w+\b", r"\bprova\b", r"\bavaliacao\b", r"\bexercici\w+",
    r"\btrabalho\s+da\s+\w+", r"\banotac\w+", r"\bresumo\s+da\s+aula\b",
    r"\bna\s+ultima\s+aula\b", r"\bo\s+que\s+(?:foi|vimos|estudamos)\b",
    r"\bministr\w*\b", r"\bensin\w*\b",
    # A transcricao e a fonte do RAG de aula: quem a cita esta pedindo material
    # gravado, e nao pode cair na rota generica so por nao ter escrito "aula".
    r"\btranscric\w+", r"\bturma\b",
)

_CALENDAR_PATTERNS = (
    r"\bagenda\b", r"\breuniao\b", r"\breunioes\b", r"\bcompromiss\w+",
    r"\bevento\b", r"\bmarcar\b", r"\bagendar\b", r"\bhorari\w+",
)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _matches(text: str, patterns: tuple[str, ...]) -> int:
    return sum(1 for pattern in patterns if re.search(pattern, text))


def detect_task(message: str) -> str:
    """Classifica o pedido para orientar a escolha do provedor.

    Heuristica proposital em vez de LLM: classificar com modelo custaria uma
    chamada extra so para decidir quem responde, o que anula a economia que a
    rota deveria trazer.
    """
    text = _normalize(message)
    if not text.strip():
        return "general"

    scores = {
        "code": _matches(text, _CODE_PATTERNS),
        "study": _matches(text, _STUDY_PATTERNS),
        "calendar": _matches(text, _CALENDAR_PATTERNS),
    }
    best = max(scores, key=lambda key: scores[key])
    return best if scores[best] > 0 else "general"


#: Abaixo disto, o modelo costuma falhar no protocolo textual de ferramenta:
#: responde em prosa em vez de emitir a chamada, ou chama e depois pede ao
#: usuario o dado que acabou de receber. O corte e empirico e grosso de
#: proposito - ele so decide ordem de fila, nunca exclui ninguem.
MIN_TOOL_PARAMS_B = 30.0

#: Nomes que a industria usa para a versao reduzida de uma familia. Um
#: provedor forte com um destes configurado nao e um provedor forte para
#: chamada de ferramenta. As bordas nao sao decoracao: sem elas, "gemini"
#: contem "mini" e o Gemini inteiro seria rebaixado por um acidente de grafia.
_SMALL_MODEL_MARKERS = re.compile(
    r"(?<![a-z0-9])(mini|nano|tiny|small|lite)(?![a-z0-9])"
)

#: "qwen3-8b", "llama-3.3-70b-instruct", "gemma2-9b-it". O `(?![a-z0-9])` evita
#: casar o "b" que abre outra palavra, como em "8bit".
_PARAM_SIZE = re.compile(r"(\d+(?:[.,]\d+)?)\s*b(?![a-z0-9])")


def configured_model(provider: str) -> str:
    """O modelo que este provedor vai usar agora, ou vazio quando automatico.

    Le do contexto do usuario ativo, e nao das variaveis globais: cada professor
    configura o proprio modelo por provedor.
    """
    from .user_llm_config_service import model_for

    try:
        return model_for(provider)
    except Exception:
        # Configuracao ilegivel nao pode derrubar a escolha de provedor: sem
        # nome, o julgamento volta a ser o do provedor.
        return ""


def model_handles_tools(model: str) -> bool | None:
    """Diz se o modelo aguenta o ciclo de ferramenta, pelo nome.

    Args:
        model: identificador configurado, como `qwen/qwen3-8b`.

    Returns:
        `True` para modelo grande o bastante, `False` para modelo reduzido, e
        **`None` quando nao da para saber** - nome vazio (modelo automatico) ou
        familia fechada que nao publica tamanho, como `claude-sonnet-4-5`.
        `None` nao e um palpite disfarcado de resposta: quem chama volta a
        julgar pelo provedor, que e o que se sabe de fato.
    """
    name = _normalize(model).strip()
    if not name:
        return None

    if _SMALL_MODEL_MARKERS.search(name):
        return False

    sizes = [
        float(match.group(1).replace(",", "."))
        for match in _PARAM_SIZE.finditer(name)
    ]
    if not sizes:
        return None
    return max(sizes) >= MIN_TOOL_PARAMS_B


def needs_registry_read(message: str) -> bool:
    """Diz se a pergunta depende de ler o cadastro do Modo Aula.

    Serve a uma decisao so: se o turno vai exigir chamada de ferramenta, ele
    nao deveria cair num modelo que nao sabe emitir a chamada.

    Args:
        message: a pergunta do usuario, como ela chegou.

    Returns:
        `True` quando a mensagem fala de quiz, questao, aluno, turma, nota,
        resultado ou tempo de estudo.
    """
    return _matches(_normalize(message), _REGISTRY_PATTERNS) > 0


def _tier(provider: str, balance_ok: bool | None) -> int:
    if provider in FREE_LOCAL_LLMS:
        return 0
    if balance_ok is True:
        return 1
    if balance_ok is None:
        return 2
    return 3


def _task_tier(
    provider: str,
    balance_ok: bool | None,
    task: str,
    demanding: bool = False,
) -> int:
    base = _tier(provider, balance_ok)
    exigente = demanding or task in DEMANDING_TASKS
    if not exigente:
        return base

    # O provedor e o que se sabe sem olhar a configuracao; o modelo, quando
    # nomeado, sabe mais. `grok` esta em STRONG_LLMS, mas apontando para um 8B
    # nao aguenta o ciclo de ferramenta - e `hf` fora da lista, com um 70B,
    # aguenta. Modelo automatico nao inventa veredito: cai de volta no provedor.
    verdict = model_handles_tools(configured_model(provider))
    forte = provider in STRONG_LLMS if verdict is None else verdict
    if not forte:
        # Rebaixa, mas nao elimina: se o local for a unica opcao, ele responde.
        return base + 10
    return base


async def pick_auto_llm(candidates: list[str], task: str = "general") -> str:
    """Escolhe o provedor padrao entre os candidatos.

    Args:
        candidates: provedores disponiveis no momento.
        task: tipo de tarefa devolvido por `detect_task`.

    Returns:
        A chave do provedor escolhido.
    """
    ranked = await rank_auto_llms(candidates, task)
    return ranked[0] if ranked else ""


async def rank_auto_llms(
    candidates: list[str],
    task: str = "general",
    *,
    available_only: bool = False,
    demanding: bool = False,
) -> list[str]:
    """Ordena provedores por custo/capacidade preservando desempates.

    O chat precisa manter o comportamento historico e pode pedir que um
    provedor configurado explique a propria indisponibilidade. Workflows com
    fallback, por outro lado, usam ``available_only`` para nao gastar uma
    tentativa com um provedor que o health check ja marcou como offline.

    ``demanding`` aplica a mesma degradacao de `DEMANDING_TASKS` a um turno
    especifico, e nao a tarefa inteira: e como uma pergunta sobre o cadastro
    entra na fila dos provedores fortes sem arrastar junto todo pedido de aula.
    """
    if not candidates:
        return []
    statuses = await get_llm_statuses()
    pool = [
        provider
        for provider in candidates
        if not available_only
        or (provider in statuses and statuses[provider].available)
    ]
    return sorted(
        pool,
        key=lambda provider: (
            _task_tier(
                provider,
                statuses[provider].balance_ok if provider in statuses else None,
                task,
                demanding,
            ),
            candidates.index(provider),
        ),
    )


async def pick_for_message(candidates: list[str], message: str) -> tuple[str, str]:
    """Detecta a tarefa e devolve (provedor, tarefa) numa chamada so."""
    task = detect_task(message)
    return await pick_auto_llm(candidates, task), task
