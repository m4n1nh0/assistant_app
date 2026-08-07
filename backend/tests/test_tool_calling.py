import asyncio
import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.models.schemas import LLMResponse, Message
from app.services import langchain_agent_service as service


def run(coro):
    return asyncio.run(coro)


class EchoInput(BaseModel):
    text: str = Field(description="texto a repetir")


def echo_tool(recorder=None):
    def _echo(text: str) -> str:
        if recorder is not None:
            recorder.append(text)
        return f"eco: {text}"

    return StructuredTool.from_function(
        func=_echo,
        name="echo",
        description="Repete o texto recebido.",
        args_schema=EchoInput,
    )


def fake_gateway(monkeypatch, replies):
    """Sequencia de respostas cruas do provedor."""
    sent = []

    async def _dispatch(provider, message, history, system_prompt):
        index = min(len(sent), len(replies) - 1)
        sent.append({
            "provider": provider,
            "message": message,
            "history": history,
            "system_prompt": system_prompt,
        })
        reply = replies[index]
        if isinstance(reply, LLMResponse):
            return reply
        return LLMResponse(llm=provider, content=reply)

    monkeypatch.setattr(service.llm_service, "dispatch_single", _dispatch)
    return sent


# --- Leitura da chamada de ferramenta --------------------------------------


def test_plain_json_tool_call_is_parsed():
    parsed = service._parse_tool_call(
        '{"tool": "echo", "args": {"text": "oi"}}', {"echo"}
    )

    assert parsed == {"name": "echo", "args": {"text": "oi"}}


def test_tool_call_inside_markdown_fence_is_parsed():
    raw = 'Claro:\n```json\n{"tool": "echo", "args": {"text": "oi"}}\n```'

    assert service._parse_tool_call(raw, {"echo"})["name"] == "echo"


def test_unknown_tool_name_is_rejected():
    """Nome fora do catalogo nunca vira chamada, mesmo em JSON valido."""
    raw = '{"tool": "rm_rf", "args": {"path": "/"}}'

    assert service._parse_tool_call(raw, {"echo"}) is None


def test_plain_text_answer_is_not_a_tool_call():
    assert service._parse_tool_call("Bom dia, tudo certo!", {"echo"}) is None


def test_malformed_json_is_not_a_tool_call():
    assert service._parse_tool_call('{"tool": "echo", args:}', {"echo"}) is None


def test_missing_args_defaults_to_empty_dict():
    parsed = service._parse_tool_call('{"tool": "echo"}', {"echo"})

    assert parsed == {"name": "echo", "args": {}}


# --- Modelo com ferramentas ------------------------------------------------


def test_bind_tools_returns_a_model_with_the_tools():
    model = service.ProviderChatModel(provider="llama")
    bound = model.bind_tools([echo_tool()])

    assert bound.bound_tools
    # O modelo original nao e mutado.
    assert model.bound_tools == []


def test_tool_catalog_is_appended_to_the_system_prompt(monkeypatch):
    sent = fake_gateway(monkeypatch, ["resposta"])
    model = service.ProviderChatModel(provider="llama").bind_tools([echo_tool()])

    run(model.ainvoke([SystemMessage(content="base"), HumanMessage(content="oi")]))

    assert "echo" in sent[0]["system_prompt"]
    assert "base" in sent[0]["system_prompt"]


def test_model_without_tools_keeps_the_prompt_untouched(monkeypatch):
    sent = fake_gateway(monkeypatch, ["resposta"])
    model = service.ProviderChatModel(provider="llama")

    run(model.ainvoke([SystemMessage(content="base"), HumanMessage(content="oi")]))

    assert sent[0]["system_prompt"] == "base"


def test_tool_json_becomes_a_tool_call_on_the_message(monkeypatch):
    fake_gateway(monkeypatch, ['{"tool": "echo", "args": {"text": "oi"}}'])
    model = service.ProviderChatModel(provider="llama").bind_tools([echo_tool()])

    result = run(model.ainvoke([HumanMessage(content="repete oi")]))

    assert result.tool_calls[0]["name"] == "echo"
    assert result.content == ""


def test_provider_error_never_becomes_a_tool_call(monkeypatch):
    fake_gateway(monkeypatch, [
        LLMResponse(llm="llama", content='{"tool": "echo"}', is_error=True)
    ])
    model = service.ProviderChatModel(provider="llama").bind_tools([echo_tool()])

    result = run(model.ainvoke([HumanMessage(content="oi")]))

    assert result.tool_calls == []


# --- Ciclo completo --------------------------------------------------------


def test_tool_is_executed_and_result_feeds_the_next_turn(monkeypatch):
    recorder = []
    sent = fake_gateway(monkeypatch, [
        '{"tool": "echo", "args": {"text": "ola"}}',
        "Pronto, repeti para voce.",
    ])

    response, trace = run(service.run_with_tools(
        "llama", "repete ola", [], "system", [echo_tool(recorder)]
    ))

    assert recorder == ["ola"]
    assert response.content == "Pronto, repeti para voce."
    assert trace[0]["tool"] == "echo"
    assert trace[0]["output"] == "eco: ola"
    # A segunda chamada ao provedor carrega o resultado da ferramenta.
    assert any(
        "eco: ola" in item.content for item in sent[1]["history"]
    ) or "eco: ola" in sent[1]["message"]


def test_answer_without_tool_use_returns_directly(monkeypatch):
    fake_gateway(monkeypatch, ["Resposta direta."])

    response, trace = run(service.run_with_tools(
        "llama", "oi", [], "system", [echo_tool()]
    ))

    assert response.content == "Resposta direta."
    assert trace == []


def test_no_tools_falls_back_to_plain_dispatch(monkeypatch):
    sent = fake_gateway(monkeypatch, ["Resposta."])

    response, trace = run(service.run_with_tools(
        "llama", "oi", [], "system", []
    ))

    assert response.content == "Resposta."
    assert trace == []
    assert "Ferramentas disponiveis" not in sent[0]["system_prompt"]


def test_failing_tool_is_reported_instead_of_crashing(monkeypatch):
    def _boom(text: str) -> str:
        raise RuntimeError("falhou")

    broken = StructuredTool.from_function(
        func=_boom,
        name="echo",
        description="Quebra sempre.",
        args_schema=EchoInput,
    )
    fake_gateway(monkeypatch, [
        '{"tool": "echo", "args": {"text": "oi"}}',
        "Nao consegui usar a ferramenta.",
    ])

    response, trace = run(service.run_with_tools(
        "llama", "oi", [], "system", [broken]
    ))

    assert "erro ao executar" in trace[0]["output"]
    assert response.is_error is False


def test_iteration_ceiling_forces_a_final_plain_answer(monkeypatch):
    """Modelo teimando em chamar ferramenta ainda entrega uma resposta final."""
    call = '{"tool": "echo", "args": {"text": "loop"}}'
    sent = fake_gateway(monkeypatch, [call, call, "Resposta final."])

    response, trace = run(service.run_with_tools(
        "llama", "oi", [], "system", [echo_tool()], max_iterations=2
    ))

    assert len(trace) == 2
    assert response.content == "Resposta final."
    # A chamada de fechamento vai sem catalogo, para o modelo parar de tentar
    # usar ferramenta e efetivamente responder.
    assert "Ferramentas disponiveis" not in sent[-1]["system_prompt"]


def test_stop_tool_halts_the_loop_without_executing(monkeypatch):
    recorder = []
    fake_gateway(monkeypatch, ['{"tool": "echo", "args": {"text": "oi"}}'])

    response, trace = run(service.run_with_tools(
        "llama", "oi", [], "system", [echo_tool(recorder)], stop_tools={"echo"}
    ))

    assert recorder == []
    assert trace[0]["stopped"] is True
    assert response is not None


# --- Conversao de mensagens ------------------------------------------------


def test_tool_messages_are_rendered_for_the_gateway():
    rendered = service._render(
        ToolMessage(content="resultado", tool_call_id="c1")
    )

    assert "Resultado da ferramenta" in rendered


def test_tool_call_message_is_not_sent_empty():
    message = AIMessage(
        content="",
        tool_calls=[{"name": "echo", "args": {"text": "x"}, "id": "c1"}],
    )

    rendered = service._render(message)

    assert rendered.strip() != ""
    assert "echo" in rendered


def test_history_roundtrip_preserves_roles():
    system, history, message = service._provider_request([
        SystemMessage(content="sys"),
        HumanMessage(content="pergunta"),
        AIMessage(content="resposta"),
        HumanMessage(content="agora"),
    ])

    assert system == "sys"
    assert message == "agora"
    assert [item.role for item in history] == ["user", "assistant"]
    assert history == [
        Message(role="user", content="pergunta"),
        Message(role="assistant", content="resposta"),
    ]


def test_tool_catalog_includes_argument_schema():
    catalog = service._tool_catalog([echo_tool()])
    payload = json.dumps(catalog)

    assert "echo" in payload
    assert "text" in payload
