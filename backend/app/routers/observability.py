"""Endpoints de observabilidade: custo, spans recentes e estado da telemetria.

Servem a tela de diagnostico da interface e o trabalho de investigacao local.
Nao substituem o backend de traces: a janela aqui e curta e em memoria, feita
para responder "o que acabou de acontecer" sem exigir um collector de pe.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from shared.observability import memory_sink
from shared.observability.langsmith import enabled as langsmith_enabled
from shared.observability.otel import available as otel_available
from ..core.database import get_db
from ..core.security import get_current_user, require_admin
from ..services import llm_price_service, llm_usage_service

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


# --- consumo por cliente e precos -----------------------------------------------------------------
#
# As rotas acima olham a janela em memoria do processo ("o que acabou de acontecer"). As de baixo
# olham o banco: o historico de consumo de cada cliente e a tabela de precos que o calcula.


@router.get("/usage")
async def llm_usage(
    days: int = Query(30, ge=1, le=366, description="janela em dias, contando hoje"),
    group_by: str = Query("provider", description="provider, model, day ou tenant"),
    scope: str = Query("mine", description="mine (a sua conta) ou all (so administrador)"),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Consumo de IA da janela: total e por provedor, modelo, dia ou cliente.

    Cada conta ve o proprio consumo. O administrador pode pedir `scope=all` para somar todos os
    clientes e agrupar por cliente. Os tokens sao os que o provedor informou; o custo e uma
    **estimativa** (preco de tabela), e `unpriced_calls` conta as chamadas que ficaram sem preco.
    """
    is_admin = user.get("role") == "admin"
    if scope == "all" and not is_admin:
        raise HTTPException(403, "Apenas administradores veem o consumo de todos os clientes")
    if group_by == "tenant" and not (is_admin and scope == "all"):
        raise HTTPException(403, "O consumo por cliente e restrito a administradores")
    tenant = None if scope == "all" else user.get("tutor_id") or ""
    data = await llm_usage_service.summarize(db, days=days, group_by=group_by, tenant_id=tenant)
    if data["group_by"] == "tenant":
        names = await llm_usage_service.tenant_names(db, [g["key"] for g in data["groups"]])
        for group in data["groups"]:
            group["label"] = names.get(group["key"]) or group["label"]
    data["scope"] = "all" if scope == "all" else "mine"
    return data


class PriceBody(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    # Vazio: o preco padrao do provedor.
    model: str = Field(default="", max_length=160)
    input_per_mtok: float = Field(ge=0)
    output_per_mtok: float = Field(ge=0)
    cached_input_per_mtok: Optional[float] = Field(default=None, ge=0)


@router.get("/prices")
async def llm_prices(
    provider: str = Query("", max_length=32),
    source: str = Query("", description="manual ou litellm"),
    q: str = Query("", max_length=160, description="parte do nome do modelo"),
    limit: int = Query(500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
):
    """Precos de token em dolar por milhao de tokens, do banco. Leitura para qualquer conta."""
    rows = await llm_price_service.list_prices(
        db, provider=provider, source=source, query=q, limit=limit)
    return {
        "providers": list(llm_price_service.PROVIDERS),
        "prices": [llm_price_service.price_out(row) for row in rows],
    }


@router.put("/prices")
async def put_llm_price(
    body: PriceBody,
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Grava um preco a mao (administrador). A sincronizacao nunca o sobrescreve."""
    try:
        row = await llm_price_service.upsert_manual(db, **body.model_dump())
    except llm_price_service.PriceError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return llm_price_service.price_out(row)


@router.delete("/prices/{price_id}")
async def delete_llm_price(
    price_id: str,
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Apaga um preco (administrador). O modelo volta ao preco padrao do provedor."""
    if not await llm_price_service.delete_price(db, price_id):
        raise HTTPException(404, "Preco nao encontrado")
    return {"ok": True}


@router.post("/prices/sync")
async def sync_llm_prices(
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Importa a tabela publica de precos (administrador), sem tocar nos precos digitados a mao."""
    try:
        result = await llm_price_service.sync_from_source(db, fetch=llm_price_service.fetch_source)
    except llm_price_service.PriceError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    result["source"] = llm_price_service.SOURCE_URL
    return result
