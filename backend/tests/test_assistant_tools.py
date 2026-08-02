from app.services import assistant_tools


def test_action_tools_are_registered_with_stable_names():
    assert [item.name for item in assistant_tools.ASSISTANT_TOOLS] == [
        "propose_computer_action",
        "propose_coding_action",
        "propose_project_action",
        "propose_shortcut_registration",
    ]


def test_computer_tool_returns_structured_action_without_executing():
    action = assistant_tools.invoke_action_tool(
        "computer",
        "Verifique minha rede e o meu IP",
    )

    assert action is not None
    assert action["type"] == "computer_action"
    assert action["action_id"] == "network_diagnostics"
    assert action["risk_level"] == "low"


def test_action_tool_returns_none_when_request_does_not_match():
    action = assistant_tools.invoke_action_tool(
        "coding",
        "Qual e a capital do Brasil?",
    )

    assert action is None


def test_registration_tool_serializes_pydantic_action():
    action = assistant_tools.invoke_action_tool(
        "registration",
        "Cadastre o Notepad como bloco",
    )

    assert action is not None
    assert action["type"] == "register_shortcut"
    assert action["name"]
    assert isinstance(action["aliases"], list)
