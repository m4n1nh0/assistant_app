import asyncio
from types import SimpleNamespace

from app.models.schemas import LLMStatus
from app.routers import chat as chat_router


def run(coro):
    return asyncio.run(coro)


def test_unavailable_response_includes_provider_label_and_error(monkeypatch):
    fake_settings = SimpleNamespace(
        active_llms=[],
        llm_labels={"gemini": "Gemini 1.5 Flash"},
    )

    async def fake_statuses():
        return {
            "gemini": LLMStatus(
                id="gemini",
                label="Gemini 1.5 Flash",
                configured=True,
                online=False,
                available=False,
                status="offline",
                error="API key not valid",
            )
        }

    monkeypatch.setattr(chat_router, "settings", fake_settings)
    monkeypatch.setattr(chat_router, "get_llm_statuses", fake_statuses)

    response = run(chat_router._llm_unavailable_response("gemini"))

    assert response.llm == "gemini"
    assert response.is_error is True
    assert "Gemini 1.5 Flash" in response.content
    assert "API key not valid" in response.content


def _collect_sse(response):
    import json

    async def drain():
        events = []
        async for raw in response.body_iterator:
            text = raw if isinstance(raw, str) else raw.decode()
            for line in text.split("\n"):
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        return events

    return run(drain())


def _stream_turn_returning(events):
    async def fake(body, user):
        for event in events:
            yield event

    return fake


def _answer(content, **extra):
    from app.models.schemas import ChatResponse, LLMResponse

    return ChatResponse(
        session_id="default",
        mode="single",
        responses=[LLMResponse(llm="gpt", content=content, **extra)],
    )


def test_chat_stream_relays_the_pieces_as_the_model_writes_them(monkeypatch):
    from app.models.schemas import ChatRequest

    # A rota nao conhece mais o cliente dos provedores: so o grafo fala com eles.
    assert not hasattr(chat_router, "llm_service")

    async def ready():
        return ["gpt"]

    final = _answer("Resposta ao vivo")
    monkeypatch.setattr(chat_router, "get_ready_llms", ready)
    monkeypatch.setattr(
        chat_router,
        "_stream_chat_turn",
        _stream_turn_returning([("reset", None), ("delta", "Resposta "), ("delta", "ao vivo"), ("final", final)]),
    )

    events = _collect_sse(run(chat_router.chat_stream(ChatRequest(message="oi"), {"uid": "u1"}, None)))

    assert events[0] == {"reset": True, "done": False}
    assert [e["chunk"] for e in events if e.get("chunk") and not e.get("done")] == ["Resposta ", "ao vivo"]
    end = events[-1]
    assert end["done"] is True and end["content"] == "Resposta ao vivo" and end["llm"] == "gpt"


def test_chat_stream_splits_the_final_text_when_nothing_was_written_live(monkeypatch):
    from app.models.schemas import ChatRequest

    async def ready():
        return ["gpt"]

    monkeypatch.setattr(chat_router, "get_ready_llms", ready)
    monkeypatch.setattr(
        chat_router, "_stream_chat_turn",
        _stream_turn_returning([("final", _answer("Agenda criada para amanha, com bastante detalhe para dividir."))]),
    )

    events = _collect_sse(run(chat_router.chat_stream(ChatRequest(message="oi"), {"uid": "u1"}, None)))

    pieces = [e["chunk"] for e in events if e.get("chunk") and not e.get("done")]
    assert len(pieces) > 1
    assert "".join(pieces) == "Agenda criada para amanha, com bastante detalhe para dividir."
    assert events[-1]["content"] == "Agenda criada para amanha, com bastante detalhe para dividir."


def test_chat_stream_after_a_reset_the_final_text_is_the_truth(monkeypatch):
    from app.models.schemas import ChatRequest

    async def ready():
        return ["gpt"]

    monkeypatch.setattr(chat_router, "get_ready_llms", ready)
    monkeypatch.setattr(
        chat_router, "_stream_chat_turn",
        _stream_turn_returning([
            ("delta", "primeira tentativa"), ("reset", None), ("delta", "texto bom"), ("final", _answer("texto bom")),
        ]),
    )

    events = _collect_sse(run(chat_router.chat_stream(ChatRequest(message="oi"), {"uid": "u1"}, None)))

    assert events[1] == {"reset": True, "done": False}
    assert events[-1]["content"] == "texto bom"


def test_chat_stream_reports_a_failed_turn_as_an_error_event(monkeypatch):
    from app.models.schemas import ChatRequest

    async def ready():
        return ["gpt"]

    async def boom(body, user):
        raise RuntimeError("grafo caiu")
        yield  # pragma: no cover

    monkeypatch.setattr(chat_router, "get_ready_llms", ready)
    monkeypatch.setattr(chat_router, "_stream_chat_turn", boom)

    events = _collect_sse(run(chat_router.chat_stream(ChatRequest(message="oi"), {"uid": "u1"}, None)))

    assert events == [{"error": "grafo caiu", "done": True}]


def test_stream_chat_turn_relays_graph_events_and_ends_with_the_saved_response(monkeypatch):
    from app.models.schemas import ChatRequest

    saved = []

    async def kwargs(body, user):
        return "tutor-1", {"message": body.message}

    async def graph(**kw):
        assert kw == {"message": "oi"}
        yield {"type": "reset"}
        yield {"type": "delta", "text": "Ola"}
        yield {"type": "final", "state": {"responses": []}}

    async def finish(body, user, state):
        saved.append(state)
        return _answer("Ola")

    monkeypatch.setattr(chat_router, "_turn_kwargs", kwargs)
    monkeypatch.setattr(chat_router, "stream_chat_graph", graph)
    monkeypatch.setattr(chat_router, "_finish_turn", finish)

    async def go():
        return [x async for x in chat_router._stream_chat_turn(ChatRequest(message="oi"), {"uid": "u1"})]

    out = run(go())

    assert [k for k, _ in out] == ["reset", "delta", "final"]
    assert saved == [{"responses": []}]


def test_chat_stream_without_ready_provider_answers_unavailable(monkeypatch):
    from app.models.schemas import ChatRequest, LLMResponse

    async def ready():
        return []

    async def unavailable(llm=None):
        return LLMResponse(llm="backend", content="Nenhum agente de IA esta disponivel", is_error=True)

    async def never(body, user):
        raise AssertionError("sem provedor pronto o grafo nao deve rodar")
        yield  # pragma: no cover

    monkeypatch.setattr(chat_router, "get_ready_llms", ready)
    monkeypatch.setattr(chat_router, "_llm_unavailable_response", unavailable)
    monkeypatch.setattr(chat_router, "_run_chat_turn", never)

    events = _collect_sse(run(chat_router.chat_stream(ChatRequest(message="oi"), {"uid": "u1"}, None)))

    assert events == [{
        "chunk": "Nenhum agente de IA esta disponivel",
        "content": "Nenhum agente de IA esta disponivel",
        "llm": "backend",
        "is_error": True,
        "done": True,
    }]
