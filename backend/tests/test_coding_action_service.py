from app.services.coding_action_service import build_coding_action


def test_build_coding_action_for_codex_request():
    action = build_coding_action(
        "Consegue trabalhar como o Codex e analisar meu projeto?"
    )

    assert action is not None
    assert action["type"] == "coding_action"
    assert action["action_id"] == "inspect_workspace"
    assert action["requires_confirmation"] is True


def test_build_coding_action_ignores_workspace_context_result():
    action = build_coding_action(
        "Contexto local do workspace capturado pela interface:\nREADME.md"
    )

    assert action is None
