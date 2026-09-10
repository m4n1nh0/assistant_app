"""Geracao de quiz em segundo plano, com acompanhamento e aviso no fim.

Gerar um quiz de dez perguntas com a IA leva mais do que os 30s que a interface
espera por uma resposta HTTP, e leva mais ainda agora que a geracao vai em lotes
e reescreve alternativa longa. Segurar a requisicao ate o fim significava tela
travada e timeout no cliente - e era o timeout que fazia o professor achar que a
geracao tinha falhado.

Entao a rota so registra o trabalho e devolve um `job_id`. A geracao roda em uma
task propria, a tela pergunta o andamento quando quer, e quando termina o
professor e avisado pelos canais que ele ja configurou (Telegram/WhatsApp).

A fila e de processo: reinicio do backend perde os jobs em andamento. E aceitavel
porque o quiz so vale quando termina - nao ha estado parcial para retomar - e o
professor refaz o pedido em um clique.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from loguru import logger

#: Jobs terminados guardados; passando disso, os mais antigos saem. A tela le o
#: resultado uma vez e some, entao a memoria aqui e curta de proposito.
MAX_FINISHED_JOBS = 50

#: Job terminado ha mais de isso ja foi lido (ou abandonado) e pode sair.
FINISHED_TTL = timedelta(hours=2)


@dataclass
class QuizJob:
    """Uma geracao de quiz em andamento ou terminada."""

    id: str
    tutor_id: str
    total: int
    titulo: str = ""
    status: str = "pending"  # pending | running | done | error
    prontas: int = 0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    finished_at: Optional[datetime] = None

    def report(self, prontas: int, total: Optional[int] = None) -> None:
        """Anota o andamento vindo do gerador."""
        self.prontas = max(0, int(prontas))
        if total:
            self.total = int(total)

    @property
    def message(self) -> str:
        if self.status == "done":
            return f"{self.prontas} pergunta(s) prontas para revisão."
        if self.status == "error":
            return self.error or "Não foi possível gerar o quiz."
        if self.prontas:
            return f"Escrevendo perguntas com a IA ({self.prontas}/{self.total})..."
        return "Lendo o conteúdo e preparando as perguntas..."

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.id,
            "status": self.status,
            "total": self.total,
            "prontas": self.prontas,
            "titulo": self.titulo,
            "message": self.message,
            "error": self.error,
            "quiz": self.result,
            "created_at": self.created_at.isoformat(),
            "finished_at": (
                self.finished_at.isoformat() if self.finished_at else None
            ),
        }


_jobs: Dict[str, QuizJob] = {}
_tasks: Dict[str, asyncio.Task] = {}


def _prune() -> None:
    """Descarta jobs terminados antigos, mantendo os mais recentes."""
    agora = datetime.now(timezone.utc)
    terminados = [
        job for job in _jobs.values()
        if job.finished_at is not None
    ]
    velhos = [
        job.id for job in terminados
        if agora - (job.finished_at or agora) > FINISHED_TTL
    ]
    if len(terminados) - len(velhos) > MAX_FINISHED_JOBS:
        sobrando = sorted(
            (job for job in terminados if job.id not in velhos),
            key=lambda job: job.finished_at or agora,
        )
        excedente = len(sobrando) - MAX_FINISHED_JOBS
        velhos.extend(job.id for job in sobrando[:excedente])

    for job_id in velhos:
        _jobs.pop(job_id, None)
        _tasks.pop(job_id, None)


async def _run(
    job: QuizJob,
    runner: Callable[[QuizJob], Awaitable[Dict[str, Any]]],
    notify: Optional[Callable[[QuizJob], Awaitable[None]]],
) -> None:
    job.status = "running"
    try:
        job.result = await runner(job)
        job.status = "done"
        questoes = (job.result or {}).get("questoes") or []
        job.prontas = len(questoes)
    except asyncio.CancelledError:
        job.status = "error"
        job.error = "Geração cancelada."
        raise
    except Exception as error:
        job.status = "error"
        # `detail` vem de HTTPException levantada na persistencia: e a frase que
        # ja foi escrita para o professor ler, melhor que o repr da excecao.
        job.error = str(getattr(error, "detail", None) or error)
        logger.warning(f"Geração de quiz {job.id} falhou: {job.error}")
    finally:
        job.finished_at = datetime.now(timezone.utc)
        _tasks.pop(job.id, None)
        if notify is not None:
            try:
                await notify(job)
            except Exception as error:  # aviso quebrado nao invalida o quiz
                logger.warning(f"Aviso do quiz {job.id} não saiu: {error}")
        _prune()


def submit(
    *,
    tutor_id: str,
    total: int,
    titulo: str,
    runner: Callable[[QuizJob], Awaitable[Dict[str, Any]]],
    notify: Optional[Callable[[QuizJob], Awaitable[None]]] = None,
) -> QuizJob:
    """Registra a geracao e devolve o job ja em andamento.

    Args:
        tutor_id: dono do job; so ele consegue consultar o andamento.
        total: quantas perguntas foram pedidas.
        titulo: titulo do quiz, usado na tela e no aviso.
        runner: a geracao em si; recebe o job para reportar andamento.
        notify: chamado no fim, com sucesso ou erro.

    Returns:
        O job criado, com `status` ja em `pending`.
    """
    job = QuizJob(
        id=str(uuid.uuid4()),
        tutor_id=tutor_id,
        total=max(int(total), 1),
        titulo=titulo,
    )
    _jobs[job.id] = job
    _tasks[job.id] = asyncio.create_task(_run(job, runner, notify))
    return job


def get_job(job_id: str, tutor_id: str) -> Optional[QuizJob]:
    """Devolve o job do professor, ou `None` quando nao e dele nem existe."""
    job = _jobs.get(job_id)
    if job is None or job.tutor_id != tutor_id:
        return None
    return job


def reset() -> None:
    """Limpa a fila. Existe para os testes nao vazarem job entre casos."""
    for task in _tasks.values():
        task.cancel()
    _tasks.clear()
    _jobs.clear()
