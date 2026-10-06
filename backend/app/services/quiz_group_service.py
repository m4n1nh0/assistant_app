"""Quiz em grupo: quem e de qual grupo, quem responde e quanto o grupo vale.

Dois modos, escolhidos pelo professor ao montar o quiz:

- `media`: todos respondem no proprio celular. O grupo vale a media dos pontos dos
  integrantes que entraram - quem nao apareceu nao puxa o grupo para baixo, e a
  tela mostra "n de m participaram" para o professor julgar;
- `representante`: o grupo discute e so o representante responde. O grupo vale o que
  o representante fez; as respostas dos outros integrantes nao contam.

O ranking de grupo sai no mesmo formato do individual (`quiz_live_service.ranking_rows`),
com o id e o nome do grupo no lugar do aluno. Assim a pagina do aluno e o painel do
professor mostram o ranking de grupo sem outra tela.

O aluno se identifica pela matricula. Ela nao e segredo - quem souber a de um colega
responde por ele -, e e isso que a sala de aula aceita: o servidor so liga a matricula
ao grupo certo da disciplina e impede que ela valha fora dela.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    ProjectGroupMemberModel,
    ProjectGroupModel,
    QuizGroupConfigModel,
    QuizGroupLinkModel,
    QuizGroupRepresentativeModel,
    StudentAnswerModel,
    StudentModel,
)
from . import group_draw_service as draw_rule
from . import project_group_service as project_groups

MODE_AVERAGE = "media"
MODE_REPRESENTATIVE = "representante"
MODES = (MODE_AVERAGE, MODE_REPRESENTATIVE)


# --- identificacao pela matricula ----------------------------------------------------


def normalize_enrollment(value: Optional[str]) -> str:
    """Matricula comparavel: so letras e numeros, sem caixa.

    O aluno digita "2024-0123 " e o cadastro tem "20240123": os dois valem a mesma.
    Zeros a esquerda ficam - "0123" e "123" sao matriculas diferentes.
    """
    return re.sub(r"[^0-9a-z]", "", (value or "").casefold())


class EnrollmentError(Exception):
    """A matricula nao leva a um grupo. `code` diz por que, para a tela do aluno."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Resolved:
    group_id: str
    group_name: str
    member_id: str
    member_name: str
    enrollment: str


def find_member(
    enrollment: str,
    students: Sequence[StudentModel],
    members: Sequence[ProjectGroupMemberModel],
    group_names: dict[str, str],
) -> Resolved:
    """Acha, entre os integrantes de grupos, quem tem essa matricula.

    `students` sao os alunos ligados a algum integrante. Um integrante sem aluno
    vinculado nao tem matricula conhecida e nao pode ser achado por ela.
    """
    alvo = normalize_enrollment(enrollment)
    if not alvo:
        raise EnrollmentError("invalid")

    ids_do_aluno = {
        student.id
        for student in students
        if normalize_enrollment(student.external_id) == alvo
    }
    if not ids_do_aluno:
        raise EnrollmentError("unknown")

    candidatos = [member for member in members if member.student_id in ids_do_aluno]
    if not candidatos:
        raise EnrollmentError("no_group")

    # Mesma pessoa em dois grupos da disciplina e erro de cadastro; sem decidir
    # por sorte, vale sempre o mesmo (o de menor nome de grupo).
    escolhido = min(
        candidatos,
        key=lambda member: (group_names.get(member.group_id, ""), member.id),
    )
    return Resolved(
        group_id=escolhido.group_id,
        group_name=group_names.get(escolhido.group_id, ""),
        member_id=escolhido.id,
        member_name=escolhido.name,
        enrollment=alvo,
    )


# --- pontuacao -----------------------------------------------------------------------


@dataclass
class GroupContext:
    """O que o ranking precisa saber sobre os grupos de um quiz."""

    mode: str
    group_names: dict[str, str] = field(default_factory=dict)
    #: aparelho (tentativa) -> integrante
    member_of_attempt: dict[str, str] = field(default_factory=dict)
    member_group: dict[str, str] = field(default_factory=dict)
    member_names: dict[str, str] = field(default_factory=dict)
    #: grupo -> integrante que responde por ele (modo representante)
    representatives: dict[str, str] = field(default_factory=dict)
    #: grupo -> quantos integrantes tem no total
    group_sizes: dict[str, int] = field(default_factory=dict)
    #: grupo -> integrantes que conseguem entrar (aluno vinculado com matricula).
    #: Sem esta informacao, so quem ja entrou pode ser contado como ausente.
    eligible: dict[str, set[str]] = field(default_factory=dict)
    #: Penalidade por ausente (`none`, `zero` ou `percent`) e o percentual de cada um.
    absence_mode: str = "none"
    absence_percent: int = 0

    def group_of_attempt(self, attempt_id: str) -> Optional[str]:
        member = self.member_of_attempt.get(attempt_id)
        return self.member_group.get(member) if member else None

    def may_answer(self, attempt_id: str) -> bool:
        """No modo representante so ele responde; na media, todo integrante."""
        member = self.member_of_attempt.get(attempt_id)
        if member is None:
            return False
        if self.mode != MODE_REPRESENTATIVE:
            return True
        return self.representatives.get(self.member_group.get(member, "")) == member


def _time_key(answer: StudentAnswerModel):
    moment = getattr(answer, "respondido_em", None)
    return (moment is None, moment.timestamp() if moment else 0)


def _member_totals(
    answers: Iterable[StudentAnswerModel],
    ctx: GroupContext,
    current_question_id: Optional[str],
) -> dict[str, dict]:
    """Pontos de cada integrante, uma resposta por pergunta.

    O mesmo aluno em dois aparelhos pode responder a mesma pergunta duas vezes; vale
    a primeira, senao responder de novo no celular do colega somaria pontos.
    """
    por_membro: dict[str, dict[str, StudentAnswerModel]] = {}
    for answer in sorted(answers, key=_time_key):
        member = ctx.member_of_attempt.get(answer.student_id or "")
        if member is None:
            continue
        por_membro.setdefault(member, {}).setdefault(answer.question_id, answer)

    totais: dict[str, dict] = {}
    for member in set(ctx.member_of_attempt.values()):
        respostas = por_membro.get(member, {}).values()
        atual = por_membro.get(member, {}).get(current_question_id or "")
        totais[member] = {
            "score": sum(int(item.pontuacao or 0) for item in respostas),
            "correct": sum(1 for item in respostas if item.correta is True),
            "answers": len(respostas),
            "round_score": int(atual.pontuacao or 0) if atual else 0,
            "round_correct": atual.correta if atual else None,
        }
    return totais


ABSENCE_NONE = "none"
ABSENCE_ZERO = "zero"
ABSENCE_PERCENT = "percent"
ABSENCE_MODES = (ABSENCE_NONE, ABSENCE_ZERO, ABSENCE_PERCENT)


def absent_members(
    group_id: str,
    totais: dict[str, dict],
    ctx: GroupContext,
    *,
    judge_answers: bool = True,
) -> list[str]:
    """Integrantes do grupo que faltaram: nao entraram, ou entraram e nao responderam.

    So conta quem consegue entrar. Integrante sem matricula vinculada nao tem como
    ler o QR Code e se identificar; penaliza-lo seria punir uma falha de cadastro, e
    o professor ja e avisado dela na tela do grupo.

    No modo representante so ele responde, entao "entrou e nao respondeu" vale so
    para ele: os outros estao presentes se entraram.

    `judge_answers=False` (quiz sem nenhuma resposta ainda) so olha quem nao entrou:
    antes da primeira pergunta ninguem respondeu, e nao e ausencia.
    """
    ligados = {
        member for member, grupo in ctx.member_group.items()
        if grupo == group_id and member in totais
    }
    elegiveis = ctx.eligible.get(group_id)
    base = ligados | set(elegiveis) if elegiveis is not None else set(ligados)
    rep = ctx.representatives.get(group_id)

    ausentes = []
    for member in base:
        if member not in totais:
            ausentes.append(member)
            continue
        responde = ctx.mode != MODE_REPRESENTATIVE or member == rep
        if judge_answers and responde and totais[member]["answers"] == 0:
            ausentes.append(member)
    return sorted(ausentes, key=lambda member: (ctx.member_names.get(member, ""), member))


def penalty_factor(ctx: GroupContext, absent: int) -> float:
    """Quanto da nota do grupo sobra. Nunca passa de 100% de desconto."""
    if ctx.absence_mode != ABSENCE_PERCENT or not ctx.absence_percent or not absent:
        return 1.0
    return max(0.0, 1.0 - ctx.absence_percent * absent / 100)


def group_ranking_rows(
    answers: Iterable[StudentAnswerModel],
    current_question_id: Optional[str],
    ctx: GroupContext,
) -> list[dict]:
    """Ranking dos grupos, no formato do ranking individual."""
    totais = _member_totals(list(answers), ctx, current_question_id)

    membros_por_grupo: dict[str, list[str]] = {}
    for member in totais:
        grupo = ctx.member_group.get(member)
        if grupo:
            membros_por_grupo.setdefault(grupo, []).append(member)

    linhas: list[dict] = []
    for grupo, membros in membros_por_grupo.items():
        ausentes = absent_members(grupo, totais, ctx)

        if ctx.mode == MODE_REPRESENTATIVE:
            rep = ctx.representatives.get(grupo)
            contam = [rep] if rep in totais else []
        else:
            contam = membros

        if contam:
            soma = sum(totais[m]["score"] for m in contam)
            rodada = sum(totais[m]["round_score"] for m in contam)
            # "Ausente conta zero": a media passa a ser dividida por todos os que
            # podiam entrar, e quem faltou entra na conta valendo zero.
            if ctx.mode != MODE_REPRESENTATIVE and ctx.absence_mode == ABSENCE_ZERO:
                divisor = max(len(set(ctx.eligible.get(grupo, ())) | set(contam)), 1)
            else:
                divisor = len(contam)
            base = soma / divisor
            base_rodada = rodada / divisor
        else:
            # Representante que ainda nao entrou: o grupo aparece, valendo zero.
            base = base_rodada = 0

        fator = penalty_factor(ctx, len(ausentes))
        score = int(round(base * fator))
        round_score = int(round(base_rodada * fator))
        correct = sum(totais[m]["correct"] for m in contam)
        round_correct = None
        if ctx.mode == MODE_REPRESENTATIVE and contam:
            round_correct = totais[contam[0]]["round_correct"]

        rep_id = ctx.representatives.get(grupo)
        linhas.append({
            "student_id": grupo,
            "student_name": ctx.group_names.get(grupo, "Grupo"),
            "score": score,
            "round_score": round_score,
            "round_correct": round_correct,
            "correct": correct,
            "answers": sum(totais[m]["answers"] for m in contam),
            # Extras que a tela do professor mostra; as telas antigas ignoram.
            "members": len(membros),
            "members_total": ctx.group_sizes.get(grupo, len(membros)),
            "representative": ctx.member_names.get(rep_id, "") if rep_id else "",
            "mode": ctx.mode,
            "absent": len(ausentes),
            "absence_mode": ctx.absence_mode,
            "absent_names": [ctx.member_names.get(m, "") for m in ausentes],
            "penalty_percent": int(round((1 - fator) * 100)),
            "score_before_penalty": int(round(base)),
        })

    linhas.sort(key=lambda item: (-item["score"], -item["correct"], item["student_name"]))
    for posicao, linha in enumerate(linhas, start=1):
        linha["position"] = posicao
    return linhas


def absence_summary(
    answers: Iterable[StudentAnswerModel], ctx: GroupContext
) -> dict[str, dict]:
    """Ausentes e desconto de cada grupo, inclusive os em que ninguem entrou.

    O ranking so lista grupo em que alguem entrou; o professor precisa ver tambem
    o grupo que ficou inteiro de fora.
    """
    respostas = list(answers)
    totais = _member_totals(respostas, ctx, None)
    resumo = {}
    for grupo in ctx.group_names:
        ausentes = absent_members(grupo, totais, ctx, judge_answers=bool(respostas))
        resumo[grupo] = {
            "absent": [ctx.member_names.get(m, "") for m in ausentes],
            "penalty_percent": int(round((1 - penalty_factor(ctx, len(ausentes))) * 100)),
        }
    return resumo


def member_rows(
    answers: Iterable[StudentAnswerModel],
    current_question_id: Optional[str],
    ctx: GroupContext,
) -> list[dict]:
    """Contribuicao de cada integrante, para o professor ver quem puxou o grupo."""
    totais = _member_totals(list(answers), ctx, current_question_id)
    linhas = [
        {
            "member_id": member,
            "member_name": ctx.member_names.get(member, ""),
            "group_id": ctx.member_group.get(member, ""),
            "group_name": ctx.group_names.get(ctx.member_group.get(member, ""), ""),
            "score": dados["score"],
            "correct": dados["correct"],
            "answers": dados["answers"],
            "counts": ctx.mode != MODE_REPRESENTATIVE
            or ctx.representatives.get(ctx.member_group.get(member, "")) == member,
        }
        for member, dados in totais.items()
    ]
    linhas.sort(key=lambda item: (item["group_name"], -item["score"], item["member_name"]))
    return linhas


# --- banco ---------------------------------------------------------------------------


async def get_config(db: AsyncSession, quiz_id: str) -> Optional[QuizGroupConfigModel]:
    return (
        await db.execute(
            select(QuizGroupConfigModel).where(QuizGroupConfigModel.quiz_id == quiz_id)
        )
    ).scalar_one_or_none()


def config_class_ids(config: QuizGroupConfigModel) -> list[str]:
    """Turmas do quiz em grupo. Quiz antigo, sem a lista, vale a turma `class_id`."""
    listed = project_groups.as_class_list((config.class_ids or "").split(","))
    if listed:
        return listed
    return project_groups.as_class_list(config.class_id)


async def _groups_of(db: AsyncSession, config: QuizGroupConfigModel) -> list[ProjectGroupModel]:
    query = select(ProjectGroupModel).where(
        ProjectGroupModel.tutor_id == config.tutor_id,
        ProjectGroupModel.discipline_id == config.discipline_id,
    )
    if config.semester:
        query = query.where(ProjectGroupModel.semester == config.semester)
    turmas = config_class_ids(config)
    if turmas:
        query = query.where(project_groups.group_in_any_class_clause(turmas))
    return list((await db.execute(query)).scalars().all())


async def _members_of(db: AsyncSession, group_ids: Sequence[str]) -> list[ProjectGroupMemberModel]:
    if not group_ids:
        return []
    return list(
        (
            await db.execute(
                select(ProjectGroupMemberModel)
                .where(ProjectGroupMemberModel.group_id.in_(list(group_ids)))
                .order_by(ProjectGroupMemberModel.position)
            )
        ).scalars()
    )


async def _students_of(
    db: AsyncSession, tutor_id: str, members: Sequence[ProjectGroupMemberModel]
) -> list[StudentModel]:
    ids = [member.student_id for member in members if member.student_id]
    if not ids:
        return []
    return list(
        (
            await db.execute(
                select(StudentModel).where(
                    StudentModel.tutor_id == tutor_id, StudentModel.id.in_(ids)
                )
            )
        ).scalars()
    )


async def resolve_enrollment(
    db: AsyncSession, config: QuizGroupConfigModel, enrollment: str
) -> Resolved:
    """Matricula -> integrante e grupo, dentro da disciplina do quiz."""
    groups = await _groups_of(db, config)
    members = await _members_of(db, [group.id for group in groups])
    students = await _students_of(db, config.tutor_id, members)
    try:
        return find_member(
            enrollment, students, members, {group.id: group.name for group in groups}
        )
    except EnrollmentError as exc:
        if exc.code != "unknown":
            raise
        # So os alunos de grupos deste quiz foram carregados. Matricula de quem
        # existe na disciplina mas esta em outra turma (ou sem grupo) nao e
        # "matricula inexistente": o aluno precisa saber que o problema e o grupo.
        alvo = normalize_enrollment(enrollment)
        elenco = await project_groups.roster_for_discipline(
            db, config.tutor_id, config.discipline_id
        )
        if alvo and any(normalize_enrollment(item.external_id) == alvo for item in elenco):
            raise EnrollmentError("no_group") from exc
        raise


async def link_attempt(
    db: AsyncSession, quiz_id: str, attempt_id: str, resolved: Resolved
) -> QuizGroupLinkModel:
    """Grava (ou atualiza) o vinculo do aparelho. Reentrar com outra matricula troca."""
    link = (
        await db.execute(
            select(QuizGroupLinkModel).where(
                QuizGroupLinkModel.quiz_id == quiz_id,
                QuizGroupLinkModel.attempt_id == attempt_id,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        link = QuizGroupLinkModel(quiz_id=quiz_id, attempt_id=attempt_id)
        db.add(link)
    link.group_id = resolved.group_id
    link.group_name = resolved.group_name
    link.member_id = resolved.member_id
    link.member_name = resolved.member_name
    link.enrollment = resolved.enrollment
    await db.commit()
    return link


async def get_link(
    db: AsyncSession, quiz_id: str, attempt_id: str
) -> Optional[QuizGroupLinkModel]:
    return (
        await db.execute(
            select(QuizGroupLinkModel).where(
                QuizGroupLinkModel.quiz_id == quiz_id,
                QuizGroupLinkModel.attempt_id == attempt_id,
            )
        )
    ).scalar_one_or_none()


async def load_context(
    db: AsyncSession, config: QuizGroupConfigModel
) -> GroupContext:
    """Monta o contexto do ranking: grupos, vinculos e representantes do quiz."""
    groups = await _groups_of(db, config)
    members = await _members_of(db, [group.id for group in groups])
    links = list(
        (
            await db.execute(
                select(QuizGroupLinkModel).where(QuizGroupLinkModel.quiz_id == config.quiz_id)
            )
        ).scalars()
    )
    reps = list(
        (
            await db.execute(
                select(QuizGroupRepresentativeModel).where(
                    QuizGroupRepresentativeModel.quiz_id == config.quiz_id
                )
            )
        ).scalars()
    )

    sizes: dict[str, int] = {}
    nomes = {member.id: member.name for member in members}
    for member in members:
        sizes[member.group_id] = sizes.get(member.group_id, 0) + 1

    elegiveis = await eligible_members(db, config)
    ctx = GroupContext(
        mode=config.mode,
        group_names={group.id: group.name for group in groups},
        group_sizes=sizes,
        representatives={rep.group_id: rep.member_id for rep in reps},
        eligible={
            grupo: {member.id for member in lista} for grupo, lista in elegiveis.items()
        },
        absence_mode=config.absence_mode or ABSENCE_NONE,
        absence_percent=int(config.absence_percent or 0),
    )
    ctx.member_names.update(nomes)
    for rep in reps:
        ctx.member_names.setdefault(rep.member_id, rep.member_name)
    for link in links:
        ctx.member_of_attempt[link.attempt_id] = link.member_id
        ctx.member_group[link.member_id] = link.group_id
        ctx.member_names[link.member_id] = link.member_name or ctx.member_names.get(
            link.member_id, ""
        )
        ctx.group_names.setdefault(link.group_id, link.group_name)
    # Representante ainda sem aparelho vinculado precisa saber a que grupo pertence.
    for rep in reps:
        ctx.member_group.setdefault(rep.member_id, rep.group_id)
    return ctx


async def eligible_members(
    db: AsyncSession, config: QuizGroupConfigModel
) -> dict[str, list[ProjectGroupMemberModel]]:
    """Integrantes que conseguem entrar no quiz: tem aluno vinculado com matricula.

    Quem nao tem matricula conhecida nao tem como se identificar, entao sortear
    um deles como representante deixaria o grupo sem ninguem para responder.
    """
    groups = await _groups_of(db, config)
    members = await _members_of(db, [group.id for group in groups])
    students = await _students_of(db, config.tutor_id, members)
    com_matricula = {
        student.id for student in students if normalize_enrollment(student.external_id)
    }
    por_grupo: dict[str, list[ProjectGroupMemberModel]] = {group.id: [] for group in groups}
    for member in members:
        if member.student_id in com_matricula:
            por_grupo.setdefault(member.group_id, []).append(member)
    return por_grupo


async def draw_representatives(
    db: AsyncSession,
    config: QuizGroupConfigModel,
    *,
    only_missing: bool = True,
) -> dict:
    """Sorteia o representante dos grupos. Devolve quem saiu e quem ficou sem.

    Pela regra do sorteio de apresentacao: a semente e a do quiz, entao o resultado
    pode ser conferido depois. Grupo sem integrante com matricula nao sorteia nada e
    vem em `skipped`, para o professor corrigir o cadastro.
    """
    elegiveis = await eligible_members(db, config)
    existentes = {
        rep.group_id: rep
        for rep in (
            await db.execute(
                select(QuizGroupRepresentativeModel).where(
                    QuizGroupRepresentativeModel.quiz_id == config.quiz_id
                )
            )
        ).scalars()
    }
    sorteados, sem_ninguem = [], []
    for group_id, membros in elegiveis.items():
        if not membros:
            sem_ninguem.append(group_id)
            continue
        if only_missing and group_id in existentes:
            continue
        rodada = 0 if group_id not in existentes else existentes[group_id].round + 1
        escolhido = draw_rule.pick_representative(
            config.seed, group_id, [m.id for m in membros], round_=rodada
        )
        membro = next(m for m in membros if m.id == escolhido)
        rep = existentes.get(group_id) or QuizGroupRepresentativeModel(
            quiz_id=config.quiz_id, group_id=group_id
        )
        rep.member_id, rep.member_name = membro.id, membro.name
        rep.round, rep.origin = rodada, "sorteio"
        db.add(rep)
        sorteados.append(group_id)
    await db.commit()
    return {"drawn": sorteados, "skipped": sem_ninguem}
