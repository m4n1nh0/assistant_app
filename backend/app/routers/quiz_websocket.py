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
    """Conexoes de um quiz em andamento, separadas por sala.

    Professor e alunos ficam no mesmo agrupamento, o que permite propagar a questao
    atual e as respostas em tempo real.
    """
    def __init__(self):
        self.active_connections: dict[str, Set[WebSocket]] = {}

    async def connect(self, quiz_id: str, websocket: WebSocket):
        """Aceita e registra a conexao na sala do quiz."""
        await websocket.accept()
        if quiz_id not in self.active_connections:
            self.active_connections[quiz_id] = set()
        self.active_connections[quiz_id].add(websocket)

    def disconnect(self, quiz_id: str, websocket: WebSocket):
        """Remove a conexao da sala do quiz."""
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
        """Quantas conexoes estao abertas na sala."""
        return len(self.active_connections.get(quiz_id, set()))


manager = QuizConnectionManager()


def _ranking_rows(answers: list[StudentAnswerModel]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for answer in answers:
        student_id = answer.student_id or "anon"
        row = grouped.setdefault(
            student_id,
            {
                "student_id": student_id,
                "student_name": answer.student_name or "Aluno",
                "score": 0,
                "correct": 0,
                "answers": 0,
            },
        )
        row["student_name"] = answer.student_name or row["student_name"]
        row["score"] += int(answer.pontuacao or 0)
        row["correct"] += 1 if answer.correta is True else 0
        row["answers"] += 1
    rows = list(grouped.values())
    rows.sort(key=lambda item: (-item["score"], -item["correct"], item["student_name"]))
    for index, row in enumerate(rows, start=1):
        row["position"] = index
    return rows


async def get_quiz_stats(quiz_id: str, db: AsyncSession) -> dict:
    """Calcula estatísticas do quiz em tempo real."""

    stmt = select(QuizModel).where(QuizModel.id == quiz_id)
    quiz = (await db.execute(stmt)).scalar_one_or_none()

    # Total de questões
    stmt = select(func.count(QuestionModel.id)).where(
        QuestionModel.quiz_id == quiz_id
    )
    total_questions = (await db.execute(stmt)).scalar() or 0

    # Total de respostas recebidas.
    stmt = select(func.count(StudentAnswerModel.id)).where(
        StudentAnswerModel.question_id.in_(
            select(QuestionModel.id).where(QuestionModel.quiz_id == quiz_id)
        )
    )
    total_answers = (await db.execute(stmt)).scalar() or 0

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

    question_ids = [q.id for q in questions]
    current_question = next(
        (q for q in questions if quiz and q.id == quiz.current_question_id),
        None,
    )

    questions_stats = []
    for index, q in enumerate(questions):
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
            "index": index,
            "is_current": bool(quiz and q.id == quiz.current_question_id),
            "question_text": (
                q.enunciado[:160] + "..."
                if len(q.enunciado) > 160
                else q.enunciado
            ),
            "total_answers": q_total,
            "correct": q_correct,
            "incorrect": q_incorrect,
            "percentage": round((q_correct / q_total * 100) if q_total > 0 else 0, 1),
        })

    all_answers = []
    current_answers = []
    if question_ids:
        all_answers = list((await db.execute(
            select(StudentAnswerModel).where(
                StudentAnswerModel.question_id.in_(question_ids)
            )
        )).scalars().all())
    if quiz and quiz.current_question_id:
        current_answers = [
            answer for answer in all_answers
            if answer.question_id == quiz.current_question_id
        ]
    overall_ranking = _ranking_rows(all_answers)
    current_ranking = _ranking_rows(current_answers)

    return {
        "timestamp": datetime.now().isoformat(),
        "quiz_id": quiz_id,
        "status": (quiz.status if quiz else "not_found") or "open",
        "live_phase": (quiz.live_phase if quiz else "not_found") or "lobby",
        "current_question_id": quiz.current_question_id if quiz else None,
        "question_started_at": (
            quiz.question_started_at.isoformat()
            if quiz and quiz.question_started_at else None
        ),
        "closed_at": quiz.closed_at.isoformat() if quiz and quiz.closed_at else None,
        "total_questions": total_questions,
        "current_question": (
            {
                "question_id": current_question.id,
                "index": next(
                    (
                        index for index, item in enumerate(questions)
                        if item.id == current_question.id
                    ),
                    0,
                ),
                "question_text": current_question.enunciado,
                "total_answers": len(current_answers),
            }
            if current_question else None
        ),
        "progress": {
            "total_answers": total_answers,
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
        "ranking_top10": overall_ranking[:10],
        "current_ranking_top10": current_ranking[:10],
        "participants": len(overall_ranking),
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
