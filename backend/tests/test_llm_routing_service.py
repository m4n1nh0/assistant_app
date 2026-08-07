import asyncio

from app.models.schemas import LLMStatus
from app.services import llm_routing_service as service


def run(coro):
    return asyncio.run(coro)


def status(provider: str, balance_ok=None) -> LLMStatus:
    return LLMStatus(
        id=provider,
        label=provider.upper(),
        configured=True,
        online=True,
        available=True,
        has_balance_check=balance_ok is not None,
        balance_ok=balance_ok,
        status="online",
    )


def fake_statuses(monkeypatch, statuses: dict[str, LLMStatus]):
    async def _get(force=False):
        return statuses

    monkeypatch.setattr(service, "get_llm_statuses", _get)


def test_free_local_provider_wins_over_paid_with_credit(monkeypatch):
    fake_statuses(
        monkeypatch,
        {
            "claude": status("claude"),
            "openrouter": status("openrouter", balance_ok=True),
            "llama": status("llama"),
        },
    )

    assert run(service.pick_auto_llm(["claude", "openrouter", "llama"])) == "llama"


def test_paid_with_confirmed_credit_wins_over_unknown_balance(monkeypatch):
    fake_statuses(
        monkeypatch,
        {
            "claude": status("claude"),
            "deepseek": status("deepseek", balance_ok=True),
        },
    )

    assert run(service.pick_auto_llm(["claude", "deepseek"])) == "deepseek"


def test_candidate_order_breaks_ties_within_same_tier(monkeypatch):
    fake_statuses(
        monkeypatch,
        {
            "localai": status("localai"),
            "llama": status("llama"),
        },
    )

    assert run(service.pick_auto_llm(["localai", "llama"])) == "localai"
    assert run(service.pick_auto_llm(["llama", "localai"])) == "llama"


def test_provider_missing_from_statuses_is_treated_as_unknown_balance(monkeypatch):
    fake_statuses(monkeypatch, {"deepseek": status("deepseek", balance_ok=True)})

    assert run(service.pick_auto_llm(["gemini", "deepseek"])) == "deepseek"


def test_empty_candidates_returns_empty_string(monkeypatch):
    fake_statuses(monkeypatch, {})

    assert run(service.pick_auto_llm([])) == ""


# --- Rota por tarefa -------------------------------------------------------


def test_detects_code_task():
    assert service.detect_task("tem um bug no meu codigo python") == "code"


def test_detects_study_task():
    assert service.detect_task("o que o professor falou sobre funcoes na aula?") == "study"


def test_detects_calendar_task():
    assert service.detect_task("marcar uma reuniao amanha") == "calendar"


def test_plain_message_is_general():
    assert service.detect_task("bom dia, tudo bem?") == "general"


def test_empty_message_is_general():
    assert service.detect_task("   ") == "general"


def test_accents_do_not_break_detection():
    assert service.detect_task("o que a professora explicou sobre a matéria?") == "study"


def test_code_task_demotes_weak_local_model(monkeypatch):
    """Tarefa exigente nao vai para o modelo local fraco quando ha alternativa."""
    fake_statuses(
        monkeypatch,
        {"llama": status("llama"), "claude": status("claude", balance_ok=True)},
    )

    assert run(service.pick_auto_llm(["llama", "claude"], "code")) == "claude"


def test_local_model_still_wins_for_general_task(monkeypatch):
    fake_statuses(
        monkeypatch,
        {"llama": status("llama"), "claude": status("claude", balance_ok=True)},
    )

    assert run(service.pick_auto_llm(["llama", "claude"], "general")) == "llama"


def test_local_model_answers_code_when_it_is_the_only_option(monkeypatch):
    """Rebaixar nao e eliminar: sem alternativa, o local responde."""
    fake_statuses(monkeypatch, {"llama": status("llama")})

    assert run(service.pick_auto_llm(["llama"], "code")) == "llama"


def test_default_task_keeps_the_original_cost_behaviour(monkeypatch):
    fake_statuses(
        monkeypatch,
        {"llama": status("llama"), "claude": status("claude", balance_ok=True)},
    )

    assert run(service.pick_auto_llm(["claude", "llama"])) == "llama"


def test_pick_for_message_returns_provider_and_task(monkeypatch):
    fake_statuses(
        monkeypatch,
        {"llama": status("llama"), "gpt": status("gpt", balance_ok=True)},
    )

    provider, task = run(
        service.pick_for_message(["llama", "gpt"], "erro de compilacao no codigo")
    )

    assert task == "code"
    assert provider == "gpt"
