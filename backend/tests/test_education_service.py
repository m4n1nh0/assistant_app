import asyncio
import json

from app.models.schemas import LLMResponse
from app.services import education_service as service


def run(coro):
    return asyncio.run(coro)


ROSTER = [
    {"id": "s1", "name": "Ana Paula Ribeiro", "aliases": ["Aninha"]},
    {"id": "s2", "name": "Thiago Souza", "aliases": []},
    {"id": "s3", "name": "Maria Clara Lima", "aliases": []},
    {"id": "s4", "name": "Maria Eduarda Alves", "aliases": []},
]


def fake_llm(monkeypatch, content: str, is_error: bool = False):
    calls = []

    async def _dispatch(llm, message, history, system_prompt):
        calls.append({"llm": llm, "message": message, "system": system_prompt})
        return LLMResponse(llm=llm, content=content, is_error=is_error)

    async def _resolve(preferred=None):
        return preferred or "llama"

    monkeypatch.setattr(service, "dispatch_single", _dispatch)
    monkeypatch.setattr(service, "resolve_llm", _resolve)
    return calls


# --- Casamento de nomes ----------------------------------------------------


def test_exact_name_matches_with_full_confidence():
    match = service.match_student("Thiago Souza", ROSTER)
    assert match["student_id"] == "s2"
    assert match["confidence"] == 1.0


def test_match_ignores_accents_and_case():
    match = service.match_student("ANA PÁULA RIBEIRO", ROSTER)
    assert match["student_id"] == "s1"


def test_alias_matches_student():
    match = service.match_student("Aninha", ROSTER)
    assert match["student_id"] == "s1"


def test_unique_first_name_matches_and_uses_registered_name():
    match = service.match_student("Thiago", ROSTER)
    assert match["student_id"] == "s2"
    assert match["student_name"] == "Thiago Souza"


def test_ambiguous_first_name_is_not_assigned_to_a_student():
    # Duas Marias na turma: atribuir a qualquer uma seria chute.
    match = service.match_student("Maria", ROSTER)
    assert match["student_id"] is None
    assert match["student_name"] == "Maria"


def test_misheard_name_still_matches_by_similarity():
    match = service.match_student("Tiago Souza", ROSTER)
    assert match["student_id"] == "s2"


def test_unknown_name_is_kept_as_heard():
    match = service.match_student("Joao Pedro", ROSTER)
    assert match["student_id"] is None
    assert match["student_name"] == "Joao Pedro"


def test_empty_roster_keeps_heard_name():
    match = service.match_student("Fulano", [])
    assert match["student_id"] is None
    assert match["student_name"] == "Fulano"


# --- Extracao de pontuacao -------------------------------------------------


def test_extract_points_maps_names_to_roster(monkeypatch):
    fake_llm(monkeypatch, json.dumps({
        "pontuacoes": [
            {
                "aluno": "Tiago",
                "pontos": 0.5,
                "motivo": "resolveu no quadro",
                "trecho": "Tiago ganhou meio ponto",
            }
        ]
    }))

    entries = run(service.extract_points(text="aula de hoje", roster=ROSTER))

    assert len(entries) == 1
    assert entries[0]["student_id"] == "s2"
    assert entries[0]["student_name"] == "Thiago Souza"
    assert entries[0]["heard_name"] == "Tiago"
    assert entries[0]["points"] == 0.5


def test_extract_points_reads_json_inside_markdown_fence(monkeypatch):
    fenced = (
        "Claro, segue:\n```json\n"
        '{"pontuacoes": [{"aluno": "Aninha", "pontos": 2}]}\n'
        "```\n"
    )
    fake_llm(monkeypatch, fenced)

    entries = run(service.extract_points(text="aula", roster=ROSTER))

    assert len(entries) == 1
    assert entries[0]["student_id"] == "s1"
    assert entries[0]["points"] == 2.0


def test_extract_points_accepts_points_written_as_text(monkeypatch):
    fake_llm(monkeypatch, json.dumps({
        "pontuacoes": [{"aluno": "Thiago Souza", "pontos": "1,5 ponto"}]
    }))

    entries = run(service.extract_points(text="aula", roster=ROSTER))

    assert entries[0]["points"] == 1.5


def test_extract_points_discards_entries_without_name_or_value(monkeypatch):
    fake_llm(monkeypatch, json.dumps({
        "pontuacoes": [
            {"aluno": "", "pontos": 1},
            {"aluno": "Thiago Souza", "pontos": 0},
            {"aluno": "Thiago Souza", "pontos": "nenhum"},
            {"aluno": "Thiago Souza", "pontos": 999},
        ]
    }))

    assert run(service.extract_points(text="aula", roster=ROSTER)) == []


def test_extract_points_returns_empty_on_unparseable_answer(monkeypatch):
    fake_llm(monkeypatch, "nao identifiquei pontuacoes nesse trecho")

    assert run(service.extract_points(text="aula", roster=ROSTER)) == []


def test_extract_points_returns_empty_when_llm_fails(monkeypatch):
    fake_llm(monkeypatch, "sem credito", is_error=True)

    assert run(service.extract_points(text="aula", roster=ROSTER)) == []


def test_extract_points_skips_llm_call_for_blank_text(monkeypatch):
    calls = fake_llm(monkeypatch, json.dumps({"pontuacoes": []}))

    assert run(service.extract_points(text="   ", roster=ROSTER)) == []
    assert calls == []


def test_points_prompt_lists_roster_names(monkeypatch):
    calls = fake_llm(monkeypatch, json.dumps({"pontuacoes": []}))

    run(service.extract_points(text="aula", roster=ROSTER))

    assert "Ana Paula Ribeiro" in calls[0]["message"]
    assert "Maria Eduarda Alves" in calls[0]["message"]


# --- Deduplicacao ----------------------------------------------------------


def test_duplicate_detected_by_identical_quote():
    entry = {
        "student_name": "Thiago Souza",
        "points": 1.0,
        "quote": "Thiago ganhou um ponto",
        "reason": None,
    }
    existing = [dict(entry)]

    assert service.is_duplicate_point(entry, existing) is True


def test_same_student_with_different_reason_is_not_duplicate():
    existing = [{
        "student_name": "Thiago Souza",
        "points": 1.0,
        "quote": "acertou a primeira",
        "reason": "primeira questao",
    }]
    entry = {
        "student_name": "Thiago Souza",
        "points": 1.0,
        "quote": "acertou a segunda",
        "reason": "segunda questao",
    }

    assert service.is_duplicate_point(entry, existing) is False


def test_different_amounts_are_not_duplicates():
    existing = [{
        "student_name": "Thiago Souza", "points": 1.0, "quote": "x", "reason": None,
    }]
    entry = {
        "student_name": "Thiago Souza", "points": 2.0, "quote": "x", "reason": None,
    }

    assert service.is_duplicate_point(entry, existing) is False


# --- Resumo ----------------------------------------------------------------


def test_summary_uses_single_call_for_short_lesson(monkeypatch):
    calls = fake_llm(monkeypatch, "## Resumo\nAula sobre funcoes.")

    outcome = run(service.generate_summary(
        subject="Matematica",
        title="Funcoes",
        segments=["primeiro trecho", "segundo trecho"],
    ))

    assert outcome["summary"] == "## Resumo\nAula sobre funcoes."
    assert outcome["used_segments"] == 2
    assert len(calls) == 1


def test_long_lesson_is_summarised_in_two_stages(monkeypatch):
    monkeypatch.setattr(
        service, "settings", type("S", (), {"education_summary_max_chars": 2000})()
    )
    calls = fake_llm(monkeypatch, "resumo parcial")

    segments = ["x" * 1500 for _ in range(4)]
    outcome = run(service.generate_summary(
        subject="Historia", title="", segments=segments
    ))

    # Quatro trechos de 1500 chars cabem em tres janelas de 2000, mais a
    # chamada final que junta os parciais.
    assert len(calls) == 5
    assert outcome["summary"] == "resumo parcial"
    assert outcome["used_segments"] == 4


def test_summary_returns_empty_for_lesson_without_text(monkeypatch):
    calls = fake_llm(monkeypatch, "nao deveria ser chamado")

    outcome = run(service.generate_summary(
        subject="Fisica", title="", segments=["", "   "]
    ))

    assert outcome["summary"] == ""
    assert outcome["used_segments"] == 0
    assert calls == []


def test_summary_reports_error_when_model_fails(monkeypatch):
    fake_llm(monkeypatch, "modelo offline", is_error=True)

    outcome = run(service.generate_summary(
        subject="Quimica", title="", segments=["trecho"]
    ))

    assert outcome["summary"] == ""
    assert outcome["error"] == "modelo offline"


def test_summary_focus_reaches_the_prompt(monkeypatch):
    calls = fake_llm(monkeypatch, "resumo")

    run(service.generate_summary(
        subject="Biologia",
        title="Genetica",
        segments=["trecho"],
        focus="datas de prova",
    ))

    assert "datas de prova" in calls[0]["message"]
    assert "Biologia" in calls[0]["message"]


def test_normalize_name_strips_accents_and_punctuation():
    assert service.normalize_name("José D'Ávila-Neto") == "jose d avila neto"
