"""Armazenamento comum da agenda: uma busca ao Google ou ao Microsoft serve a todos.

Agendador (lembretes), interface (`/calendar/events` e o `calendar_sync` do WebSocket) e chat
(perguntas sobre a agenda) liam o calendario cada um por conta propria, e cada leitura era uma ida
ao provedor. Aqui fica o resultado da ultima leitura de cada conta, e quem pergunta aproveita:

- **Quem le** (`read`) aceita um resultado de ate `max_age` segundos e so vai ao provedor quando
  nao ha nenhum recente que cubra o periodo pedido.
- **Quem atualiza** (o agendador, a cada ciclo) le sempre do provedor e grava (`write`): e ele que
  mantem o armazenamento fresco para os demais.
- **Quem altera** a agenda (criar evento) invalida a conta (`invalidate`), para a proxima leitura
  ja trazer o evento novo.

O que se guarda e a lista de eventos de **uma conta** e o periodo que ela cobre, na memoria do
processo e, quando ha Redis, la tambem: o Redis e o que faz a API, o agendador e o orquestrador
(que responde as perguntas sobre agenda do chat) verem o mesmo resultado. Sem Redis cada processo
guarda o seu. A chave e um resumo (hash) da conta: o token de acesso nunca entra aqui.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from loguru import logger

from ..core.config import get_settings
from ..core.redis_client import get_client as get_redis_client
from ..models.schemas import CalendarEvent

settings = get_settings()

_KEY_PREFIX = "calendar:events"
# Tolerancia ao comparar o inicio de um periodo com o do resultado guardado: o "agora" de quem
# pede e de quem gravou diferem por milissegundos, e nao deve forcar uma ida ao provedor.
_START_SLACK_SECONDS = 60


def account_key(provider: str, account: dict) -> str:
    """Identificador estavel de uma conta de calendario, sem expor credencial."""
    raw = "|".join(
        [
            provider,
            str(account.get("client_id", "")),
            str(account.get("tenant_id", "")),
            str(account.get("refresh_token", "")),
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@dataclass
class Snapshot:
    """Resultado de uma leitura de uma conta: o periodo, o teto pedido e os eventos."""

    start: datetime
    end: datetime
    max_results: int
    fetched_at: float  # epoch, em segundos
    events: List[CalendarEvent]

    @property
    def complete(self) -> bool:
        """Verdadeiro quando o provedor devolveu menos que o teto: nao ficou evento de fora."""
        return len(self.events) < self.max_results

    def covers(self, start: datetime, end: datetime, max_results: int) -> bool:
        """Este resultado responde ao periodo pedido sem perder nenhum evento?"""
        if _aware(end) > _aware(self.end):
            return False
        if _aware(start) < _aware(self.start):
            # Pedido que comeca antes do que foi lido: o provedor pode ter eventos ali.
            if (_aware(self.start) - _aware(start)).total_seconds() > _START_SLACK_SECONDS:
                return False
        if self.complete:
            return True
        # Leitura cortada no teto: so a ponta inicial dela e confiavel.
        starts_together = (
            abs((_aware(start) - _aware(self.start)).total_seconds()) <= _START_SLACK_SECONDS
        )
        return starts_together and max_results <= self.max_results

    def select(self, start: datetime, end: datetime, max_results: int) -> List[CalendarEvent]:
        """Os eventos do periodo pedido, como o provedor os devolveria."""
        lo, hi = _aware(start), _aware(end)
        chosen = [
            event
            for event in self.events
            if _aware(event.end_time or event.start_time) > lo and _aware(event.start_time) < hi
        ]
        chosen.sort(key=lambda event: event.start_time)
        # Copias: quem recebe pode alterar (etiquetar, marcar notificado) sem sujar o guardado.
        return [event.model_copy(deep=True) for event in chosen[:max_results]]

    def to_json(self) -> str:
        return json.dumps(
            {
                "start": self.start.isoformat(),
                "end": self.end.isoformat(),
                "max_results": self.max_results,
                "fetched_at": self.fetched_at,
                "events": [event.model_dump(mode="json") for event in self.events],
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "Snapshot":
        data = json.loads(raw)
        return cls(
            start=datetime.fromisoformat(data["start"]),
            end=datetime.fromisoformat(data["end"]),
            max_results=int(data["max_results"]),
            fetched_at=float(data["fetched_at"]),
            events=[CalendarEvent.model_validate(item) for item in data["events"]],
        )


_memory: dict[str, Snapshot] = {}


def clear_memory() -> None:
    """Esvazia a memoria deste processo (testes e troca de configuracao)."""
    _memory.clear()


def _redis_key(key: str) -> str:
    return f"{_KEY_PREFIX}:{key}"


async def read(
    key: str,
    start: datetime,
    end: datetime,
    max_results: int,
    max_age: float,
) -> Optional[List[CalendarEvent]]:
    """Eventos do periodo se ha resultado guardado recente que o cubra; `None` caso contrario.

    Args:
        key: conta (`account_key`).
        start: inicio do periodo pedido.
        end: fim do periodo pedido.
        max_results: teto de eventos pedido.
        max_age: idade maxima aceita do resultado, em segundos.
    """
    now = time.time()
    snapshot = _memory.get(key)
    if snapshot is None or now - snapshot.fetched_at > max_age:
        snapshot = await _read_shared(key, now, max_age)
        if snapshot is not None:
            _memory[key] = snapshot
    if snapshot is None or now - snapshot.fetched_at > max_age:
        return None
    if not snapshot.covers(start, end, max_results):
        return None
    return snapshot.select(start, end, max_results)


async def _read_shared(key: str, now: float, max_age: float) -> Optional[Snapshot]:
    client = get_redis_client()
    if client is None:
        return None
    try:
        raw = await client.get(_redis_key(key))
        if not raw:
            return None
        snapshot = Snapshot.from_json(raw)
    except Exception as e:
        logger.debug(f"Calendar cache: leitura no Redis ignorada: {e}")
        return None
    return snapshot if now - snapshot.fetched_at <= max_age else None


async def write(
    key: str,
    start: datetime,
    end: datetime,
    max_results: int,
    events: List[CalendarEvent],
) -> None:
    """Guarda o resultado de uma leitura ao provedor, para os demais aproveitarem."""
    snapshot = Snapshot(
        start=start,
        end=end,
        max_results=max_results,
        fetched_at=time.time(),
        events=[event.model_copy(deep=True) for event in events],
    )
    _memory[key] = snapshot
    client = get_redis_client()
    if client is None:
        return
    try:
        await client.set(
            _redis_key(key), snapshot.to_json(), ex=max(60, settings.calendar_cache_ttl_seconds)
        )
    except Exception as e:
        logger.debug(f"Calendar cache: escrita no Redis ignorada: {e}")


async def invalidate(key: str) -> None:
    """Descarta o que se sabe de uma conta: a proxima leitura vai ao provedor."""
    _memory.pop(key, None)
    client = get_redis_client()
    if client is None:
        return
    try:
        await client.delete(_redis_key(key))
    except Exception as e:
        logger.debug(f"Calendar cache: invalidacao no Redis ignorada: {e}")
