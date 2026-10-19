import asyncio

from app.models.schemas import LLMResponse, LaunchAction, ShortcutType
from app.routers import websocket as websocket_router


def test_websocket_chat_uses_graph_and_serializes_action(monkeypatch):
    sent: list[tuple[str, dict]] = []

    async def ready_llms():
        return ["gpt"]

    async def run_graph(**kwargs):
        assert kwargs["message"] == "Abra o navegador"
        assert kwargs["requested_llm"] == "gpt"
        assert kwargs["active_llms"] == ["gpt"]
        assert kwargs["tutor_id"] == "tutor-1"
        return {
            "responses": [LLMResponse(llm="gpt", content="Abrindo.")],
            "action": LaunchAction(
                shortcut_id="shortcut-1",
                name="Navegador",
                target="browser",
                target_type=ShortcutType.app,
            ),
        }

    async def send(session_id, data):
        sent.append((session_id, data))

    monkeypatch.setattr(websocket_router, "get_ready_llms", ready_llms)
    monkeypatch.setattr(websocket_router, "run_chat_graph", run_graph)
    monkeypatch.setattr(websocket_router.manager, "send", send)

    asyncio.run(
        websocket_router._handle_chat(
            "connection-1",
            {
                "message": "Abra o navegador",
                "mode": "single",
                "llm": "gpt",
                "history": [],
            },
            tutor_id="tutor-1",
        )
    )

    assert sent[0][1]["type"] == "thinking"
    response = sent[1][1]
    assert response["type"] == "chat_response"
    assert response["payload"]["responses"][0]["content"] == "Abrindo."
    assert response["payload"]["action"]["shortcut_id"] == "shortcut-1"


def test_websocket_chat_stream_runs_through_the_graph_and_sends_pieces(monkeypatch):
    sent: list[dict] = []

    # O WebSocket nao conhece mais o cliente dos provedores: so o grafo fala com eles.
    assert not hasattr(websocket_router, "llm_service")

    async def ready_llms():
        return ["gpt"]

    async def run_graph(**kwargs):
        assert kwargs["message"] == "Oi"
        assert kwargs["tutor_id"] == "tutor-1"
        assert kwargs["user_id"] == "user-1"
        return {
            "responses": [LLMResponse(llm="gpt", content="Ola, tudo bem? Esta resposta vem pronta do grafo e sai em pedacos.")],
            "action": None,
        }

    async def send(session_id, data):
        sent.append(data)

    monkeypatch.setattr(websocket_router, "get_ready_llms", ready_llms)
    monkeypatch.setattr(websocket_router, "run_chat_graph", run_graph)
    monkeypatch.setattr(websocket_router.manager, "send", send)

    asyncio.run(
        websocket_router._handle_chat_stream(
            "connection-1",
            {"message": "Oi", "llm": "gpt", "history": []},
            tutor_id="tutor-1",
            user_id="user-1",
        )
    )

    assert sent[0]["type"] == "thinking"
    chunks = [m["payload"]["chunk"] for m in sent if m["type"] == "stream_chunk"]
    end = sent[-1]
    assert len(chunks) > 1
    assert "".join(chunks) == "Ola, tudo bem? Esta resposta vem pronta do grafo e sai em pedacos."
    assert end["type"] == "stream_end"
    assert end["payload"]["full_response"] == "".join(chunks)
    assert end["payload"]["llm"] == "gpt" and end["payload"]["done"] is True


def test_websocket_chat_stream_reports_graph_failure_as_error(monkeypatch):
    sent: list[dict] = []

    async def ready_llms():
        return ["gpt"]

    async def boom(**kwargs):
        raise RuntimeError("grafo caiu")

    async def send(session_id, data):
        sent.append(data)

    monkeypatch.setattr(websocket_router, "get_ready_llms", ready_llms)
    monkeypatch.setattr(websocket_router, "run_chat_graph", boom)
    monkeypatch.setattr(websocket_router.manager, "send", send)

    asyncio.run(websocket_router._handle_chat_stream("c", {"message": "Oi"}))

    assert sent[-1]["type"] == "error"
    assert "grafo caiu" in str(sent[-1])
