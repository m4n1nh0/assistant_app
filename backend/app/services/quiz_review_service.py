"""Revisao das perguntas do quiz por agentes especialistas (Codex e Claude).

Codex e Claude Code rodam no computador do professor, nao no servidor: o app pede
o prompt aqui, executa cada agente no CLI dele e devolve o texto bruto. O servidor
faz o resto - le o JSON, confere com o gabarito e decide o veredito.

O desenho evita o vicio mais comum de revisao por IA, o de concordar com o que
ja esta escrito. O agente **nao recebe o gabarito**: resolve cada pergunta so com
o texto da aula e responde qual alternativa e a correta. Quem compara com a
chave gravada e o servidor. Pergunta que dois modelos independentes resolvem do
mesmo jeito que o gerador tem muito mais chance de estar certa do que a que um
modelo apenas "aprovou" depois de ver a resposta.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from .quiz_generator_service import json_from_content

#: Agentes que o app sabe executar na maquina do professor.
REVIEW_AGENTS = {
    "codex_cli": "Codex",
    "claude_cli": "Claude",
}

STATUS_APPROVED = "aprovada"
STATUS_DIVERGENT = "divergente"
STATUS_REVIEW = "revisar"
STATUS_NO_KEY = "sem_gabarito"

REVIEW_SYSTEM_PROMPT = (
    "Você é um professor especialista revisando perguntas de múltipla escolha "
    "antes de elas serem aplicadas a uma turma. Responda somente com JSON válido."
)

REVIEW_PROMPT = """Revise as perguntas de quiz abaixo usando SOMENTE o conteúdo da aula.

**Conteúdo da aula (fonte das perguntas):**
{fonte}

**Perguntas (o gabarito foi omitido de propósito):**
{perguntas_json}

Para cada pergunta, faça nesta ordem:
1. Resolva a pergunta sozinho, como um aluno atento que estudou o conteúdo acima,
   e informe a letra da alternativa correta em "resposta". Se nenhuma estiver
   correta, ou mais de uma puder ser defendida, deixe "resposta" vazio.
2. Diga em "ancorada" se o conteúdo da aula sustenta essa resposta (true/false).{ancorada_aviso}
3. Liste em "problemas" apenas defeitos reais: erro factual, duas alternativas
   corretas, nenhuma correta, enunciado ambíguo, alternativa que entrega a
   resposta, ou conteúdo que a aula não ensinou. Lista vazia quando está tudo bem
   — não liste detalhes de estilo.
4. Só se a pergunta tiver defeito que uma correção mínima resolve, preencha
   "sugestao" com a pergunta corrigida por inteiro; senão use null. Mantenha as
   alternativas curtas (até 8 palavras) e informe "resposta_correta" com a letra.

Responda somente com JSON válido, sem markdown e sem comentários fora do JSON:
{{
  "revisoes": [
    {{
      "id": "o id da pergunta, copiado",
      "resposta": "B",
      "ancorada": true,
      "confianca": 0.9,
      "problemas": [],
      "sugestao": null
    }}
  ]
}}
"""

_NO_SOURCE_NOTE = (
    "\n   (Nenhum texto de aula está disponível: não avalie `ancorada`, use null.)"
)


def agent_label(agent_id: str) -> str:
    return REVIEW_AGENTS.get(agent_id, agent_id)


def build_review_prompt(
    *,
    source_text: str,
    questions: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Monta o prompt de revisao, sem o gabarito.

    `questions` traz `id`, `enunciado` e `opcoes` (cada uma com `label` e
    `texto`). O campo `correta` e removido aqui, e nao no chamador: a garantia de
    que o agente nao ve o gabarito precisa viver num lugar so.
    """
    cegas = [
        {
            "id": str(question["id"]),
            "enunciado": question.get("enunciado", ""),
            "opcoes": [
                {"label": opcao.get("label"), "texto": opcao.get("texto")}
                for opcao in question.get("opcoes") or []
                if isinstance(opcao, dict)
            ],
        }
        for question in questions
    ]
    fonte = (source_text or "").strip()
    prompt = REVIEW_PROMPT.format(
        fonte=fonte or "(sem texto de aula disponível)",
        perguntas_json=json.dumps(cegas, ensure_ascii=False, indent=2),
        ancorada_aviso="" if fonte else _NO_SOURCE_NOTE,
    )
    return {
        "system_prompt": REVIEW_SYSTEM_PROMPT,
        "prompt": prompt,
        "question_ids": [item["id"] for item in cegas],
        "has_source": bool(fonte),
    }


def _clean_suggestion(raw: Any) -> Optional[Dict[str, Any]]:
    """Aceita a sugestao so se ela se sustenta como pergunta respondivel."""
    if not isinstance(raw, dict):
        return None
    enunciado = str(raw.get("enunciado") or "").strip()
    opcoes_brutas = raw.get("opcoes")
    if not enunciado or not isinstance(opcoes_brutas, list):
        return None

    opcoes = []
    for indice, item in enumerate(opcoes_brutas):
        if not isinstance(item, dict):
            continue
        texto = str(item.get("texto") or "").strip()
        if not texto:
            continue
        label = str(item.get("label") or chr(ord("A") + indice)).strip().upper()
        opcoes.append({"label": label, "texto": texto})
    if len(opcoes) < 2:
        return None

    correta = str(raw.get("resposta_correta") or "").strip().upper()
    if correta not in {opcao["label"] for opcao in opcoes}:
        # Sugestao sem gabarito resolvido nao pode ser aplicada: o professor
        # teria de adivinhar qual alternativa vale.
        return None

    return {
        "enunciado": enunciado,
        "opcoes": [{**opcao, "correta": opcao["label"] == correta} for opcao in opcoes],
        "resposta_correta": correta,
        "justificativa": str(raw.get("justificativa") or "").strip(),
    }


def _confidence(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(min(max(number, 0.0), 1.0), 2)


def parse_agent_review(
    content: str,
    question_ids: Sequence[str],
) -> Dict[str, Dict[str, Any]]:
    """Le a resposta bruta do agente e devolve a leitura por id de pergunta.

    O `id` ecoado e o que casa a leitura com a pergunta; o `indice`, quando o
    agente erra o id, so vale dentro do tamanho da lista. Pergunta que o agente
    nao comentou fica de fora - e o veredito dela continua dependendo de quem
    comentou.
    """
    data = json_from_content(content or "")
    itens = data.get("revisoes") or data.get("reviews") or data.get("validacoes")
    if not isinstance(itens, list):
        return {}

    validos = set(question_ids)
    leituras: Dict[str, Dict[str, Any]] = {}
    for posicao, item in enumerate(itens):
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("id") or "").strip()
        if question_id not in validos:
            try:
                indice = int(item.get("indice", posicao))
            except (TypeError, ValueError):
                indice = posicao
            if not 0 <= indice < len(question_ids):
                continue
            question_id = question_ids[indice]

        ancorada = item.get("ancorada")
        problemas = item.get("problemas")
        leituras[question_id] = {
            "resposta": str(item.get("resposta") or "").strip().upper()[:4],
            "ancorada": ancorada if isinstance(ancorada, bool) else None,
            "confianca": _confidence(item.get("confianca")),
            "problemas": [
                str(problema).strip()[:300]
                for problema in (problemas if isinstance(problemas, list) else [])
                if str(problema).strip()
            ][:6],
            "sugestao": _clean_suggestion(item.get("sugestao")),
        }
    return leituras


def stored_key(question: Dict[str, Any]) -> str:
    """Letra da alternativa que o gerador marcou como correta, ou vazio."""
    for opcao in question.get("opcoes") or []:
        if isinstance(opcao, dict) and opcao.get("correta") is True:
            return str(opcao.get("label") or "").strip().upper()
    return ""


def assess(
    key: str,
    agentes: Dict[str, Dict[str, Any]],
) -> str:
    """Veredito consolidado de uma pergunta, dadas as leituras dos agentes.

    - `aprovada`: todo agente que revisou resolveu a pergunta com a letra do
      gabarito, achou a resposta ancorada na aula e nao apontou defeito.
    - `divergente`: algum agente chegou a outra resposta. E o sinal mais forte
      de gabarito errado e nunca e resolvido em silencio.
    - `revisar`: o gabarito bate, mas o agente apontou defeito ou disse que a
      aula nao sustenta a resposta.
    - `sem_gabarito`: o gerador nao deixou uma alternativa correta unica; o
      agente so pode sugerir.
    """
    if not agentes:
        return ""
    if not key:
        return STATUS_NO_KEY
    if any(leitura.get("resposta") != key for leitura in agentes.values()):
        return STATUS_DIVERGENT
    if any(
        leitura.get("ancorada") is False or leitura.get("problemas")
        for leitura in agentes.values()
    ):
        return STATUS_REVIEW
    return STATUS_APPROVED


def merge_review(
    previous: Optional[Dict[str, Any]],
    *,
    agent_id: str,
    reading: Dict[str, Any],
    key: str,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Soma a leitura de um agente as dos que ja revisaram esta pergunta.

    Rodar o Codex hoje e o Claude amanha acumula, em vez de o segundo apagar o
    primeiro: o veredito sai de todos os agentes que ja leram a pergunta.
    """
    agentes: Dict[str, Dict[str, Any]] = dict((previous or {}).get("agentes") or {})
    agentes[agent_id] = {
        **reading,
        "em": (now or datetime.now(timezone.utc)).isoformat(),
    }
    return {
        "status": assess(key, agentes),
        "agentes": agentes,
    }


def dump_review(review: Dict[str, Any]) -> str:
    return json.dumps(review, ensure_ascii=False)


def load_review(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


def summarize(reviews: Sequence[Optional[Dict[str, Any]]]) -> Dict[str, int]:
    """Quantas perguntas caiu em cada veredito, para a mensagem ao professor."""
    contagem: Dict[str, int] = {}
    for review in reviews:
        status = (review or {}).get("status") or ""
        if status:
            contagem[status] = contagem.get(status, 0) + 1
    return contagem


def verified_flag(status: str) -> Optional[bool]:
    """O que o veredito diz sobre `verificado`; `None` deixa como esta."""
    if not status:
        return None
    return status == STATUS_APPROVED
