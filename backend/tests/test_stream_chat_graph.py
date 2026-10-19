import asyncio

import pytest

from app.models.schemas import LLMResponse, ResponseModeEnum
from app.orchestration import graph as graph_module
from app.services.stream_sink import current_sink


def run(coro):
    return asyncio.run(coro)


async def collect(agen):
    return [event async for event in agen]


KWARGS = dict(
    message="oi", history=[], mode=ResponseModeEnum.single, requested_llm="gpt",
    active_llms=["gpt"], system_prompt="s", tutor_id="t",
)


def test_single_mode_forwards_what_the_model_writes_and_ends_with_the_state(monkeypatch):
    async def fake_run(**kwargs):
        sink = current_sink()
        assert sink is not None
        await sink({"type": "reset"})
        await sink({"type": "delta", "text": "Ola"})
        await asyncio.sleep(0)
        await sink({"type": "delta", "text": "!"})
        return {"responses": [LLMResponse(llm="gpt", content="Ola!")]}

    monkeypatch.setattr(graph_module, "run_chat_graph", fake_run)

    events = run(collect(graph_module.stream_chat_graph(**KWARGS)))

    assert [e["type"] for e in events] == ["reset", "delta", "delta", "final"]
    assert events[-1]["state"]["responses"][0].content == "Ola!"


def test_the_sink_is_not_left_bound_after_the_turn_starts(monkeypatch):
    async def fake_run(**kwargs):
        return {"responses": []}

    monkeypatch.setattr(graph_module, "run_chat_graph", fake_run)

    run(collect(graph_module.stream_chat_graph(**KWARGS)))

    assert current_sink() is None


@pytest.mark.parametrize("mode", [ResponseModeEnum.multi, ResponseModeEnum.chain])
def test_multi_and_chain_are_not_streamed_only_the_final_arrives(monkeypatch, mode):
    async def fake_run(**kwargs):
        assert current_sink() is None
        return {"responses": [LLMResponse(llm="gpt", content="a"), LLMResponse(llm="claude", content="b")]}

    monkeypatch.setattr(graph_module, "run_chat_graph", fake_run)

    events = run(collect(graph_module.stream_chat_graph(**{**KWARGS, "mode": mode})))

    assert [e["type"] for e in events] == ["final"]


def test_leaving_early_cancels_the_running_turn(monkeypatch):
    state = {"cancelled": False}

    async def fake_run(**kwargs):
        sink = current_sink()
        await sink({"type": "delta", "text": "x"})
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    monkeypatch.setattr(graph_module, "run_chat_graph", fake_run)

    async def go():
        agen = graph_module.stream_chat_graph(**KWARGS)
        first = await agen.__anext__()
        await agen.aclose()
        await asyncio.sleep(0.05)
        return first

    first = run(go())

    assert first == {"type": "delta", "text": "x"}
    assert state["cancelled"] is True
