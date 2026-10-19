import asyncio

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from app.models.schemas import LLMResponse
from app.services import langchain_agent_service as agent
from app.services.llm_stream_service import StreamDelta, StreamDone
from app.services.stream_sink import bind_sink, reset_sink


@tool
def agenda(day: str) -> str:
    """Le a agenda de um dia."""
    return "ok"


def fake_stream(*pieces, final=None):
    text = "".join(pieces)

    async def stream(provider, message, history, system_prompt, **kwargs):
        for piece in pieces:
            yield StreamDelta(piece)
        yield StreamDone(final or LLMResponse(llm=provider, content=text, output_tokens=3))

    return stream


def run_model(monkeypatch, stream, *, tools=(), sink=True):
    events: list[dict] = []

    async def collect(event):
        events.append(event)

    monkeypatch.setattr(agent.llm_stream_service, "stream_single", stream)

    async def go():
        model = agent.ProviderChatModel(provider="gpt")
        if tools:
            model = model.bind_tools(list(tools))
        token = bind_sink(collect) if sink else None
        try:
            return await model._agenerate([HumanMessage(content="oi")])
        finally:
            if token is not None:
                reset_sink(token)

    result = asyncio.run(go())
    return result.generations[0].message, events


def texts(events):
    return "".join(e["text"] for e in events if e["type"] == "delta")


def test_plain_answer_streams_pieces_after_a_reset(monkeypatch):
    message, events = run_model(monkeypatch, fake_stream("Ola, ", "tudo ", "bem?"))

    assert events[0] == {"type": "reset"}
    assert texts(events) == "Ola, tudo bem?"
    assert message.content == "Ola, tudo bem?"
    assert message.usage_metadata["output_tokens"] == 3


def test_tool_call_is_held_and_never_shown(monkeypatch):
    stream = fake_stream('{"tool": "agenda", ', '"args": {"day": "hoje"}}')

    message, events = run_model(monkeypatch, stream, tools=[agenda])

    assert events == [{"type": "reset"}]
    assert message.content == ""
    assert message.tool_calls[0]["name"] == "agenda"
    assert message.tool_calls[0]["args"] == {"day": "hoje"}


def test_text_that_looks_like_json_but_is_not_a_tool_is_released_at_the_end(monkeypatch):
    stream = fake_stream('{"nota": ', "10}")

    message, events = run_model(monkeypatch, stream, tools=[agenda])

    assert texts(events) == '{"nota": 10}'
    assert message.tool_calls == []
    assert message.content == '{"nota": 10}'


def test_json_answer_streams_normally_when_no_tools_are_bound(monkeypatch):
    message, events = run_model(monkeypatch, fake_stream('{"a": ', "1}"))

    assert texts(events) == '{"a": 1}'


def test_text_with_tools_bound_but_a_normal_answer_streams_live(monkeypatch):
    message, events = run_model(monkeypatch, fake_stream("Nao preciso de ferramenta."), tools=[agenda])

    assert texts(events) == "Nao preciso de ferramenta."
    assert message.tool_calls == []


def test_every_call_starts_with_a_reset(monkeypatch):
    _, first = run_model(monkeypatch, fake_stream("a"))
    _, second = run_model(monkeypatch, fake_stream("b"))

    assert first[0] == second[0] == {"type": "reset"}


def test_provider_error_comes_back_as_an_error_response_without_text(monkeypatch):
    err = LLMResponse(llm="gpt", content="sem saldo", is_error=True)

    async def stream(provider, message, history, system_prompt, **kwargs):
        yield StreamDone(err)

    message, events = run_model(monkeypatch, stream)

    assert texts(events) == ""
    assert message.response_metadata["is_error"] is True


def test_without_a_sink_the_whole_call_is_used_as_before(monkeypatch):
    async def whole(provider, message, history, system_prompt, **kwargs):
        return LLMResponse(llm=provider, content="inteira")

    def never(*args, **kwargs):
        raise AssertionError("sem sink nao deve usar streaming")

    monkeypatch.setattr(agent.llm_service, "dispatch_single", whole)
    monkeypatch.setattr(agent.llm_stream_service, "stream_single", never)

    async def go():
        return await agent.ProviderChatModel(provider="gpt")._agenerate([HumanMessage(content="oi")])

    result = asyncio.run(go())

    assert result.generations[0].message.content == "inteira"
