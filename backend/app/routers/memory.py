from datetime import datetime, timezone
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import MemoryReviewModel, get_db
from ..models.schemas import (
    MemoryDecisionRequest,
    MemoryReviewCreate,
    MemoryReviewResponse,
    MemorySearchResponse,
    MemoryVoiceDecisionRequest,
    MemoryVoiceDecisionResponse,
)
from ..services import qdrant_service

router = APIRouter(prefix="/memory", tags=["Memory"])

VOICE_APPROVAL_EXACT = {
    "sim",
    "ok",
    "pode",
    "aprovado",
    "aprovar",
    "confirmo",
    "confirmado",
    "autorizo",
    "autorizado",
    "beleza",
}

VOICE_APPROVAL_PHRASES = (
    "pode guardar",
    "pode salvar",
    "pode aprender",
    "pode registrar",
    "guardar isso",
    "salvar isso",
    "aprenda isso",
    "guarde isso",
    "salve isso",
    "esta aprovado",
    "ta aprovado",
)

VOICE_REJECTION_EXACT = {
    "nao",
    "rejeito",
    "rejeitar",
    "cancela",
    "cancelar",
    "descarte",
    "descartar",
}

VOICE_REJECTION_PHRASES = (
    "nao guardar",
    "nao salvar",
    "nao aprender",
    "nao registrar",
    "nao autorizar",
    "nao autorizo",
    "nao esta aprovado",
    "nao ta aprovado",
    "cancela isso",
    "cancelar isso",
    "descarte isso",
    "descartar isso",
)


def _memory_response(item: MemoryReviewModel) -> MemoryReviewResponse:
    return MemoryReviewResponse(
        id=item.id,
        tutor_id=item.tutor_id,
        category=item.category,
        content=item.content,
        source=item.source,
        status=item.status,
        confidence=item.confidence,
        qdrant_point_id=item.qdrant_point_id,
        metadata=item.metadata_ or {},
        reviewer_note=item.reviewer_note,
        created_at=item.created_at,
        reviewed_at=item.reviewed_at,
    )


def _normalize_voice_text(transcript: str) -> str:
    normalized = unicodedata.normalize("NFKD", transcript.lower())
    text = "".join(char for char in normalized if not unicodedata.combining(char))
    punctuation = str.maketrans({char: " " for char in ".,!?;:"})
    return " ".join(text.translate(punctuation).split())


def _voice_decision(transcript: str) -> str:
    text = _normalize_voice_text(transcript)
    if not text:
        return "unclear"
    if text in VOICE_REJECTION_EXACT or any(phrase in text for phrase in VOICE_REJECTION_PHRASES):
        return "rejected"
    if text in VOICE_APPROVAL_EXACT or any(phrase in text for phrase in VOICE_APPROVAL_PHRASES):
        return "approved"
    return "unclear"


async def _approve_item(
    item: MemoryReviewModel,
    db: AsyncSession,
    reviewer_note: str = "",
) -> MemoryReviewModel:
    if item.status == "approved":
        return item

    point_id = qdrant_service.upsert_memory(
        point_id=item.id,
        tutor_id=item.tutor_id,
        category=item.category,
        content=item.content,
        metadata={
            **(item.metadata_ or {}),
            "source": item.source,
            "confidence": item.confidence,
        },
    )
    item.status = "approved"
    item.qdrant_point_id = point_id
    item.reviewer_note = reviewer_note
    item.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(item)
    return item


async def _reject_item(
    item: MemoryReviewModel,
    db: AsyncSession,
    reviewer_note: str = "",
) -> MemoryReviewModel:
    item.status = "rejected"
    item.reviewer_note = reviewer_note
    item.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(item)
    return item


@router.post("/review", response_model=MemoryReviewResponse)
async def propose_memory(body: MemoryReviewCreate, db: AsyncSession = Depends(get_db)):
    item = MemoryReviewModel(
        tutor_id=body.tutor_id,
        category=body.category,
        content=body.content,
        source=body.source,
        confidence=body.confidence,
        metadata_=body.metadata,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _memory_response(item)


@router.get("/review", response_model=list[MemoryReviewResponse])
async def list_memory_reviews(
    tutor_id: str,
    status: str = Query("pending"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MemoryReviewModel)
        .where(
            MemoryReviewModel.tutor_id == tutor_id,
            MemoryReviewModel.status == status,
        )
        .order_by(MemoryReviewModel.created_at.desc())
    )
    return [_memory_response(item) for item in result.scalars().all()]


@router.post("/review/{memory_id}/approve", response_model=MemoryReviewResponse)
async def approve_memory(
    memory_id: str,
    body: MemoryDecisionRequest = MemoryDecisionRequest(),
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(MemoryReviewModel, memory_id)
    if item is None:
        raise HTTPException(404, "Memória não encontrada")
    item = await _approve_item(item, db, body.reviewer_note)
    return _memory_response(item)


@router.post("/review/{memory_id}/reject", response_model=MemoryReviewResponse)
async def reject_memory(
    memory_id: str,
    body: MemoryDecisionRequest = MemoryDecisionRequest(),
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(MemoryReviewModel, memory_id)
    if item is None:
        raise HTTPException(404, "Memória não encontrada")
    item = await _reject_item(item, db, body.reviewer_note)
    return _memory_response(item)


@router.post("/review/{memory_id}/voice-decision", response_model=MemoryVoiceDecisionResponse)
async def decide_memory_by_voice(
    memory_id: str,
    body: MemoryVoiceDecisionRequest,
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(MemoryReviewModel, memory_id)
    if item is None:
        raise HTTPException(404, "Memória não encontrada")

    decision = _voice_decision(body.transcript)
    reviewer_note = body.reviewer_note or f"confirmacao verbal: {body.transcript}"
    if decision == "approved":
        item = await _approve_item(item, db, reviewer_note)
        return MemoryVoiceDecisionResponse(
            decision=decision,
            message="Aprendizado aprovado por voz.",
            memory=_memory_response(item),
        )
    if decision == "rejected":
        item = await _reject_item(item, db, reviewer_note)
        return MemoryVoiceDecisionResponse(
            decision=decision,
            message="Aprendizado rejeitado por voz.",
            memory=_memory_response(item),
        )

    return MemoryVoiceDecisionResponse(
        decision=decision,
        message="Confirmacao verbal nao reconhecida.",
        memory=_memory_response(item),
    )


@router.get("/search", response_model=list[MemorySearchResponse])
async def search_memory(
    tutor_id: str,
    q: str,
    category: str | None = None,
    limit: int = Query(5, ge=1, le=25),
):
    return qdrant_service.search_memory(
        tutor_id=tutor_id,
        query=q,
        category=category,
        limit=limit,
    )
