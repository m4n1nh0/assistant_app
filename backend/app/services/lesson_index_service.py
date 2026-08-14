"""Reconstrucao do indice de aulas no Qdrant a partir do MySQL.

O MySQL guarda a transcricao; o Qdrant e um indice derivado dela. Isso significa
que o indice pode ficar atras da base sem que nada se perca - e acontece: o
Qdrant estava fora do ar quando o trecho chegou, o provedor de embedding falhou,
ou o modelo mudou e os vetores antigos deixaram de ser comparaveis com os novos.

Em qualquer desses casos a resposta e a mesma: reler os trechos do MySQL e
gravar os vetores de novo. O banco relacional nao entra na resposta do chat, so
na reconstrucao do indice.
"""

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from loguru import logger
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import AsyncSessionLocal, LessonModel, LessonSegmentModel
from . import embedding_service, qdrant_service

# Quantos trechos por chamada ao modelo. Lote grande acelera o embedding, mas
# um lote que falha e refeito inteiro na proxima rodada.
_BATCH_SIZE = 32
# Teto de uma reindexacao manual e da automatica. A automatica roda dentro de
# uma pergunta do chat, entao aceita bem menos trecho.
_MAX_PER_RUN = 600
_AUTO_MAX_SEGMENTS = 120
# Uma pergunta sem resposta nao pode disparar reindexacao a cada tentativa.
_COOLDOWN_SECONDS = 300.0

_last_attempt: Dict[str, float] = {}
_running: set = set()


def _as_utc(value: Optional[datetime]) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def current_signature() -> str:
    """`provedor:modelo` ativo, resolvendo o provedor se ainda nao foi usado."""
    signature = embedding_service.active_signature()
    if signature:
        return signature
    try:
        await embedding_service.embed_text("verificacao do indice de aulas")
    except Exception as exc:
        logger.warning(f"Nenhum provedor de embedding respondeu: {exc}")
        return ""
    return embedding_service.active_signature()


def _stale_condition(signature: str):
    """Trechos que precisam de vetor: nunca indexados ou indexados por outro modelo."""
    conditions = [LessonSegmentModel.indexed.is_(False)]
    if embedding_service.is_semantic(signature):
        # So um modelo de verdade justifica refazer o que ja tem vetor. Estando
        # no hash, reindexar destruiria vetores bons por vetores piores.
        conditions.append(LessonSegmentModel.embedding_model.is_(None))
        conditions.append(LessonSegmentModel.embedding_model != signature)
    return or_(*conditions)


async def pending_count(
    db: AsyncSession,
    *,
    tutor_id: str,
    signature: str,
    lesson_id: Optional[str] = None,
) -> int:
    query = select(func.count(LessonSegmentModel.id)).where(
        LessonSegmentModel.tutor_id == tutor_id,
        _stale_condition(signature),
    )
    if lesson_id:
        query = query.where(LessonSegmentModel.lesson_id == lesson_id)
    return int((await db.execute(query)).scalar() or 0)


async def _segments_to_index(
    db: AsyncSession,
    *,
    tutor_id: str,
    signature: str,
    lesson_id: Optional[str],
    force: bool,
    limit: int,
) -> List[Tuple[LessonSegmentModel, LessonModel]]:
    query = (
        select(LessonSegmentModel, LessonModel)
        .join(LessonModel, LessonModel.id == LessonSegmentModel.lesson_id)
        .where(LessonSegmentModel.tutor_id == tutor_id)
        .order_by(LessonSegmentModel.created_at)
        .limit(limit)
    )
    if lesson_id:
        query = query.where(LessonSegmentModel.lesson_id == lesson_id)
    if not force:
        query = query.where(_stale_condition(signature))
    return list((await db.execute(query)).all())


async def _write_batch(
    db: AsyncSession,
    *,
    lesson: LessonModel,
    segments: Sequence[LessonSegmentModel],
    signature: str,
) -> int:
    started = _as_utc(lesson.started_at)
    written = await qdrant_service.index_lesson_segments(
        tutor_id=lesson.tutor_id,
        lesson_id=lesson.id,
        discipline=lesson.discipline,
        segments=[{
            "id": segment.id,
            "text": segment.text,
            "sequence": segment.sequence,
            "class_group": lesson.class_group or "",
            "lesson_date": started.date().isoformat(),
            "lesson_ts": int(started.timestamp()),
        } for segment in segments],
    )
    if not written:
        return 0

    for segment in segments:
        segment.indexed = True
        segment.qdrant_point_id = segment.id
        segment.embedding_model = signature
    await db.commit()
    return written


async def _forget_indexed_vectors(db: AsyncSession) -> None:
    """Marca todo trecho como nao indexado apos a colecao ser recriada.

    A colecao e de todos os professores da instalacao, entao apagar os vetores
    de um deles apaga os dos outros: quem nao for reindexado agora precisa
    voltar para a fila, senao o indice mente que esta em dia.
    """
    await db.execute(
        update(LessonSegmentModel)
        .where(LessonSegmentModel.indexed.is_(True))
        .values(indexed=False, embedding_model=None)
    )
    await db.commit()


async def reindex(
    db: AsyncSession,
    *,
    tutor_id: str,
    lesson_id: Optional[str] = None,
    force: bool = False,
    limit: int = _MAX_PER_RUN,
) -> Dict[str, Any]:
    """Regrava no Qdrant os trechos que o indice nao tem, ou tem desatualizados."""
    signature = await current_signature()
    if not signature:
        return {
            "indexed": 0,
            "failed": 0,
            "pending": await pending_count(
                db, tutor_id=tutor_id, signature="", lesson_id=lesson_id
            ),
            "embedding": "",
            "error": "nenhum provedor de embedding disponivel",
        }

    try:
        await qdrant_service.ensure_lesson_collection()
    except qdrant_service.LessonCollectionMismatch as exc:
        # Modelo novo, dimensao nova: os vetores antigos nao sao comparaveis
        # com os novos e a colecao recusa a escrita. Recriar so e aceitavel
        # sob pedido explicito, e so porque o texto continua no MySQL.
        if not force:
            return {
                "indexed": 0,
                "failed": 0,
                "pending": await pending_count(
                    db, tutor_id=tutor_id, signature=signature, lesson_id=lesson_id
                ),
                "embedding": signature,
                "error": str(exc),
            }
        await qdrant_service.rebuild_lesson_collection()
        await _forget_indexed_vectors(db)

    rows = await _segments_to_index(
        db,
        tutor_id=tutor_id,
        signature=signature,
        lesson_id=lesson_id,
        force=force,
        limit=limit,
    )

    # Uma chamada por aula: o payload do ponto carrega disciplina e data, que
    # sao da aula e nao do trecho.
    by_lesson: Dict[str, Tuple[LessonModel, List[LessonSegmentModel]]] = {}
    for segment, lesson in rows:
        entry = by_lesson.setdefault(lesson.id, (lesson, []))
        entry[1].append(segment)

    indexed = 0
    failed = 0
    for lesson, segments in by_lesson.values():
        for start in range(0, len(segments), _BATCH_SIZE):
            batch = segments[start:start + _BATCH_SIZE]
            try:
                indexed += await _write_batch(
                    db, lesson=lesson, segments=batch, signature=signature
                )
            except Exception as exc:
                failed += len(batch)
                await db.rollback()
                logger.warning(
                    f"Reindexacao falhou na aula {lesson.id} "
                    f"({len(batch)} trechos): {exc}"
                )

    pending = await pending_count(
        db, tutor_id=tutor_id, signature=signature, lesson_id=lesson_id
    )
    if indexed:
        logger.info(
            f"Reindexacao: {indexed} trecho(s) gravados com '{signature}', "
            f"{pending} restante(s)"
        )
    return {
        "indexed": indexed,
        "failed": failed,
        "pending": pending,
        "embedding": signature,
    }


async def catch_up(*, tutor_id: str, reason: str = "") -> Dict[str, Any]:
    """Reindexacao automatica, disparada quando a busca no Qdrant nao acha nada.

    Abre a propria sessao porque quem chama e o chat, que nao tem a do request.
    Tem trava e intervalo minimo: pergunta sem resposta e comum, e nao pode
    virar uma reindexacao a cada mensagem.
    """
    if tutor_id in _running:
        return {"indexed": 0, "skipped": "ja em andamento"}

    now = time.monotonic()
    last = _last_attempt.get(tutor_id)
    if last is not None and now - last < _COOLDOWN_SECONDS:
        return {"indexed": 0, "skipped": "intervalo minimo"}

    _last_attempt[tutor_id] = now
    _running.add(tutor_id)
    try:
        async with AsyncSessionLocal() as db:
            signature = await current_signature()
            pending = await pending_count(db, tutor_id=tutor_id, signature=signature)
            if not pending:
                return {"indexed": 0, "pending": 0, "skipped": "indice em dia"}
            if reason:
                logger.info(
                    f"Reindexando {pending} trecho(s) de aula ({reason})"
                )
            return await reindex(db, tutor_id=tutor_id, limit=_AUTO_MAX_SEGMENTS)
    except Exception as exc:
        logger.warning(f"Reindexacao automatica falhou: {exc}")
        return {"indexed": 0, "error": str(exc)}
    finally:
        _running.discard(tutor_id)


def reset_cooldown() -> None:
    """Usado pelos testes e pela reindexacao manual, que nao espera intervalo."""
    _last_attempt.clear()
    _running.clear()


async def status(db: AsyncSession, *, tutor_id: str) -> Dict[str, Any]:
    signature = embedding_service.active_signature()
    total = int((await db.execute(
        select(func.count(LessonSegmentModel.id))
        .where(LessonSegmentModel.tutor_id == tutor_id)
    )).scalar() or 0)
    pending = await pending_count(db, tutor_id=tutor_id, signature=signature)
    return {
        "segments": total,
        "pending": pending,
        "embedding": signature,
        "semantic": embedding_service.is_semantic(signature),
    }


__all__ = [
    "catch_up",
    "current_signature",
    "pending_count",
    "reindex",
    "reset_cooldown",
    "status",
]
