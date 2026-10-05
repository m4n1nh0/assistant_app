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
