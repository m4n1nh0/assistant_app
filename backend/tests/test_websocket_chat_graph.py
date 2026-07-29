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
