"""Consumo de IA por cliente, somado por hora e guardado no banco.

As metricas do Prometheus respondem "como esta o sistema" e somam todos os clientes de proposito:
um rotulo por cliente criaria uma serie por cliente. A pergunta "quanto cada cliente usou" e de
negocio e precisa de historico, entao mora aqui, numa tabela com **uma linha por hora, cliente,
provedor e modelo**: meses de uso cabem em poucas linhas, e somar um periodo e barato. A hora e a
menor unidade que deixa o grafico mostrar a variacao do consumo ao longo do dia; somar por dia e por
mes sai da mesma tabela.

O cliente e o perfil de dados (`tutor_id`) da conta que fez a chamada. Ele sai do contexto de
provedores ativo (`runtime_scope()`): toda chamada a um modelo roda com o contexto do usuario ativo,
porque e dele que vem a chave, entao nenhuma rota precisa informar quem esta chamando.

A gravacao e **desligada por padrao** e ligada na subida dos processos que tem banco (a API e o
orquestrador). Assim os testes e os servicos sem banco nao tentam conectar a cada chamada.

Chamadas de agentes conectados (Codex, Claude Code) rodam na maquina do professor: o backend nao
ve os tokens. Elas entram so como contagem de chamadas, sem token e sem custo, e contam como
"sem preco" para o total nao parecer completo.

Antes da tabela por hora o consumo era guardado por dia (`llm_usage_daily`). `migrate_legacy_daily`
copia essas linhas uma vez, sem duplicar, e a tabela antiga deixa de receber gravacao.
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

from ..core.database import (
    AsyncSessionLocal,
    LLMUsageDailyModel,
    LLMUsageHourlyModel,
    UserModel,
)

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


def current_bucket(moment: datetime | None = None) -> datetime:
    """Inicio da hora (UTC, sem fuso) em que a linha de consumo e somada."""
    moment = moment or datetime.now(timezone.utc)
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment.replace(minute=0, second=0, microsecond=0)


# --- gravacao -------------------------------------------------------------------------------------


def _increments(usage: UsageRecord) -> dict[str, Any]:
    return dict(
        calls=1,
        errors=0 if usage.ok else 1,
        # Sem preco: a chamada deu certo, mas o provedor nao informou token ou nao ha preco para o
        # modelo (e o caso dos agentes conectados). Chamada que FALHOU nao entra aqui: nao ter
        # token nem custo e da natureza da falha, e ela ja e contada em `errors`.
        unpriced_calls=1 if (usage.ok and usage.estimated_cost_usd is None) else 0,
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        cached_tokens=usage.cached_tokens or 0,
        cost_usd=usage.estimated_cost_usd or 0.0,
    )


async def add_usage(
    db: AsyncSession, usage: UsageRecord, tenant_id: str, *, bucket: datetime | None = None,
) -> None:
    """Soma uma chamada na linha da hora. Atomico: dois processos podem somar ao mesmo tempo."""
    key = dict(
        bucket=current_bucket(bucket), tenant_id=(tenant_id or "")[:64],
        provider=(usage.provider or "")[:32], model=(usage.model or "")[:160])
    add = _increments(usage)
    columns = {name: getattr(LLMUsageHourlyModel, name) for name in add}
    for attempt in range(2):
        result = await db.execute(
            update(LLMUsageHourlyModel)
            .where(*(getattr(LLMUsageHourlyModel, name) == value for name, value in key.items()))
            .values(**{name: columns[name] + value for name, value in add.items()}))
        if result.rowcount:
            await db.commit()
            return
        db.add(LLMUsageHourlyModel(**key, **add))
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


# --- historico por dia (tabela antiga) -------------------------------------------------------------

_SUMS = ("calls", "errors", "unpriced_calls", "input_tokens", "output_tokens", "cached_tokens",
         "cost_usd")


async def migrate_legacy_daily(db: AsyncSession) -> int:
    """Copia o consumo por dia da tabela antiga para a por hora. Devolve quantas linhas copiou.

    Cada dia vira uma linha no inicio dele (00:00 UTC). Seguro para rodar em toda subida: so
    copia a linha cujo (hora, cliente, provedor, modelo) ainda nao existe na tabela nova, entao
    repetir nao duplica. A tabela antiga so e lida, e nao recebe mais gravacao.

    No caminho, corrige o "sem preco" do historico: a regra antiga contava toda falha como sem
    preco, e a nova so conta a chamada que deu certo e ficou sem custo. Como toda falha antiga
    foi contada, tirar `errors` de `unpriced_calls` deixa o numero certo.
    """
    legacy = (await db.execute(select(LLMUsageDailyModel))).scalars().all()
    if not legacy:
        return 0
    existing = {
        (row.bucket, row.tenant_id, row.provider, row.model or "")
        for row in (await db.execute(select(
            LLMUsageHourlyModel.bucket, LLMUsageHourlyModel.tenant_id,
            LLMUsageHourlyModel.provider, LLMUsageHourlyModel.model))).all()
    }
    copied = 0
    for old in legacy:
        try:
            bucket = datetime.strptime(old.day, "%Y-%m-%d")
        except (TypeError, ValueError):
            continue
        key = (bucket, old.tenant_id or "", old.provider, old.model or "")
        if key in existing:
            continue
        values = {name: getattr(old, name) or 0 for name in _SUMS}
        values["unpriced_calls"] = max(values["unpriced_calls"] - values["errors"], 0)
        db.add(LLMUsageHourlyModel(
            bucket=bucket, tenant_id=old.tenant_id or "", provider=old.provider,
            model=old.model or "", **values))
        existing.add(key)
        copied += 1
    if copied:
        await db.commit()
    return copied


async def migrate_legacy_on_startup() -> None:
    """Copia o historico antigo na subida. Falha (tabela ausente, banco fora) so vira aviso."""
    try:
        async with AsyncSessionLocal() as db:
            copied = await migrate_legacy_daily(db)
        if copied:
            logger.info(f"Consumo de IA: {copied} linha(s) por dia copiadas para a tabela por hora")
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Historico de consumo por dia nao copiado: {exc}")


# --- consulta -------------------------------------------------------------------------------------


def _label(group: str, key: tuple) -> str:
    if group == "model":
        return f"{key[0]}/{key[1] or 'desconhecido'}"
    return str(key[0]) or "(sem conta)"


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
    start = current_bucket().replace(hour=0) - timedelta(days=days - 1)
    day = func.date(LLMUsageHourlyModel.bucket)
    column = {
        "provider": (LLMUsageHourlyModel.provider,),
        "model": (LLMUsageHourlyModel.provider, LLMUsageHourlyModel.model),
        "day": (day,),
        "tenant": (LLMUsageHourlyModel.tenant_id,),
    }[group]
    sums = tuple(func.sum(getattr(LLMUsageHourlyModel, name)) for name in _SUMS)
    stmt = select(*column, *sums).where(LLMUsageHourlyModel.bucket >= start).group_by(*column)
    if tenant_id is not None:
        stmt = stmt.where(LLMUsageHourlyModel.tenant_id == tenant_id)

    groups: list[dict[str, Any]] = []
    total = dict(calls=0, errors=0, unpriced_calls=0, input_tokens=0, output_tokens=0,
                 cached_tokens=0, cost_usd=0.0)
    for row in (await db.execute(stmt)).all():
        key = tuple(row[:len(column)])
        values = [value or 0 for value in row[len(column):]]
        item = dict(zip(total, values))
        item["cost_usd"] = round(float(item["cost_usd"]), 6)
        groups.append({"key": str(key[0]) if group != "model" else f"{key[0]}/{key[1]}",
                       "label": _label(group, key), **item})
        for name in total:
            total[name] += item[name]
    total["cost_usd"] = round(float(total["cost_usd"]), 6)

    if group == "day":
        groups.sort(key=lambda g: g["key"])
    else:
        groups.sort(key=lambda g: (-g["cost_usd"], -(g["input_tokens"] + g["output_tokens"])))
    return {"days": days, "since": start.strftime("%Y-%m-%d"), "group_by": group, "total": total,
            "groups": groups, "estimated": True}


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
