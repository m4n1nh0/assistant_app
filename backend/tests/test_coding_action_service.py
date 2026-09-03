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


def test_build_coding_action_ignores_local_action_result():
    # O `ipconfig` do diagnostico de rede traz `https://api.ipify.org` na saida:
    # o "api" ali com o "Analise" do cabecalho propunha inspecionar o workspace
    # depois de todo diagnostico.
    action = build_coding_action(
        'Resultado da acao local "Diagnostico de rede" executada neste computador.\n'
        "Analise os dados abaixo, destaque problemas provaveis e diga os "
        "proximos passos praticos.\n\n"
        "--- IP externo ---\n"
        "Comando: GET https://api.ipify.org\n"
        "Exit code: 0\n"
        "STDOUT:\n"
        "170.78.32.127\n"
    )

    assert action is None


def test_build_coding_action_ignores_local_script_result():
    action = build_coding_action(
        "Resultado do script local: coleta de recursos.\n"
        "Analise a saida e diga se o backend em python esta com erro.\n"
    )

    assert action is None
