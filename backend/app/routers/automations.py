"""Endpoints das automacoes aprovadas e do log de auditoria.

Automacao so roda depois de aprovada explicitamente, e toda execucao vira linha
de auditoria - as duas coisas juntas sao o que torna aceitavel dar acao com
efeito colateral a um assistente.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    ActionAuditLogModel,
    ApprovedAutomationModel,
    get_db,
)
from ..models.schemas import (
    ActionAuditRequest,
    ActionAuditResponse,
    AutomationApproveRequest,
    AutomationResponse,
    AutomationUpdateRequest,
)
from ..core.security import get_current_user
from ..services import qdrant_service

router = APIRouter(
    prefix="/automations", tags=["Automations"], dependencies=[Depends(get_current_user)]
)


def _automation_response(item: ApprovedAutomationModel) -> AutomationResponse:
    return AutomationResponse(
        id=item.id,
        tutor_id=item.tutor_id,
        title=item.title,
        description=item.description or "",
        trigger=item.trigger,
        instructions=item.instructions,
        schedule=item.schedule or {},
        risk_level=item.risk_level,
        enabled=bool(item.enabled),
        approved_at=item.approved_at,
        last_run_at=item.last_run_at,
        metadata=item.metadata_ or {},
    )


def _audit_response(item: ActionAuditLogModel) -> ActionAuditResponse:
    return ActionAuditResponse(
        id=item.id,
        tutor_id=item.tutor_id,
        automation_id=item.automation_id,
        action_type=item.action_type,
        status=item.status,
        request=item.request or {},
        result=item.result or {},
        created_at=item.created_at,
    )


@router.post("/", response_model=AutomationResponse)
async def approve_automation(
    body: AutomationApproveRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Registra a autorizacao do usuario para uma automacao.

    Sem um registro aprovado aqui, nada e executado automaticamente.
    """
    item = ApprovedAutomationModel(
        tutor_id=user["tutor_id"],
        title=body.title,
        description=body.description,
        trigger=body.trigger,
        instructions=body.instructions,
        schedule=body.schedule,
        risk_level=body.risk_level,
        enabled=body.enabled,
        metadata_=body.metadata,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    qdrant_service.upsert_memory(
        point_id=item.id,
        tutor_id=item.tutor_id,
        category="automation_knowledge",
        content=f"{item.title}\n{item.description or ''}\n{item.instructions}",
        metadata={
            **(item.metadata_ or {}),
            "automation_id": item.id,
            "trigger": item.trigger,
            "risk_level": item.risk_level,
        },
    )
    return _automation_response(item)


@router.get("/", response_model=list[AutomationResponse])
async def list_automations(
    tutor_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lista as automacoes aprovadas do usuario."""
    tutor_id = user["tutor_id"]
    result = await db.execute(
        select(ApprovedAutomationModel)
        .where(ApprovedAutomationModel.tutor_id == tutor_id)
        .order_by(ApprovedAutomationModel.approved_at.desc())
    )
    return [_automation_response(item) for item in result.scalars().all()]


@router.patch("/{automation_id}", response_model=AutomationResponse)
async def update_automation(
    automation_id: str,
    body: AutomationUpdateRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Altera uma automacao aprovada (habilitar, reagendar, editar)."""
    item = await db.get(ApprovedAutomationModel, automation_id)
    if item is None or item.tutor_id != user["tutor_id"]:
        raise HTTPException(404, "Automação não encontrada")

    if body.enabled is not None:
        item.enabled = body.enabled
    if body.schedule is not None:
        item.schedule = body.schedule
    if body.metadata is not None:
        item.metadata_ = body.metadata

    await db.commit()
    await db.refresh(item)
    return _automation_response(item)


@router.post("/audit", response_model=ActionAuditResponse)
async def write_audit(
    body: ActionAuditRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Grava no log de auditoria uma acao executada pela interface."""
    item = ActionAuditLogModel(
        tutor_id=user["tutor_id"],
        automation_id=body.automation_id,
        action_type=body.action_type,
        status=body.status,
        request=body.request,
        result=body.result,
    )
    db.add(item)

    if body.automation_id:
        automation = await db.get(ApprovedAutomationModel, body.automation_id)
        if automation is None or automation.tutor_id != user["tutor_id"]:
            raise HTTPException(404, "Automacao nao encontrada")
        if body.status == "executed":
            automation.last_run_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(item)
    return _audit_response(item)


@router.get("/audit", response_model=list[ActionAuditResponse])
async def list_audit(
    tutor_id: str,
    automation_id: str | None = None,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lista o log de auditoria, opcionalmente filtrado por automacao."""
    tutor_id = user["tutor_id"]
    query = select(ActionAuditLogModel).where(ActionAuditLogModel.tutor_id == tutor_id)
    if automation_id:
        query = query.where(ActionAuditLogModel.automation_id == automation_id)
    result = await db.execute(query.order_by(ActionAuditLogModel.created_at.desc()))
    return [_audit_response(item) for item in result.scalars().all()]
