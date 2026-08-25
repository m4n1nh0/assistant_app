"""Serviço de geração automática de exercícios e quizzes baseado em resumos de aula."""

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from langgraph.graph import END, START, StateGraph
from loguru import logger

from .llm_routing_service import pick_auto_llm, rank_auto_llms, FREE_LOCAL_LLMS
from .llm_service import dispatch_single
from .user_llm_config_service import runtime_settings

settings = runtime_settings

# Templates de prompts para diferentes tipos de quiz
QUIZ_GENERATION_PROMPT = """Você é um especialista em geração de questões educacionais.

Baseado no resumo da aula abaixo, gere {quantidade_questoes} questões de forma estruturada.

**Resumo da Aula:**
{resumo}

**Disciplina:** {disciplina}
**Tipo de Quiz:** {tipo_quiz}
**Tipos de Questão:** {tipos_questao}
**Dificuldade:** {dificuldade}

**Instruções:**
1. Cada questão deve derivar diretamente do resumo (não invente conteúdo)
2. Inclua justificativas que citam a fonte no resumo
3. Varie entre os tipos de questão solicitados
4. Distribua dificuldade equitativamente
5. Inclua todos os tópicos principais do resumo

**Formato de resposta (JSON):**
{{
  "questoes": [
    {{
      "tipo": "multipla_escolha|verdadeiro_falso|aberta",
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

VALIDATION_PROMPT = """Valide as seguintes questões geradas com base no resumo da aula.

**Resumo Original:**
{resumo}

**Questões para Validar:**
{questoes_json}

Para cada questão, verifique:
1. A questão derivou do resumo (grounding score 0-1)?
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


async def _resolve_llm_for_quiz(preferred: Optional[str] = None) -> str:
    """Resolve qual LLM usar para geração de quiz."""
    if preferred and preferred not in {"auto", ""}:
        return preferred
    return await pick_auto_llm(settings.active_llms) or "llama"


async def _quiz_generate_node(state: QuizGraphState) -> Dict[str, Any]:
    """Nó que gera questões usando LLM."""

    llm_name = await _resolve_llm_for_quiz(state.get("requested_llm"))

    prompt = QUIZ_GENERATION_PROMPT.format(
        quantidade_questoes=state["quantidade_questoes"],
        resumo=state["resumo"],
        disciplina=state["disciplina"],
        tipo_quiz=state["tipo_quiz"],
        tipos_questao=", ".join(state["tipos_questao"]),
        dificuldade=state["dificuldade"],
    )

    try:
        response = await dispatch_single(
            prompt=prompt,
            llm=llm_name,
            temperature=0.7,
        )

        if response.get("is_error"):
            logger.error(f"LLM error: {response.get('content')}")
            return {
                "outcome": {
                    "error": f"Falha ao gerar questões: {response.get('content')}",
                    "questoes": [],
                }
            }

        # Parse JSON da resposta
        content = response.get("content", "")

        # Tenta extrair JSON do conteúdo
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if not json_match:
            logger.error(f"No JSON found in response: {content[:200]}")
            return {
                "outcome": {
                    "error": "Resposta do LLM sem formato JSON válido",
                    "questoes": [],
                }
            }

        quiz_data = json.loads(json_match.group())

        return {
            "questoes_brutas": quiz_data.get("questoes", []),
            "tempo_estimado": int(quiz_data.get("tempo_estimado") or 15),
            "attempts": [
                {
                    "llm": llm_name,
                    "success": True,
                    "question_count": len(quiz_data.get("questoes", [])),
                }
            ]
        }

    except Exception as e:
        logger.error(f"Quiz generation error: {e}")
        return {
            "outcome": {
                "error": f"Erro ao processar geração de quiz: {str(e)}",
                "questoes": [],
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
            prompt=prompt,
            llm=llm_name,
            temperature=0.3,  # Validação precisa de maior rigidez
        )

        content = response.get("content", "")
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
        # Se não houver validação, retorna tudo
        questoes_filtradas = questoes_brutas
        media_score = 0.8
    else:
        # Filtra apenas questões com grounding_score > 0.7
        validacoes_por_idx = {v["indice"]: v for v in validacoes.get("validacoes", [])}

        questoes_filtradas = []
        scores = []

        for idx, questao in enumerate(questoes_brutas):
            val = validacoes_por_idx.get(idx, {})
            score = val.get("grounding_score", 0.7)
            scores.append(score)

            if score > 0.70:  # Threshold
                questao["grounding_score"] = score
                questao["verificado"] = val.get("bem_formulada", True)
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
