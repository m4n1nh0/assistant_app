"""Quiz em grupo, do lado do professor: ativar o modo, representantes e ranking.

A pontuacao e a identificacao pela matricula estao em `quiz_group_service`; o lado
do aluno (entrada por matricula e resposta) fica em `quiz_play`.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete as sql_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    ClassGroupModel,
    DisciplineModel,
    ProjectGroupMemberModel,
    ProjectGroupModel,
    QuestionModel,
    QuizGroupConfigModel,
    QuizGroupLinkModel,
    QuizGroupRepresentativeModel,
    QuizModel,
    StudentAnswerModel,
    get_db,
)
from ..core.security import get_current_user
from ..services import group_draw_service as draw_rule
from ..services import quiz_group_service as groups
from ..services.project_group_service import (
    as_class_list, class_labels, group_in_any_class_clause,
)

router = APIRouter(prefix="/education/quiz/{quiz_id}/group", tags=["education-quiz-group"])


class GroupConfigBody(BaseModel):
    mode: Literal["media", "representante"] = "media"
    discipline_id: str
    semester: str = ""
    #: Turma (dia de aula) cujos grupos jogam. Vazio: os grupos da disciplina toda.
    #: `class_ids` e a aula reunida (duas turmas no mesmo dia); `class_id` mantem
    #: clientes antigos.
    class_id: Optional[str] = None
    class_ids: list[str] = Field(default_factory=list, max_length=20)
    #: Grupos que não jogam este quiz (o que acabou de apresentar, por exemplo).
    exclude_group_ids: list[str] = Field(default_factory=list, max_length=50)
    #: `none`: sem penalidade; `zero`: ausente conta zero na média (só no modo média);
    #: `percent`: cada ausente tira `absence_percent` por cento da nota do grupo.
    absence_mode: Literal["none", "zero", "percent"] = "none"
    absence_percent: int = Field(default=0, ge=0, le=100)


class RepresentativeBody(BaseModel):
    member_id: str = Field(min_length=1)


class DrawBody(BaseModel):
    #: Refaz tambem os grupos que ja tem representante.
    redraw: bool = False


async def _owned_quiz(quiz_id: str, tutor_id: str, db: AsyncSession) -> QuizModel:
    quiz = await db.get(QuizModel, quiz_id)
    if quiz is None or quiz.tutor_id != tutor_id:
        raise HTTPException(404, "Quiz não encontrado")
    return quiz


async def _answers(db: AsyncSession, quiz_id: str) -> list[StudentAnswerModel]:
    question_ids = list(
        (
            await db.execute(select(QuestionModel.id).where(QuestionModel.quiz_id == quiz_id))
        ).scalars()
    )
    if not question_ids:
        return []
    return list(
        (
            await db.execute(
                select(StudentAnswerModel).where(StudentAnswerModel.question_id.in_(question_ids))
            )
        ).scalars()
    )


async def _answer_count(db: AsyncSession, quiz_id: str) -> int:
    return len(await _answers(db, quiz_id))


def _ensure_editable(quiz: QuizModel) -> None:
    if quiz.status == "closed":
        raise HTTPException(409, "O quiz já foi encerrado.")
    if quiz.status == "open" and (quiz.live_phase or "lobby") == "question":
        raise HTTPException(
            409, "Há uma pergunta aberta para a turma. Encerre a pergunta antes de mudar o grupo."
        )


async def _config_or_404(db: AsyncSession, quiz_id: str) -> QuizGroupConfigModel:
    config = await groups.get_config(db, quiz_id)
    if config is None:
        raise HTTPException(404, "Este quiz não é em grupo.")
    return config


async def _overview(db: AsyncSession, quiz: QuizModel, config: QuizGroupConfigModel) -> dict:
    ctx = await groups.load_context(db, config)
    elegiveis = await groups.eligible_members(db, config)
    answers = await _answers(db, quiz.id)
    discipline = await db.get(DisciplineModel, config.discipline_id)
    turma_ids = groups.config_class_ids(config)
    turmas = await class_labels(db, config.tutor_id, turma_ids)
    excluidos = groups.config_excluded_ids(config)

    grupos = (
        await db.execute(
            select(ProjectGroupModel)
            .where(
                ProjectGroupModel.tutor_id == config.tutor_id,
                ProjectGroupModel.discipline_id == config.discipline_id,
                *([ProjectGroupModel.semester == config.semester] if config.semester else []),
                *([group_in_any_class_clause(turma_ids)] if turma_ids else []),
                *([ProjectGroupModel.id.not_in(excluidos)] if excluidos else []),
            )
            .order_by(ProjectGroupModel.name)
        )
    ).scalars().all()

    reps = {
        rep.group_id: rep
        for rep in (
            await db.execute(
                select(QuizGroupRepresentativeModel).where(
                    QuizGroupRepresentativeModel.quiz_id == quiz.id
                )
            )
        ).scalars()
    }
    entraram = set(ctx.member_of_attempt.values())
    contribuicao = {
        item["member_id"]: item for item in groups.member_rows(answers, None, ctx)
    }

    membros = (
        await db.execute(
            select(ProjectGroupMemberModel)
            .where(ProjectGroupMemberModel.group_id.in_([g.id for g in grupos] or [""]))
            .order_by(ProjectGroupMemberModel.position)
        )
    ).scalars().all()
    elegiveis_ids = {m.id for lista in elegiveis.values() for m in lista}

    ausencias = groups.absence_summary(answers, ctx)
    saida = []
    for grupo in grupos:
        rep = reps.get(grupo.id)
        saida.append({
            "id": grupo.id,
            "name": grupo.name,
            "absent": ausencias.get(grupo.id, {}).get("absent", []),
            "penalty_percent": ausencias.get(grupo.id, {}).get("penalty_percent", 0),
            "representative": None if rep is None else {
                "member_id": rep.member_id,
                "name": rep.member_name,
                "round": rep.round,
                "origin": rep.origin,
            },
            "members": [
                {
                    "id": m.id,
                    "name": m.name,
                    "eligible": m.id in elegiveis_ids,
                    "joined": m.id in entraram,
                    "score": contribuicao.get(m.id, {}).get("score", 0),
                    "answers": contribuicao.get(m.id, {}).get("answers", 0),
                }
                for m in membros
                if m.group_id == grupo.id
            ],
        })

    return {
        "enabled": True,
        "mode": config.mode,
        "discipline_id": config.discipline_id,
        "discipline": (
            " - ".join(
                part for part in ((discipline.code or "").strip(), (discipline.name or "").strip())
                if part
            )
            if discipline else ""
        ),
        "semester": config.semester,
        "class_id": turma_ids[0] if turma_ids else None,
        "class_ids": turma_ids,
        "class_label": " + ".join(
            turmas[item]["display"] for item in turma_ids if item in turmas),
        "excluded_group_ids": excluidos,
        "excluded_groups": [
            nome for nome in (await db.execute(
                select(ProjectGroupModel.name)
                .where(ProjectGroupModel.id.in_(excluidos or [""]))
                .order_by(ProjectGroupModel.name)
            )).scalars().all()
        ],
        "seed": config.seed,
        "absence_mode": config.absence_mode or groups.ABSENCE_NONE,
        "absence_percent": int(config.absence_percent or 0),
        "algorithm": draw_rule.ALGORITHM,
        "groups": saida,
        "ranking": groups.group_ranking_rows(answers, None, ctx),
        "without_representative": [
            g["name"] for g in saida
            if config.mode == groups.MODE_REPRESENTATIVE and g["representative"] is None
        ],
    }


@router.get("")
async def get_group_quiz(
    quiz_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Situação do quiz em grupo; `enabled: false` quando o quiz é individual."""
    quiz = await _owned_quiz(quiz_id, user["tutor_id"], db)
    config = await groups.get_config(db, quiz.id)
    if config is None:
        return {"enabled": False}
    return await _overview(db, quiz, config)


async def configure_group(
    db: AsyncSession, quiz: QuizModel, tutor_id: str, body: GroupConfigBody
) -> QuizGroupConfigModel:
    """Liga (ou ajusta) o modo em grupo do quiz, com todas as validações.

    Serve à rota do professor e ao quiz rápido da apresentação, que nasce já em grupo.
    """
    if body.absence_mode == groups.ABSENCE_ZERO and body.mode == groups.MODE_REPRESENTATIVE:
        raise HTTPException(
            422,
            "\"Ausente conta zero\" só vale na média do grupo. No modo representante "
            "use o desconto por ausente.",
        )
    if body.absence_mode == groups.ABSENCE_PERCENT and body.absence_percent < 1:
        raise HTTPException(422, "Informe o desconto por ausente (de 1% a 100%).")
    percent = body.absence_percent if body.absence_mode == groups.ABSENCE_PERCENT else 0

    atual = await groups.get_config(db, quiz.id)
    semester = body.semester.strip()
    class_ids = as_class_list([*body.class_ids, body.class_id or ""])
    class_id = class_ids[0] if class_ids else None
    excluded = as_class_list(body.exclude_group_ids)
    if atual is not None and (
        atual.mode, atual.discipline_id, atual.semester, groups.config_class_ids(atual),
        groups.config_excluded_ids(atual),
    ) == (body.mode, body.discipline_id, semester, class_ids, excluded):
        atual.absence_mode, atual.absence_percent = body.absence_mode, percent
        await db.commit()
        await db.refresh(atual)
        return atual

    _ensure_editable(quiz)

    discipline = await db.get(DisciplineModel, body.discipline_id)
    if discipline is None or discipline.tutor_id != tutor_id:
        raise HTTPException(404, "Disciplina não encontrada")
    for item in class_ids:
        turma = await db.get(ClassGroupModel, item)
        if turma is None or turma.tutor_id != tutor_id:
            raise HTTPException(404, "Turma não encontrada")
        if turma.discipline_id != body.discipline_id:
            raise HTTPException(422, "Essa turma não é desta disciplina")
    if excluded:
        found = (await db.execute(
            select(ProjectGroupModel.id).where(
                ProjectGroupModel.tutor_id == tutor_id,
                ProjectGroupModel.discipline_id == body.discipline_id,
                ProjectGroupModel.id.in_(excluded),
            )
        )).scalars().all()
        if len(found) != len(excluded):
            raise HTTPException(404, "Grupo a deixar de fora não encontrado nesta disciplina")
    total_grupos = (
        await db.execute(
            select(func.count())
            .select_from(ProjectGroupModel)
            .where(
                ProjectGroupModel.tutor_id == tutor_id,
                ProjectGroupModel.discipline_id == body.discipline_id,
                *([ProjectGroupModel.semester == semester] if semester else []),
                *([group_in_any_class_clause(class_ids)] if class_ids else []),
                *([ProjectGroupModel.id.not_in(excluded)] if excluded else []),
            )
        )
    ).scalar_one()
    if not total_grupos:
        raise HTTPException(
            422,
            "Não sobra nenhum grupo para jogar: o grupo deixado de fora era o único."
            if excluded else
            "Essa turma não tem grupos de projeto cadastrados."
            if class_ids else "Essa disciplina não tem grupos de projeto cadastrados.",
        )

    config = await groups.get_config(db, quiz.id)
    mudou_grupos = False
    if config is None:
        config = QuizGroupConfigModel(
            quiz_id=quiz.id, tutor_id=tutor_id, seed=draw_rule.new_seed()
        )
        db.add(config)
    else:
        mudou_grupos = (
            config.discipline_id, groups.config_class_ids(config),
            groups.config_excluded_ids(config),
        ) != (body.discipline_id, class_ids, excluded)
        if (config.mode, config.discipline_id, config.semester,
                groups.config_class_ids(config), groups.config_excluded_ids(config)) != (
            body.mode, body.discipline_id, semester, class_ids, excluded
        ) and await _answer_count(db, quiz.id):
            raise HTTPException(
                409,
                "A turma já respondeu: não dá para mudar o modo, a disciplina, as turmas "
                "nem os grupos que ficam de fora.",
            )
    if mudou_grupos:
        await db.execute(sql_delete(QuizGroupRepresentativeModel).where(
            QuizGroupRepresentativeModel.quiz_id == quiz.id))
        await db.execute(sql_delete(QuizGroupLinkModel).where(
            QuizGroupLinkModel.quiz_id == quiz.id))

    config.mode = body.mode
    config.discipline_id = body.discipline_id
    config.semester = semester
    config.class_id = class_id
    config.class_ids = ",".join(class_ids)
    config.excluded_group_ids = ",".join(excluded)
    config.absence_mode = body.absence_mode
    config.absence_percent = percent
    await db.commit()
    await db.refresh(config)
    return config


async def apply_group_setup(
    db: AsyncSession, quiz_id: str, tutor_id: str, setup
) -> QuizGroupConfigModel:
    """Deixa o quiz recém-gerado em grupo, como pediu o quiz rápido da apresentação."""
    quiz = await db.get(QuizModel, quiz_id)
    if quiz is None or quiz.tutor_id != tutor_id:
        raise HTTPException(404, "Quiz não encontrado")
    discipline = await db.get(DisciplineModel, setup.discipline_id)
    return await configure_group(
        db, quiz, tutor_id,
        GroupConfigBody(
            mode=setup.mode,
            discipline_id=setup.discipline_id,
            semester=(discipline.semester or "") if discipline else "",
            class_ids=list(setup.class_ids),
            exclude_group_ids=list(setup.exclude_group_ids),
            absence_mode=setup.absence_mode,
            absence_percent=setup.absence_percent,
        ),
    )


@router.put("")
async def set_group_quiz(
    quiz_id: str,
    body: GroupConfigBody,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Torna o quiz em grupo (ou muda o modo/disciplina enquanto ninguém respondeu).

    A penalidade por ausente é só uma regra de cálculo, não altera nenhuma resposta
    gravada: pode ser ajustada a qualquer momento, até com o quiz encerrado. Já o
    modo e a disciplina mudam quem pode responder, e por isso têm as travas.
    """
    tutor_id = user["tutor_id"]
    quiz = await _owned_quiz(quiz_id, tutor_id, db)
    config = await configure_group(db, quiz, tutor_id, body)
    return await _overview(db, quiz, config)


@router.delete("")
async def unset_group_quiz(
    quiz_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Volta o quiz a ser individual."""
    quiz = await _owned_quiz(quiz_id, user["tutor_id"], db)
    _ensure_editable(quiz)
    if await groups.get_config(db, quiz.id) is None:
        return {"enabled": False}
    if await _answer_count(db, quiz.id):
        raise HTTPException(
            409, "A turma já respondeu como grupo: não dá para voltar o quiz a individual."
        )
    for model in (QuizGroupRepresentativeModel, QuizGroupLinkModel, QuizGroupConfigModel):
        await db.execute(sql_delete(model).where(model.quiz_id == quiz.id))
    await db.commit()
    return {"enabled": False}


@router.post("/representatives/draw")
async def draw_representatives(
    quiz_id: str,
    body: DrawBody = DrawBody(),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sorteia o representante dos grupos que ainda não têm (ou de todos, com `redraw`)."""
    quiz = await _owned_quiz(quiz_id, user["tutor_id"], db)
    config = await _config_or_404(db, quiz.id)
    resultado = await groups.draw_representatives(db, config, only_missing=not body.redraw)
    painel = await _overview(db, quiz, config)
    painel["draw_result"] = resultado
    return painel


@router.post("/representatives/{group_id}/redraw")
async def redraw_representative(
    quiz_id: str,
    group_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sorteia outro representante para um grupo (o escolhido faltou, por exemplo)."""
    quiz = await _owned_quiz(quiz_id, user["tutor_id"], db)
    config = await _config_or_404(db, quiz.id)
    elegiveis = await groups.eligible_members(db, config)
    if group_id not in elegiveis:
        raise HTTPException(404, "Grupo não encontrado neste quiz")
    if not elegiveis[group_id]:
        raise HTTPException(
            422, "Nenhum integrante deste grupo tem matrícula vinculada para responder."
        )

    existente = (
        await db.execute(
            select(QuizGroupRepresentativeModel).where(
                QuizGroupRepresentativeModel.quiz_id == quiz.id,
                QuizGroupRepresentativeModel.group_id == group_id,
            )
        )
    ).scalar_one_or_none()
    rodada = 0 if existente is None else existente.round + 1
    ids = [m.id for m in elegiveis[group_id]]
    if len(ids) == 1:
        rodada = 0
    escolhido = draw_rule.pick_representative(config.seed, group_id, ids, round_=rodada)
    membro = next(m for m in elegiveis[group_id] if m.id == escolhido)
    rep = existente or QuizGroupRepresentativeModel(quiz_id=quiz.id, group_id=group_id)
    rep.member_id, rep.member_name = membro.id, membro.name
    rep.round, rep.origin = rodada, "sorteio"
    db.add(rep)
    await db.commit()
    return await _overview(db, quiz, config)


@router.put("/representatives/{group_id}")
async def set_representative(
    quiz_id: str,
    group_id: str,
    body: RepresentativeBody,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """O professor escolhe quem responde pelo grupo."""
    quiz = await _owned_quiz(quiz_id, user["tutor_id"], db)
    config = await _config_or_404(db, quiz.id)
    elegiveis = await groups.eligible_members(db, config)
    if group_id not in elegiveis:
        raise HTTPException(404, "Grupo não encontrado neste quiz")
    membro = next((m for m in elegiveis[group_id] if m.id == body.member_id), None)
    if membro is None:
        raise HTTPException(
            422, "Esse integrante não pertence ao grupo ou não tem matrícula vinculada."
        )

    rep = (
        await db.execute(
            select(QuizGroupRepresentativeModel).where(
                QuizGroupRepresentativeModel.quiz_id == quiz.id,
                QuizGroupRepresentativeModel.group_id == group_id,
            )
        )
    ).scalar_one_or_none() or QuizGroupRepresentativeModel(quiz_id=quiz.id, group_id=group_id)
    rep.member_id, rep.member_name = membro.id, membro.name
    rep.origin = "manual"
    db.add(rep)
    await db.commit()
    return await _overview(db, quiz, config)
