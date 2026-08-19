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


def fake_settings(monkeypatch, *, max_chars: int, context_tokens: int):
    monkeypatch.setattr(
        service,
        "settings",
        type("S", (), {
            "education_summary_max_chars": max_chars,
            "local_llm_context_tokens": context_tokens,
        })(),
    )


def fake_llm(monkeypatch, content: str, is_error: bool = False):
    calls = []

    async def _dispatch(llm, message, history, system_prompt, **options):
        calls.append({
            "llm": llm,
            "message": message,
            "system": system_prompt,
            "options": options,
        })
        return LLMResponse(llm=llm, content=content, is_error=is_error)

    async def _resolve(preferred=None):
        return preferred or "llama"

    async def _providers(preferred=None):
        return [await _resolve(preferred)]

    monkeypatch.setattr(service, "dispatch_single", _dispatch)
    monkeypatch.setattr(service, "resolve_llm", _resolve)
    monkeypatch.setattr(service, "_summary_provider_candidates", _providers)
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


TRANSCRIPT = (
    "pessoal, o Tiago foi no quadro e resolveu a questao, "
    "entao o Tiago ganhou meio ponto extra hoje"
)


def test_extract_points_maps_names_to_roster(monkeypatch):
    fake_llm(monkeypatch, json.dumps({
        "pontuacoes": [
            {
                "aluno": "Tiago",
                "pontos": 0.5,
                "motivo": "resolveu no quadro",
                "trecho": "o Tiago ganhou meio ponto extra",
            }
        ]
    }))

    entries = run(service.extract_points(text=TRANSCRIPT, roster=ROSTER))

    assert len(entries) == 1
    assert entries[0]["student_id"] == "s2"
    assert entries[0]["student_name"] == "Thiago Souza"
    assert entries[0]["heard_name"] == "Tiago"
    assert entries[0]["points"] == 0.5


def test_extract_points_reads_json_inside_markdown_fence(monkeypatch):
    fenced = (
        "Claro, segue:\n```json\n"
        '{"pontuacoes": [{"aluno": "Aninha", "pontos": 2, '
        '"trecho": "dois pontos pra Aninha"}]}\n'
        "```\n"
    )
    fake_llm(monkeypatch, fenced)

    entries = run(service.extract_points(
        text="isso ai, dois pontos pra Aninha pela participacao",
        roster=ROSTER,
    ))

    assert len(entries) == 1
    assert entries[0]["student_id"] == "s1"
    assert entries[0]["points"] == 2.0


def test_extract_points_accepts_points_written_as_text(monkeypatch):
    fake_llm(monkeypatch, json.dumps({
        "pontuacoes": [
            {
                "aluno": "Thiago Souza",
                "pontos": "1,5 ponto",
                "trecho": "o Thiago leva um ponto e meio",
            }
        ]
    }))

    entries = run(service.extract_points(
        text="o Thiago leva um ponto e meio pela pergunta",
        roster=ROSTER,
    ))

    assert entries[0]["points"] == 1.5


def test_extract_points_discards_entries_without_name_or_value(monkeypatch):
    fake_llm(monkeypatch, json.dumps({
        "pontuacoes": [
            {"aluno": "", "pontos": 1, "trecho": "ganhou meio ponto extra"},
            {"aluno": "Tiago", "pontos": 0, "trecho": "ganhou meio ponto extra"},
            {"aluno": "Tiago", "pontos": "nenhum", "trecho": "meio ponto"},
            {"aluno": "Tiago", "pontos": 999, "trecho": "meio ponto"},
        ]
    }))

    assert run(service.extract_points(text=TRANSCRIPT, roster=ROSTER)) == []


def test_extract_points_discards_student_never_named_in_the_block(monkeypatch):
    # O prompt leva a turma inteira; o modelo nao pode premiar quem so
    # aparece nessa lista.
    fake_llm(monkeypatch, json.dumps({
        "pontuacoes": [
            {
                "aluno": "Maria Clara Lima",
                "pontos": 1,
                "trecho": "o Tiago ganhou meio ponto extra",
            }
        ]
    }))

    assert run(service.extract_points(text=TRANSCRIPT, roster=ROSTER)) == []


def test_extract_points_discards_quote_absent_from_the_transcript(monkeypatch):
    fake_llm(monkeypatch, json.dumps({
        "pontuacoes": [
            {
                "aluno": "Tiago",
                "pontos": 1,
                "trecho": "vou dar um ponto para todo mundo que veio hoje",
            }
        ]
    }))

    assert run(service.extract_points(text=TRANSCRIPT, roster=ROSTER)) == []


def test_extract_points_accepts_a_quote_reworded_by_the_model(monkeypatch):
    fake_llm(monkeypatch, json.dumps({
        "pontuacoes": [
            {
                "aluno": "Tiago",
                "pontos": 0.5,
                "trecho": "o Tiago ganhou meio ponto extra hoje.",
            }
        ]
    }))

    entries = run(service.extract_points(text=TRANSCRIPT, roster=ROSTER))

    assert len(entries) == 1


def test_extract_points_skips_the_llm_when_the_block_has_no_trigger(monkeypatch):
    calls = fake_llm(monkeypatch, json.dumps({"pontuacoes": []}))

    entries = run(service.extract_points(
        text="hoje a gente comeca normalizacao de tabelas, terceira forma normal",
        roster=ROSTER,
    ))

    assert entries == []
    assert calls == []


def test_mentions_points_ignores_words_that_only_contain_the_trigger():
    assert not service.mentions_points("vamos apontar as chaves estrangeiras")
    assert service.mentions_points("isso vale meio ponto")
    assert service.mentions_points("dou um decimo pra quem responder agora")


def test_extract_points_returns_empty_on_unparseable_answer(monkeypatch):
    fake_llm(monkeypatch, "nao identifiquei pontuacoes nesse trecho")

    assert run(service.extract_points(text=TRANSCRIPT, roster=ROSTER)) == []


def test_extract_points_returns_empty_when_llm_fails(monkeypatch):
    fake_llm(monkeypatch, "sem credito", is_error=True)

    assert run(service.extract_points(text=TRANSCRIPT, roster=ROSTER)) == []


def test_extract_points_skips_llm_call_for_blank_text(monkeypatch):
    calls = fake_llm(monkeypatch, json.dumps({"pontuacoes": []}))

    assert run(service.extract_points(text="   ", roster=ROSTER)) == []
    assert calls == []


def test_points_prompt_lists_roster_names(monkeypatch):
    calls = fake_llm(monkeypatch, json.dumps({"pontuacoes": []}))

    run(service.extract_points(text=TRANSCRIPT, roster=ROSTER))

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
        discipline="Matematica",
        title="Funcoes",
        segments=["primeiro trecho", "segundo trecho"],
    ))

    assert outcome["summary"] == "## Resumo\nAula sobre funcoes."
    assert outcome["used_segments"] == 2
    assert len(calls) == 1


def test_long_lesson_is_summarised_in_two_stages(monkeypatch):
    fake_settings(monkeypatch, max_chars=2000, context_tokens=4096)
    calls = fake_llm(monkeypatch, "resumo parcial")

    segments = ["x" * 1500 for _ in range(4)]
    outcome = run(service.generate_summary(
        discipline="Historia", title="", segments=segments
    ))

    # Quatro trechos de 1500 chars cabem em tres janelas de 2000, mais a
    # chamada final que junta os parciais.
    assert len(calls) == 5
    assert outcome["summary"] == "resumo parcial"
    assert outcome["used_segments"] == 4


def test_summary_returns_empty_for_lesson_without_text(monkeypatch):
    calls = fake_llm(monkeypatch, "nao deveria ser chamado")

    outcome = run(service.generate_summary(
        discipline="Fisica", title="", segments=["", "   "]
    ))

    assert outcome["summary"] == ""
    assert outcome["used_segments"] == 0
    assert calls == []


def test_summary_reports_error_when_model_fails(monkeypatch):
    fake_llm(monkeypatch, "modelo offline", is_error=True)

    outcome = run(service.generate_summary(
        discipline="Quimica", title="", segments=["trecho"]
    ))

    assert outcome["summary"] == ""
    assert outcome["error"] == "modelo offline"


def test_summary_graph_falls_back_to_next_free_provider(monkeypatch):
    calls = []

    async def _providers(preferred=None):
        return ["localai", "llama"]

    async def _dispatch(llm, message, history, system_prompt, **options):
        calls.append(llm)
        if llm == "localai":
            return LLMResponse(llm=llm, content="modelo lento", is_error=True)
        return LLMResponse(llm=llm, content="resumo pelo Ollama")

    monkeypatch.setattr(service, "_summary_provider_candidates", _providers)
    monkeypatch.setattr(service, "dispatch_single", _dispatch)

    outcome = run(service.generate_summary(
        discipline="Quimica", title="", segments=["trecho"]
    ))

    assert outcome["summary"] == "resumo pelo Ollama"
    assert outcome["llm"] == "llama"
    assert calls == ["localai", "llama"]
    assert [item["success"] for item in outcome["attempts"]] == [False, True]


def test_long_summary_stops_after_first_provider_failure(monkeypatch):
    fake_settings(monkeypatch, max_chars=2000, context_tokens=4096)
    calls = fake_llm(monkeypatch, "Timeout ao consultar o provedor", is_error=True)

    outcome = run(service.generate_summary(
        discipline="Quimica",
        title="",
        segments=["x" * 1500 for _ in range(4)],
    ))

    assert outcome["summary"] == ""
    assert "Timeout" in outcome["error"]
    assert len(calls) == 1


def test_summary_reports_empty_model_response(monkeypatch):
    fake_llm(monkeypatch, "")

    outcome = run(service.generate_summary(
        discipline="Quimica", title="", segments=["trecho"]
    ))

    assert outcome["summary"] == ""
    assert outcome["error"] == "O modelo retornou um resumo vazio"


def test_summary_focus_reaches_the_prompt(monkeypatch):
    calls = fake_llm(monkeypatch, "resumo")

    run(service.generate_summary(
        discipline="Biologia",
        title="Genetica",
        segments=["trecho"],
        focus="datas de prova",
    ))

    assert "datas de prova" in calls[0]["message"]
    assert "Biologia" in calls[0]["message"]


def test_summary_prompt_repairs_only_unambiguous_transcription_errors(monkeypatch):
    calls = fake_llm(monkeypatch, "resumo")

    run(service.generate_summary(
        discipline="Banco de Dados",
        title="Normalizacao",
        segments=["a terceira forma normau evita dependencia transitiva"],
    ))

    prompt = calls[0]["message"]
    assert "erros evidentes de reconhecimento de fala" in prompt
    assert "quando ela for inequivoca" in prompt
    assert "em vez de preencher com suposicao" in prompt


def test_localai_summary_disables_thinking_and_limits_output(monkeypatch):
    calls = fake_llm(monkeypatch, "resumo")

    outcome = run(service.generate_summary(
        discipline="Banco de Dados",
        title="",
        segments=["trecho"],
        llm="localai",
    ))

    assert outcome["summary"] == "resumo"
    assert calls[0]["options"] == {
        "max_tokens": service._answer_tokens("localai"),
        "reasoning_effort": "none",
    }


def test_detailed_summary_asks_for_the_long_structure(monkeypatch):
    calls = fake_llm(monkeypatch, "resumo detalhado")

    outcome = run(service.generate_summary(
        discipline="Banco de Dados",
        title="Normalizacao",
        segments=["trecho da aula"],
        llm="localai",
        style="detailed",
    ))

    prompt = calls[0]["message"]
    assert outcome["style"] == "detailed"
    assert "## Desenvolvimento da aula" in prompt
    assert "## Exemplos e exercicios resolvidos" in prompt
    # O tamanho e pedido no prompt, nao imposto por um corte de tokens.
    assert "nao encurte para economizar espaco" in prompt


def test_standard_summary_keeps_the_short_structure(monkeypatch):
    calls = fake_llm(monkeypatch, "resumo")

    outcome = run(service.generate_summary(
        discipline="Banco de Dados",
        title="",
        segments=["trecho da aula"],
        llm="localai",
    ))

    prompt = calls[0]["message"]
    assert outcome["style"] == "standard"
    assert "## Principais topicos" in prompt
    assert "## Desenvolvimento da aula" not in prompt
    assert "Mantenha o resumo enxuto" in prompt


def test_both_styles_get_the_same_output_ceiling(monkeypatch):
    # O teto de saida e tecnico (nenhum provedor aceita resposta infinita) e
    # nao um jeito de encurtar um dos formatos: quem define o tamanho e o
    # prompt. Se o teto voltar a variar por estilo, o detalhado volta a sair
    # cortado antes das ultimas secoes.
    padrao = fake_llm(monkeypatch, "resumo")
    run(service.generate_summary(
        discipline="Banco de Dados", title="", segments=["trecho"],
        llm="claude",
    ))

    detalhado = fake_llm(monkeypatch, "resumo")
    run(service.generate_summary(
        discipline="Banco de Dados", title="", segments=["trecho"],
        llm="claude", style="detailed",
    ))

    teto = service._answer_tokens("claude")
    assert padrao[0]["options"]["max_tokens"] == teto
    assert detalhado[0]["options"]["max_tokens"] == teto


def test_unknown_summary_style_falls_back_to_standard(monkeypatch):
    calls = fake_llm(monkeypatch, "resumo")

    outcome = run(service.generate_summary(
        discipline="Banco de Dados",
        title="",
        segments=["trecho da aula"],
        style="completissimo",
    ))

    assert outcome["style"] == "standard"
    assert "## Desenvolvimento da aula" not in calls[0]["message"]


def test_partial_size_comes_from_the_share_of_the_final_window(monkeypatch):
    # O parcial nao tem tamanho fixo: ele recebe a fatia da janela final que
    # sobra para ele. Com poucos blocos a fatia e grande e o parcial preserva
    # o desenvolvimento da aula; era o corte fixo em 8/16 linhas que fazia o
    # resumo detalhado chegar sem material e sair menor que o comum.
    fake_settings(monkeypatch, max_chars=24000, context_tokens=32000)
    calls = fake_llm(monkeypatch, "parcial")

    run(service.generate_summary(
        discipline="Banco de Dados",
        title="",
        segments=["x" * 20000 for _ in range(2)],
        llm="claude",
        style="detailed",
    ))

    esperado = service._partial_lines(service._partial_budget_chars(24000, 2))
    partial = calls[0]
    assert "Este e um trecho de uma aula longa" in partial["message"]
    assert f"no maximo {esperado} linhas" in partial["message"]
    assert esperado > 100


def test_more_blocks_means_shorter_partials(monkeypatch):
    # A soma dos parciais precisa caber em uma chamada: quanto mais blocos,
    # menor a fatia de cada um.
    dois = service._partial_lines(service._partial_budget_chars(24000, 2))
    dez = service._partial_lines(service._partial_budget_chars(24000, 10))

    assert dez < dois
    assert dez >= 8


def test_partials_fit_together_in_the_final_call():
    # Com folga: um modelo que passa um pouco do tamanho pedido nao pode
    # fazer a condensacao empacar, porque empacar trunca o fim da aula.
    for blocos in (2, 3, 5, 10):
        soma = service._partial_budget_chars(24000, blocos) * blocos
        assert soma < 24000


def test_local_window_keeps_room_for_the_answer(monkeypatch):
    fake_settings(monkeypatch, max_chars=24000, context_tokens=8192)

    budget = service.summary_budget_chars("localai")
    answer = service._answer_tokens("localai")

    # Transcricao + prompt + resposta cabem na janela do modelo local: o que
    # o modelo escreve nao pode disputar espaco com o que ele le.
    usados = budget / service._CHARS_PER_TOKEN + service._PROMPT_TOKENS + answer
    assert usados <= 8192
    assert answer >= 768


def test_summary_candidates_can_forbid_paid_fallback(monkeypatch):
    monkeypatch.setattr(
        service,
        "settings",
        type("S", (), {
            "active_llms": ["claude", "localai", "llama"],
            "education_summary_allow_paid_fallback": False,
            "education_summary_max_providers": 3,
        })(),
    )

    async def _rank(candidates, task, available_only=False):
        assert task == "study"
        assert available_only is True
        return ["localai", "llama", "claude"]

    monkeypatch.setattr(service, "rank_auto_llms", _rank)

    providers = run(service._summary_provider_candidates(None))

    assert providers == ["localai", "llama"]


# --- Janela de contexto do resumo ------------------------------------------


def test_local_model_window_shrinks_the_transcript_block(monkeypatch):
    fake_settings(monkeypatch, max_chars=24000, context_tokens=2048)

    budget = service.summary_budget_chars("localai")

    # A aula inteira nao pode ser oferecida a um modelo de 2048 tokens: o
    # servidor recusa a chamada em vez de resumir pior.
    assert budget < 4000
    assert budget > 800


def test_cloud_model_keeps_the_configured_window(monkeypatch):
    fake_settings(monkeypatch, max_chars=24000, context_tokens=2048)

    assert service.summary_budget_chars("claude") == 24000


def test_context_limit_is_read_from_the_model_error():
    localai = (
        "rpc error: code = Internal desc = request (6224 tokens) exceeds the "
        "available context size (2048 tokens), try increasing it"
    )
    openai = "This model's maximum context length is 8192 tokens, however..."

    assert service.context_limit_from_error(localai) == 2048
    assert service.context_limit_from_error(openai) == 8192
    assert service.context_limit_from_error("modelo offline") is None


def test_summary_retries_with_the_window_reported_by_the_model(monkeypatch):
    fake_settings(monkeypatch, max_chars=24000, context_tokens=8192)
    calls = []

    async def _dispatch(llm, message, history, system_prompt, **options):
        calls.append(message)
        if len(calls) == 1:
            return LLMResponse(
                llm=llm,
                content="request (6224 tokens) exceeds the available context "
                        "size (2048 tokens), try increasing it",
                is_error=True,
            )
        return LLMResponse(llm=llm, content="resumo")

    async def _resolve(preferred=None):
        return "localai"

    monkeypatch.setattr(service, "dispatch_single", _dispatch)
    monkeypatch.setattr(service, "resolve_llm", _resolve)

    outcome = run(service.generate_summary(
        discipline="Banco de Dados",
        title="",
        segments=["x " * 1500],
        llm="localai",
    ))

    # A primeira tentativa foi em uma janela so; depois do erro a aula e
    # refatiada pela medida que o proprio modelo informou.
    assert outcome["summary"] == "resumo"
    assert len(calls) > 2


def test_segment_longer_than_the_window_is_split():
    windows = service._windows(["frase. " * 2000], 2000)

    assert len(windows) > 1
    assert all(len(window) <= 2000 for window in windows)
    # Nada pode se perder na quebra.
    assert "".join(windows).count("frase") == 2000


def test_normalize_name_strips_accents_and_punctuation():
    assert service.normalize_name("José D'Ávila-Neto") == "jose d avila neto"


# --- Contexto de estudo para o chat ----------------------------------------


def fake_hits(monkeypatch, hits):
    from app.services import qdrant_service

    async def _search(**kwargs):
        return hits

    monkeypatch.setattr(qdrant_service, "search_lesson_transcripts", _search)


def fake_catch_up(monkeypatch, indexed: int = 0):
    """Impede que a busca vazia dispare reindexacao de verdade no teste."""
    from app.services import lesson_index_service

    calls = []

    async def _catch_up(*, tutor_id, reason=""):
        calls.append(reason)
        return {"indexed": indexed}

    monkeypatch.setattr(lesson_index_service, "catch_up", _catch_up)
    return calls


def test_study_context_formats_hits_with_discipline_and_date(monkeypatch):
    fake_hits(monkeypatch, [
        {
            "score": 0.8,
            "discipline": "Matematica",
            "lesson_date": "2026-08-04",
            "content": "funcao do primeiro grau",
        }
    ])

    context = run(service.build_study_context(tutor_id="t1", message="funcoes"))

    assert "Matematica, 2026-08-04" in context
    assert "funcao do primeiro grau" in context


def test_study_context_drops_weak_matches(monkeypatch):
    fake_hits(monkeypatch, [
        {"score": 0.05, "discipline": "Historia", "content": "nada a ver"}
    ])
    fake_catch_up(monkeypatch)

    assert run(service.build_study_context(tutor_id="t1", message="funcoes")) == ""


def test_study_context_is_empty_without_hits(monkeypatch):
    fake_hits(monkeypatch, [])
    fake_catch_up(monkeypatch)

    assert run(service.build_study_context(tutor_id="t1", message="funcoes")) == ""


def test_empty_search_asks_for_a_reindex_before_giving_up(monkeypatch):
    from app.services import qdrant_service

    attempts = []
    # A primeira busca nao acha nada; depois da reindexacao o trecho aparece.
    async def _search(**kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            return []
        return [{
            "score": 0.7,
            "discipline": "Banco de Dados",
            "lesson_date": "2026-08-13",
            "content": "normalizacao de tabelas",
        }]

    monkeypatch.setattr(qdrant_service, "search_lesson_transcripts", _search)
    calls = fake_catch_up(monkeypatch, indexed=12)

    context = run(service.build_study_context(tutor_id="t1", message="normalizacao"))

    assert "normalizacao de tabelas" in context
    assert len(attempts) == 2
    assert calls and "sem resultado" in calls[0]


def test_reindex_that_writes_nothing_does_not_search_again(monkeypatch):
    from app.services import qdrant_service

    attempts = []

    async def _search(**kwargs):
        attempts.append(1)
        return []

    monkeypatch.setattr(qdrant_service, "search_lesson_transcripts", _search)
    fake_catch_up(monkeypatch, indexed=0)

    assert run(service.build_study_context(tutor_id="t1", message="funcoes")) == ""
    assert len(attempts) == 1


def test_study_context_survives_a_qdrant_failure(monkeypatch):
    from app.services import qdrant_service

    async def _boom(**kwargs):
        raise RuntimeError("qdrant fora do ar")

    monkeypatch.setattr(qdrant_service, "search_lesson_transcripts", _boom)
    fake_catch_up(monkeypatch)

    assert run(service.build_study_context(tutor_id="t1", message="funcoes")) == ""


def test_study_context_tells_the_model_not_to_guess(monkeypatch):
    fake_hits(monkeypatch, [
        {"score": 0.9, "discipline": "Fisica", "content": "segunda lei de newton"}
    ])

    context = run(service.build_study_context(tutor_id="t1", message="newton"))

    assert "em vez de completar com suposicao" in context
