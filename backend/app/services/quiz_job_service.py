"""Fila de geracao de quiz: persistente, uma geracao por professor por vez.

Gerar um quiz leva minutos - lotes de perguntas, reescrita de alternativa
longa, varios provedores tentados. Por isso a rota so enfileira e devolve o
pedido; quem gera e um worker em segundo plano, e o professor acompanha pela
central de quizzes e e avisado no fim.

Tres decisoes que moldam este modulo:

- **Fila no banco** (`quiz_jobs`). A fila em memoria sumia a cada deploy ou
  reinicio: o professor pedia o quiz, o processo reiniciava e o pedido
  desaparecia sem aviso. No banco, o que estava rodando volta para a fila na
  subida (`recover`) e e gerado de novo.
- **Uma geracao por professor.** Pedidos seguintes esperam na ordem. Rodar
  varias ao mesmo tempo multiplica as chamadas aos provedores e e o caminho
  mais curto para estourar limite de taxa e credito - justamente o que mais
  derruba geracao hoje. Professores diferentes nao esperam um pelo outro.
- **Processo unico.** O worker vive no processo da API. Com mais de uma replica,
  duas poderiam pegar o mesmo pedido; a troca de estado e condicional
  (`queued -> running` so se ainda estiver `queued`), o que evita a geracao
  dupla, mas a fila foi desenhada para uma replica.

O que gerar de fato fica fora daqui: o modulo recebe um `runner` e um
`notifier`, e a rota de educacao os configura. E o que deixa a fila testavel
sem IA.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..core.database import AsyncSessionLocal, QuizJobModel

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
ERROR = "error"
CANCELED = "canceled"

ACTIVE_STATUSES = (QUEUED, RUNNING)
FINISHED_STATUSES = (DONE, ERROR, CANCELED)

#: Quantos pedidos a central lista por padrao.
DEFAULT_LIST_LIMIT = 50

#: Recebe (prontas, total) do gerador.
ProgressFn = Callable[[int, int], None]
#: Gera o quiz do pedido e devolve {quiz_id, prontas, message, attempts}.
Runner = Callable[[QuizJobModel, ProgressFn], Awaitable[Dict[str, Any]]]
#: Avisa o professor pelos canais externos quando o pedido termina.
Notifier = Callable[[QuizJobModel], Awaitable[None]]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def job_message(job: QuizJobModel, *, position: Optional[int] = None, prontas: Optional[int] = None) -> str:
    """A frase que a central mostra para o estado do pedido."""
    feitas = job.prontas if prontas is None else prontas
    if job.status == QUEUED:
        if position and position > 1:
            return f"Na fila: {position - 1} pedido(s) antes deste."
        return "Na fila: começa assim que a geração atual terminar."
    if job.status == RUNNING:
        if feitas:
            return f"Escrevendo perguntas com a IA ({feitas}/{job.total})..."
        return "Lendo o conteúdo e preparando as perguntas..."
    if job.status == DONE:
        return job.message or f"{feitas} pergunta(s) prontas para revisão."
    if job.status == CANCELED:
        return "Geração cancelada."
    return job.error or "Não foi possível gerar o quiz."


def job_to_dict(
    job: QuizJobModel,
    *,
    position: Optional[int] = None,
    prontas: Optional[int] = None,
) -> Dict[str, Any]:
    """O pedido no formato que a interface consome."""
    feitas = job.prontas if prontas is None else prontas
    try:
        attempts = json.loads(job.attempts_json or "[]")
    except (TypeError, ValueError):
        attempts = []
    return {
        "job_id": job.id,
        "status": job.status,
        "titulo": job.titulo,
        "total": job.total,
        "prontas": feitas,
        "position": position,
        "message": job_message(job, position=position, prontas=feitas),
        "error": job.error,
        "quiz_id": job.quiz_id,
        "attempts": attempts,
        "created_at": _iso(job.created_at),
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
        "seen": job.seen_at is not None,
        "can_cancel": job.status in ACTIVE_STATUSES,
        "can_retry": job.status in (ERROR, CANCELED),
        "can_review": job.status == DONE and bool(job.quiz_id),
    }


class QuizQueue:
    """A fila de geracao, com um worker por professor."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
        *,
        runner: Optional[Runner] = None,
        notifier: Optional[Notifier] = None,
    ) -> None:
        self._sessions = session_factory
        self._runner = runner
        self._notifier = notifier
        self._workers: Dict[str, asyncio.Task] = {}
        self._running: Dict[str, asyncio.Task] = {}
        self._progress: Dict[str, int] = {}
        self._cancel_requested: set[str] = set()

    def configure(self, *, runner: Runner, notifier: Optional[Notifier] = None) -> None:
        """Define quem gera e quem avisa. Chamado uma vez, pela rota de educacao."""
        self._runner = runner
        self._notifier = notifier

    # --- pedidos -------------------------------------------------------------

    async def enqueue(
        self,
        *,
        tutor_id: str,
        user_id: str,
        titulo: str,
        total: int,
        request: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Grava o pedido na fila e acorda o worker do professor."""
        async with self._sessions() as db:
            job = QuizJobModel(
                id=str(uuid.uuid4()),
                created_at=_now(),
                tutor_id=tutor_id,
                user_id=user_id or "",
                titulo=(titulo or "Quiz")[:255],
                status=QUEUED,
                total=max(int(total), 1),
                request_json=json.dumps(request, ensure_ascii=False),
            )
            db.add(job)
            await db.commit()
        self.kick(tutor_id)
        return await self._describe(job)

    async def list_jobs(self, tutor_id: str, *, limit: int = DEFAULT_LIST_LIMIT) -> List[Dict[str, Any]]:
        """Pedidos do professor: ativos primeiro, depois os mais recentes."""
        async with self._sessions() as db:
            rows = (await db.execute(
                select(QuizJobModel)
                .where(QuizJobModel.tutor_id == tutor_id)
                .order_by(QuizJobModel.created_at.desc())
                .limit(max(1, min(limit, 200)))
            )).scalars().all()
        positions = self._positions(rows)
        ordem = {RUNNING: 0, QUEUED: 1}
        rows = sorted(rows, key=lambda job: (ordem.get(job.status, 2), -_ts(job.created_at)))
        return [
            job_to_dict(job, position=positions.get(job.id), prontas=self._progress.get(job.id))
            for job in rows
        ]

    async def get(self, job_id: str, tutor_id: str) -> Optional[Dict[str, Any]]:
        job = await self._load(job_id, tutor_id)
        return await self._describe(job) if job else None

    async def cancel(self, job_id: str, tutor_id: str) -> Optional[Dict[str, Any]]:
        """Cancela pedido na fila ou em andamento. Terminado fica como esta."""
        async with self._sessions() as db:
            job = await db.get(QuizJobModel, job_id)
            if job is None or job.tutor_id != tutor_id:
                return None
            if job.status == QUEUED:
                job.status = CANCELED
                job.finished_at = _now()
                await db.commit()
                return await self._describe(job)
            if job.status != RUNNING:
                return await self._describe(job)

        task = self._running.get(job_id)
        if task is None:
            # Rodando no banco, mas sem task neste processo: sobra de reinicio
            # que o `recover` ainda nao pegou. Encerrar direto e o que resta.
            await self._finish(job_id, status=CANCELED)
        else:
            self._cancel_requested.add(job_id)
            task.cancel()
            # Espera o worker gravar o cancelamento, para a resposta ja sair com
            # o estado final - e nao com "running" de um pedido que parou.
            for _ in range(100):
                if job_id not in self._running:
                    break
                await asyncio.sleep(0.05)
        job = await self._load(job_id, tutor_id)
        return await self._describe(job) if job else None

    async def retry(self, job_id: str, tutor_id: str) -> Optional[Dict[str, Any]]:
        """Enfileira de novo um pedido que falhou ou foi cancelado."""
        job = await self._load(job_id, tutor_id)
        if job is None:
            return None
        if job.status not in (ERROR, CANCELED):
            raise ValueError("Só dá para tentar de novo um pedido que falhou ou foi cancelado.")
        return await self.enqueue(
            tutor_id=job.tutor_id,
            user_id=job.user_id,
            titulo=job.titulo,
            total=job.total,
            request=json.loads(job.request_json or "{}"),
        )

    async def mark_seen(self, tutor_id: str, job_ids: Sequence[str]) -> int:
        """Marca avisos de fim como vistos; devolve quantos mudaram."""
        ids = [item for item in job_ids if item]
        if not ids:
            return 0
        async with self._sessions() as db:
            result = await db.execute(
                update(QuizJobModel)
                .where(
                    QuizJobModel.tutor_id == tutor_id,
                    QuizJobModel.id.in_(ids),
                    QuizJobModel.status.in_(FINISHED_STATUSES),
                    QuizJobModel.seen_at.is_(None),
                )
                .values(seen_at=_now())
            )
            await db.commit()
        return int(result.rowcount or 0)

    # --- ciclo de vida ------------------------------------------------------

    async def recover(self) -> int:
        """Na subida: devolve a fila o que estava rodando e acorda os workers.

        Um pedido `running` no banco sem processo que o execute e sobra de
        reinicio. Gerar de novo do zero e seguro: nada do quiz e gravado ate a
        geracao terminar.
        """
        async with self._sessions() as db:
            await db.execute(
                update(QuizJobModel)
                .where(QuizJobModel.status == RUNNING)
                .values(status=QUEUED, started_at=None, prontas=0)
            )
            await db.commit()
            tutors = (await db.execute(
                select(QuizJobModel.tutor_id)
                .where(QuizJobModel.status == QUEUED)
                .distinct()
            )).scalars().all()
        for tutor_id in tutors:
            self.kick(tutor_id)
        if tutors:
            logger.info(f"Fila de quiz retomada para {len(tutors)} professor(es)")
        return len(tutors)

    async def shutdown(self) -> None:
        """No encerramento: para os workers sem marcar erro.

        O que estava rodando fica `running` no banco e volta para a fila no
        proximo `recover`.
        """
        workers = list(self._workers.values())
        for task in workers:
            task.cancel()
        for task in workers:
            try:
                await task
            except BaseException:
                pass
        self._workers.clear()
        self._running.clear()

    async def wait_idle(self, tutor_id: str) -> None:
        """Espera o worker do professor esvaziar a fila. Usado nos testes."""
        while (task := self._workers.get(tutor_id)) is not None:
            await asyncio.shield(task)

    def kick(self, tutor_id: str) -> None:
        """Garante um worker vivo para o professor."""
        task = self._workers.get(tutor_id)
        if task is not None and not task.done():
            return
        self._workers[tutor_id] = asyncio.create_task(self._work(tutor_id))

    # --- worker -------------------------------------------------------------

    async def _work(self, tutor_id: str) -> None:
        current = asyncio.current_task()
        try:
            while True:
                job = await self._claim_next(tutor_id)
                if job is None:
                    break
                await self._execute(job)
        finally:
            if self._workers.get(tutor_id) is current:
                self._workers.pop(tutor_id, None)
        # Pedido que chegou entre a ultima busca e a saida do worker ficaria
        # parado ate o proximo pedido: conferir de novo fecha essa janela.
        if await self._has_queued(tutor_id):
            self.kick(tutor_id)

    async def _claim_next(self, tutor_id: str) -> Optional[QuizJobModel]:
        async with self._sessions() as db:
            candidate = (await db.execute(
                select(QuizJobModel)
                .where(QuizJobModel.tutor_id == tutor_id, QuizJobModel.status == QUEUED)
                .order_by(QuizJobModel.created_at)
                .limit(1)
            )).scalars().first()
            if candidate is None:
                return None
            claimed = await db.execute(
                update(QuizJobModel)
                .where(QuizJobModel.id == candidate.id, QuizJobModel.status == QUEUED)
                .values(status=RUNNING, started_at=_now(), prontas=0)
            )
            await db.commit()
            if not claimed.rowcount:
                # Outro processo pegou antes: tenta o proximo.
                return await self._claim_next(tutor_id)
            candidate.status = RUNNING
            candidate.prontas = 0
            return candidate

    async def _execute(self, job: QuizJobModel) -> None:
        if self._runner is None:
            await self._finish(job.id, status=ERROR, error="Fila de quiz sem gerador configurado.")
            return

        def progress(prontas: int, total: int) -> None:
            self._progress[job.id] = max(0, int(prontas))

        task = asyncio.create_task(self._runner(job, progress))
        self._running[job.id] = task
        try:
            result = await task
        except asyncio.CancelledError:
            if job.id in self._cancel_requested:
                await self._finish(job.id, status=CANCELED)
            else:
                # Encerramento do processo: fica `running` e volta no recover.
                task.cancel()
                raise
        except Exception as error:
            mensagem = str(getattr(error, "detail", None) or error) or "Falha desconhecida."
            logger.warning(f"Geração de quiz {job.id} falhou: {mensagem}")
            await self._finish(job.id, status=ERROR, error=mensagem)
        else:
            await self._finish(
                job.id,
                status=DONE,
                quiz_id=str(result.get("quiz_id") or "") or None,
                prontas=int(result.get("prontas") or 0),
                message=str(result.get("message") or ""),
                attempts=result.get("attempts") or [],
            )
        finally:
            self._running.pop(job.id, None)
            self._progress.pop(job.id, None)
            self._cancel_requested.discard(job.id)

    async def _finish(
        self,
        job_id: str,
        *,
        status: str,
        error: Optional[str] = None,
        quiz_id: Optional[str] = None,
        prontas: Optional[int] = None,
        message: Optional[str] = None,
        attempts: Optional[list] = None,
    ) -> None:
        async with self._sessions() as db:
            job = await db.get(QuizJobModel, job_id)
            if job is None:
                return
            job.status = status
            job.finished_at = _now()
            job.error = error
            if quiz_id is not None:
                job.quiz_id = quiz_id
            if prontas is not None:
                job.prontas = prontas
            if message is not None:
                job.message = message
            if attempts is not None:
                job.attempts_json = json.dumps(attempts, ensure_ascii=False, default=str)
            await db.commit()

        # Cancelamento foi pedido pelo proprio professor: nao ha o que avisar.
        if status == CANCELED or self._notifier is None:
            return
        try:
            await self._notifier(job)
        except Exception as problem:  # aviso quebrado nao invalida o quiz
            logger.warning(f"Aviso do quiz {job_id} não saiu: {problem}")

    # --- leitura ------------------------------------------------------------

    async def _load(self, job_id: str, tutor_id: str) -> Optional[QuizJobModel]:
        async with self._sessions() as db:
            job = await db.get(QuizJobModel, job_id)
        if job is None or job.tutor_id != tutor_id:
            return None
        return job

    async def _has_queued(self, tutor_id: str) -> bool:
        async with self._sessions() as db:
            found = (await db.execute(
                select(QuizJobModel.id)
                .where(QuizJobModel.tutor_id == tutor_id, QuizJobModel.status == QUEUED)
                .limit(1)
            )).scalars().first()
        return found is not None

    async def _describe(self, job: QuizJobModel) -> Dict[str, Any]:
        position = None
        if job.status == QUEUED:
            async with self._sessions() as db:
                active = (await db.execute(
                    select(QuizJobModel)
                    .where(
                        QuizJobModel.tutor_id == job.tutor_id,
                        QuizJobModel.status.in_(ACTIVE_STATUSES),
                    )
                )).scalars().all()
            position = self._positions(active).get(job.id)
        return job_to_dict(job, position=position, prontas=self._progress.get(job.id))

    @staticmethod
    def _positions(jobs: Sequence[QuizJobModel]) -> Dict[str, int]:
        """Posicao de cada pedido na fila, contando o que esta gerando como 1."""
        running = [job for job in jobs if job.status == RUNNING]
        queued = sorted(
            (job for job in jobs if job.status == QUEUED),
            key=lambda job: _ts(job.created_at),
        )
        offset = 1 if running else 0
        return {job.id: index + 1 + offset for index, job in enumerate(queued)}


def _ts(value: Optional[datetime]) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


#: A fila do processo.
queue = QuizQueue()
