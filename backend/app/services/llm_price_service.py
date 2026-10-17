"""Precos de token: leitura do banco, edicao e importacao da tabela publica.

O custo de uma chamada e `tokens x preco`. Os tokens vem do provedor e sao exatos; o preco e o que
muda. Cada cliente escolhe o proprio modelo (isso fica no banco dele), entao um preco fixo por
provedor erra para quem usa o modelo mais caro ou o mais barato. Aqui o preco e dado de banco: um
administrador edita, e a importacao traz a tabela publica da comunidade (LiteLLM), que lista o
custo por token de centenas de modelos.

Tres regras que a importacao respeita:

- **Preco digitado a mao nunca e sobrescrito.** A linha `manual` vence a importada; quem corrigiu
  um preco nao o perde na proxima sincronizacao.
- **A rede e opcional.** Sem ela, ou com a fonte fora do ar, a importacao falha com uma mensagem e
  os precos que ja estavam no banco continuam valendo.
- **A fonte e uma estimativa.** E o preco de tabela do provedor, nao o do seu contrato. O custo que
  sai daqui continua sendo uma estimativa.

O modulo `shared.observability.costs` so consulta a tabela em memoria; quem a carrega e renova e
este servico, porque aquele nao pode depender de banco (ele serve tambem a servicos sem banco).
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.observability import ModelPrice, set_db_prices

from ..core.database import AsyncSessionLocal, LLMPriceModel

#: Tabela publica de precos mantida pela comunidade (custo por token, por modelo).
SOURCE_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)

#: Provedores do app. `localai` e `llama` rodam na maquina do cliente: custam energia, nao token.
PROVIDERS = (
    "claude", "gpt", "gemini", "deepseek", "grok", "together", "openrouter", "hf",
    "localai", "llama",
)

#: Nome do provedor na fonte -> chave do provedor no app. `xai` e `groq` entram os dois em `grok`,
#: porque o app usa a mesma chave para os dois; o nome do modelo desfaz a ambiguidade.
_SOURCE_PROVIDERS = {
    "anthropic": "claude",
    "openai": "gpt",
    "gemini": "gemini",
    "deepseek": "deepseek",
    "xai": "grok",
    "groq": "grok",
    "together_ai": "together",
    "openrouter": "openrouter",
}

_PER_MTOK = 1_000_000
_REFRESH_SECONDS = 300.0
_refresher: asyncio.Task | None = None


class PriceError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# --- tabela em memoria ----------------------------------------------------------------------------


def _price_of(row: LLMPriceModel) -> ModelPrice:
    return ModelPrice(
        input_per_mtok=float(row.input_per_mtok or 0.0),
        output_per_mtok=float(row.output_per_mtok or 0.0),
        cached_input_per_mtok=(
            float(row.cached_input_per_mtok) if row.cached_input_per_mtok is not None else None
        ),
    )


async def refresh_cache(db: AsyncSession | None = None) -> int:
    """Recarrega os precos do banco para a memoria. Devolve quantos precos ha."""
    async def load(session: AsyncSession) -> list[LLMPriceModel]:
        return list((await session.execute(select(LLMPriceModel))).scalars().all())

    if db is not None:
        rows = await load(db)
    else:
        async with AsyncSessionLocal() as session:
            rows = await load(session)
    prices = {
        ((row.provider or "").lower(), (row.model or "").lower()): _price_of(row) for row in rows
    }
    set_db_prices(prices)
    return len(prices)


def start_background_refresh() -> None:
    """Carrega os precos agora e os renova a cada poucos minutos, uma vez por processo.

    A API, o orquestrador e os outros processos editam e leem o mesmo banco, mas cada um tem a
    sua memoria: sem a renovacao, um preco editado so valeria depois de reiniciar os demais.
    Falha ao ler (banco fora do ar, tabela ainda nao criada) nao derruba nada: mantem o que tinha.
    """
    global _refresher
    if _refresher is not None and not _refresher.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def run() -> None:
        while True:
            try:
                await refresh_cache()
            except Exception as exc:  # noqa: BLE001 - nunca derruba o processo
                logger.debug(f"Renovacao de precos de IA falhou: {exc}")
            await asyncio.sleep(_REFRESH_SECONDS)

    _refresher = loop.create_task(run())


# --- consulta e edicao ----------------------------------------------------------------------------


def _clean_model(value: Any) -> str:
    return " ".join(str(value or "").split()).lower()[:160]


def _clean_price(value: Any, field: str, *, required: bool = True) -> float | None:
    if value is None or value == "":
        if required:
            raise PriceError(f"Informe o preco de {field}.")
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise PriceError(f"Preco de {field} invalido.") from None
    if math.isnan(number) or math.isinf(number) or number < 0:
        raise PriceError(f"Preco de {field} deve ser zero ou maior.")
    return round(number, 6)


def price_out(row: LLMPriceModel) -> dict[str, Any]:
    return dict(
        id=row.id, provider=row.provider, model=row.model or "",
        input_per_mtok=row.input_per_mtok, output_per_mtok=row.output_per_mtok,
        cached_input_per_mtok=row.cached_input_per_mtok, source=row.source,
        updated_at=row.updated_at)


async def list_prices(
    db: AsyncSession, *, provider: str = "", source: str = "", query: str = "", limit: int = 500,
) -> list[LLMPriceModel]:
    stmt = select(LLMPriceModel)
    if provider:
        stmt = stmt.where(LLMPriceModel.provider == provider)
    if source:
        stmt = stmt.where(LLMPriceModel.source == source)
    if query.strip():
        like = f"%{query.strip().lower()}%"
        stmt = stmt.where(or_(
            func.lower(LLMPriceModel.model).like(like), func.lower(LLMPriceModel.provider).like(like)))
    stmt = stmt.order_by(LLMPriceModel.provider, LLMPriceModel.model).limit(max(1, min(limit, 2000)))
    return list((await db.execute(stmt)).scalars().all())


async def upsert_manual(
    db: AsyncSession, *, provider: str, model: str, input_per_mtok: Any, output_per_mtok: Any,
    cached_input_per_mtok: Any = None,
) -> LLMPriceModel:
    """Grava um preco digitado por um administrador (`model` vazio e o padrao do provedor)."""
    provider = (provider or "").strip().lower()
    if provider not in PROVIDERS:
        raise PriceError("Provedor desconhecido.")
    model = _clean_model(model)
    row = (await db.execute(select(LLMPriceModel).where(
        LLMPriceModel.provider == provider, LLMPriceModel.model == model))).scalar_one_or_none()
    if row is None:
        row = LLMPriceModel(provider=provider, model=model)
        db.add(row)
    row.input_per_mtok = _clean_price(input_per_mtok, "entrada")
    row.output_per_mtok = _clean_price(output_per_mtok, "saida")
    row.cached_input_per_mtok = _clean_price(cached_input_per_mtok, "cache", required=False)
    row.source = "manual"
    await db.commit()
    await db.refresh(row)
    await refresh_cache(db)
    return row


async def delete_price(db: AsyncSession, price_id: str) -> bool:
    result = await db.execute(delete(LLMPriceModel).where(LLMPriceModel.id == price_id))
    await db.commit()
    await refresh_cache(db)
    return bool(result.rowcount)


# --- importacao -----------------------------------------------------------------------------------


def parse_source(data: Any) -> list[dict[str, Any]]:
    """Linhas `(provedor, modelo, precos)` da tabela publica, so de modelos de chat do app."""
    if not isinstance(data, dict):
        raise PriceError("A tabela de precos veio num formato inesperado.", 502)
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for key, entry in data.items():
        if not isinstance(entry, dict) or entry.get("mode") != "chat":
            continue
        source_provider = entry.get("litellm_provider")
        provider = _SOURCE_PROVIDERS.get(source_provider)
        cost_in, cost_out = entry.get("input_cost_per_token"), entry.get("output_cost_per_token")
        if provider is None or cost_in is None or cost_out is None:
            continue
        model = str(key)
        prefix = f"{source_provider}/"
        if model.startswith(prefix):
            model = model[len(prefix):]
        model = _clean_model(model)
        if not model or model.startswith("ft:"):
            continue
        try:
            cached = entry.get("cache_read_input_token_cost")
            row = dict(
                provider=provider, model=model,
                input_per_mtok=round(float(cost_in) * _PER_MTOK, 6),
                output_per_mtok=round(float(cost_out) * _PER_MTOK, 6),
                cached_input_per_mtok=(
                    round(float(cached) * _PER_MTOK, 6) if cached is not None else None),
            )
        except (TypeError, ValueError):
            continue
        rows.setdefault((provider, model), row)
    return list(rows.values())


async def fetch_source() -> Any:
    """Baixa a tabela publica. Falha de rede vira `PriceError` com a causa."""
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(SOURCE_URL)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise PriceError(f"Nao consegui baixar a tabela de precos: {exc}", 502) from exc


async def sync_from_source(
    db: AsyncSession, *, fetch: Callable[[], Awaitable[Any]] = fetch_source,
) -> dict[str, int]:
    """Importa a tabela publica, sem tocar nos precos digitados a mao."""
    incoming = parse_source(await fetch())
    existing = {
        (row.provider, row.model or ""): row
        for row in (await db.execute(select(LLMPriceModel))).scalars().all()
    }
    added = updated = kept_manual = 0
    for item in incoming:
        row = existing.get((item["provider"], item["model"]))
        if row is None:
            db.add(LLMPriceModel(source="litellm", **item))
            added += 1
        elif row.source == "manual":
            kept_manual += 1
        elif (row.input_per_mtok, row.output_per_mtok, row.cached_input_per_mtok) != (
            item["input_per_mtok"], item["output_per_mtok"], item["cached_input_per_mtok"]
        ):
            row.input_per_mtok = item["input_per_mtok"]
            row.output_per_mtok = item["output_per_mtok"]
            row.cached_input_per_mtok = item["cached_input_per_mtok"]
            updated += 1
    await db.commit()
    await refresh_cache(db)
    return {"models_in_source": len(incoming), "added": added, "updated": updated,
            "kept_manual": kept_manual}
