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
