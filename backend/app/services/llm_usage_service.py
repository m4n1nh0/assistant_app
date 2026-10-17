"""Consumo de IA por cliente, somado por dia e guardado no banco.

As metricas do Prometheus respondem "como esta o sistema" e somam todos os clientes de proposito:
um rotulo por cliente criaria uma serie por cliente. A pergunta "quanto cada cliente usou" e de
negocio e precisa de historico, entao mora aqui, numa tabela com **uma linha por dia, cliente,
provedor e modelo**: meses de uso cabem em poucas linhas, e somar um periodo e barato.

O cliente e o perfil de dados (`tutor_id`) da conta que fez a chamada. Ele sai do contexto de
provedores ativo (`runtime_scope()`): toda chamada a um modelo roda com o contexto do usuario ativo,
porque e dele que vem a chave, entao nenhuma rota precisa informar quem esta chamando.

A gravacao e **desligada por padrao** e ligada na subida dos processos que tem banco (a API e o
orquestrador). Assim os testes e os servicos sem banco nao tentam conectar a cada chamada.

Chamadas de agentes conectados (Codex, Claude Code) rodam na maquina do professor: o backend nao
ve os tokens. Elas entram so como contagem de chamadas, sem token e sem custo, e contam como
"sem preco" para o total nao parecer completo.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ports.telemetry import UsageRecord

from ..core.database import AsyncSessionLocal, LLMUsageDailyModel, UserModel

GROUPS = ("provider", "model", "day", "tenant")

_enabled = False
_pending: set[asyncio.Task] = set()


def enable() -> None:
    """Liga a gravacao no banco. Chamado na subida dos processos que tem banco."""
    global _enabled
    _enabled = True


def tenant_of_scope(scope: str) -> str:
    """Cliente de um escopo de provedores (`tutor:<id>`); vazio para o escopo local."""
    return scope[len("tutor:"):] if scope.startswith("tutor:") else ""


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# --- gravacao -------------------------------------------------------------------------------------


def _increments(usage: UsageRecord) -> dict[str, Any]:
    return dict(
        calls=1,
        errors=0 if usage.ok else 1,
        # Sem preco: o provedor nao informou token, ou nao ha preco para o modelo.
        unpriced_calls=1 if usage.estimated_cost_usd is None else 0,
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        cached_tokens=usage.cached_tokens or 0,
        cost_usd=usage.estimated_cost_usd or 0.0,
    )


async def add_usage(
    db: AsyncSession, usage: UsageRecord, tenant_id: str, *, day: str | None = None,
) -> None:
    """Soma uma chamada na linha do dia. Atomico: dois processos podem somar ao mesmo tempo."""
    key = dict(
        day=day or _today(), tenant_id=(tenant_id or "")[:64],
        provider=(usage.provider or "")[:32], model=(usage.model or "")[:160])
    add = _increments(usage)
    columns = {name: getattr(LLMUsageDailyModel, name) for name in add}
    for attempt in range(2):
        result = await db.execute(
            update(LLMUsageDailyModel)
            .where(*(getattr(LLMUsageDailyModel, name) == value for name, value in key.items()))
            .values(**{name: columns[name] + value for name, value in add.items()}))
        if result.rowcount:
            await db.commit()
            return
        db.add(LLMUsageDailyModel(**key, **add))
        try:
            await db.commit()
            return
        except IntegrityError:
            # Outro processo criou a linha entre o UPDATE e o INSERT: soma nela.
            await db.rollback()
            if attempt:
                raise


async def _persist(usage: UsageRecord, tenant_id: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            await add_usage(db, usage, tenant_id)
    except Exception as exc:  # noqa: BLE001 - contar consumo nunca pode derrubar a chamada
        logger.debug(f"Consumo de IA nao gravado: {exc}")


def schedule(usage: UsageRecord, tenant_id: str) -> None:
    """Grava o consumo em segundo plano, sem atrasar a resposta de quem chamou o modelo."""
    if not _enabled:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_persist(usage, tenant_id))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


def record_agent_call(provider: str, tenant_id: str, *, ok: bool = True) -> None:
    """Conta uma chamada de agente conectado (sem token nem custo: rodou fora do backend)."""
    schedule(UsageRecord(provider=provider, ok=ok), tenant_id)


# --- consulta -------------------------------------------------------------------------------------


def _label(group: str, key: tuple) -> str:
    if group == "model":
        return f"{key[0]}/{key[1] or 'desconhecido'}"
    return key[0] or "(sem conta)"


async def summarize(
    db: AsyncSession, *, days: int = 30, group_by: str = "provider", tenant_id: str | None = None,
) -> dict[str, Any]:
    """Consumo dos ultimos `days` dias, total e por grupo.

    Args:
        days: janela, contando hoje (1 a 366).
        group_by: `provider`, `model`, `day` ou `tenant`.
        tenant_id: restringe a um cliente; `None` soma todos (so para administrador).
    """
    days = max(1, min(int(days), 366))
    group = group_by if group_by in GROUPS else "provider"
    since = (datetime.now(timezone.utc) - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    column = {
        "provider": (LLMUsageDailyModel.provider,),
        "model": (LLMUsageDailyModel.provider, LLMUsageDailyModel.model),
        "day": (LLMUsageDailyModel.day,),
        "tenant": (LLMUsageDailyModel.tenant_id,),
    }[group]
    sums = (
        func.sum(LLMUsageDailyModel.calls), func.sum(LLMUsageDailyModel.errors),
        func.sum(LLMUsageDailyModel.unpriced_calls), func.sum(LLMUsageDailyModel.input_tokens),
        func.sum(LLMUsageDailyModel.output_tokens), func.sum(LLMUsageDailyModel.cached_tokens),
        func.sum(LLMUsageDailyModel.cost_usd),
    )
    stmt = select(*column, *sums).where(LLMUsageDailyModel.day >= since).group_by(*column)
    if tenant_id is not None:
        stmt = stmt.where(LLMUsageDailyModel.tenant_id == tenant_id)

    groups: list[dict[str, Any]] = []
    total = dict(calls=0, errors=0, unpriced_calls=0, input_tokens=0, output_tokens=0,
                 cached_tokens=0, cost_usd=0.0)
    for row in (await db.execute(stmt)).all():
        key = tuple(row[:len(column)])
        values = [value or 0 for value in row[len(column):]]
        item = dict(zip(total, values))
        item["cost_usd"] = round(float(item["cost_usd"]), 6)
        groups.append({"key": key[0] if group != "model" else f"{key[0]}/{key[1]}",
                       "label": _label(group, key), **item})
        for name in total:
            total[name] += item[name]
    total["cost_usd"] = round(float(total["cost_usd"]), 6)

    if group == "day":
        groups.sort(key=lambda g: g["key"])
    else:
        groups.sort(key=lambda g: (-g["cost_usd"], -(g["input_tokens"] + g["output_tokens"])))
    return {"days": days, "since": since, "group_by": group, "total": total, "groups": groups,
            "estimated": True}


async def tenant_names(db: AsyncSession, tenant_ids: list[str]) -> dict[str, str]:
    """Nome legivel de cada cliente (e-mail ou usuario da conta), para a tela do administrador."""
    ids = [t for t in tenant_ids if t]
    if not ids:
        return {}
    rows = (await db.execute(select(UserModel).where(UserModel.tutor_id.in_(ids)))).scalars().all()
    names: dict[str, str] = {}
    for user in rows:
        names.setdefault(user.tutor_id, user.email or user.username)
    return names
