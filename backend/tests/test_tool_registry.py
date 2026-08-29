"""Catalogo e execucao governada de ferramentas.

O que se verifica aqui e a fronteira do Tool Service: quem pode chamar o que,
o que acontece quando a ferramenta demora, falha ou nao existe, e se a falha
volta como resultado em vez de excecao. Sao as garantias que permitem ao agente
disparar uma ferramenta sem tratar erro no proprio codigo.
"""

import asyncio

import pytest

from app.core.observability import configure_sink, default_sink
from app.ports.tools import ToolDescriptor, ToolInvocation
from app.toolkit.executor import ToolExecutor
from app.toolkit.registry import ToolRegistry

pytestmark = pytest.mark.unit


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def telemetry():
    """Sink real para garantir que a execucao emite span sem quebrar."""
    sink, memory = default_sink()
    configure_sink(sink, memory=memory)
    yield memory
    memory.clear()


def descriptor(name: str, **kwargs) -> ToolDescriptor:
    kwargs.setdefault("description", f"{name} de teste")
    kwargs.setdefault("args_schema", {"type": "object", "properties": {}})
    return ToolDescriptor(name=name, **kwargs)


def registry_with(name: str, runner, **kwargs) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(descriptor(name, **kwargs), runner)
    return registry


async def echo(args):
    return f"eco: {args.get('text', '')}"


# --- Catalogo ---------------------------------------------------------------


def test_registered_tool_appears_in_the_catalog():
    registry = registry_with("echo", echo)

    assert registry.names() == {"echo"}
    assert [item.name for item in registry.descriptors()] == ["echo"]


def test_catalog_is_ordered_by_name():
    """Ordem estavel: o prompt do modelo nao pode mudar sem motivo."""
    registry = ToolRegistry()
    for name in ("zeta", "alpha", "meio"):
        registry.register(descriptor(name), echo)

    assert [item.name for item in registry.descriptors()] == [
        "alpha",
        "meio",
        "zeta",
    ]


def test_scope_filters_what_an_agent_sees():
    registry = ToolRegistry()
    registry.register(descriptor("so_do_code", scopes=("code",)), echo)
    registry.register(descriptor("so_da_agenda", scopes=("calendar",)), echo)

    assert [i.name for i in registry.descriptors(agent_id="code")] == ["so_do_code"]
    assert [i.name for i in registry.descriptors(agent_id="calendar")] == [
        "so_da_agenda"
    ]


def test_tool_without_scope_is_not_offered_to_any_agent():
    """Negar por omissao: ferramenta nova nao aparece para todos por acidente."""
    registry = registry_with("interna", echo)

    assert registry.descriptors(agent_id="code") == []
    # Continua no catalogo para uso interno do grafo, sem agente atribuido.
    assert [item.name for item in registry.descriptors()] == ["interna"]


def test_unregistering_a_source_keeps_the_others():
    registry = ToolRegistry()
    registry.register(descriptor("local_tool"), echo)
    registry.register(descriptor("mcp_tool", source="mcp", server="fs"), echo)

    removed = registry.unregister_source("mcp")

    assert removed == 1
    assert registry.names() == {"local_tool"}


def test_unregistering_one_mcp_server_keeps_the_other():
    registry = ToolRegistry()
    registry.register(descriptor("a", source="mcp", server="fs"), echo)
    registry.register(descriptor("b", source="mcp", server="docs"), echo)

    registry.unregister_source("mcp", server="fs")

    assert registry.names() == {"b"}


# --- Execucao ---------------------------------------------------------------


def test_successful_call_returns_the_output():
    executor = ToolExecutor(registry_with("echo", echo))

    result = run(executor.invoke(ToolInvocation(name="echo", args={"text": "oi"})))

    assert result.ok is True
    assert result.output == "eco: oi"


def test_unknown_tool_is_refused_without_raising():
    executor = ToolExecutor(ToolRegistry())

    result = run(executor.invoke(ToolInvocation(name="fantasma")))

    assert result.ok is False
    assert "desconhecida" in result.error


def test_agent_outside_the_scope_is_refused():
    executor = ToolExecutor(registry_with("echo", echo, scopes=("calendar",)))

    result = run(
        executor.invoke(ToolInvocation(name="echo", agent_id="code"))
    )

    assert result.ok is False
    assert "nao esta liberada" in result.error


def test_internal_call_without_agent_skips_the_scope_check():
    """O grafo chama construtoras de acao direto, sem passar pelo modelo."""
    executor = ToolExecutor(registry_with("echo", echo, scopes=("calendar",)))

    result = run(executor.invoke(ToolInvocation(name="echo", args={"text": "x"})))

    assert result.ok is True


def test_missing_required_argument_is_rejected_before_running():
    ran = []

    async def runner(args):
        ran.append(args)
        return "nao deveria rodar"

    registry = registry_with(
        "echo",
        runner,
        args_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )

    result = run(ToolExecutor(registry).invoke(ToolInvocation(name="echo")))

    assert result.ok is False
    assert "exige text" in result.error
    assert ran == []


def test_exception_becomes_a_failed_result():
    async def boom(args):
        raise RuntimeError("quebrou")

    result = run(ToolExecutor(registry_with("boom", boom)).invoke(
        ToolInvocation(name="boom")
    ))

    assert result.ok is False
    assert "quebrou" in result.error


def test_timeout_is_enforced():
    async def lenta(args):
        await asyncio.sleep(5)

    executor = ToolExecutor(
        registry_with("lenta", lenta), default_timeout=0.05, max_retries=0
    )

    result = run(executor.invoke(ToolInvocation(name="lenta")))

    assert result.ok is False
    assert "excedeu" in result.error


def test_tool_specific_timeout_wins_over_the_global_one():
    async def lenta(args):
        await asyncio.sleep(5)

    executor = ToolExecutor(
        registry_with("lenta", lenta, timeout_seconds=0.05),
        default_timeout=30.0,
        max_retries=0,
    )

    result = run(executor.invoke(ToolInvocation(name="lenta")))

    assert result.ok is False


def test_timeout_is_retried_up_to_the_ceiling():
    attempts = []

    async def instavel(args):
        attempts.append(1)
        if len(attempts) < 2:
            await asyncio.sleep(5)
        return "voltou"

    executor = ToolExecutor(
        registry_with("instavel", instavel),
        default_timeout=0.05,
        max_retries=2,
        retry_backoff=0.0,
    )

    result = run(executor.invoke(ToolInvocation(name="instavel")))

    assert result.ok is True
    assert result.retries == 1


def test_domain_error_is_not_retried():
    """Repetir o que nao e transitorio so multiplica latencia."""
    attempts = []

    async def invalida(args):
        attempts.append(1)
        raise ValueError("argumento invalido")

    executor = ToolExecutor(
        registry_with("invalida", invalida), max_retries=3, retry_backoff=0.0
    )

    result = run(executor.invoke(ToolInvocation(name="invalida")))

    assert result.ok is False
    assert len(attempts) == 1


def test_execution_emits_a_span(telemetry):
    executor = ToolExecutor(registry_with("echo", echo))

    run(executor.invoke(ToolInvocation(name="echo", args={"text": "oi"})))

    spans = [item for item in telemetry.spans() if item.kind == "tool"]
    assert spans and spans[-1].name == "tool.echo"


def test_failed_execution_marks_the_span(telemetry):
    async def boom(args):
        raise RuntimeError("quebrou")

    run(ToolExecutor(registry_with("boom", boom)).invoke(
        ToolInvocation(name="boom")
    ))

    spans = [item for item in telemetry.spans() if item.kind == "tool"]
    assert spans[-1].ok is False


def test_result_text_is_capped_for_the_model():
    async def enorme(args):
        return "x" * 10_000

    result = run(ToolExecutor(registry_with("enorme", enorme)).invoke(
        ToolInvocation(name="enorme")
    ))

    assert len(result.as_text(limit=100)) == 100
