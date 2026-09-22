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


def test_rank_auto_llms_returns_free_providers_before_paid(monkeypatch):
    fake_statuses(
        monkeypatch,
        {
            "claude": status("claude", balance_ok=True),
            "localai": status("localai"),
            "llama": status("llama"),
        },
    )

    ranked = run(service.rank_auto_llms(["claude", "localai", "llama"], "study"))

    assert ranked == ["localai", "llama", "claude"]


def test_rank_auto_llms_can_exclude_unavailable_providers(monkeypatch):
    offline = status("localai")
    offline.available = False
    offline.online = False
    fake_statuses(
        monkeypatch,
        {"localai": offline, "llama": status("llama")},
    )

    ranked = run(service.rank_auto_llms(
        ["localai", "llama"], "study", available_only=True
    ))

    assert ranked == ["llama"]


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


# --- Pergunta que depende do cadastro ---------------------------------------


def test_registry_questions_are_detected():
    """O gatilho e a pergunta que so se responde lendo o cadastro."""
    assert service.needs_registry_read(
        "Pode acessar o banco de questoes de banco de dados no modo aula?"
    )
    assert service.needs_registry_read("Quais quizzes eu tenho cadastrados?")
    assert service.needs_registry_read("Como foi o desempenho da turma?")
    assert service.needs_registry_read("Quanto tempo de estudo o aluno teve?")


def test_plain_lesson_questions_are_not_registry_reads():
    """Resumo de aula o RAG resolve; encarecer isso nao compra qualidade."""
    assert not service.needs_registry_read("Resuma a ultima aula de banco de dados")
    assert not service.needs_registry_read("O que o professor falou sobre normalizacao?")
    assert not service.needs_registry_read("Bom dia, tudo bem?")


def test_registry_turn_demotes_weak_model_without_changing_the_task(monkeypatch):
    """O turno entra exigente, e a tarefa `study` continua barata por padrao."""
    fake_statuses(
        monkeypatch,
        {"llama": status("llama"), "claude": status("claude", balance_ok=True)},
    )

    exigente = run(service.rank_auto_llms(
        ["llama", "claude"], "study", demanding=True
    ))
    normal = run(service.rank_auto_llms(["llama", "claude"], "study"))

    assert exigente[0] == "claude"
    assert normal[0] == "llama"


def test_registry_turn_still_answers_with_the_only_model(monkeypatch):
    """Rebaixar nao e eliminar, tambem aqui."""
    fake_statuses(monkeypatch, {"llama": status("llama")})

    assert run(service.rank_auto_llms(["llama"], "study", demanding=True)) == ["llama"]


# --- O modelo configurado sobrepoe o provedor --------------------------------


def test_model_size_is_read_from_the_name():
    assert service.model_handles_tools("qwen/qwen3-8b") is False
    assert service.model_handles_tools("meta-llama/Llama-3.3-70B-Instruct") is True
    assert service.model_handles_tools("gemma2-9b-it") is False
    assert service.model_handles_tools("gpt-4o-mini") is False


def test_unknown_or_automatic_model_gives_no_verdict():
    """Modelo automatico nao vira palpite: quem chama volta a julgar o provedor."""
    assert service.model_handles_tools("") is None
    assert service.model_handles_tools("claude-sonnet-4-5") is None
    assert service.model_handles_tools("deepseek-chat") is None


def test_mini_marker_does_not_match_inside_a_family_name():
    """"gemini" contem "mini"; a borda e o que impede rebaixar o Gemini inteiro."""
    assert service.model_handles_tools("gemini-2.0-flash") is None
    assert service.model_handles_tools("gemini-1.5-flash-8b") is False


def test_strong_provider_with_a_small_model_loses_the_registry_turn(monkeypatch):
    """O caso real: `grok` esta em STRONG_LLMS apontando para um 8B."""
    fake_statuses(
        monkeypatch,
        {
            "grok": status("grok", balance_ok=True),
            "hf": status("hf", balance_ok=True),
        },
    )
    monkeypatch.setattr(
        service,
        "configured_model",
        lambda provider: {
            "grok": "qwen/qwen3-8b",
            "hf": "meta-llama/Llama-3.3-70B-Instruct",
        }[provider],
    )

    ranked = run(service.rank_auto_llms(["grok", "hf"], "study", demanding=True))

    assert ranked[0] == "hf"


def test_automatic_model_keeps_the_provider_judgement(monkeypatch):
    """Sem nome de modelo, vale o que se sabe: o provedor."""
    fake_statuses(
        monkeypatch,
        {
            "claude": status("claude", balance_ok=True),
            "llama": status("llama"),
        },
    )
    monkeypatch.setattr(service, "configured_model", lambda provider: "")

    ranked = run(service.rank_auto_llms(["llama", "claude"], "study", demanding=True))

    assert ranked[0] == "claude"
