"""Métricas OpenTelemetry: tokens, custo, chamadas, duração e requisições.

O que isto protege: o endpoint OTLP vale para traces e métricas com um valor só, o consumo de
toda chamada a modelo (não só a do chat) vira métrica uma única vez, o que o provedor não
informou não vira zero, e os rótulos ficam nos de baixa cardinalidade.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("opentelemetry.sdk.metrics")

from opentelemetry.sdk.metrics.export import InMemoryMetricReader  # noqa: E402

from app.models.schemas import LLMResponse  # noqa: E402
from app.services import llm_service  # noqa: E402
from shared.observability import (  # noqa: E402
    build_usage,
    configure_sink,
    otel,
    record_usage,
)
from shared.observability.sinks import InMemorySink  # noqa: E402


@pytest.fixture
def reader():
    leitor = InMemoryMetricReader()
    assert otel._setup_metrics(service_name="teste", endpoint="", reader=leitor)
    yield leitor
    otel._instruments.clear()
    otel._meter_provider = None


def pontos(reader, nome):
    """Pontos de dados de uma métrica: lista de (rótulos, valor)."""
    dados = reader.get_metrics_data()
    encontrados = []
    for recurso in dados.resource_metrics if dados else []:
        for escopo in recurso.scope_metrics:
            for metrica in escopo.metrics:
                if metrica.name == nome:
                    for ponto in metrica.data.data_points:
                        valor = getattr(ponto, "value", None)
                        if valor is None:
                            valor = ponto.sum  # histograma: soma das observações
                        encontrados.append((dict(ponto.attributes), valor))
    return encontrados


# --- endpoint ----------------------------------------------------------------------------------


@pytest.mark.parametrize("valor", [
    "http://collector:4318",
    "http://collector:4318/",
    "http://collector:4318/v1/traces",
    "http://collector:4318/v1/metrics",
])
def test_o_mesmo_endpoint_serve_a_traces_e_a_metricas(valor):
    assert otel.signal_url(valor, "traces") == "http://collector:4318/v1/traces"
    assert otel.signal_url(valor, "metrics") == "http://collector:4318/v1/metrics"


# --- consumo de modelo -------------------------------------------------------------------------


def test_chamada_a_modelo_vira_tokens_custo_chamada_e_duracao(reader):
    record_usage(build_usage(
        "claude", model="sonnet", input_tokens=1000, output_tokens=500, cached_tokens=200,
        duration_ms=1200.0))

    rotulos = {"provider": "claude", "model": "sonnet"}
    tokens = dict((p[0]["type"], p[1]) for p in pontos(reader, "assistant.llm.tokens"))
    assert tokens == {"input": 1000, "output": 500, "cached": 200}
    assert pontos(reader, "assistant.llm.calls") == [({**rotulos, "ok": "true"}, 1)]
    assert pontos(reader, "assistant.llm.duration") == [(rotulos, 1200.0)]
    assert pontos(reader, "assistant.llm.cost.usd")[0][1] > 0


def test_o_que_o_provedor_nao_informou_nao_vira_zero(reader):
    record_usage(build_usage("localai", model="", duration_ms=50.0))

    assert pontos(reader, "assistant.llm.tokens") == []
    assert pontos(reader, "assistant.llm.cost.usd") == []
    # A chamada e a duracao existem, e o modelo desconhecido tem um rotulo legivel.
    assert pontos(reader, "assistant.llm.calls")[0][0]["model"] == "desconhecido"


def test_chamada_com_erro_e_contada_como_falha(reader):
    record_usage(build_usage("gpt", model="x", ok=False))

    assert pontos(reader, "assistant.llm.calls")[0][0]["ok"] == "false"


def test_rotulos_nao_carregam_conversa_nem_requisicao(reader):
    record_usage(build_usage(
        "claude", model="sonnet", input_tokens=1, agent_id="a1",
        correlation={"conversation_id": "c-123", "request_id": "r-9"}))

    for nome in ("assistant.llm.tokens", "assistant.llm.calls"):
        for rotulos, _ in pontos(reader, nome):
            assert not ({"conversation_id", "request_id", "agent_id"} & set(rotulos))


# --- por onde a chamada passa ------------------------------------------------------------------


def test_toda_chamada_pelo_dispatch_single_e_contada_uma_vez(reader, monkeypatch):
    async def falso(message, history, system, **kwargs):
        return LLMResponse(
            llm="claude", content="ok", model="sonnet", input_tokens=10, output_tokens=5,
            duration_ms=7)

    monkeypatch.setitem(llm_service.LLM_CALLERS, "claude", falso)
    memoria = InMemorySink()
    configure_sink(memoria, memory=memoria)

    resposta = asyncio.run(llm_service.dispatch_single("claude", "oi", [], "sistema"))

    assert resposta.content == "ok"
    assert pontos(reader, "assistant.llm.calls") == [
        ({"provider": "claude", "model": "sonnet", "ok": "true"}, 1)]
    assert len(memoria.usage()) == 1


def test_o_multi_conta_cada_provedor_consultado(reader, monkeypatch):
    async def falso(message, history, system, **kwargs):
        return LLMResponse(llm="x", content="ok", model="m", input_tokens=1)

    monkeypatch.setitem(llm_service.LLM_CALLERS, "claude", falso)
    monkeypatch.setitem(llm_service.LLM_CALLERS, "gpt", falso)

    asyncio.run(llm_service.dispatch_multi(["claude", "gpt"], "oi", [], "sistema"))

    assert sum(v for _, v in pontos(reader, "assistant.llm.calls")) == 2


# --- HTTP --------------------------------------------------------------------------------------


def test_requisicao_http_mede_a_duracao_pela_rota(reader):
    otel.record_http_metric("GET", "/education/materials/{material_id}", 200, 35.0)

    assert pontos(reader, "assistant.http.request.duration") == [
        ({"http.method": "GET", "http.route": "/education/materials/{material_id}",
          "http.status_code": 200}, 35.0)]


def test_sem_metricas_ligadas_nada_quebra():
    otel._instruments.clear()

    otel.record_http_metric("GET", "/x", 200, 1.0)
    record_usage(build_usage("claude", input_tokens=1))
