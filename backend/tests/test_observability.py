"""Correlacao, tracing e telemetria de custo.

A promessa da camada de observabilidade tem duas metades. A primeira e util:
identificadores que atravessam API, grafo, agente, tool e MCP, e consumo que
vira custo agregavel. A segunda e uma garantia negativa, e e a que mais precisa
de teste: **observar nunca pode mudar o que estava sendo observado**. Sink que
levanta excecao, provedor que nao informa token, SDK ausente - nada disso pode
alterar o resultado.
"""

import asyncio

import pytest

from app.core.observability import (
    InMemorySink,
    ObservabilityContext,
    bind,
    build_usage,
    configure_sink,
    context_from_headers,
    current_context,
    default_sink,
    estimate_cost,
    load_pricing_overrides,
    parse_traceparent,
    record_usage,
    set_context,
    span,
)
from app.core.observability.context import REQUEST_ID_HEADER, TRACEPARENT_HEADER

pytestmark = pytest.mark.unit


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def memory() -> InMemorySink:
    sink, window = default_sink()
    configure_sink(sink, memory=window)
    yield window
    window.clear()


# --- Correlacao -------------------------------------------------------------


def test_context_is_created_when_the_caller_sends_nothing():
    context = context_from_headers({})

    assert context.request_id
    assert len(context.trace_id) == 32


def test_incoming_traceparent_is_continued():
    trace_id = "a" * 32
    span_id = "b" * 16
    context = context_from_headers(
        {TRACEPARENT_HEADER: f"00-{trace_id}-{span_id}-01"}
    )

    assert context.trace_id == trace_id
    assert context.span_id == span_id


def test_malformed_traceparent_starts_a_new_trace():
    """Telemetria quebrada nao pode recusar a requisicao."""
    context = context_from_headers({TRACEPARENT_HEADER: "lixo"})

    assert len(context.trace_id) == 32
    assert parse_traceparent("lixo") == ("", "")


def test_request_id_is_reused_when_the_caller_sends_one():
    context = context_from_headers({REQUEST_ID_HEADER: "req-123"})

    assert context.request_id == "req-123"


def test_headers_carry_the_context_to_another_service():
    context = ObservabilityContext(
        request_id="req-1",
        trace_id="c" * 32,
        span_id="d" * 16,
        conversation_id="sessao-1",
        execution_id="exec-1",
    )

    headers = context.headers()

    assert headers[REQUEST_ID_HEADER] == "req-1"
    assert headers[TRACEPARENT_HEADER].startswith(f"00-{'c' * 32}-")
    assert headers["X-Conversation-ID"] == "sessao-1"


def test_bind_adds_fields_and_restores_them_afterwards():
    token = set_context(ObservabilityContext(request_id="req-1"))
    try:
        with bind(agent_id="code"):
            assert current_context().agent_id == "code"
            assert current_context().request_id == "req-1"
        assert current_context().agent_id == ""
    finally:
        from app.core.observability import reset_context

        reset_context(token)


def test_bind_ignores_empty_fields():
    """`bind(agent_id="")` nao pode apagar o agente que ja estava no contexto."""
    token = set_context(ObservabilityContext(agent_id="calendar"))
    try:
        with bind(agent_id=""):
            assert current_context().agent_id == "calendar"
    finally:
        from app.core.observability import reset_context

        reset_context(token)


# --- Spans ------------------------------------------------------------------


def test_span_records_a_successful_operation(memory):
    async def work():
        async with span("tool.echo", "tool", tool="echo") as observed:
            observed.set(source="local")

    run(work())

    record = memory.spans()[-1]
    assert record.name == "tool.echo"
    assert record.ok is True
    assert record.attributes["source"] == "local"


def test_span_marks_an_exception_and_lets_it_through(memory):
    async def work():
        async with span("tool.boom", "tool"):
            raise RuntimeError("estourou")

    with pytest.raises(RuntimeError):
        run(work())

    record = memory.spans()[-1]
    assert record.ok is False
    assert "estourou" in record.error


def test_span_carries_the_correlation_ids(memory):
    async def work():
        with bind(execution_id="exec-9", agent_id="study"):
            async with span("agent.study", "agent"):
                pass

    run(work())

    assert memory.spans()[-1].correlation["execution_id"] == "exec-9"


def test_a_failing_sink_does_not_break_the_operation():
    class _Broken:
        def record_span(self, span):
            raise RuntimeError("sink quebrado")

        def record_usage(self, usage):
            raise RuntimeError("sink quebrado")

    configure_sink(_Broken())

    async def work():
        async with span("tool.echo", "tool"):
            return "resultado"

    # O valor volta intacto: o sink quebrado nao virou excecao no caminho util.
    assert run(work()) == "resultado"


# --- Custo ------------------------------------------------------------------


def test_cost_is_estimated_from_the_reported_tokens():
    cost = estimate_cost(
        "claude", "claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0
    )

    assert cost == pytest.approx(3.0)


def test_cost_is_unknown_when_the_provider_reports_nothing():
    """Ausencia de dado nao pode virar custo zero num relatorio."""
    assert estimate_cost("claude") is None


def test_local_providers_cost_nothing():
    assert estimate_cost("llama", input_tokens=1000, output_tokens=1000) == 0.0


def test_unknown_provider_has_no_price():
    assert estimate_cost("provedor-novo", input_tokens=10) is None


def test_cached_tokens_are_billed_at_the_cached_rate():
    full = estimate_cost("claude", input_tokens=1_000_000, output_tokens=0)
    cached = estimate_cost(
        "claude", input_tokens=1_000_000, output_tokens=0, cached_tokens=1_000_000
    )

    assert cached < full


def test_pricing_can_be_overridden_by_configuration():
    load_pricing_overrides('{"llama": {"input": 1.0, "output": 2.0}}')
    try:
        assert estimate_cost("llama", input_tokens=1_000_000) == pytest.approx(1.0)
    finally:
        load_pricing_overrides("")


def test_invalid_pricing_configuration_keeps_the_defaults():
    load_pricing_overrides("{nao e json}")

    assert estimate_cost("llama", input_tokens=1000) == 0.0


def test_usage_is_aggregated_by_provider(memory):
    for provider in ("claude", "claude", "llama"):
        record_usage(
            build_usage(provider, input_tokens=1000, output_tokens=500)
        )

    summary = memory.summarize(group_by="provider")

    assert summary["groups"]["claude"]["calls"] == 2
    assert summary["totals"]["calls"] == 3
    assert summary["groups"]["claude"]["input_tokens"] == 2000


def test_usage_can_be_aggregated_by_conversation(memory):
    record_usage(
        build_usage(
            "gpt",
            input_tokens=10,
            output_tokens=10,
            correlation={"conversation_id": "sessao-1"},
        )
    )

    summary = memory.summarize(group_by="conversation_id")

    assert "sessao-1" in summary["groups"]


def test_calls_without_a_price_are_counted_separately(memory):
    record_usage(build_usage("provedor-novo", input_tokens=100))

    totals = memory.summarize()["totals"]

    assert totals["calls"] == 1
    assert totals["priced_calls"] == 0


def test_memory_window_is_bounded():
    """Backend roda por dias na maquina do usuario: a janela nao pode crescer."""
    window = InMemorySink(max_events=3)
    for index in range(10):
        record = build_usage("gpt", input_tokens=index)
        window.record_usage(record)

    assert len(window.usage()) == 3
