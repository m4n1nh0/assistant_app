"""WebSocket para monitoramento em tempo real de quiz."""

import json
import asyncio
from typing import Set
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    QuizModel,
    QuestionModel,
    StudentAnswerModel,
    get_db,
)

router = APIRouter(prefix="/ws", tags=["websocket"])

# Gerencia conexões WebSocket ativas por quiz
class QuizConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, Set[WebSocket]] = {}

    async def connect(self, quiz_id: str, websocket: WebSocket):
        await websocket.accept()
        if quiz_id not in self.active_connections:
            self.active_connections[quiz_id] = set()
        self.active_connections[quiz_id].add(websocket)

    def disconnect(self, quiz_id: str, websocket: WebSocket):
        if quiz_id in self.active_connections:
            self.active_connections[quiz_id].discard(websocket)
            if not self.active_connections[quiz_id]:
                del self.active_connections[quiz_id]

    async def broadcast(self, quiz_id: str, message: dict):
        """Envia mensagem para todos os clientes do quiz."""
        if quiz_id in self.active_connections:
            dead_connections = set()
            for websocket in self.active_connections[quiz_id]:
                try:
                    await websocket.send_json(message)
                except Exception:
                    dead_connections.add(websocket)

            # Remove conexões mortas
            for ws in dead_connections:
                self.disconnect(quiz_id, ws)

    def get_connection_count(self, quiz_id: str) -> int:
        return len(self.active_connections.get(quiz_id, set()))


manager = QuizConnectionManager()


async def get_quiz_stats(quiz_id: str, db: AsyncSession) -> dict:
    """Calcula estatísticas do quiz em tempo real."""

    # Total de questões
    stmt = select(func.count(QuestionModel.id)).where(
        QuestionModel.quiz_id == quiz_id
    )
    total_questions = (await db.execute(stmt)).scalar() or 0

    # Total de respostas únicas
    stmt = select(func.count(func.distinct(StudentAnswerModel.question_id))).where(
        StudentAnswerModel.question_id.in_(
            select(QuestionModel.id).where(QuestionModel.quiz_id == quiz_id)
        )
    )
    unique_answers = (await db.execute(stmt)).scalar() or 0

    # Respostas corretas
    stmt = select(func.count(StudentAnswerModel.id)).where(
        (StudentAnswerModel.question_id.in_(
            select(QuestionModel.id).where(QuestionModel.quiz_id == quiz_id)
        )) &
        (StudentAnswerModel.correta == True)
    )
    correct_answers = (await db.execute(stmt)).scalar() or 0

    # Respostas incorretas
    stmt = select(func.count(StudentAnswerModel.id)).where(
        (StudentAnswerModel.question_id.in_(
            select(QuestionModel.id).where(QuestionModel.quiz_id == quiz_id)
        )) &
        (StudentAnswerModel.correta == False)
    )
    incorrect_answers = (await db.execute(stmt)).scalar() or 0

    # Respostas em aberto (perguntas aberta = None)
    open_answers = (await db.execute(
        select(func.count(StudentAnswerModel.id)).where(
            (StudentAnswerModel.question_id.in_(
                select(QuestionModel.id).where(QuestionModel.quiz_id == quiz_id)
            )) &
            (StudentAnswerModel.correta.is_(None))
        )
    )).scalar() or 0

    # Estatísticas por questão
    stmt = select(QuestionModel).where(QuestionModel.quiz_id == quiz_id)
    questions = (await db.execute(stmt)).scalars().all()

    questions_stats = []
    for q in questions:
        stmt = select(func.count(StudentAnswerModel.id)).where(
            StudentAnswerModel.question_id == q.id
        )
        q_total = (await db.execute(stmt)).scalar() or 0

        stmt = select(func.count(StudentAnswerModel.id)).where(
            (StudentAnswerModel.question_id == q.id) &
            (StudentAnswerModel.correta == True)
        )
        q_correct = (await db.execute(stmt)).scalar() or 0

        stmt = select(func.count(StudentAnswerModel.id)).where(
            (StudentAnswerModel.question_id == q.id) &
            (StudentAnswerModel.correta == False)
        )
        q_incorrect = (await db.execute(stmt)).scalar() or 0

        questions_stats.append({
            "question_id": q.id,
            "question_text": q.enunciado[:50] + "..." if len(q.enunciado) > 50 else q.enunciado,
            "total_answers": q_total,
            "correct": q_correct,
            "incorrect": q_incorrect,
            "percentage": round((q_correct / q_total * 100) if q_total > 0 else 0, 1),
        })

    return {
        "timestamp": datetime.now().isoformat(),
        "quiz_id": quiz_id,
        "total_questions": total_questions,
        "progress": {
            "total_answers": unique_answers,
            "correct": correct_answers,
            "incorrect": incorrect_answers,
            "open": open_answers,
        },
        "overall_percentage": round(
            (correct_answers / (correct_answers + incorrect_answers) * 100)
            if (correct_answers + incorrect_answers) > 0
            else 0,
            1
        ),
        "questions": questions_stats,
        "active_connections": manager.get_connection_count(quiz_id),
    }


@router.websocket("/quiz/{quiz_id}/monitor")
async def quiz_monitor_websocket(
    websocket: WebSocket,
    quiz_id: str,
    db: AsyncSession = Depends(get_db),
):
    """WebSocket para monitoramento em tempo real do quiz pelo professor."""

    await manager.connect(quiz_id, websocket)

    # Envia status inicial
    try:
        stats = await get_quiz_stats(quiz_id, db)
        await websocket.send_json({
            "type": "initial_stats",
            "data": stats,
        })
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "message": str(e),
        })
        manager.disconnect(quiz_id, websocket)
        return

    try:
        # Monitora mudanças a cada 2 segundos
        while True:
            await asyncio.sleep(2)

            try:
                stats = await get_quiz_stats(quiz_id, db)
                await websocket.send_json({
                    "type": "stats_update",
                    "data": stats,
                })
            except Exception as e:
                print(f"Erro ao calcular stats: {e}")
                continue

    except WebSocketDisconnect:
        manager.disconnect(quiz_id, websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(quiz_id, websocket)


@router.websocket("/quiz/{quiz_id}/broadcast")
async def quiz_broadcast_websocket(
    websocket: WebSocket,
    quiz_id: str,
    token: str = Query(...),  # Token para autorizar
    db: AsyncSession = Depends(get_db),
):
    """WebSocket que recebe atualizações quando alunos respondem (backend → frontend)."""

    # Valida token (simplificado - você pode usar JWT)
    if not token:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await manager.connect(quiz_id, websocket)

    try:
        # Listener que aguarda mensagens
        while True:
            # Recebe mensagem (se houver)
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                message = json.loads(data)

                if message.get("type") == "ping":
                    # Keep-alive
                    await websocket.send_json({"type": "pong"})

            except asyncio.TimeoutError:
                # Timeout - envia pong automático
                await websocket.send_json({"type": "pong"})
                continue

    except WebSocketDisconnect:
        manager.disconnect(quiz_id, websocket)
    except Exception as e:
        print(f"WebSocket broadcast error: {e}")
        manager.disconnect(quiz_id, websocket)


async def notify_quiz_update(quiz_id: str, update_type: str, data: dict = None):
    """Notifica todos os conectados sobre uma atualização do quiz."""

    message = {
        "type": update_type,
        "timestamp": datetime.now().isoformat(),
    }

    if data:
        message["data"] = data

    await manager.broadcast(quiz_id, message)
