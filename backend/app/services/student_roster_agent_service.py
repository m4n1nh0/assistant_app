"""Interpretação assistida de listas de alunos que o parser não resolveu."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from . import langchain_agent_service
from .llm_routing_service import pick_auto_llm


SYSTEM_PROMPT = """Você interpreta listas acadêmicas para uma prévia revisável.
Responda SOMENTE com JSON válido, sem markdown, neste formato:
{"disciplina":"ARA0000","turma":"3001","semestre":"2026.1",
 "confidence":0.0,"students":[{"matricula":"...","nome":"...",
 "confidence":0.0}]}
Regras: não invente dados; omita valores ausentes; matrícula deve vir literalmente
da fonte; confidence varia de 0 a 1; ignore professor, datas, presença e cabeçalhos.
"""


def _json_object(value: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", value, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group())
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _validated(payload: dict[str, Any], provider: str) -> dict[str, Any] | None:
    def confidence(value: Any, default: float = 0.5) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return default

    students = []
    enrollments = set()
    for item in payload.get("students", []):
        if not isinstance(item, dict):
            continue
        enrollment = str(item.get("matricula", "")).strip()
        name = str(item.get("nome", "")).strip()
        # O agente interpreta; regras determinísticas continuam sendo a barreira.
        if not re.fullmatch(r"\d{7,16}", enrollment) or len(name.split()) < 2:
            continue
        if enrollment in enrollments:
            continue
        enrollments.add(enrollment)
        item_confidence = confidence(item.get("confidence"))
        students.append({"enrollment": enrollment, "name": name,
                         "confidence": item_confidence})
    if not students:
        return None
    overall_confidence = confidence(payload.get("confidence"))
    discipline = str(payload.get("disciplina", "")).strip()
    discipline_match = re.search(r"\bARA\d{4}\b", discipline, re.I)
    class_match = re.search(r"\b\d{4,8}\b", str(payload.get("turma", "")))
    return {
        "students": students,
        "discipline": discipline_match.group().upper() if discipline_match else "",
        "class_code": class_match.group() if class_match else "",
        "semester": str(payload.get("semestre", "")).strip()[:20],
        "confidence": overall_confidence,
        "provider": provider,
    }


async def interpret_student_roster(text: str, active_llms: list[str]) -> dict[str, Any] | None:
    """Pede estruturação ao melhor provedor disponível, com timeout e validação."""
    if not text.strip() or not active_llms:
        return None
    provider = await pick_auto_llm(active_llms)
    if not provider:
        return None
    try:
        response = await asyncio.wait_for(langchain_agent_service.dispatch_single(
            provider, text[:30_000], [], SYSTEM_PROMPT), timeout=35)
    except Exception:
        return None
    if response.is_error:
        return None
    payload = _json_object(response.content)
    result = _validated(payload, provider) if payload else None
    if result:
        # Uma matrícula sugerida só sobrevive se estiver literalmente na fonte.
        result["students"] = [item for item in result["students"]
                              if item["enrollment"] in text]
        if not result["students"]:
            return None
    return result
