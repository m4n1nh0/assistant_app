"""Relatorio de desempenho de um quiz, por aluno e por pergunta.

Os dados ja existem (respostas, participantes, pontos); o que faltava era junta-los
no que o professor precisa depois da aula: quem foi bem, quem precisa de apoio, e
quais perguntas a turma errou - que e tambem o retrato do que a aula nao passou.

A funcao e pura: recebe linhas ja lidas do banco e devolve um dicionario, o que
permite testar as regras de contagem sem banco nem rota.

Decisoes de contagem que o professor ve nos numeros:

- **So conta pergunta que foi aplicada.** Quiz encerrado antes do fim tem perguntas
  que a turma nunca viu; contar essas como "nao respondida" derrubaria o percentual
  de todo mundo. Aplicada e a que recebeu ao menos uma resposta ou esta no ar.
- **Quem entrou e nao respondeu aparece**, com zero. O ranking ao vivo so conhece
  quem respondeu; o relatorio e a unica conta que fecha com a lista de presentes.
- **O aluno e a tentativa (o navegador dele), nao uma pessoa.** O aluno digita o
  nome na entrada; dois navegadores com o mesmo nome sao duas linhas, porque
  juntar nomes iguais misturaria pessoas diferentes. A chamada e a lista da
  turma e que identificam gente de verdade.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Sequence

#: Abaixo disso (percentual de acerto) a pergunta entra em "atencao": a turma errou
#: mais do que acertou, e isso costuma apontar o que a aula nao passou.
LOW_QUESTION_RATE = 50.0

#: Abaixo disso o aluno entra em "precisa de apoio".
LOW_STUDENT_RATE = 50.0

#: Pergunta respondida por menos gente que isso nao serve de sinal: dois erros em
#: dois alunos nao dizem nada sobre a turma.
MIN_ANSWERS_FOR_SIGNAL = 3

#: Quantos itens cada lista de atencao mostra.
ATTENTION_LIMIT = 8


def _options(question: Any) -> List[Dict[str, Any]]:
    if getattr(question, "tipo", "") != "multipla_escolha" or not question.opcoes:
        return []
    try:
        decoded = json.loads(question.opcoes)
    except (TypeError, ValueError):
        return []
    return [item for item in decoded if isinstance(item, dict)] if isinstance(decoded, list) else []


def _correct_label(question: Any, options: Sequence[Dict[str, Any]]) -> str:
    for option in options:
        if option.get("correta") is True:
            return str(option.get("label", "")).strip()
    return str(getattr(question, "resposta_correta", "") or "").strip()


def _pct(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def _mean(values: Iterable[Optional[float]]) -> Optional[int]:
    numbers = [value for value in values if value is not None]
    return int(round(sum(numbers) / len(numbers))) if numbers else None


def build_report(
    *,
    quiz: Any,
    questions: Sequence[Any],
    participants: Sequence[Any],
    answers: Sequence[Any],
    disciplines: Sequence[str] = (),
    sources: Sequence[str] = (),
) -> Dict[str, Any]:
    """Monta o relatorio.

    Args:
        quiz: o `QuizModel` (usa `id`, `titulo`, `status`, `current_question_id`...).
        questions: perguntas do quiz, na ordem em que a turma as ve.
        participants: quem entrou (`QuizParticipantModel`).
        answers: respostas gravadas (`StudentAnswerModel`).
    """
    ordered = list(questions)
    by_question: Dict[str, List[Any]] = {}
    by_student: Dict[str, List[Any]] = {}
    for answer in answers:
        by_question.setdefault(answer.question_id, []).append(answer)
        by_student.setdefault(answer.student_id or "anon", []).append(answer)

    phase = getattr(quiz, "live_phase", "") or ""
    current_id = getattr(quiz, "current_question_id", None)
    applied_ids = {
        question.id
        for question in ordered
        if by_question.get(question.id)
        or (question.id == current_id and phase in {"question", "results"})
    }
    applied = [question for question in ordered if question.id in applied_ids]
    applied_total = len(applied)

    # --- quem participou ----------------------------------------------------
    names: Dict[str, str] = {}
    for participant in participants:
        names[participant.attempt_id] = participant.student_name or "Aluno"
    for student_id, rows in by_student.items():
        label = next((row.student_name for row in rows if row.student_name), "")
        names.setdefault(student_id, label or "Aluno")
        if label:
            names[student_id] = label

    students: List[Dict[str, Any]] = []
    for student_id, name in names.items():
        mine = {row.question_id: row for row in by_student.get(student_id, [])}
        per_question = []
        hits = misses = skipped = missing = 0
        for question in applied:
            row = mine.get(question.id)
            index = ordered.index(question)
            if row is None:
                missing += 1
                status = "sem_resposta"
            elif row.correta is True:
                hits += 1
                status = "acertou"
            elif row.correta is False:
                misses += 1
                status = "errou"
            else:
                skipped += 1
                status = "pulou"
            per_question.append({
                "question_id": question.id,
                "indice": index,
                "resposta": (row.resposta or "") if row is not None else "",
                "correta": row.correta if row is not None else None,
                "pontos": int(row.pontuacao or 0) if row is not None else 0,
                "tempo_ms": row.tempo_resposta if row is not None else None,
                "status": status,
            })
        points = sum(item["pontos"] for item in per_question)
        answered = hits + misses + skipped
        students.append({
            "student_id": student_id,
            "nome": name,
            "pontos": points,
            "acertos": hits,
            "erros": misses,
            "puladas": skipped,
            "sem_resposta": missing,
            "respondidas": answered,
            "percentual": _pct(hits, applied_total),
            "tempo_medio_ms": _mean(item["tempo_ms"] for item in per_question),
            "por_pergunta": per_question,
        })

    # Mesma ordem do ranking ao vivo (pontos, acertos, nome). Entre quem empata
    # em tudo, quem respondeu vem antes de quem so entrou.
    students.sort(key=lambda s: (-s["pontos"], -s["acertos"], -s["respondidas"], s["nome"].lower()))
    for position, student in enumerate(students, start=1):
        student["posicao"] = position

    # --- perguntas ------------------------------------------------------------
    joined = len(students)
    question_rows: List[Dict[str, Any]] = []
    for index, question in enumerate(ordered):
        rows = by_question.get(question.id, [])
        options = _options(question)
        correct = _correct_label(question, options)
        hits = sum(1 for row in rows if row.correta is True)
        misses = sum(1 for row in rows if row.correta is False)
        skipped = sum(1 for row in rows if row.correta is None)
        was_applied = question.id in applied_ids

        distribution = []
        for option in options:
            label = str(option.get("label", "")).strip()
            chosen = sum(1 for row in rows if (row.resposta or "").strip() == label)
            distribution.append({
                "label": label,
                "texto": str(option.get("texto", "")),
                "quantidade": chosen,
                "correta": option.get("correta") is True,
            })
        wrong = [item for item in distribution if not item["correta"] and item["quantidade"] > 0]
        most_wrong = max(wrong, key=lambda item: item["quantidade"]) if wrong else None

        question_rows.append({
            "question_id": question.id,
            "indice": index,
            "aplicada": was_applied,
            "enunciado": question.enunciado,
            "tipo": question.tipo,
            "dificuldade": question.dificuldade,
            "correta": correct,
            "respostas": len(rows),
            "acertos": hits,
            "erros": misses,
            "puladas": skipped,
            "sem_resposta": max(joined - len(rows), 0) if was_applied else 0,
            "percentual": _pct(hits, hits + misses),
            "tempo_medio_ms": _mean(row.tempo_resposta for row in rows),
            "distribuicao": distribution,
            "mais_escolhida_errada": most_wrong,
        })

    # --- resumo e pontos de atencao --------------------------------------------
    total_hits = sum(s["acertos"] for s in students)
    total_misses = sum(s["erros"] for s in students)
    total_skipped = sum(s["puladas"] for s in students)
    responded = [s for s in students if s["respondidas"] > 0]

    weak_questions = sorted(
        (
            row for row in question_rows
            if row["aplicada"]
            and row["respostas"] >= MIN_ANSWERS_FOR_SIGNAL
            and row["percentual"] < LOW_QUESTION_RATE
        ),
        key=lambda row: row["percentual"],
    )[:ATTENTION_LIMIT]

    needs_support = [
        s["nome"] for s in sorted(responded, key=lambda s: s["percentual"])
        if applied_total and s["percentual"] < LOW_STUDENT_RATE
    ][:ATTENTION_LIMIT]

    return {
        "quiz": {
            "id": quiz.id,
            "titulo": quiz.titulo,
            "tipo_quiz": getattr(quiz, "tipo_quiz", None),
            "status": getattr(quiz, "status", None) or "open",
            "total_questoes": len(ordered),
            "perguntas_aplicadas": applied_total,
            "criado_em": quiz.created_at.isoformat() if getattr(quiz, "created_at", None) else None,
            "encerrado_em": quiz.closed_at.isoformat() if getattr(quiz, "closed_at", None) else None,
            "disciplinas": list(disciplines),
            "fontes": list(sources),
        },
        "resumo": {
            "participantes": joined,
            "responderam": len(responded),
            "sem_resposta_nenhuma": joined - len(responded),
            "respostas": len(answers),
            "acertos": total_hits,
            "erros": total_misses,
            "puladas": total_skipped,
            "taxa_acerto": _pct(total_hits, total_hits + total_misses),
            "pontos_medios": int(round(sum(s["pontos"] for s in students) / joined)) if joined else 0,
            "tempo_medio_ms": _mean(
                row.tempo_resposta for row in answers
            ),
        },
        "alunos": students,
        "perguntas": question_rows,
        "atencao": {
            "perguntas": [
                {
                    "indice": row["indice"],
                    "enunciado": row["enunciado"],
                    "percentual": row["percentual"],
                    "respostas": row["respostas"],
                    "mais_escolhida_errada": row["mais_escolhida_errada"],
                }
                for row in weak_questions
            ],
            "alunos_com_dificuldade": needs_support,
            "alunos_sem_resposta": [s["nome"] for s in students if s["respondidas"] == 0][:ATTENTION_LIMIT * 2],
        },
    }
