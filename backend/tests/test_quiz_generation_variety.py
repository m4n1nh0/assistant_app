"""Variedade e completude das perguntas geradas.

Falha de aula real: o professor pediu 20 perguntas e vieram 15, parecidas entre si
e com a alternativa correta sempre na A. As causas, uma a uma:

- a correta ficava na A porque o exemplo do prompt a marcava na A e nada
  reordenava as alternativas no codigo;
- as perguntas saiam parecidas porque cada lote so sabia a lista do que ja tinha
  saido, sem um plano de conceitos distintos, e a checagem de repeticao comparava
  so palavras do enunciado (a pergunta reescrita passava);
- vinham menos porque as perdas (repeticao, reprovacao na validacao) nao tinham
  folga, e o professor nao era avisado do motivo.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from collections import Counter

import pytest

from app.models.schemas import LLMResponse
from app.routers import education
from app.services import quiz_generator_service as service

CONCEITOS = [
    "Normalização", "Chave primária", "Transação", "Índice", "Visão",
    "Procedimento armazenado", "Junção interna", "Agregação",
    "Restrição de unicidade", "Integridade referencial", "Modelo relacional",
    "Álgebra relacional", "Dependência funcional", "Forma normal de Boyce-Codd",
    "Isolamento de transações", "Bloqueio otimista", "Replicação",
    "Cardinalidade", "Entidade fraca", "Atributo derivado", "Generalização",
    "Particionamento", "Cache de consultas", "Plano de execução", "Subconsulta",
    "Chave candidata", "Tabela temporária", "Linguagem de definição de dados",
    "Consistência eventual", "Teorema CAP", "Controle de concorrência",
]


def run(coro):
    return asyncio.run(coro)


def _questao(conceito: str, objetivo=None, correta_em: int = 0) -> dict:
    """Questao como o modelo as escreve: a correta na A, sempre."""
    opcoes = [
        {"label": "A", "texto": f"Definição de {conceito}", "correta": True},
        {"label": "B", "texto": "Chave estrangeira", "correta": False},
        {"label": "C", "texto": "Índice composto", "correta": False},
        {"label": "D", "texto": "Gatilho", "correta": False},
    ]
    return {
        "objetivo": objetivo,
        "tipo": "multipla_escolha",
        "dificuldade": "medio",
        "enunciado": f"Qual das alternativas descreve {conceito}?",
        "opcoes": opcoes,
        "resposta_correta": "A",
        "justificativa": f"A aula trata de {conceito}.",
        "conceitos": [conceito],
        "topico_origem": "Aula",
    }


class Modelo:
    """Provedor de mentira com plano, geracao e validacao, e com o vicio do real."""

    def __init__(
        self,
        *,
        conceitos=None,
        sem_plano=False,
        plano=None,
        reprovar=(),
        fracas=(),
        repetir_alem_do_plano=True,
    ):
        self.conceitos = list(conceitos or CONCEITOS)
        self.sem_plano = sem_plano
        self.plano = self.conceitos if plano is None else plano
        self.reprovar = tuple(reprovar)
        self.fracas = tuple(fracas)
        self.repetir_alem_do_plano = repetir_alem_do_plano
        self.chamadas: list[str] = []
        self.proximo_livre = 0

    async def __call__(self, llm, prompt, _history, _system, *, max_tokens=None):
        self.chamadas.append(prompt)

        if "planejando um quiz" in prompt:
            if self.sem_plano:
                return LLMResponse(llm=llm, content="sem json")
            quantidade = int(re.search(r"planeje (\d+) perguntas", prompt).group(1))
            objetivos = [
                {"topico": "Aula", "conceito": c, "angulo": "definicao"}
                for c in self.plano[:quantidade]
            ]
            return LLMResponse(llm=llm, content=json.dumps({"objetivos": objetivos}))

        if "Valide as seguintes" in prompt:
            trecho = prompt.split("**Questões para Validar:**\n", 1)[1]
            lote = json.loads(trecho.split("\n\nPara cada questão", 1)[0])
            validacoes = []
            for indice, questao in enumerate(lote):
                reprovada = any(m in questao["enunciado"] for m in self.reprovar)
                fraca = any(m in questao["enunciado"] for m in self.fracas)
                validacoes.append({
                    "indice": indice,
                    "grounding_score": 0.5 if fraca else 0.95,
                    "bem_formulada": True,
                    "risco_alucinacao": reprovada,
                })
            return LLMResponse(llm=llm, content=json.dumps({"validacoes": validacoes}))

        quantidade = int(re.search(r"gere (\d+) quest", prompt).group(1))
        objetivos = re.findall(r"^(\d+)\. \[[^\]]*\] (.+?) — ângulo", prompt, re.MULTILINE)
        if objetivos:
            questoes = [_questao(conceito, int(numero)) for numero, conceito in objetivos]
        elif self.repetir_alem_do_plano:
            # Sem objetivo para cobrir, o modelo volta ao que ja escreveu.
            questoes = [_questao(self.conceitos[0]) for _ in range(quantidade)]
        else:
            questoes = []
            for _ in range(quantidade):
                questoes.append(_questao(self.conceitos[self.proximo_livre % len(self.conceitos)]))
                self.proximo_livre += 1
        return LLMResponse(llm=llm, content=json.dumps({"questoes": questoes[:quantidade]}))


def _usa(monkeypatch, modelo: Modelo, semente: int = 7):
    async def candidatos(_preferido=None):
        return ["modelo"]

    async def resolve(_preferido=None):
        return "modelo"

    monkeypatch.setattr(service, "_candidate_llms_for_quiz", candidatos)
    monkeypatch.setattr(service, "_resolve_llm_for_quiz", resolve)
    monkeypatch.setattr(service, "dispatch_single", modelo)
    monkeypatch.setattr(service, "_new_rng", lambda: random.Random(semente))


def gerar(quantidade: int):
    return run(service.generate_quiz(
        resumo="Resumo da aula sobre bancos de dados relacionais.",
        disciplina="Banco de Dados",
        titulo_aula="Modelagem",
        quantidade_questoes=quantidade,
    ))


# --- a alternativa correta deixa de ficar sempre na A ------------------------


@pytest.mark.unit
def test_correta_deixa_de_ficar_sempre_na_a(monkeypatch):
    _usa(monkeypatch, Modelo())

    resultado = gerar(20)

    posicoes = Counter(
        [o["correta"] for o in q["opcoes"]].index(True) for q in resultado["questoes"]
    )
    assert len(resultado["questoes"]) == 20
    # Equilibrado, nao so sorteado: 20 perguntas, 4 posicoes, 5 em cada.
    assert posicoes == {0: 5, 1: 5, 2: 5, 3: 5}


@pytest.mark.unit
def test_gabarito_e_letras_acompanham_a_reordenacao(monkeypatch):
    _usa(monkeypatch, Modelo())

    resultado = gerar(12)

    for questao in resultado["questoes"]:
        assert [o["label"] for o in questao["opcoes"]] == ["A", "B", "C", "D"]
        corretas = [o for o in questao["opcoes"] if o["correta"]]
        assert len(corretas) == 1
        assert questao["resposta_correta"] == corretas[0]["label"]
        # A correta continua sendo a que o modelo escreveu para aquele conceito.
        conceito = questao["conceitos"][0]
        assert corretas[0]["texto"] == f"Definição de {conceito}"
        # E nenhuma alternativa se perdeu na troca.
        assert {o["texto"] for o in questao["opcoes"]} >= {
            "Chave estrangeira", "Índice composto", "Gatilho",
        }


@pytest.mark.unit
def test_pergunta_que_depende_da_ordem_nao_e_reordenada():
    questao = {
        "tipo": "multipla_escolha",
        "opcoes": [
            {"label": "A", "texto": "1FN", "correta": False},
            {"label": "B", "texto": "2FN", "correta": False},
            {"label": "C", "texto": "3FN", "correta": True},
            {"label": "D", "texto": "Todas as anteriores", "correta": False},
        ],
        "resposta_correta": "C",
    }

    service._balance_correct_positions([questao], random.Random(1))

    assert [o["texto"] for o in questao["opcoes"]] == [
        "1FN", "2FN", "3FN", "Todas as anteriores",
    ]
    assert questao["resposta_correta"] == "C"


@pytest.mark.unit
@pytest.mark.parametrize(
    "texto",
    ["Nenhuma das anteriores", "Ambas as alternativas", "As alternativas A e B", "Itens B e C"],
)
def test_referencias_entre_alternativas_seguram_a_ordem(texto):
    questao = {
        "tipo": "multipla_escolha",
        "opcoes": [
            {"label": "A", "texto": "Um", "correta": True},
            {"label": "B", "texto": "Dois", "correta": False},
            {"label": "C", "texto": texto, "correta": False},
        ],
    }

    service._balance_correct_positions([questao], random.Random(3))

    assert [o["texto"] for o in questao["opcoes"]] == ["Um", "Dois", texto]


@pytest.mark.unit
def test_letras_do_modelo_desencontradas_viram_sequenciais():
    questao = {
        "tipo": "multipla_escolha",
        "opcoes": [
            {"label": "A", "texto": "Um", "correta": False},
            {"label": "A", "texto": "Dois", "correta": True},
            {"label": "C", "texto": "Tres", "correta": False},
        ],
        "resposta_correta": "A",
    }

    service._relabel(questao)

    assert [o["label"] for o in questao["opcoes"]] == ["A", "B", "C"]
    assert questao["resposta_correta"] == "B"


# --- alternativas que nao servem ---------------------------------------------


@pytest.mark.unit
def test_alternativas_iguais_sao_unificadas_mantendo_a_correta():
    opcoes = service._dedupe_options([
        {"label": "A", "texto": "3FN", "correta": False},
        {"label": "B", "texto": "  3fn ", "correta": True},
        {"label": "C", "texto": "1FN", "correta": False},
        {"label": "D", "texto": "", "correta": False},
    ])

    assert [o["texto"] for o in opcoes] == ["3FN", "1FN"]
    assert [o["correta"] for o in opcoes] == [True, False]


@pytest.mark.unit
def test_pergunta_com_menos_de_tres_alternativas_distintas_nao_vale():
    base = {"tipo": "multipla_escolha"}
    assert not service._is_answerable({**base, "opcoes": [{"texto": "A"}, {"texto": "B"}]})
    assert service._is_answerable(
        {**base, "opcoes": [{"texto": "A"}, {"texto": "B"}, {"texto": "C"}]}
    )
    assert service._is_answerable({"tipo": "verdadeiro_falso", "opcoes": []})


@pytest.mark.unit
def test_pergunta_cujas_alternativas_colapsam_e_descartada_e_contada(monkeypatch):
    ruim = _questao("Visão")
    ruim["opcoes"] = [
        {"label": "A", "texto": "Mesma", "correta": True},
        {"label": "B", "texto": "mesma", "correta": False},
        {"label": "C", "texto": "MESMA", "correta": False},
        {"label": "D", "texto": "Mesma ", "correta": False},
    ]

    class ComRuim(Modelo):
        async def __call__(self, llm, prompt, h, s, *, max_tokens=None):
            if "gere " in prompt and "planejando" not in prompt and "Valide" not in prompt:
                self.chamadas.append(prompt)
                quantidade = int(re.search(r"gere (\d+) quest", prompt).group(1))
                bons = [_questao(c) for c in CONCEITOS[:quantidade]]
                return LLMResponse(llm=llm, content=json.dumps({"questoes": [ruim] + bons}))
            return await super().__call__(llm, prompt, h, s, max_tokens=max_tokens)

    _usa(monkeypatch, ComRuim(sem_plano=True))

    resultado = gerar(4)

    assert all(q["conceitos"] != ["Visão"] for q in resultado["questoes"])
    assert resultado["descartes"]["invalidas"] >= 1


# --- perguntas parecidas -------------------------------------------------------


@pytest.mark.unit
def test_plural_conta_como_a_mesma_palavra():
    antes = service._key_words("Qual forma normal elimina dependências transitivas?")
    depois = service._key_words("Qual forma normal elimina dependência transitiva?")

    assert antes == depois
    assert service._is_repeat(
        "Qual forma normal elimina dependência transitiva?", [antes], set()
    )


@pytest.mark.unit
def test_mesma_resposta_com_enunciado_reescrito_e_a_mesma_pergunta():
    existente = _questao("a 3FN")
    existente["enunciado"] = "Qual forma normal elimina dependência transitiva?"
    existente["opcoes"][0]["texto"] = "3FN"
    reescrita = dict(existente)
    reescrita["enunciado"] = "Que forma normal remove dependências transitivas?"
    vistas = [(service._key_words(existente["enunciado"]), service._answer_key(existente))]

    # As palavras do enunciado sozinhas (0.71) nao pegam; a resposta igual pega.
    assert not service._is_repeat(
        reescrita["enunciado"], [vistas[0][0]], {service._dedupe_key(existente["enunciado"])}
    )
    assert service._is_same_fact(reescrita, vistas)


@pytest.mark.unit
def test_mesma_resposta_com_pergunta_diferente_nao_e_repeticao():
    existente = _questao("a 3FN")
    existente["enunciado"] = "Qual forma normal elimina dependência transitiva?"
    existente["opcoes"][0]["texto"] = "3FN"
    outra = _questao("outra")
    outra["enunciado"] = "Qual forma normal exige a 2FN como pré-requisito imediato?"
    outra["opcoes"][0]["texto"] = "3FN"
    vistas = [(service._key_words(existente["enunciado"]), service._answer_key(existente))]

    assert not service._is_same_fact(outra, vistas)


@pytest.mark.unit
def test_pergunta_sem_resposta_marcada_nunca_e_igual_por_resposta():
    sem = _questao("x")
    for opcao in sem["opcoes"]:
        opcao["correta"] = False

    assert not service._is_same_fact(sem, [(service._key_words(sem["enunciado"]), "")])


# --- plano de objetivos ---------------------------------------------------------


@pytest.mark.unit
def test_plano_descarta_objetivos_que_repetem_outro():
    bruto = json.dumps({"objetivos": [
        {"topico": "A", "conceito": "Chave primária identifica a linha", "angulo": "definicao"},
        {"topico": "A", "conceito": "A chave primária identifica a linha", "angulo": "aplicacao"},
        {"topico": "B", "conceito": "Índice acelera a busca", "angulo": "causa"},
        {"conceito": "  "},
        "lixo",
    ]})

    slots = service._parse_plan(bruto, limite=10)

    assert [s["conceito"] for s in slots] == [
        "Chave primária identifica a linha", "Índice acelera a busca",
    ]


@pytest.mark.unit
def test_plano_respeita_o_limite_pedido():
    bruto = json.dumps({"objetivos": [
        {"conceito": c, "angulo": "definicao"} for c in CONCEITOS
    ]})

    assert len(service._parse_plan(bruto, limite=5)) == 5


@pytest.mark.unit
def test_cada_lote_recebe_os_objetivos_do_plano_e_cobre_todos(monkeypatch):
    modelo = Modelo()
    _usa(monkeypatch, modelo)

    resultado = gerar(10)

    lotes = [c for c in modelo.chamadas if "gere " in c and "planejando" not in c]
    assert all("Objetivos desta rodada" in lote for lote in lotes)
    conceitos = [q["conceitos"][0] for q in resultado["questoes"]]
    assert len(set(conceitos)) == 10, "dez perguntas, dez conceitos diferentes"
    # Planejou o pedido com a folga: 10 pedidos, 12 objetivos.
    assert resultado["descartes"]["objetivos_pedidos"] == 12
    assert resultado["descartes"]["objetivos_planejados"] == 12


@pytest.mark.unit
def test_plano_pede_o_pedido_mais_a_folga_e_nao_diz_gere_n_questoes(monkeypatch):
    modelo = Modelo()
    _usa(monkeypatch, modelo)

    gerar(20)

    plano = next(c for c in modelo.chamadas if "planejando um quiz" in c)
    assert "planeje 25 perguntas" in plano
    assert not re.search(r"gere \d+ quest", plano)


@pytest.mark.unit
def test_sem_plano_a_geracao_continua_como_antes(monkeypatch):
    modelo = Modelo(sem_plano=True, repetir_alem_do_plano=False)
    _usa(monkeypatch, modelo)

    resultado = gerar(6)

    assert len(resultado["questoes"]) == 6
    assert resultado["descartes"]["objetivos_planejados"] == 0


# --- folga para as perdas ---------------------------------------------------------


@pytest.mark.unit
def test_pedido_vem_inteiro_mesmo_com_reprovacao_na_validacao(monkeypatch):
    """Antes: 20 pedidos, 5 reprovadas na validacao, 15 entregues."""
    reprovadas = [CONCEITOS[i] for i in (1, 4, 7, 9, 12)]
    _usa(monkeypatch, Modelo(reprovar=reprovadas))

    resultado = gerar(20)

    assert len(resultado["questoes"]) == 20
    enunciados = " ".join(q["enunciado"] for q in resultado["questoes"])
    assert not any(c in enunciados for c in reprovadas)
    assert resultado["descartes"]["reprovadas"] == 5
    assert resultado["descartes"]["excedentes"] == 0


@pytest.mark.unit
def test_sobra_depois_do_corte_fica_com_as_melhores(monkeypatch):
    fracas = [CONCEITOS[0], CONCEITOS[3]]
    _usa(monkeypatch, Modelo(fracas=fracas))

    resultado = gerar(10)

    assert len(resultado["questoes"]) == 10
    assert resultado["descartes"]["excedentes"] == 2
    # As duas fracas (grounding baixo, nao verificadas) sao as que saem no corte.
    assert all(q["verificado"] for q in resultado["questoes"])
    enunciados = " ".join(q["enunciado"] for q in resultado["questoes"])
    assert not any(c in enunciados for c in fracas)


@pytest.mark.unit
def test_sem_perdas_entrega_exatamente_o_pedido(monkeypatch):
    _usa(monkeypatch, Modelo())

    resultado = gerar(7)

    assert len(resultado["questoes"]) == 7
    assert resultado["descartes"]["excedentes"] == 2


@pytest.mark.unit
@pytest.mark.parametrize(
    "pedido, esperado",
    [(1, 3), (4, 6), (10, 12), (20, 25), (40, 48), (50, 58)],
)
def test_folga_cresce_com_o_pedido_mas_tem_teto(pedido, esperado):
    assert service._oversample(pedido) == esperado


# --- conteudo que nao sustenta o pedido ---------------------------------------------


@pytest.mark.unit
def test_conteudo_curto_entrega_menos_e_diz_por_que(monkeypatch):
    """So seis assuntos distintos: o professor tem de ouvir isso, nao ver so '15'."""
    _usa(monkeypatch, Modelo(plano=CONCEITOS[:6]))

    resultado = gerar(10)

    assert len(resultado["questoes"]) == 6
    assert resultado["descartes"]["objetivos_planejados"] == 6
    assert resultado["descartes"]["repetidas"] > 0

    mensagem = education._mensagem_do_quiz(
        len(resultado["questoes"]), [{"id": "l1"}], [],
        pedidas=10, descartes=resultado["descartes"],
    )
    assert "Você pediu 10 e vieram 6" in mensagem
    assert "O conteúdo só sustentou 6 assunto(s) distinto(s)" in mensagem
    assert "marque mais aulas ou materiais" in mensagem


# --- mensagem ao professor ------------------------------------------------------------


@pytest.mark.unit
def test_mensagem_completa_nao_acrescenta_aviso():
    mensagem = education._mensagem_do_quiz(20, [{"id": "l1"}], [], pedidas=20, descartes={})

    assert mensagem.startswith("20 questões preparadas para revisão")
    assert "Você pediu" not in mensagem


@pytest.mark.unit
def test_mensagem_de_falta_lista_os_motivos():
    mensagem = education._mensagem_do_quiz(
        15, [{"id": "l1"}], [], pedidas=20,
        descartes={"repetidas": 3, "invalidas": 1, "reprovadas": 1,
                   "objetivos_planejados": 25, "objetivos_pedidos": 25},
    )

    assert "Você pediu 20 e vieram 15" in mensagem
    assert "3 repetida(s) de outra pergunta" in mensagem
    assert "1 com alternativas insuficientes ou repetidas" in mensagem
    assert "1 reprovada(s) na validação" in mensagem
    # O plano achou assunto de sobra: a falha foi do modelo, entao gerar de novo ajuda.
    assert "Gere de novo para completar o que faltou." in mensagem
    assert "só sustentou" not in mensagem


@pytest.mark.unit
def test_mensagem_de_falta_sem_detalhes_continua_util():
    mensagem = education._mensagem_do_quiz(15, [{"id": "l1"}], [], pedidas=20, descartes=None)

    assert "Você pediu 20 e vieram 15." in mensagem
