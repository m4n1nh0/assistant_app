import asyncio

import pytest

from app.services import computer_action_service as service


def test_build_computer_action_detects_network_diagnostics_request():
    action = service.build_computer_action(
        "Verifique meu IP, DNS, gateway e ping da internet"
    )

    assert action is not None
    assert action["type"] == "computer_action"
    assert action["action_id"] == "network_diagnostics"
    assert action["risk_level"] == "low"


def test_build_computer_action_detects_short_network_analysis_request():
    action = service.build_computer_action("Analisar rede")

    assert action is not None
    assert action["action_id"] == "network_diagnostics"


def test_build_computer_action_ignores_existing_action_result():
    action = service.build_computer_action(
        "Resultado da acao local Diagnostico de rede\nPing Google..."
    )

    assert action is None


def test_build_computer_action_detects_system_diagnostics_request():
    action = service.build_computer_action(
        "Verifique memoria RAM, processos e uso de disco do computador"
    )

    assert action is not None
    assert action["type"] == "computer_action"
    assert action["action_id"] == "system_diagnostics"
    assert action["requires_confirmation"] is False


def test_build_computer_action_detects_explicit_script_request():
    action = service.build_computer_action(
        "Execute este powershell:\n```powershell\nGet-Process | Select-Object -First 1\n```"
    )

    assert action is not None
    assert action["action_id"] == "run_script"
    assert action["requires_confirmation"] is True
    assert action["arguments"]["shell"] == "powershell"
    assert "Get-Process" in action["arguments"]["script"]


def test_build_computer_action_does_not_run_pasted_ai_disclaimer():
    action = service.build_computer_action(
        "Nao tenho capacidade real de executar scripts. Copie, execute e cole o resultado:\n"
        "```powershell\nGet-Process\n```"
    )

    assert action is None


def test_get_action_rejects_unknown_action():
    with pytest.raises(service.ComputerActionError):
        service.get_action("format_disk")


def test_run_action_rejects_backend_execution():
    with pytest.raises(service.ComputerActionError, match="interface desktop"):
        asyncio.run(service.run_action("network_diagnostics"))
