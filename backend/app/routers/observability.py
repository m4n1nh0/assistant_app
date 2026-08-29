"""Endpoints de observabilidade: custo, spans recentes e estado da telemetria.

Servem a tela de diagnostico da interface e o trabalho de investigacao local.
Nao substituem o backend de traces: a janela aqui e curta e em memoria, feita
para responder "o que acabou de acontecer" sem exigir um collector de pe.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..core.config import get_settings
from ..core.observability import memory_sink
from ..core.observability.langsmith import enabled as langsmith_enabled
from ..core.observability.otel import available as otel_available
from ..core.security import get_current_user

router = APIRouter(
    prefix="/observability",
    tags=["Observability"],
    dependencies=[Depends(get_current_user)],
)
settings = get_settings()

_GROUPS = (
    "provider",
    "model",
    "agent_id",
    "tool_name",
    "conversation_id",
    "request_id",
    "execution_id",
)


@router.get("/status")
async def observability_status():
    """O que esta ligado e quanto ha na janela em memoria."""
    memory = memory_sink()
    return {
        "opentelemetry": {
            "enabled": settings.otel_enabled,
            "active": otel_available(),
            "service_name": settings.otel_service_name,
            "endpoint": settings.otel_exporter_endpoint or "padrao do SDK",
        },
        "langsmith": {
            "enabled": settings.langsmith_enabled,
            "active": langsmith_enabled(),
            "project": settings.langsmith_project,
        },
        "memory_window": {
            "spans": len(memory.spans()) if memory else 0,
            "usage": len(memory.usage()) if memory else 0,
            "capacity": settings.telemetry_memory_events,
        },
    }


@router.get("/costs")
async def observability_costs(
    group_by: str = Query("provider", description="dimensao da agregacao"),
):
    """Consumo e custo estimado da janela atual, agregados por uma dimensao.

    Args:
        group_by: `provider`, `model`, `agent_id`, `tool_name`,
            `conversation_id`, `request_id` ou `execution_id`.

    Returns:
        Totais gerais e por grupo. Os valores sao **estimativas**: dependem da
        tabela de preco configurada e do que cada provedor informa de token.
    """
    memory = memory_sink()
    if memory is None:
        return {"available": False, "reason": "janela em memoria desligada"}
    dimension = group_by if group_by in _GROUPS else "provider"
    summary = memory.summarize(group_by=dimension)
    summary["available"] = True
    summary["estimated"] = True
    summary["valid_groups"] = list(_GROUPS)
    return summary


@router.get("/spans")
async def observability_spans(
    kind: str = Query("", description="filtra por familia de operacao"),
    limit: int = Query(100, ge=1, le=1000),
):
    """Ultimos spans registrados, do mais recente para o mais antigo."""
    memory = memory_sink()
    if memory is None:
        return {"available": False, "spans": []}
    spans = memory.spans()
    if kind:
        spans = [span for span in spans if span.kind == kind]
    return {
        "available": True,
        "spans": [
            {
                "name": span.name,
                "kind": span.kind,
                "duration_ms": span.duration_ms,
                "ok": span.ok,
                "error": span.error,
                "retries": span.retries,
                "attributes": span.attributes,
                "correlation": span.correlation,
            }
            for span in reversed(spans[-limit:])
        ],
    }


@router.delete("/window")
async def clear_observability_window():
    """Descarta a janela em memoria, sem afetar o que ja foi exportado."""
    memory = memory_sink()
    if memory is not None:
        memory.clear()
    return {"ok": True}
