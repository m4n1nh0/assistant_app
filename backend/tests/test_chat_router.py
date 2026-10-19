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


def test_chat_stream_runs_through_the_graph_and_never_calls_a_provider(monkeypatch):
    from app.models.schemas import ChatRequest, ChatResponse, LLMResponse

    # A rota nao conhece mais o cliente dos provedores: so o grafo fala com eles.
    assert not hasattr(chat_router, "llm_service")

    turns = []

    async def ready():
        return ["gpt"]

    async def fake_turn(body, user):
        turns.append((body.message, user["uid"]))
        return ChatResponse(
            session_id=body.session_id,
            mode="single",
            responses=[LLMResponse(llm="gpt", content="Resposta do grafo com bastante texto para dividir em pedacos.")],
        )

    monkeypatch.setattr(chat_router, "get_ready_llms", ready)
    monkeypatch.setattr(chat_router, "_run_chat_turn", fake_turn)

    response = run(chat_router.chat_stream(ChatRequest(message="oi"), {"uid": "u1"}, None))
    events = _collect_sse(response)

    assert turns == [("oi", "u1")]
    chunks = [e["chunk"] for e in events if not e.get("done")]
    assert len(chunks) > 1
    assert "".join(chunks) == "Resposta do grafo com bastante texto para dividir em pedacos."
    assert events[-1]["done"] is True and events[-1]["llm"] == "gpt"


def test_chat_stream_without_ready_provider_answers_unavailable(monkeypatch):
    from app.models.schemas import ChatRequest, LLMResponse

    async def ready():
        return []

    async def unavailable(llm=None):
        return LLMResponse(llm="backend", content="Nenhum agente de IA esta disponivel", is_error=True)

    async def never(body, user):
        raise AssertionError("sem provedor pronto o grafo nao deve rodar")

    monkeypatch.setattr(chat_router, "get_ready_llms", ready)
    monkeypatch.setattr(chat_router, "_llm_unavailable_response", unavailable)
    monkeypatch.setattr(chat_router, "_run_chat_turn", never)

    events = _collect_sse(run(chat_router.chat_stream(ChatRequest(message="oi"), {"uid": "u1"}, None)))

    assert events == [{"chunk": "Nenhum agente de IA esta disponivel", "done": True}]
