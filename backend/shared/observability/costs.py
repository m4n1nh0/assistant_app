"""Estimativa de custo das chamadas de IA.

O preco de token nao pertence ao codigo: muda sem aviso e e diferente por
contrato. Por isso a tabela daqui e so um ponto de partida, sobrescrevivel por
`LLM_PRICING` no ambiente, e o custo sai sempre marcado como *estimado*.

Provedor que nao informa token nenhum fica com custo `None`, e nao zero. Somar
ausencia como zero produziria um relatorio que parece barato e esta errado.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from loguru import logger

from ...ports.telemetry import UsageRecord


@dataclass(frozen=True)
class ModelPrice:
    """Preco em dolar por milhao de tokens."""

    input_per_mtok: float
    output_per_mtok: float
    cached_input_per_mtok: float | None = None


# Referencia de ordem de grandeza por provedor, usada quando nao ha preco
# especifico do modelo. Modelo local custa energia, nao token: fica zerado de
# proposito para o relatorio mostrar a economia de rotear para ele.
_DEFAULT_PRICING: dict[str, ModelPrice] = {
    "claude": ModelPrice(3.0, 15.0, 0.30),
    "gpt": ModelPrice(2.5, 10.0, 1.25),
    "gemini": ModelPrice(0.075, 0.30),
    "deepseek": ModelPrice(0.27, 1.10, 0.07),
    "grok": ModelPrice(2.0, 10.0),
    "together": ModelPrice(0.88, 0.88),
    "openrouter": ModelPrice(1.0, 3.0),
    "hf": ModelPrice(0.20, 0.20),
    "localai": ModelPrice(0.0, 0.0),
    "llama": ModelPrice(0.0, 0.0),
}

_overrides: dict[str, ModelPrice] = {}


def load_pricing_overrides(raw: str) -> None:
    """Carrega precos declarados no ambiente.

    Aceita `{"claude": {"input": 3.0, "output": 15.0, "cached_input": 0.3}}` e
    tambem a chave mais especifica `"provider:modelo"`. JSON invalido vira
    warning e mantem a tabela padrao - preco errado no ambiente nao pode
    impedir o backend de subir.

    Args:
        raw: conteudo de `LLM_PRICING`.
    """
    _overrides.clear()
    text = (raw or "").strip()
    if not text:
        return
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning(f"LLM_PRICING nao e JSON valido: {exc}")
        return
    if not isinstance(parsed, dict):
        logger.warning("LLM_PRICING deve ser um objeto")
        return
    for key, value in parsed.items():
        if not isinstance(value, dict):
            continue
        try:
            _overrides[str(key).lower()] = ModelPrice(
                input_per_mtok=float(value.get("input", 0.0)),
                output_per_mtok=float(value.get("output", 0.0)),
                cached_input_per_mtok=(
                    float(value["cached_input"])
                    if value.get("cached_input") is not None
                    else None
                ),
            )
        except (TypeError, ValueError):
            logger.warning(f"LLM_PRICING: preco invalido para {key}")


def price_for(provider: str, model: str = "") -> ModelPrice | None:
    """Preco aplicavel, preferindo a chave `provider:modelo` a chave do provedor."""
    provider_key = (provider or "").lower()
    if model:
        specific = _overrides.get(f"{provider_key}:{model.lower()}")
        if specific is not None:
            return specific
    return _overrides.get(provider_key) or _DEFAULT_PRICING.get(provider_key)


def estimate_cost(
    provider: str,
    model: str = "",
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cached_tokens: int | None = None,
) -> float | None:
    """Custo estimado de uma chamada, em dolar.

    Args:
        provider: chave do provedor.
        model: modelo efetivamente usado, quando conhecido.
        input_tokens: tokens de entrada informados pelo provedor.
        output_tokens: tokens de saida informados pelo provedor.
        cached_tokens: tokens de entrada servidos de cache, quando informados.

    Returns:
        O custo estimado, ou `None` quando nao ha preco conhecido ou o provedor
        nao informou token algum.
    """
    price = price_for(provider, model)
    if price is None:
        return None
    if input_tokens is None and output_tokens is None:
        return None

    billed_input = max(0, (input_tokens or 0) - (cached_tokens or 0))
    total = billed_input * price.input_per_mtok / 1_000_000
    total += (output_tokens or 0) * price.output_per_mtok / 1_000_000
    if cached_tokens:
        cached_rate = (
            price.cached_input_per_mtok
            if price.cached_input_per_mtok is not None
            else price.input_per_mtok
        )
        total += cached_tokens * cached_rate / 1_000_000
    return round(total, 8)


def build_usage(
    provider: str,
    *,
    model: str = "",
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cached_tokens: int | None = None,
    total_tokens: int | None = None,
    duration_ms: float = 0.0,
    agent_id: str = "",
    tool_name: str = "",
    ok: bool = True,
    correlation: dict[str, str] | None = None,
) -> UsageRecord:
    """Monta o `UsageRecord` de uma chamada, ja com o custo estimado."""
    resolved_total = total_tokens
    if resolved_total is None and (
        input_tokens is not None or output_tokens is not None
    ):
        resolved_total = (input_tokens or 0) + (output_tokens or 0)
    return UsageRecord(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        total_tokens=resolved_total,
        duration_ms=duration_ms,
        estimated_cost_usd=estimate_cost(
            provider,
            model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
        ),
        agent_id=agent_id,
        tool_name=tool_name,
        ok=ok,
        correlation=dict(correlation or {}),
    )
