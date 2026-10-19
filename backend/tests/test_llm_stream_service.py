import asyncio
import json

import httpx

from app.models.schemas import LLMResponse
from app.services import llm_stream_service
from app.services.llm_stream_service import (
    StreamDelta,
    StreamDone,
    stream_openai_compatible,
    stream_single,
)


def run(coro):
    return asyncio.run(coro)


async def collect(agen):
    return [event async for event in agen]


def sse(*chunks) -> bytes:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return body.encode()


def transport(handler):
    return httpx.MockTransport(handler)


def call(transport_, key="k", **kwargs):
    return stream_openai_compatible(
        "together", key, "https://example.test/v1/chat/completions", "m-1",
        "Oi", [], "sistema", transport=transport_, **kwargs,
    )


def test_openai_compatible_streams_pieces_and_ends_with_usage():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, content=sse(
            {"model": "m-1-real", "choices": [{"delta": {"role": "assistant"}}]},
            {"choices": [{"delta": {"content": "Ola"}}]},
            {"choices": [{"delta": {"content": ", mundo"}}]},
            {"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 4,
                                      "prompt_tokens_details": {"cached_tokens": 2}}},
        ), headers={"content-type": "text/event-stream"})

    events = run(collect(call(transport(handler))))

    assert [e.text for e in events if isinstance(e, StreamDelta)] == ["Ola", ", mundo"]
    done = events[-1]
    assert isinstance(done, StreamDone)
    assert done.response.content == "Ola, mundo"
    assert done.response.is_error is False
    assert (done.response.input_tokens, done.response.output_tokens, done.response.cached_tokens) == (11, 4, 2)
    assert done.response.model == "m-1-real"
    assert seen["body"]["stream"] is True
    assert seen["body"]["stream_options"] == {"include_usage": True}
    assert seen["body"]["messages"][0] == {"role": "system", "content": "sistema"}
    assert seen["auth"] == "Bearer k"


def test_openai_compatible_without_usage_leaves_tokens_unknown_not_zero():
    def handler(request):
        return httpx.Response(200, content=sse({"choices": [{"delta": {"content": "x"}}]}))

    done = run(collect(call(transport(handler))))[-1]

    assert done.response.input_tokens is None and done.response.output_tokens is None


def test_openai_compatible_http_error_becomes_error_done():
    def handler(request):
        return httpx.Response(402, json={"error": {"message": "saldo insuficiente"}})

    events = run(collect(call(transport(handler))))

    assert len(events) == 1 and isinstance(events[0], StreamDone)
    assert events[0].response.is_error is True
    assert "saldo" in events[0].response.content


def test_openai_compatible_error_in_the_middle_of_the_stream_is_an_error_done():
    def handler(request):
        return httpx.Response(200, content=sse(
            {"choices": [{"delta": {"content": "meio"}}]},
            {"error": {"message": "conexao caiu"}},
        ))

    events = run(collect(call(transport(handler))))

    assert isinstance(events[0], StreamDelta)
    assert events[-1].response.is_error is True


def test_openai_compatible_without_key_fails_before_any_request():
    def handler(request):
        raise AssertionError("nao deveria chamar o provedor")

    events = run(collect(call(transport(handler), key="")))

    assert events[0].response.is_error is True and "Credencial" in events[0].response.content


def test_provider_without_streaming_falls_back_to_one_piece(monkeypatch):
    calls = []

    async def dispatch(llm, message, history, system_prompt, *, max_tokens=None):
        calls.append(llm)
        return LLMResponse(llm=llm, content="resposta inteira")

    monkeypatch.setattr(llm_stream_service.llm_service, "dispatch_single", dispatch)

    events = run(collect(stream_single("gemini", "oi", [], "sis")))

    assert calls == ["gemini"]
    assert isinstance(events[0], StreamDelta) and events[0].text == "resposta inteira"
    assert events[-1].response.content == "resposta inteira"


def test_streaming_provider_records_usage_and_failure(monkeypatch):
    recorded, failures = [], []

    async def fake_streamer(message, history, system_prompt, max_tokens):
        yield StreamDelta("a")
        yield StreamDone(LLMResponse(llm="gpt", content="a", output_tokens=1))

    async def fake_failure(llm, detail):
        failures.append((llm, detail))

    monkeypatch.setattr(llm_stream_service, "_streamer_for", lambda llm: fake_streamer)
    monkeypatch.setattr(llm_stream_service.llm_service, "_record_call_usage", recorded.append)
    monkeypatch.setattr(llm_stream_service, "mark_llm_failure", fake_failure)

    run(collect(stream_single("gpt", "oi", [], "sis")))

    assert [r.output_tokens for r in recorded] == [1]
    assert failures == []


def test_streaming_provider_error_feeds_the_health(monkeypatch):
    failures = []

    async def fake_streamer(message, history, system_prompt, max_tokens):
        yield StreamDone(LLMResponse(llm="gpt", content="sem saldo", is_error=True))

    async def fake_failure(llm, detail):
        failures.append((llm, detail))

    monkeypatch.setattr(llm_stream_service, "_streamer_for", lambda llm: fake_streamer)
    monkeypatch.setattr(llm_stream_service.llm_service, "_record_call_usage", lambda r: None)
    monkeypatch.setattr(llm_stream_service, "mark_llm_failure", fake_failure)

    run(collect(stream_single("gpt", "oi", [], "sis")))

    assert failures == [("gpt", "sem saldo")]


def test_every_cloud_provider_has_a_streamer_except_the_ones_that_answer_whole():
    streams = {name for name in ["claude", "gpt", "together", "openrouter", "deepseek", "grok", "localai", "llama"]
               if llm_stream_service._streamer_for(name) is not None}
    assert streams == {"claude", "gpt", "together", "openrouter", "deepseek", "grok", "localai", "llama"}
    assert llm_stream_service._streamer_for("gemini") is None
    assert llm_stream_service._streamer_for("hf") is None
