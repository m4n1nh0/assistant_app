"""Ferramentas de leitura do Modo Educacao: o assistente consulta o banco.

Ate aqui o assistente so tinha dois caminhos para falar de conteudo: os trechos
de transcricao que o RAG injeta no prompt, e as ferramentas `propose_*`, que
montam acao e nao leem nada. Faltava o meio: disciplina, turma, aluno, aula,
quiz, banco de questoes e tempo de estudo vivem em tabelas, e nenhuma ferramenta
alcancava. Perguntado "voce consegue ver as questoes?", o modelo respondia que
nao tinha acesso - e depois inventava o que poderia fazer se tivesse.

Tres regras valem para todas as ferramentas daqui:

- **Sao somente leitura.** Nada aqui grava, publica ou apaga. Alterar dado
  continua sendo acao proposta que a interface confirma com o usuario.
- **O dono dos dados nao e argumento.** Cada consulta filtra por
  `require_principal().tutor_id`, que o grafo preencheu com a identidade
  autenticada. O modelo nao tem como escolher de quem ler, nem por engano nem
  por pedido do usuario.
- **A saida tem dois destinos.** `text` e a leitura em portugues que volta para
  o modelo; `items` e a mesma leitura estruturada, que a interface desenha para
  o usuario decidir o que fazer. O modelo nunca precisa redigitar numero.

O envelope e sempre o mesmo (`kind`, `title`, `text`, `total`, `items`,
`truncated`), porque a interface desenha um card so para todos os tipos.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional, Sequence

from langchain.tools import tool
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    AsyncSessionLocal,
    ClassGroupModel,
    DisciplineModel,
    LessonModel,
    LessonPointModel,
    QuestionModel,
    QuizModel,
    StudentAnswerModel,
    StudentModel,
    StudyTimeModel,
)
from shared.toolkit.principal import require_principal

#: Teto de linhas por consulta. O modelo nao precisa do banco inteiro para
#: responder, e catalogo grande demais no prompt piora a resposta - `total` diz
#: quanto existe de verdade, entao ele sabe que ha mais e pode filtrar melhor.
_MAX_ROWS = 25


# --- envelope ----------------------------------------------------------------


def _envelope(
    *,
    kind: str,
    title: str,
    text: str,
    items: list[dict[str, Any]],
    total: int,
) -> dict[str, Any]:
    """Monta a saida padrao das ferramentas de leitura."""
    return {
        "kind": kind,
        "title": title,
        "text": text,
        "total": total,
        "items": items,
        "truncated": total > len(items),
    }


def _empty(kind: str, title: str, text: str) -> dict[str, Any]:
    return _envelope(kind=kind, title=title, text=text, items=[], total=0)


def _date(value: Optional[datetime]) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


async def _count(db: AsyncSession, stmt) -> int:
    """Quantas linhas a consulta alcanca, antes do teto de exibicao."""
    return int(
        (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar()
        or 0
    )


def _lines(items: Sequence[str], *, total: int, shown: int) -> str:
    body = "\n".join(f"- {item}" for item in items)
    if total > shown:
        body += f"\n(mostrando {shown} de {total})"
    return body


# --- entradas ----------------------------------------------------------------


class DisciplineFilter(BaseModel):
    """Filtro opcional por disciplina."""

    discipline: str = Field(
        default="",
        description="Nome ou codigo da disciplina; vazio traz todas.",
    )


class LessonFilter(DisciplineFilter):
    """Filtro de aulas gravadas."""

    class_group: str = Field(
        default="", description="Turma, quando quiser restringir a uma."
    )
    limit: int = Field(
        default=10, ge=1, le=_MAX_ROWS, description="Quantas aulas trazer."
    )


class LessonRef(BaseModel):
    """Referencia a uma aula ja identificada."""

    lesson_id: str = Field(min_length=1, description="Id da aula.")


class QuizFilter(DisciplineFilter):
    """Filtro de quizzes."""

    status: str = Field(
        default="",
        description="Situacao do quiz: draft, open ou closed. Vazio traz todas.",
    )
    limit: int = Field(
        default=10, ge=1, le=_MAX_ROWS, description="Quantos quizzes trazer."
    )


class QuizRef(BaseModel):
    """Referencia a um quiz ja identificado."""

    quiz_id: str = Field(min_length=1, description="Id do quiz.")


class StudyTimeFilter(DisciplineFilter):
    """Filtro do tempo de estudo importado."""

    semester: str = Field(
        default="",
        description="Periodo letivo, como 2026.2; vazio traz todos, separados.",
    )


class BankFilter(DisciplineFilter):
    """Filtro do banco de questoes."""

    search: str = Field(
        default="", description="Texto procurado no enunciado da questao."
    )
    dificuldade: str = Field(
        default="", description="facil, medio ou dificil. Vazio traz todas."
    )
    limit: int = Field(
        default=10, ge=1, le=_MAX_ROWS, description="Quantas questoes trazer."
    )


class StudentFilter(DisciplineFilter):
    """Filtro de alunos."""

    class_group: str = Field(default="", description="Turma do aluno.")
    search: str = Field(default="", description="Parte do nome do aluno.")
    limit: int = Field(
        default=_MAX_ROWS, ge=1, le=_MAX_ROWS, description="Quantos alunos trazer."
    )


# --- disciplinas, turmas e alunos --------------------------------------------


@tool("education_list_disciplines", args_schema=DisciplineFilter)
async def education_list_disciplines(discipline: str = "") -> dict[str, Any]:
    """Lista as disciplinas cadastradas pelo professor, com codigo e semestre."""
    owner = require_principal()
    async with AsyncSessionLocal() as db:
        stmt = select(DisciplineModel).where(DisciplineModel.tutor_id == owner.tutor_id)
        if discipline:
            stmt = stmt.where(
                or_(
                    DisciplineModel.name.ilike(f"%{discipline}%"),
                    DisciplineModel.code.ilike(f"%{discipline}%"),
                )
            )
        total = await _count(db, stmt)
        rows = (
            await db.execute(stmt.order_by(DisciplineModel.name).limit(_MAX_ROWS))
        ).scalars().all()

    if not rows:
        return _empty(
            "disciplines",
            "Disciplinas",
            "Nao ha disciplina cadastrada com esse filtro.",
        )

    items = [
        {
            "id": row.id,
            "codigo": row.code,
            "nome": row.name,
            "semestre": row.semester,
            "ativa": bool(row.active),
        }
        for row in rows
    ]
    text = "Disciplinas cadastradas:\n" + _lines(
        [f"{item['codigo']} {item['nome']} ({item['semestre']})" for item in items],
        total=total,
        shown=len(items),
    )
    return _envelope(
        kind="disciplines",
        title=f"{total} disciplina(s)",
        text=text,
        items=items,
        total=total,
    )


@tool("education_list_classes", args_schema=DisciplineFilter)
async def education_list_classes(discipline: str = "") -> dict[str, Any]:
    """Lista as turmas cadastradas, com codigo, disciplina e semestre."""
    owner = require_principal()
    async with AsyncSessionLocal() as db:
        stmt = select(ClassGroupModel).where(ClassGroupModel.tutor_id == owner.tutor_id)
        if discipline:
            stmt = stmt.where(ClassGroupModel.discipline.ilike(f"%{discipline}%"))
        total = await _count(db, stmt)
        rows = (
            await db.execute(
                stmt.order_by(ClassGroupModel.discipline, ClassGroupModel.code).limit(
                    _MAX_ROWS
                )
            )
        ).scalars().all()

    if not rows:
        return _empty("classes", "Turmas", "Nao ha turma cadastrada com esse filtro.")

    items = [
        {
            "id": row.id,
            "codigo": row.code,
            "nome": row.name,
            "disciplina": row.discipline,
            "semestre": row.semester,
        }
        for row in rows
    ]
    text = "Turmas cadastradas:\n" + _lines(
        [
            f"{item['codigo']} {item['nome']} - {item['disciplina']}"
            for item in items
        ],
        total=total,
        shown=len(items),
    )
    return _envelope(
        kind="classes", title=f"{total} turma(s)", text=text, items=items, total=total
    )


@tool("education_list_students", args_schema=StudentFilter)
async def education_list_students(
    discipline: str = "",
    class_group: str = "",
    search: str = "",
    limit: int = _MAX_ROWS,
) -> dict[str, Any]:
    """Lista alunos cadastrados, por disciplina, turma ou parte do nome."""
    owner = require_principal()
    async with AsyncSessionLocal() as db:
        stmt = select(StudentModel).where(
            StudentModel.tutor_id == owner.tutor_id,
            StudentModel.active.is_(True),
        )
        if discipline:
            stmt = stmt.where(StudentModel.discipline.ilike(f"%{discipline}%"))
        if class_group:
            stmt = stmt.where(StudentModel.class_group.ilike(f"%{class_group}%"))
        if search:
            stmt = stmt.where(StudentModel.name.ilike(f"%{search}%"))
        total = await _count(db, stmt)
        rows = (
            await db.execute(
                stmt.order_by(StudentModel.name).limit(min(limit, _MAX_ROWS))
            )
        ).scalars().all()

    if not rows:
        return _empty("students", "Alunos", "Nao ha aluno com esse filtro.")

    items = [
        {
            "id": row.id,
            "nome": row.name,
            "matricula": row.external_id or "",
            "turma": row.class_group,
            "disciplina": row.discipline,
        }
        for row in rows
    ]
    text = f"{total} aluno(s) encontrados:\n" + _lines(
        [f"{item['nome']} - {item['turma']}" for item in items],
        total=total,
        shown=len(items),
    )
    return _envelope(
        kind="students", title=f"{total} aluno(s)", text=text, items=items, total=total
    )


# --- aulas -------------------------------------------------------------------


@tool("education_list_lessons", args_schema=LessonFilter)
async def education_list_lessons(
    discipline: str = "",
    class_group: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """Lista as aulas gravadas, da mais recente para a mais antiga."""
    owner = require_principal()
    async with AsyncSessionLocal() as db:
        stmt = select(LessonModel).where(LessonModel.tutor_id == owner.tutor_id)
        if discipline:
            stmt = stmt.where(LessonModel.discipline.ilike(f"%{discipline}%"))
        if class_group:
            stmt = stmt.where(LessonModel.class_group.ilike(f"%{class_group}%"))
        total = await _count(db, stmt)
        rows = (
            await db.execute(
                stmt.order_by(LessonModel.started_at.desc()).limit(
                    min(limit, _MAX_ROWS)
                )
            )
        ).scalars().all()

    if not rows:
        return _empty("lessons", "Aulas", "Nao ha aula gravada com esse filtro.")

    items = [
        {
            "id": row.id,
            "titulo": row.title,
            "disciplina": row.discipline,
            "turma": row.class_group,
            "data": _date(row.started_at),
            "status": row.status,
            "tem_resumo": bool(row.summary),
            "trechos": row.segment_count,
        }
        for row in rows
    ]
    text = f"{total} aula(s) gravadas:\n" + _lines(
        [
            f"{item['data']} - {item['disciplina']} - "
            f"{item['titulo'] or 'sem titulo'} ({item['trechos']} trechos)"
            for item in items
        ],
        total=total,
        shown=len(items),
    )
    return _envelope(
        kind="lessons", title=f"{total} aula(s)", text=text, items=items, total=total
    )


@tool("education_get_lesson", args_schema=LessonRef)
async def education_get_lesson(lesson_id: str) -> dict[str, Any]:
    """Detalha uma aula: disciplina, data, resumo e pontos registrados."""
    owner = require_principal()
    async with AsyncSessionLocal() as db:
        lesson = await db.get(LessonModel, lesson_id)
        if lesson is None or lesson.tutor_id != owner.tutor_id:
            return _empty("lesson", "Aula", "Aula nao encontrada nesta conta.")
        points = (
            await db.execute(
                select(LessonPointModel)
                .where(LessonPointModel.lesson_id == lesson_id)
                .order_by(LessonPointModel.created_at)
            )
        ).scalars().all()

    items = [
        {
            "aluno": point.student_name,
            "pontos": point.points,
            "motivo": point.reason or "",
        }
        for point in points
    ]
    resumo = lesson.summary or "(sem resumo gerado)"
    text = (
        f"Aula de {lesson.discipline} em {_date(lesson.started_at)}"
        f" - {lesson.title or 'sem titulo'} (turma {lesson.class_group or '-'}).\n"
        f"Situacao: {lesson.status}. Trechos transcritos: {lesson.segment_count}.\n"
        f"Resumo: {resumo}"
    )
    if items:
        text += f"\nPontos registrados: {len(items)}."
    return _envelope(
        kind="lesson",
        title=f"{lesson.discipline} - {_date(lesson.started_at)}",
        text=text,
        items=items,
        total=len(items),
    )


# --- quiz e banco de questoes ------------------------------------------------


def _options(question: QuestionModel) -> list[dict[str, Any]]:
    if not question.opcoes:
        return []
    try:
        decoded = json.loads(question.opcoes)
    except (TypeError, ValueError):
        return []
    return decoded if isinstance(decoded, list) else []


@tool("education_list_quizzes", args_schema=QuizFilter)
async def education_list_quizzes(
    discipline: str = "",
    status: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """Lista os quizzes criados, com situacao e numero de questoes."""
    owner = require_principal()
    async with AsyncSessionLocal() as db:
        stmt = select(QuizModel, LessonModel).join(
            LessonModel, LessonModel.id == QuizModel.lesson_id, isouter=True
        ).where(QuizModel.tutor_id == owner.tutor_id)
        if status:
            stmt = stmt.where(QuizModel.status == status)
        if discipline:
            stmt = stmt.where(LessonModel.discipline.ilike(f"%{discipline}%"))
        total = await _count(db, stmt)
        rows = (
            await db.execute(
                stmt.order_by(QuizModel.created_at.desc()).limit(min(limit, _MAX_ROWS))
            )
        ).all()

    if not rows:
        return _empty("quizzes", "Quizzes", "Nao ha quiz com esse filtro.")

    items = [
        {
            "id": quiz.id,
            "titulo": quiz.titulo,
            "situacao": quiz.status,
            "fase": quiz.live_phase,
            "questoes": quiz.total_questoes,
            "disciplina": lesson.discipline if lesson else "",
            "criado_em": _date(quiz.created_at),
        }
        for quiz, lesson in rows
    ]
    text = f"{total} quiz(zes):\n" + _lines(
        [
            f"{item['titulo']} - {item['questoes']} questoes "
            f"({item['situacao']}) - {item['disciplina']}"
            for item in items
        ],
        total=total,
        shown=len(items),
    )
    return _envelope(
        kind="quizzes", title=f"{total} quiz(zes)", text=text, items=items, total=total
    )


@tool("education_get_quiz", args_schema=QuizRef)
async def education_get_quiz(quiz_id: str) -> dict[str, Any]:
    """Traz um quiz com o enunciado, as alternativas e o gabarito de cada questao."""
    owner = require_principal()
    async with AsyncSessionLocal() as db:
        quiz = await db.get(QuizModel, quiz_id)
        if quiz is None or quiz.tutor_id != owner.tutor_id:
            return _empty("quiz", "Quiz", "Quiz nao encontrado nesta conta.")
        questions = (
            await db.execute(
                select(QuestionModel)
                .where(QuestionModel.quiz_id == quiz_id)
                .order_by(QuestionModel.created_at, QuestionModel.id)
            )
        ).scalars().all()

    items = [
        {
            "id": q.id,
            "numero": index + 1,
            "tipo": q.tipo,
            "dificuldade": q.dificuldade,
            "enunciado": q.enunciado,
            "opcoes": _options(q),
            "resposta_correta": q.resposta_correta or "",
            "justificativa": q.justificativa or "",
        }
        for index, q in enumerate(questions)
    ]
    corpo = "\n".join(
        f"{item['numero']}. [{item['dificuldade']}] {item['enunciado']} "
        f"(gabarito: {item['resposta_correta'] or 'nao informado'})"
        for item in items
    )
    text = (
        f"Quiz \"{quiz.titulo}\" ({quiz.status}), {len(items)} questao(oes):\n{corpo}"
        if items
        else f"Quiz \"{quiz.titulo}\" ainda nao tem questoes."
    )
    return _envelope(
        kind="quiz", title=quiz.titulo, text=text, items=items, total=len(items)
    )


@tool("education_search_question_bank", args_schema=BankFilter)
async def education_search_question_bank(
    discipline: str = "",
    search: str = "",
    dificuldade: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """Procura questoes no banco, por disciplina, dificuldade ou texto do enunciado.

    Traz so as questoes originais: copia feita para montar outro quiz nao conta
    como questao nova do banco.
    """
    owner = require_principal()
    async with AsyncSessionLocal() as db:
        stmt = (
            select(QuestionModel, QuizModel, LessonModel)
            .join(QuizModel, QuizModel.id == QuestionModel.quiz_id)
            .join(LessonModel, LessonModel.id == QuizModel.lesson_id, isouter=True)
            .where(
                QuizModel.tutor_id == owner.tutor_id,
                QuestionModel.arquivada.is_(False),
                QuestionModel.origem_id.is_(None),
            )
        )
        if discipline:
            stmt = stmt.where(LessonModel.discipline.ilike(f"%{discipline}%"))
        if dificuldade:
            stmt = stmt.where(QuestionModel.dificuldade == dificuldade)
        if search:
            stmt = stmt.where(QuestionModel.enunciado.ilike(f"%{search}%"))
        total = await _count(db, stmt)
        rows = (
            await db.execute(
                stmt.order_by(QuestionModel.created_at.desc()).limit(
                    min(limit, _MAX_ROWS)
                )
            )
        ).all()

    if not rows:
        return _empty(
            "question_bank",
            "Banco de questoes",
            "Nao ha questao no banco com esse filtro.",
        )

    items = [
        {
            "id": question.id,
            "enunciado": question.enunciado,
            "tipo": question.tipo,
            "dificuldade": question.dificuldade,
            "opcoes": _options(question),
            "resposta_correta": question.resposta_correta or "",
            "disciplina": lesson.discipline if lesson else "",
            "quiz_id": quiz.id,
            "quiz": quiz.titulo,
        }
        for question, quiz, lesson in rows
    ]
    text = f"{total} questao(oes) no banco:\n" + _lines(
        [
            f"[{item['dificuldade']}] {item['enunciado']} "
            f"(de \"{item['quiz']}\")"
            for item in items
        ],
        total=total,
        shown=len(items),
    )
    return _envelope(
        kind="question_bank",
        title=f"{total} questao(oes)",
        text=text,
        items=items,
        total=total,
    )


@tool("education_get_quiz_results", args_schema=QuizRef)
async def education_get_quiz_results(quiz_id: str) -> dict[str, Any]:
    """Traz o desempenho de um quiz aplicado: ranking dos alunos e acertos."""
    owner = require_principal()
    async with AsyncSessionLocal() as db:
        quiz = await db.get(QuizModel, quiz_id)
        if quiz is None or quiz.tutor_id != owner.tutor_id:
            return _empty("quiz_results", "Resultado", "Quiz nao encontrado.")
        answers = (
            await db.execute(
                select(StudentAnswerModel).where(
                    StudentAnswerModel.question_id.in_(
                        select(QuestionModel.id).where(
                            QuestionModel.quiz_id == quiz_id
                        )
                    )
                )
            )
        ).scalars().all()

    if not answers:
        return _empty(
            "quiz_results",
            f"Resultado de {quiz.titulo}",
            f"O quiz \"{quiz.titulo}\" ainda nao recebeu respostas.",
        )

    grouped: dict[str, dict[str, Any]] = {}
    for answer in answers:
        key = answer.student_id or "anon"
        row = grouped.setdefault(
            key,
            {
                "aluno": answer.student_name or "Aluno",
                "pontos": 0,
                "acertos": 0,
                "respostas": 0,
            },
        )
        row["aluno"] = answer.student_name or row["aluno"]
        row["pontos"] += int(answer.pontuacao or 0)
        row["acertos"] += 1 if answer.correta is True else 0
        row["respostas"] += 1

    items = sorted(
        grouped.values(),
        key=lambda item: (-item["pontos"], -item["acertos"], item["aluno"]),
    )
    for position, item in enumerate(items, start=1):
        item["posicao"] = position

    corretas = sum(1 for answer in answers if answer.correta is True)
    text = (
        f"Quiz \"{quiz.titulo}\": {len(items)} participante(s), "
        f"{len(answers)} resposta(s), {corretas} acerto(s).\n"
        + _lines(
            [
                f"{item['posicao']}. {item['aluno']} - {item['pontos']} pts "
                f"({item['acertos']}/{item['respostas']})"
                for item in items[:_MAX_ROWS]
            ],
            total=len(items),
            shown=min(len(items), _MAX_ROWS),
        )
    )
    return _envelope(
        kind="quiz_results",
        title=f"Resultado de {quiz.titulo}",
        text=text,
        items=items[:_MAX_ROWS],
        total=len(items),
    )


# --- tempo de estudo ---------------------------------------------------------


@tool("education_study_time_summary", args_schema=StudyTimeFilter)
async def education_study_time_summary(
    discipline: str = "",
    semester: str = "",
) -> dict[str, Any]:
    """Resume o tempo de estudo importado, por periodo letivo e turma.

    O periodo entra no agrupamento, e nao so no filtro: a mesma turma importada
    em dois semestres sao duas linhas. Somadas, o total diria que a turma
    estudou o dobro do que estudou em qualquer um dos dois.
    """
    owner = require_principal()
    async with AsyncSessionLocal() as db:
        stmt = select(
            StudyTimeModel.semester,
            StudyTimeModel.group_sequence,
            StudyTimeModel.discipline_code,
            func.count(StudyTimeModel.id),
            func.sum(StudyTimeModel.minutes),
        ).where(StudyTimeModel.tutor_id == owner.tutor_id)
        if discipline:
            stmt = stmt.where(StudyTimeModel.discipline_code.ilike(f"%{discipline}%"))
        if semester:
            stmt = stmt.where(StudyTimeModel.semester == semester)
        rows = (
            await db.execute(
                stmt.group_by(
                    StudyTimeModel.semester,
                    StudyTimeModel.group_sequence,
                    StudyTimeModel.discipline_code,
                ).order_by(
                    StudyTimeModel.semester.desc(),
                    func.sum(StudyTimeModel.minutes).desc(),
                )
            )
        ).all()

    if not rows:
        return _empty(
            "study_time",
            "Tempo de estudo",
            "Nao ha tempo de estudo importado com esse filtro.",
        )

    items = [
        {
            "periodo": periodo or "(sem periodo)",
            "turma": turma or "(sem turma)",
            "disciplina": codigo,
            "alunos": int(alunos or 0),
            "minutos": int(minutos or 0),
            "horas": round(int(minutos or 0) / 60, 1),
        }
        for periodo, turma, codigo, alunos, minutos in rows
    ]
    # Um total por periodo, e nenhum total geral: somar semestres seria dizer
    # que a turma estudou a soma de dois semestres que nunca correram juntos.
    por_periodo: dict[str, int] = {}
    for item in items:
        por_periodo[item["periodo"]] = por_periodo.get(item["periodo"], 0) + item["minutos"]
    cabecalho = "; ".join(
        f"{periodo}: {round(minutos / 60, 1)}h" for periodo, minutos in por_periodo.items()
    )
    text = (
        f"Tempo de estudo importado por periodo — {cabecalho}. "
        f"{len(items)} turma(s) no total.\n"
        + _lines(
            [
                f"{item['periodo']} · {item['turma']} ({item['disciplina']}): "
                f"{item['horas']}h em {item['alunos']} registro(s)"
                for item in items[:_MAX_ROWS]
            ],
            total=len(items),
            shown=min(len(items), _MAX_ROWS),
        )
    )
    return _envelope(
        kind="study_time",
        title="Tempo de estudo",
        text=text,
        items=items[:_MAX_ROWS],
        total=len(items),
    )


EDUCATION_TOOLS: tuple[BaseTool, ...] = (
    education_list_disciplines,
    education_list_classes,
    education_list_students,
    education_list_lessons,
    education_get_lesson,
    education_list_quizzes,
    education_get_quiz,
    education_search_question_bank,
    education_get_quiz_results,
    education_study_time_summary,
)
"""Ferramentas de leitura publicadas no catalogo."""
