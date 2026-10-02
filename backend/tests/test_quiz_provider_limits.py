"""Geracao do quiz com provedores que falham de jeitos diferentes.

Falha de aula real: pedidas 20 perguntas, veio 1, com esta fila de provedores:

- `claude` e `gpt` sem credito, os dois primeiros do ranking;
- `gemini` com 404;
- `grok` recusando a fonte por tamanho ("Limit 7000, Requested 14940");
- `together` e `hf` respondendo, mas sem plano repetindo a mesma pergunta.

O que quebrava, cada um coberto aqui:

- o plano tentava so os dois primeiros da fila, justamente os mortos, e sem plano
  os modelos menores repetem;
- recusa por tamanho nao era tratada: o provedor ficava na fila e falhava em todo
  lote, quando cabia com a fonte menor;
- a validacao perguntava ao ranking antigo, comecando pelo provedor sem credito;
- "todas repetiam as ja geradas" aparecia tambem para pergunta descartada por
  alternativas insuficientes, e a tela mostrava um texto fixo em vez da explicacao.
"""

from __future__ import annotations

import asyncio
import json
import random
import re

import pytest

from app.models.schemas import LLMResponse
from app.routers import education
from app.services import quiz_generator_service as service

CREDITO = (
    "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
    "'message': 'Your credit balance is too low to access the Anthropic API.'}}"
)
GROQ = (
    "Request too large for model `qwen` in organization `org_x` service tier "
    "`on_demand` on input tokens per minute (ITPM): Limit 7000, Requested 14940"
)


def run(coro):
    return asyncio.run(coro)


# --- reconhecer recusa por tamanho ----------------------------------------------


@pytest.mark.unit
def test_recusa_do_groq_da_a_razao_exata():
    assert service._size_ratio(GROQ) == pytest.approx(7000 / 14940)


@pytest.mark.unit
def test_limite_maior_que_o_pedido_e_taxa_passageira_nao_tamanho():
    taxa = "Rate limit reached. Limit 30000, Used 29000, Requested 500. Try again in 2s."

    assert service._size_ratio(taxa) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "erro",
    [
        "This model's maximum context length is 8192 tokens",
        "prompt is too long: 250000 tokens",
        "Request too large",
        "context_length_exceeded",
    ],
)
def test_recusa_por_tamanho_sem_numeros_pede_metade(erro):
    assert service._size_ratio(erro) == 0.5


@pytest.mark.unit
@pytest.mark.parametrize("erro", [CREDITO, "HTTP 404: resposta vazia", "", "timeout"])
def test_erro_que_nao_e_de_tamanho_nao_encolhe_a_fonte(erro):
    assert service._size_ratio(erro) is None
    assert service._next_limit(40_000, erro) is None


@pytest.mark.unit
def test_novo_teto_tem_folga_e_nunca_passa_do_piso():
    # 7000/14940 = 0.47; com folga de 0.7, 60 mil vira cerca de 19,7 mil.
    novo = service._next_limit(60_000, GROQ)
    assert 19_000 < novo < 20_500

    # Fonte ja pequena: encolher mais seria entregar pergunta sem base.
    assert service._next_limit(3_000, GROQ) is None


# --- encolher a fonte --------------------------------------------------------------


def _fonte(blocos: int, tamanho: int) -> str:
    return "\n\n".join(
        f"=== AULA: Aula {i} ===\nRESUMO VALIDADO DA AULA:\n"
        + ("Conceito importante da aula. " * (tamanho // 29))
        for i in range(1, blocos + 1)
    )


@pytest.mark.unit
def test_fonte_dentro_do_teto_nao_muda():
    fonte = _fonte(2, 500)

    assert service._shrink_source(fonte, 10_000) == fonte
    assert service._shrink_source(fonte, None) == fonte


@pytest.mark.unit
def test_cada_aula_ou_material_ganha_sua_parte_do_espaco():
    """Cortar so o fim tiraria a ultima aula inteira."""
    fonte = _fonte(3, 6_000)

    curta = service._shrink_source(fonte, 4_500)

    assert len(curta) < len(fonte)
    for numero in (1, 2, 3):
        assert f"=== AULA: Aula {numero} ===" in curta
    assert len(curta) <= 4_500 + 3 * 40


@pytest.mark.unit
def test_corte_termina_em_fim_de_frase_e_marca_o_corte():
    fonte = "Primeira frase completa. " * 200

    curta = service._shrink_source(fonte, 1_000)

    assert len(curta) < 1_100
    assert curta.endswith("…")
    assert curta.rstrip(" …").endswith(".")


@pytest.mark.unit
def test_resumo_vem_antes_da_transcricao_entao_e_a_transcricao_que_perde():
    fonte = (
        "=== AULA: Unica ===\nRESUMO VALIDADO DA AULA:\nResumo importante.\n\n"
        "TRANSCRIÇÃO DA AULA:\n" + ("fala longa da aula. " * 500)
    )

    curta = service._shrink_source(fonte, 800)

    assert "Resumo importante." in curta
    assert len(curta) < len(fonte)


# --- chamada que se ajusta ao provedor -------------------------------------------------


@pytest.mark.unit
def test_provedor_que_recusa_por_tamanho_recebe_a_fonte_menor_e_o_teto_fica(monkeypatch):
    chamadas: list[int] = []

    async def dispatch(llm, prompt, _h, _s, *, max_tokens=None):
        chamadas.append(len(prompt))
        if len(prompt) > 30_000:
            return LLMResponse(llm=llm, content=GROQ, is_error=True)
        return LLMResponse(llm=llm, content='{"ok": true}')

    monkeypatch.setattr(service, "dispatch_single", dispatch)
    limites: dict[str, int] = {}
    fonte = _fonte(3, 20_000)

    resposta = run(service._dispatch_fitting(
        "grok", fonte, lambda f: f"PROMPT {f}", "sistema", 500, limites,
    ))

    assert not resposta.is_error
    assert len(chamadas) == 2 and chamadas[1] < chamadas[0], "recusou e foi refeita menor"
    assert "grok" in limites

    # O proximo lote ja sai no tamanho que cabe, sem pagar a recusa de novo.
    chamadas.clear()
    run(service._dispatch_fitting(
        "grok", fonte, lambda f: f"PROMPT {f}", "sistema", 500, limites,
    ))
    assert len(chamadas) == 1


@pytest.mark.unit
def test_recusa_por_excecao_tambem_encolhe(monkeypatch):
    chamadas = []

    async def dispatch(llm, prompt, _h, _s, *, max_tokens=None):
        chamadas.append(len(prompt))
        if len(prompt) > 30_000:
            raise RuntimeError(GROQ)
        return LLMResponse(llm=llm, content="{}")

    monkeypatch.setattr(service, "dispatch_single", dispatch)

    run(service._dispatch_fitting(
        "grok", _fonte(3, 20_000), lambda f: f, "s", 100, {},
    ))

    assert len(chamadas) == 2


@pytest.mark.unit
def test_erro_de_credencial_nao_e_repetido_nem_encolhe(monkeypatch):
    chamadas = []

    async def dispatch(llm, prompt, _h, _s, *, max_tokens=None):
        chamadas.append(1)
        return LLMResponse(llm=llm, content=CREDITO, is_error=True)

    monkeypatch.setattr(service, "dispatch_single", dispatch)
    limites: dict[str, int] = {}

    resposta = run(service._dispatch_fitting(
        "claude", _fonte(2, 20_000), lambda f: f, "s", 100, limites,
    ))

    assert resposta.is_error
    assert len(chamadas) == 1
    assert limites == {}


@pytest.mark.unit
def test_fonte_ja_no_piso_devolve_a_recusa_em_vez_de_insistir(monkeypatch):
    chamadas = []

    async def dispatch(llm, prompt, _h, _s, *, max_tokens=None):
        chamadas.append(1)
        return LLMResponse(llm=llm, content=GROQ, is_error=True)

    monkeypatch.setattr(service, "dispatch_single", dispatch)

    resposta = run(service._dispatch_fitting(
        "grok", "texto curto " * 100, lambda f: f, "s", 100, {},
    ))

    assert resposta.is_error
    assert len(chamadas) == 1


# --- mensagem do lote vazio ----------------------------------------------------------


@pytest.mark.unit
def test_lote_vazio_diz_repetida_so_quando_foi_repeticao():
    lidas = [{"enunciado": f"p{i}"} for i in range(4)]

    assert "todas repetiam as já geradas" in service._empty_batch_reason(
        "{...}", lidas, {"repetidas": 4, "invalidas": 0}
    )
    assert "todas repetiam as já geradas" in service._empty_batch_reason("{...}", lidas)


@pytest.mark.unit
def test_lote_de_perguntas_sem_alternativas_nao_e_chamado_de_repeticao():
    lidas = [{"enunciado": f"p{i}"} for i in range(4)]

    texto = service._empty_batch_reason("{...}", lidas, {"repetidas": 0, "invalidas": 4})

    assert "repetiam" not in texto
    assert "alternativas diferentes entre si" in texto
    assert f"ao menos {service.MIN_DISTINCT_OPTIONS}" in texto


@pytest.mark.unit
def test_lote_misto_conta_cada_motivo():
    lidas = [{"enunciado": f"p{i}"} for i in range(4)]

    texto = service._empty_batch_reason("{...}", lidas, {"repetidas": 3, "invalidas": 1})

    assert "3 repetiam as já geradas e 1 tinham alternativas insuficientes" in texto


# --- plano percorre a fila ------------------------------------------------------------


class Fila:
    """Provedores de mentira, cada um com o seu jeito de falhar."""

    def __init__(self, comportamentos: dict, *, total_conceitos: int = 40):
        self.comportamentos = comportamentos
        self.conceitos = [f"Conceito {i}" for i in range(total_conceitos)]
        self.livres = 0
        self.chamadas: list[tuple[str, str]] = []
        self.tamanhos: dict[str, list[int]] = {}

    async def __call__(self, llm, prompt, _h, _s, *, max_tokens=None):
        tipo = (
            "plano" if "planejando um quiz" in prompt
            else "validacao" if "Valide as seguintes" in prompt
            else "geracao"
        )
        self.chamadas.append((llm, tipo))
        self.tamanhos.setdefault(llm, []).append(len(prompt))
        comportamento = self.comportamentos[llm]

        if comportamento == "sem_credito":
            return LLMResponse(llm=llm, content=CREDITO, is_error=True)
        if comportamento == "404":
            return LLMResponse(llm=llm, content="HTTP 404: resposta vazia", is_error=True)
        if comportamento == "pequeno" and len(prompt) > 18_000:
            # Como o provedor real: o pedido em tokens (~4 caracteres cada) e o limite
            # vem na mensagem, entao a razao e a verdadeira.
            return LLMResponse(
                llm=llm,
                content=f"Request too large. Limit 4500, Requested {len(prompt) // 4}",
                is_error=True,
            )

        if tipo == "plano":
            quantidade = int(re.search(r"planeje (\d+) perguntas", prompt).group(1))
            return LLMResponse(llm=llm, content=json.dumps({"objetivos": [
                {"topico": "Aula", "conceito": c, "angulo": "definicao"}
                for c in self.conceitos[:quantidade]
            ]}))
        if tipo == "validacao":
            trecho = prompt.split("**Questões para Validar:**\n", 1)[1]
            lote = json.loads(trecho.split("\n\nPara cada questão", 1)[0])
            return LLMResponse(llm=llm, content=json.dumps({"validacoes": [
                {"indice": i, "grounding_score": 0.95, "bem_formulada": True,
                 "risco_alucinacao": False}
                for i in range(len(lote))
            ]}))

        objetivos = re.findall(r"^(\d+)\. \[[^\]]*\] (.+?) — ângulo", prompt, re.MULTILINE)
        if comportamento == "repete":
            questoes = [_q("Conceito 0", None)] * 4
        elif objetivos:
            questoes = [_q(c, int(n)) for n, c in objetivos]
        else:
            # Sem plano: escreve perguntas livres, cada uma de um conceito novo.
            quantidade = int(re.search(r"gere (d+) quest", prompt).group(1))
            questoes = [
                _q(self.conceitos[(self.livres + i) % len(self.conceitos)], None)
                for i in range(quantidade)
            ]
            self.livres += quantidade
        return LLMResponse(llm=llm, content=json.dumps({"questoes": questoes}))


def _q(conceito: str, objetivo) -> dict:
    return {
        "objetivo": objetivo,
        "tipo": "multipla_escolha",
        "dificuldade": "medio",
        "enunciado": f"Qual das alternativas descreve {conceito}?",
        "opcoes": [
            {"label": "A", "texto": f"Definição de {conceito}", "correta": True},
            {"label": "B", "texto": "Chave estrangeira", "correta": False},
            {"label": "C", "texto": "Índice composto", "correta": False},
            {"label": "D", "texto": "Gatilho", "correta": False},
        ],
        "resposta_correta": "A",
        "justificativa": "A aula trata disso.",
        "conceitos": [conceito],
    }


def _usa(monkeypatch, fila: Fila, ordem: list[str]):
    async def candidatos(_preferido=None):
        return list(ordem)

    async def resolve(_preferido=None):
        # O ranking antigo: o primeiro, que e justamente o sem credito.
        return ordem[0]

    monkeypatch.setattr(service, "_candidate_llms_for_quiz", candidatos)
    monkeypatch.setattr(service, "_resolve_llm_for_quiz", resolve)
    monkeypatch.setattr(service, "dispatch_single", fila)
    monkeypatch.setattr(service, "_new_rng", lambda: random.Random(3))


def gerar(quantidade: int, resumo: str = "Resumo da aula sobre modelagem."):
    return run(service.generate_quiz(
        resumo=resumo,
        disciplina="Banco de Dados",
        titulo_aula="Modelagem",
        quantidade_questoes=quantidade,
    ))


@pytest.mark.unit
def test_plano_nao_morre_nos_dois_primeiros_provedores_sem_credito(monkeypatch):
    """O plano so tentava os dois primeiros: claude e gpt, os dois sem credito."""
    fila = Fila({"claude": "sem_credito", "gpt": "sem_credito", "together": "ok"})
    _usa(monkeypatch, fila, ["claude", "gpt", "together"])

    resultado = gerar(8)

    planos = [(llm, tipo) for llm, tipo in fila.chamadas if tipo == "plano"]
    assert ("together", "plano") in planos, "o plano chegou ao terceiro da fila"
    assert resultado["descartes"]["objetivos_planejados"] > 0
    assert len(resultado["questoes"]) == 8


@pytest.mark.unit
def test_quem_falha_por_credito_sai_da_fila_e_nao_e_chamado_de_novo(monkeypatch):
    fila = Fila({"claude": "sem_credito", "gpt": "sem_credito", "together": "ok"})
    _usa(monkeypatch, fila, ["claude", "gpt", "together"])

    gerar(8)

    chamadas_aos_mortos = [c for c in fila.chamadas if c[0] in {"claude", "gpt"}]
    # Uma chamada de plano a cada um e nada depois: nem geracao nem validacao.
    assert sorted(chamadas_aos_mortos) == [("claude", "plano"), ("gpt", "plano")]


@pytest.mark.unit
def test_falha_do_plano_aparece_na_lista_de_tentativas(monkeypatch):
    """Sem isso, a tela deixava de citar justamente os provedores sem credito."""
    fila = Fila({"claude": "sem_credito", "together": "ok"})
    _usa(monkeypatch, fila, ["claude", "together"])

    resultado = gerar(4)

    falhas = [a for a in resultado["attempts"] if not a["success"]]
    assert [(a["llm"], "credit balance" in a["error"]) for a in falhas] == [("claude", True)]


@pytest.mark.unit
def test_validacao_fala_com_quem_funcionou_e_nao_com_o_ranking_antigo(monkeypatch):
    """Antes: validava no primeiro do ranking (sem credito) e todo quiz saia com
    "validacao automatica indisponivel"."""
    fila = Fila({"claude": "sem_credito", "together": "ok"})
    _usa(monkeypatch, fila, ["claude", "together"])

    resultado = gerar(4)

    validacoes = [llm for llm, tipo in fila.chamadas if tipo == "validacao"]
    assert validacoes and set(validacoes) == {"together"}
    assert all(q["verificado"] for q in resultado["questoes"])


@pytest.mark.unit
def test_plano_tem_teto_de_tentativas(monkeypatch):
    nomes = [f"morto{i}" for i in range(8)] + ["vivo"]
    fila = Fila({**{n: "sem_credito" for n in nomes[:-1]}, "vivo": "ok"})
    _usa(monkeypatch, fila, nomes)

    gerar(4)

    planos_mortos = [c for c in fila.chamadas if c[1] == "plano" and c[0].startswith("morto")]
    assert len(planos_mortos) == service.MAX_PLAN_ATTEMPTS


# --- o cenario do print ---------------------------------------------------------------


@pytest.mark.unit
def test_cenario_do_print_entrega_as_vinte(monkeypatch):
    """claude e gpt sem credito, gemini 404, grok recusando a fonte por tamanho,
    together funcionando. Antes: 1 pergunta de 20."""
    fila = Fila({
        "claude": "sem_credito", "gpt": "sem_credito", "together": "ok",
        "gemini": "404", "hf": "repete", "grok": "pequeno",
    })
    _usa(monkeypatch, fila, ["claude", "gpt", "together", "gemini", "hf", "grok"])
    fonte = "\n\n".join(
        f"=== AULA: Aula {i} ===\nRESUMO VALIDADO DA AULA:\n" + ("Conceito importante da aula. " * 800)
        for i in range(1, 4)
    )

    resultado = gerar(20, resumo=fonte)

    assert len(resultado["questoes"]) == 20
    conceitos = [q["conceitos"][0] for q in resultado["questoes"]]
    assert len(set(conceitos)) == 20
    falhas = {a["llm"] for a in resultado["attempts"] if not a["success"]}
    assert {"claude", "gpt"} <= falhas, "a tela continua dizendo quem falhou"


@pytest.mark.unit
def test_grok_que_recusa_por_tamanho_passa_a_ser_atendido_com_a_fonte_menor(monkeypatch):
    fila = Fila({"grok": "pequeno"})
    _usa(monkeypatch, fila, ["grok"])
    fonte = "=== AULA: Unica ===\nRESUMO VALIDADO DA AULA:\n" + ("Conceito da aula. " * 3000)

    resultado = gerar(4, resumo=fonte)

    assert len(resultado["questoes"]) == 4
    tamanhos = fila.tamanhos["grok"]
    assert tamanhos[0] > 18_000, "a primeira chamada levou a fonte inteira e foi recusada"
    assert all(t <= 18_000 for t in tamanhos[1:]), "as seguintes ja foram no tamanho que cabe"


# --- o que o professor le --------------------------------------------------------------


@pytest.mark.unit
def test_conteudo_curto_e_fonte_com_perguntas_anteriores_sao_explicados():
    mensagem = education._mensagem_do_quiz(
        1, [{"id": "l1"}], [], pedidas=20,
        descartes={
            "repetidas": 12, "invalidas": 3, "reprovadas": 0,
            "conteudo_caracteres": 840, "ja_existentes": 34,
        },
    )

    assert "Você pediu 20 e vieram 1" in mensagem
    assert "12 repetida(s) de outra pergunta" in mensagem
    assert "Esta fonte já tem 34 pergunta(s) em outros quizzes, e as novas não as repetem." in mensagem
    assert "O conteúdo selecionado tem só 840 caracteres, pouco para 20 perguntas distintas." in mensagem
    assert "marque mais aulas ou materiais" in mensagem
    assert "Gere de novo" not in mensagem, "gerar de novo daria o mesmo resultado"


@pytest.mark.unit
def test_fonte_grande_sem_perguntas_anteriores_continua_sugerindo_gerar_de_novo():
    mensagem = education._mensagem_do_quiz(
        15, [{"id": "l1"}], [], pedidas=20,
        descartes={"repetidas": 3, "conteudo_caracteres": 40_000, "ja_existentes": 0},
    )

    assert "Gere de novo para completar o que faltou." in mensagem
    assert "só" not in mensagem.split("vieram 15")[1].split("Gere")[0].replace("de outra pergunta", "")


@pytest.mark.unit
def test_so_perguntas_anteriores_ja_explicam_a_falta():
    mensagem = education._mensagem_do_quiz(
        5, [{"id": "l1"}], [], pedidas=20,
        descartes={"conteudo_caracteres": 40_000, "ja_existentes": 20},
    )

    assert "Esta fonte já tem 20 pergunta(s) em outros quizzes" in mensagem
    assert "Para mais perguntas diferentes, marque mais aulas ou materiais." in mensagem


@pytest.mark.unit
def test_geracao_registra_tamanho_do_conteudo_e_perguntas_anteriores(monkeypatch):
    fila = Fila({"together": "ok"})
    _usa(monkeypatch, fila, ["together"])
    anteriores = [
        {"enunciado": "Pergunta antiga sobre outra coisa?", "opcoes": [], "conceitos": []},
        {"enunciado": "Outra pergunta antiga?", "opcoes": [], "conceitos": []},
    ]

    resultado = run(service.generate_quiz(
        resumo="Resumo da aula sobre modelagem.",
        disciplina="BD", titulo_aula="Aula", quantidade_questoes=4,
        questoes_existentes=anteriores,
    ))

    assert resultado["descartes"]["conteudo_caracteres"] == len("Resumo da aula sobre modelagem.")
    assert resultado["descartes"]["ja_existentes"] == 2
