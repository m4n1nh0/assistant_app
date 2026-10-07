"""O resumo segue o tipo da gravacao: aula, palestra ou apresentacao de grupo.

Falha real: uma palestra era resumida com o prompt de aula. O texto saia dizendo "A aula
iniciou com...", "O professor destacou..." e "os alunos", para um palestrante e um
publico que nao tinham nada de sala de aula.
"""

from __future__ import annotations

import asyncio

import pytest

from app.models.schemas import LLMResponse
from app.services import education_service as service


def run(coro):
    return asyncio.run(coro)


def fake_llm(monkeypatch, content="resumo"):
    calls = []

    async def _dispatch(llm, message, history, system_prompt, **options):
        calls.append({"message": message, "system": system_prompt})
        return LLMResponse(llm=llm, content=content, is_error=False)

    async def _providers(preferred=None):
        return [preferred or "llama"]

    monkeypatch.setattr(service, "dispatch_single", _dispatch)
    monkeypatch.setattr(service, "_summary_provider_candidates", _providers)
    return calls


def prompt_de(kind, style="standard", **extra):
    return service.build_summary_prompt(
        discipline=extra.pop("discipline", ""),
        title=extra.pop("title", "Titulo"),
        segments=["falou sobre sensores"],
        style=style,
        kind=kind,
        **extra,
    )


# --- tipo ------------------------------------------------------------------


def test_tipo_desconhecido_ou_vazio_vira_aula():
    assert service.normalize_recording_kind(None) == "aula"
    assert service.normalize_recording_kind("") == "aula"
    assert service.normalize_recording_kind("webinar") == "aula"
    assert service.normalize_recording_kind(" Palestra ") == "palestra"
    assert service.normalize_recording_kind("apresentacao") == "apresentacao"


# --- aula: o texto de sempre ----------------------------------------------


@pytest.mark.parametrize("style", ["standard", "detailed"])
def test_aula_sem_tipo_e_aula_com_tipo_geram_o_mesmo_prompt(style):
    sem_tipo = service.build_summary_prompt(
        discipline="Banco de Dados", title="Normalizacao",
        segments=["falou sobre sensores"], style=style)
    com_tipo = prompt_de("aula", style=style, discipline="Banco de Dados",
                         title="Normalizacao")

    assert sem_tipo["prompt"] == com_tipo["prompt"]
    assert sem_tipo["system_prompt"] == com_tipo["system_prompt"]


def test_prompt_de_aula_continua_falando_de_aula_e_professor():
    construido = prompt_de("aula", style="detailed", discipline="Banco de Dados",
                           title="Normalizacao")

    assert "Disciplina: Banco de Dados\nAula: Normalizacao" in construido["prompt"]
    assert "## Desenvolvimento da aula" in construido["prompt"]
    assert "Monte o resumo da aula" in construido["prompt"]
    assert "substitui a aula para quem faltou" in construido["prompt"]
    assert construido["system_prompt"].startswith("Voce resume aulas")


# --- palestra --------------------------------------------------------------


@pytest.mark.parametrize("style", ["standard", "detailed"])
def test_palestra_nao_fala_de_aula_nem_de_professor(style):
    construido = prompt_de("palestra", style=style, title="Sistemas de controle")
    texto = construido["prompt"] + construido["system_prompt"]

    assert "Palestra: Sistemas de controle" in construido["prompt"]
    assert "Monte o resumo da palestra" in construido["prompt"]
    assert "Voce resume palestras" in construido["system_prompt"]
    assert "## Principais ideias" in construido["prompt"] or style == "detailed"
    assert "## Perguntas do publico" in construido["prompt"]
    # A estrutura de aula nao vaza para a palestra.
    for secao in ("## Tarefas e avisos", "## Duvidas levantadas",
                  "## Definicoes e formulas", "datas de prova"):
        assert secao not in construido["prompt"]
    # E o modelo e avisado de nao inventar professor, aluno ou turma.
    assert "nao os chame de professor, aluno ou turma" in construido["system_prompt"]
    assert "Aula:" not in construido["prompt"]
    assert "da aula" not in construido["prompt"]
    assert "a aula" not in construido["prompt"].replace("palestra", "")


def test_palestra_sem_disciplina_nao_imprime_disciplina_vazia():
    construido = prompt_de("palestra", discipline="", title="IoT")

    assert "Disciplina:" not in construido["prompt"]
    assert construido["prompt"].startswith("Palestra: IoT")


def test_palestra_com_disciplina_informada_mantem_a_linha():
    construido = prompt_de("palestra", discipline="2026.2 IoT", title="Sensores")

    assert construido["prompt"].startswith("Disciplina: 2026.2 IoT\nPalestra: Sensores")


def test_resumo_detalhado_da_palestra_tem_desenvolvimento_proprio():
    construido = prompt_de("palestra", style="detailed", title="Sensores")

    assert "## Desenvolvimento da palestra" in construido["prompt"]
    assert "## Exemplos, casos e historias" in construido["prompt"]
    assert "substitui a palestra para quem nao assistiu" in construido["prompt"]
    assert "## Desenvolvimento da aula" not in construido["prompt"]


# --- apresentacao ----------------------------------------------------------


@pytest.mark.parametrize("style", ["standard", "detailed"])
def test_apresentacao_descreve_o_trabalho_do_grupo_sem_nota(style):
    construido = prompt_de("apresentacao", style=style, discipline="ARA0040 - BD",
                           title="Apresentacao: GRUPO 3")

    # O titulo ja traz o rotulo: nao sai "Apresentacao: Apresentacao: GRUPO 3".
    assert "\nApresentacao: GRUPO 3" in construido["prompt"]
    assert "Apresentacao: Apresentacao" not in construido["prompt"]
    assert "## O projeto" in construido["prompt"]
    assert "## Perguntas e respostas" in construido["prompt"]
    assert "## Pontos a esclarecer" in construido["prompt"]
    assert "Tarefas e avisos" not in construido["prompt"]
    assert "Monte o resumo da apresentacao" in construido["prompt"]
    assert "nao atribua nota" in construido["system_prompt"]
    assert "Voce resume apresentacoes de trabalhos de grupo" in construido["system_prompt"]


def test_titulo_sem_o_rotulo_ganha_o_rotulo_do_tipo():
    construido = prompt_de("apresentacao", title="Projeto de IoT")

    assert "Apresentacao: Projeto de IoT" in construido["prompt"]


# --- caminho do servidor (generate_summary) --------------------------------


def test_generate_summary_usa_o_prompt_do_tipo_no_modelo_e_no_papel(monkeypatch):
    calls = fake_llm(monkeypatch)

    run(service.generate_summary(
        discipline="", title="Sistemas de controle",
        segments=["falou sobre sensores"], kind="palestra",
    ))

    assert len(calls) == 1
    assert "Palestra: Sistemas de controle" in calls[0]["message"]
    assert "Monte o resumo da palestra" in calls[0]["message"]
    assert "Voce resume palestras" in calls[0]["system"]


def test_generate_summary_sem_tipo_continua_sendo_de_aula(monkeypatch):
    calls = fake_llm(monkeypatch)

    run(service.generate_summary(
        discipline="Matematica", title="Funcoes", segments=["x"]))

    assert "Aula: Funcoes" in calls[0]["message"]
    assert calls[0]["system"].startswith("Voce resume aulas")


def test_blocos_parciais_de_palestra_tambem_falam_de_palestra(monkeypatch):
    monkeypatch.setattr(
        service, "settings",
        type("S", (), {"education_summary_max_chars": 2000,
                       "local_llm_context_tokens": 4096})(),
    )
    calls = fake_llm(monkeypatch, "parcial")

    run(service.generate_summary(
        discipline="", title="Sensores",
        segments=["x" * 1500 for _ in range(4)], kind="palestra",
    ))

    parciais = [c for c in calls if "Este e um trecho de" in c["message"]]
    assert parciais, "esperava ao menos um resumo parcial"
    for chamada in parciais:
        assert "Este e um trecho de uma palestra longa" in chamada["message"]
        assert "uma aula longa" not in chamada["message"]
        assert "Voce resume palestras" in chamada["system"]


# --- reuniao ---------------------------------------------------------------------


@pytest.mark.parametrize("style", ["standard", "detailed"])
def test_reuniao_fala_de_participantes_decisoes_e_encaminhamentos(style):
    construido = prompt_de("reuniao", style=style, title="Colegiado de outubro")
    prompt = construido["prompt"]

    assert "Reuniao: Colegiado de outubro" in prompt
    assert "Monte o resumo da reuniao" in prompt
    assert "## Decisoes" in prompt and "## Encaminhamentos" in prompt
    assert "## Pendencias e duvidas em aberto" in prompt
    assert "Voce resume reunioes" in construido["system_prompt"]
    assert "nunca invente responsavel nem prazo" in construido["system_prompt"]
    assert "nao os chame de professor, aluno ou turma" in construido["system_prompt"]
    # Nada da estrutura de aula ou de palestra vaza para a reuniao.
    for secao in ("## Tarefas e avisos", "## Duvidas levantadas",
                  "## Perguntas do publico", "datas de prova", "Aula:"):
        assert secao not in prompt
    assert "Disciplina:" not in prompt


def test_reuniao_detalhada_tem_desenvolvimento_proprio():
    prompt = prompt_de("reuniao", style="detailed", title="Colegiado")["prompt"]

    assert "## Desenvolvimento da reuniao" in prompt
    assert "## Divergencias e alternativas" in prompt
    assert "substitui a reuniao para quem nao participou" in prompt


def test_tipo_reuniao_e_normalizado_e_listado():
    assert service.normalize_recording_kind(" Reuniao ") == "reuniao"
    assert "reuniao" in service.RECORDING_KINDS


def test_generate_summary_de_reuniao_usa_o_prompt_do_tipo(monkeypatch):
    calls = fake_llm(monkeypatch)

    run(service.generate_summary(
        discipline="", title="Colegiado", segments=["decidimos adiar a compra"],
        kind="reuniao",
    ))

    assert "Reuniao: Colegiado" in calls[0]["message"]
    assert "Voce resume reunioes" in calls[0]["system"]
