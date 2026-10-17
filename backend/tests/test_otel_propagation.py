"""Trace que atravessa os servicos: span de servidor na entrada, herdando o contexto recebido.

O que isto protege: o mapa de servicos do collector so desenha uma ligacao quando o span de CLIENTE
de um servico e o span de SERVIDOR do outro estao no mesmo trace. Isso exige tres coisas: a
requisicao que entra abre um span de servidor, esse span herda o `traceparent` que veio no
cabecalho, e o que o servico abre depois fica dentro dele.
"""

from __future__ import annotations

import pytest

pytest.importorskip("opentelemetry.sdk.trace")
pytest.importorskip("opentelemetry.instrumentation.fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402
from opentelemetry.trace import SpanKind  # noqa: E402

from shared.observability import otel, span_sync  # noqa: E402

pytestmark = pytest.mark.unit

TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
PARENT_ID = "b7ad6b7169203331"


@pytest.fixture
def traced(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(otel, "_enabled", True)
    monkeypatch.setattr(otel, "_tracer", provider.get_tracer("teste"))

    app = FastAPI()

    @app.get("/items/{item_id}")
    def item(item_id: str):
        with span_sync("dominio.operacao", "tool"):
            return {"id": item_id}

    @app.get("/health")
    def health():
        return {"ok": True}

    assert otel.instrument_server(app, excluded_paths=("/health",), tracer_provider=provider)
    yield app, exporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.uninstrument_app(app)


def finished(exporter):
    return {s.name: s for s in exporter.get_finished_spans()}


def test_requisicao_que_entra_vira_span_de_servidor_pela_rota(traced):
    app, exporter = traced

    TestClient(app).get("/items/42")

    servidor = [s for s in exporter.get_finished_spans() if s.kind == SpanKind.SERVER]
    assert [s.name for s in servidor] == ["GET /items/{item_id}"]


def test_o_span_herda_o_traceparent_recebido(traced):
    app, exporter = traced

    TestClient(app).get("/items/42", headers={"traceparent": f"00-{TRACE_ID}-{PARENT_ID}-01"})

    servidor = next(s for s in exporter.get_finished_spans() if s.kind == SpanKind.SERVER)
    assert format(servidor.context.trace_id, "032x") == TRACE_ID
    assert format(servidor.parent.span_id, "016x") == PARENT_ID


def test_o_que_o_servico_abre_depois_fica_dentro_do_span_de_servidor(traced):
    app, exporter = traced

    TestClient(app).get("/items/42")

    spans = finished(exporter)
    servidor = spans["GET /items/{item_id}"]
    interno = spans["dominio.operacao"]
    assert interno.context.trace_id == servidor.context.trace_id
    assert interno.parent.span_id == servidor.context.span_id


def test_healthcheck_nao_gera_span(traced):
    app, exporter = traced

    TestClient(app).get("/health")

    assert exporter.get_finished_spans() == ()


def test_sem_otel_ligado_nada_e_instrumentado(monkeypatch):
    monkeypatch.setattr(otel, "_enabled", False)

    assert otel.instrument_server(FastAPI()) is False
    assert otel.instrument_clients() == []
    assert otel.instrument_database(object()) is False
