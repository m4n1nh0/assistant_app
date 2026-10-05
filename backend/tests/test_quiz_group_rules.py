"""Pontuacao e identificacao do quiz em grupo (regra pura, sem banco)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import quiz_group_service as svc
from app.services.quiz_live_service import ranking_rows

BASE = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def resposta(attempt, question, points, *, correct=True, seconds=0):
    return SimpleNamespace(
        student_id=attempt, student_name=attempt, question_id=question,
        pontuacao=points, correta=correct, respondido_em=BASE + timedelta(seconds=seconds),
    )


def contexto(mode=svc.MODE_AVERAGE, representatives=None):
    """Dois grupos: G1 (Ana, Bia, Caio) e G2 (Davi, Eva). Caio e Eva nao entraram."""
    ctx = svc.GroupContext(
        mode=mode,
        group_names={"g1": "Grupo 1", "g2": "Grupo 2"},
        group_sizes={"g1": 3, "g2": 2},
        representatives=representatives or {},
    )
    ctx.member_of_attempt.update({"a-ana": "ana", "a-bia": "bia", "a-davi": "davi"})
    ctx.member_group.update({"ana": "g1", "bia": "g1", "davi": "g2"})
    ctx.member_names.update(
        {"ana": "Ana", "bia": "Bia", "caio": "Caio", "davi": "Davi", "eva": "Eva"}
    )
    return ctx


RESPOSTAS = [
    resposta("a-ana", "q1", 1000), resposta("a-ana", "q2", 800),
    resposta("a-bia", "q1", 400), resposta("a-bia", "q2", 0, correct=False),
    resposta("a-davi", "q1", 700), resposta("a-davi", "q2", 700),
]


# --- matricula ----------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "digitado, esperado",
    [("2024-0123 ", "20240123"), ("RA 12.345", "ra12345"), ("  ", ""), (None, ""), ("0123", "0123")],
)
def test_matricula_e_comparada_sem_pontuacao_nem_caixa(digitado, esperado):
    assert svc.normalize_enrollment(digitado) == esperado


def student(id_, matricula):
    return SimpleNamespace(id=id_, external_id=matricula)


def member(id_, group, student_id):
    return SimpleNamespace(id=id_, group_id=group, student_id=student_id, name=f"Nome {id_}")


GRUPOS = {"g1": "Grupo 1", "g2": "Grupo 2"}


@pytest.mark.unit
def test_matricula_leva_ao_integrante_e_ao_grupo():
    achado = svc.find_member(
        "2024-0002", [student("s1", "20240001"), student("s2", "20240002")],
        [member("m1", "g1", "s1"), member("m2", "g2", "s2")], GRUPOS,
    )
    assert (achado.group_id, achado.group_name, achado.member_id) == ("g2", "Grupo 2", "m2")
    assert achado.enrollment == "20240002"


@pytest.mark.unit
@pytest.mark.parametrize(
    "digitado, codigo",
    [("", "invalid"), ("---", "invalid"), ("99999", "unknown")],
)
def test_matricula_invalida_ou_desconhecida(digitado, codigo):
    with pytest.raises(svc.EnrollmentError) as erro:
        svc.find_member(digitado, [student("s1", "20240001")], [member("m1", "g1", "s1")], GRUPOS)
    assert erro.value.code == codigo


@pytest.mark.unit
def test_aluno_que_existe_mas_nao_esta_em_grupo_da_disciplina():
    with pytest.raises(svc.EnrollmentError) as erro:
        svc.find_member(
            "20240009", [student("s1", "20240001"), student("s9", "20240009")],
            [member("m1", "g1", "s1")], GRUPOS,
        )
    assert erro.value.code == "no_group"


@pytest.mark.unit
def test_integrante_sem_aluno_vinculado_nao_e_achado_por_matricula():
    with pytest.raises(svc.EnrollmentError) as erro:
        svc.find_member("20240001", [student("s1", "20240001")], [member("m1", "g1", None)], GRUPOS)
    assert erro.value.code == "no_group"


@pytest.mark.unit
def test_pessoa_em_dois_grupos_cai_sempre_no_mesmo():
    membros = [member("m2", "g2", "s1"), member("m1", "g1", "s1")]
    primeiro = svc.find_member("20240001", [student("s1", "20240001")], membros, GRUPOS)
    segundo = svc.find_member("20240001", [student("s1", "20240001")], membros[::-1], GRUPOS)
    assert primeiro.group_id == segundo.group_id == "g1"


# --- modo media ---------------------------------------------------------------------


@pytest.mark.unit
def test_media_do_grupo_so_conta_quem_entrou():
    linhas = {row["student_id"]: row for row in svc.group_ranking_rows(RESPOSTAS, None, contexto())}

    # G1: Ana 1800 e Bia 400 -> media 1100; Caio nao entrou e nao entra na conta.
    assert linhas["g1"]["score"] == 1100
    assert linhas["g1"]["members"] == 2 and linhas["g1"]["members_total"] == 3
    # G2: so o Davi entrou, 1400.
    assert linhas["g2"]["score"] == 1400
    assert linhas["g2"]["members_total"] == 2


@pytest.mark.unit
def test_ranking_de_grupo_tem_o_mesmo_formato_do_individual_e_ordena_por_pontos():
    individual = ranking_rows([r for r in RESPOSTAS], None)
    grupos = svc.group_ranking_rows(RESPOSTAS, None, contexto())

    assert set(individual[0]) <= set(grupos[0])
    assert [row["student_name"] for row in grupos] == ["Grupo 2", "Grupo 1"]
    assert [row["position"] for row in grupos] == [1, 2]


@pytest.mark.unit
def test_pontos_da_rodada_sao_a_media_da_pergunta_atual():
    linhas = {r["student_id"]: r for r in svc.group_ranking_rows(RESPOSTAS, "q1", contexto())}
    assert linhas["g1"]["round_score"] == 700  # (1000 + 400) / 2
    assert linhas["g2"]["round_score"] == 700


@pytest.mark.unit
def test_resposta_de_aparelho_sem_vinculo_nao_entra_no_ranking_de_grupo():
    estranha = [*RESPOSTAS, resposta("a-fora", "q1", 5000)]
    linhas = svc.group_ranking_rows(estranha, None, contexto())
    assert all(row["score"] < 5000 for row in linhas)


@pytest.mark.unit
def test_mesmo_aluno_em_dois_aparelhos_nao_soma_duas_vezes_a_mesma_pergunta():
    ctx = contexto()
    ctx.member_of_attempt["a-ana-2"] = "ana"
    duplicada = [*RESPOSTAS, resposta("a-ana-2", "q1", 1000, seconds=30)]

    ana = next(
        item for item in svc.member_rows(duplicada, None, ctx) if item["member_id"] == "ana"
    )
    assert ana["score"] == 1800 and ana["answers"] == 2


@pytest.mark.unit
def test_ninguem_entrou_nenhum_grupo_aparece():
    assert svc.group_ranking_rows([], None, svc.GroupContext(mode=svc.MODE_AVERAGE)) == []


# --- modo representante -------------------------------------------------------------


@pytest.mark.unit
def test_representante_vale_pelo_grupo_e_os_outros_nao_contam():
    ctx = contexto(svc.MODE_REPRESENTATIVE, {"g1": "bia", "g2": "davi"})
    linhas = {r["student_id"]: r for r in svc.group_ranking_rows(RESPOSTAS, None, ctx)}

    assert linhas["g1"]["score"] == 400  # so a Bia; os 1800 da Ana nao contam
    assert linhas["g1"]["representative"] == "Bia"
    assert linhas["g2"]["score"] == 1400


@pytest.mark.unit
def test_so_o_representante_pode_responder_e_so_depois_de_vinculado():
    ctx = contexto(svc.MODE_REPRESENTATIVE, {"g1": "bia", "g2": "davi"})
    assert ctx.may_answer("a-bia") is True
    assert ctx.may_answer("a-ana") is False
    assert ctx.may_answer("aparelho-desconhecido") is False

    media = contexto(svc.MODE_AVERAGE)
    assert media.may_answer("a-ana") is True
    assert media.may_answer("aparelho-desconhecido") is False


@pytest.mark.unit
def test_grupo_cujo_representante_ainda_nao_entrou_aparece_valendo_zero():
    ctx = contexto(svc.MODE_REPRESENTATIVE, {"g1": "caio", "g2": "davi"})
    linhas = {r["student_id"]: r for r in svc.group_ranking_rows(RESPOSTAS, None, ctx)}
    assert linhas["g1"]["score"] == 0
    assert linhas["g1"]["members"] == 2


@pytest.mark.unit
def test_contribuicao_por_integrante_marca_quem_conta_para_o_grupo():
    ctx = contexto(svc.MODE_REPRESENTATIVE, {"g1": "bia", "g2": "davi"})
    contam = {row["member_id"]: row["counts"] for row in svc.member_rows(RESPOSTAS, None, ctx)}
    assert contam == {"ana": False, "bia": True, "davi": True}


# --- penalidade por ausente ------------------------------------------------------------


def com_penalidade(mode=svc.MODE_AVERAGE, absence="none", percent=0, representatives=None):
    """Mesmo cenario, agora sabendo quem consegue entrar.

    G1: Ana e Bia entram; Caio nao tem matricula vinculada (nao pode entrar).
    G2: Davi entrou; Eva pode entrar e nao apareceu.
    """
    ctx = contexto(mode, representatives)
    ctx.eligible = {"g1": {"ana", "bia"}, "g2": {"davi", "eva"}}
    ctx.absence_mode = absence
    ctx.absence_percent = percent
    return ctx


def linhas_de(ctx, respostas=RESPOSTAS, atual=None):
    return {row["student_id"]: row for row in svc.group_ranking_rows(respostas, atual, ctx)}


@pytest.mark.unit
def test_sem_penalidade_o_ausente_nao_muda_a_nota_mas_aparece_na_lista():
    linhas = linhas_de(com_penalidade())

    assert linhas["g2"]["score"] == 1400
    assert linhas["g2"]["absent"] == 1 and linhas["g2"]["absent_names"] == ["Eva"]
    assert linhas["g2"]["penalty_percent"] == 0


@pytest.mark.unit
def test_ausente_conta_zero_divide_a_media_por_todos_que_podiam_entrar():
    linhas = linhas_de(com_penalidade(absence="zero"))

    assert linhas["g2"]["score"] == 700  # 1400 / (Davi + Eva)
    assert linhas["g2"]["score_before_penalty"] == 700
    # G1 estava completo (o Caio nao entra na conta): nada muda.
    assert linhas["g1"]["score"] == 1100


@pytest.mark.unit
def test_desconto_percentual_por_ausente():
    linhas = linhas_de(com_penalidade(absence="percent", percent=10))

    assert linhas["g2"]["score"] == 1260  # 1400 menos 10%
    assert linhas["g2"]["score_before_penalty"] == 1400
    assert linhas["g2"]["penalty_percent"] == 10
    assert linhas["g1"]["score"] == 1100 and linhas["g1"]["penalty_percent"] == 0


@pytest.mark.unit
def test_desconto_soma_por_ausente_e_nunca_passa_de_cem_por_cento():
    ctx = com_penalidade(absence="percent", percent=60)
    ctx.eligible["g1"] = {"ana", "bia", "caio"}  # agora o Caio podia entrar e faltou

    linhas = linhas_de(ctx)
    assert linhas["g1"]["absent_names"] == ["Caio"]
    assert linhas["g1"]["score"] == 440  # 1100 menos 60%

    ctx.eligible["g1"] = {"ana", "bia", "caio", "x1"}
    ctx.member_names["x1"] = "X"
    dois = linhas_de(ctx)["g1"]
    assert dois["absent"] == 2 and dois["penalty_percent"] == 100 and dois["score"] == 0


@pytest.mark.unit
def test_integrante_sem_matricula_vinculada_nunca_conta_como_ausente():
    for absence in ("none", "zero", "percent"):
        linhas = linhas_de(com_penalidade(absence=absence, percent=50))
        assert "Caio" not in linhas["g1"]["absent_names"]
        assert linhas["g1"]["score"] == 1100


@pytest.mark.unit
def test_entrou_e_nao_respondeu_nada_tambem_e_ausente():
    so_ana_e_davi = [r for r in RESPOSTAS if r.student_id != "a-bia"]
    linhas = linhas_de(com_penalidade(absence="percent", percent=10), so_ana_e_davi)

    # Bia entrou (tem aparelho vinculado) mas nao respondeu: ausente.
    assert linhas["g1"]["absent_names"] == ["Bia"]
    assert linhas["g1"]["score"] == round(1800 / 2 * 0.9)


@pytest.mark.unit
def test_ausente_conta_zero_inclui_quem_entrou_e_nao_respondeu():
    so_ana_e_davi = [r for r in RESPOSTAS if r.student_id != "a-bia"]
    linhas = linhas_de(com_penalidade(absence="zero"), so_ana_e_davi)
    assert linhas["g1"]["score"] == 900  # 1800 / (Ana + Bia)


@pytest.mark.unit
def test_pular_a_pergunta_conta_como_ter_respondido():
    pulou = [resposta("a-bia", "q1", 0, correct=None), *[r for r in RESPOSTAS if r.student_id != "a-bia"]]
    linhas = linhas_de(com_penalidade(absence="percent", percent=10), pulou)
    assert linhas["g1"]["absent"] == 0


@pytest.mark.unit
def test_representante_vale_so_o_desconto_e_so_ele_precisa_responder():
    ctx = com_penalidade(svc.MODE_REPRESENTATIVE, "percent", 10, {"g1": "bia", "g2": "davi"})
    linhas = linhas_de(ctx)

    # Ana entrou e nao responde por regra: presente. Em G2 a Eva nao entrou.
    assert linhas["g1"]["absent"] == 0 and linhas["g1"]["score"] == 400
    assert linhas["g2"]["absent_names"] == ["Eva"]
    assert linhas["g2"]["score"] == 1260


@pytest.mark.unit
def test_representante_que_entrou_e_nao_respondeu_conta_como_ausente():
    ctx = com_penalidade(svc.MODE_REPRESENTATIVE, "percent", 10, {"g1": "bia", "g2": "davi"})
    sem_bia = [r for r in RESPOSTAS if r.student_id != "a-bia"]

    assert linhas_de(ctx, sem_bia)["g1"]["absent_names"] == ["Bia"]


@pytest.mark.unit
def test_pontos_da_rodada_recebem_o_mesmo_desconto():
    linhas = linhas_de(com_penalidade(absence="percent", percent=10), atual="q1")
    assert linhas["g2"]["round_score"] == round(700 * 0.9)


@pytest.mark.unit
def test_resumo_inclui_grupo_em_que_ninguem_entrou():
    ctx = com_penalidade(absence="percent", percent=10)
    ctx.group_names["g3"] = "Grupo 3"
    ctx.eligible["g3"] = {"x", "y"}
    ctx.member_names.update({"x": "Xavier", "y": "Yara"})

    resumo = svc.absence_summary(RESPOSTAS, ctx)

    assert resumo["g3"] == {"absent": ["Xavier", "Yara"], "penalty_percent": 20}
    assert resumo["g2"] == {"absent": ["Eva"], "penalty_percent": 10}
    assert resumo["g1"] == {"absent": [], "penalty_percent": 0}


@pytest.mark.unit
def test_antes_da_primeira_resposta_so_quem_nao_entrou_e_ausente():
    ctx = com_penalidade(absence="percent", percent=10)

    resumo = svc.absence_summary([], ctx)

    # Ana, Bia e Davi entraram e ainda nao responderam: nao e ausencia.
    assert resumo["g1"]["absent"] == []
    assert resumo["g2"]["absent"] == ["Eva"]


@pytest.mark.unit
def test_penalidade_desligada_ou_sem_percentual_nao_desconta():
    ctx = com_penalidade(absence="percent", percent=0)
    assert svc.penalty_factor(ctx, 3) == 1.0
    assert svc.penalty_factor(com_penalidade(absence="none", percent=50), 3) == 1.0
    assert svc.penalty_factor(com_penalidade(absence="percent", percent=50), 0) == 1.0


@pytest.mark.unit
def test_contexto_sem_dados_de_elegibilidade_so_conta_quem_ja_entrou():
    ctx = contexto()
    ctx.absence_mode, ctx.absence_percent = "percent", 10
    linhas = linhas_de(ctx, [r for r in RESPOSTAS if r.student_id != "a-bia"])
    # Sem saber quem podia entrar, Eva nao e ausente; Bia entrou sem responder: e.
    assert linhas["g2"]["absent"] == 0
    assert linhas["g1"]["absent_names"] == ["Bia"]
