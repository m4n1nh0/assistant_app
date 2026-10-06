"""Material das apresentacoes enviado pelos alunos por um link publico.

O professor cria um link por disciplina (e, se quiser, por turmas). O aluno abre,
digita a matricula, o sistema acha o grupo dele - pela mesma regra do quiz em grupo,
inclusive nas turmas da aula reunida - e o arquivo (PDF, PPTX ou DOCX) vira um
`MaterialModel` ligado ao grupo, com o texto ja extraido. Esse texto, junto com a
gravacao da apresentacao do grupo, e o que alimenta o quiz rapido.

So o texto extraido e guardado, nao o arquivo original: e o que o material didatico do
professor ja faz, e o disco do servidor e descartado a cada deploy.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    DisciplineModel,
    LessonModel,
    LessonSegmentModel,
    MaterialModel,
    MaterialSubmissionLinkModel,
    ProjectGroupMemberModel,
    ProjectGroupModel,
    QuizGroupConfigModel,
)
from . import material_service
from . import project_group_service as project_groups
from . import quiz_group_service as quiz_groups

#: Formatos que o aluno pode enviar. O extrator entende mais (imagem com OCR, texto),
#: mas OCR de foto enviada por qualquer celular pesa no servidor sem ganho aqui.
STUDENT_EXTENSIONS: tuple[str, ...] = (".pdf", ".pptx", ".docx")

#: Teto do arquivo. Apresentacao com imagens passa de 10 MB com facilidade.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

DEFAULT_MAX_FILES_PER_GROUP = 5
MAX_FILES_PER_GROUP_LIMIT = 20

KIND_SUBMISSION = "link"


class SubmissionError(Exception):
    """O envio nao pode ser aceito. `code` diz por que; `message` e para o aluno."""

    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def new_token() -> str:
    """Parte secreta da URL: curta para o QR Code, impossivel de adivinhar."""
    return secrets.token_urlsafe(12)


def _now() -> datetime:
    # As colunas de data chegam sem fuso do MySQL; compara-se sempre em UTC "ingenuo".
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def link_class_ids(link: MaterialSubmissionLinkModel) -> list[str]:
    return project_groups.as_class_list((link.class_ids or "").split(","))


def link_state(link: MaterialSubmissionLinkModel, now: Optional[datetime] = None) -> str:
    """`open`, `closed` (professor fechou) ou `expired` (o prazo passou)."""
    if not link.active:
        return "closed"
    deadline = _naive(link.closes_at)
    if deadline is not None and deadline <= (_naive(now) or _now()):
        return "expired"
    return "open"


async def get_link_by_token(db: AsyncSession, token: str) -> Optional[MaterialSubmissionLinkModel]:
    token = (token or "").strip()
    if not token:
        return None
    return (await db.execute(select(MaterialSubmissionLinkModel).where(
        MaterialSubmissionLinkModel.token == token))).scalar_one_or_none()


def _config_for(link: MaterialSubmissionLinkModel) -> QuizGroupConfigModel:
    """Config transitoria: reaproveita a busca de grupo por matricula do quiz em grupo."""
    turmas = link_class_ids(link)
    return QuizGroupConfigModel(
        quiz_id="", tutor_id=link.tutor_id, discipline_id=link.discipline_id,
        semester=link.semester or "", class_id=turmas[0] if turmas else None,
        class_ids=",".join(turmas), seed="",
    )


@dataclass(frozen=True)
class Submitter:
    """Quem esta enviando e o grupo dele."""

    group_id: str
    group_name: str
    member_id: str
    member_name: str
    student_id: Optional[str]
    members: tuple[str, ...]


async def identify(db: AsyncSession, link: MaterialSubmissionLinkModel,
                   enrollment: str) -> Submitter:
    """Matricula -> grupo, dentro das turmas do link."""
    try:
        resolved = await quiz_groups.resolve_enrollment(db, _config_for(link), enrollment)
    except quiz_groups.EnrollmentError as exc:
        messages = {
            "invalid": "Digite a sua matrícula.",
            "unknown": "Matrícula não encontrada. Confira os números ou fale com o professor.",
            "no_group": "Essa matrícula não está em nenhum grupo desta disciplina. "
                        "Fale com o professor.",
        }
        raise SubmissionError(
            exc.code, messages.get(exc.code, "Não consegui identificar a matrícula."), 404
        ) from exc
    member = await db.get(ProjectGroupMemberModel, resolved.member_id)
    members = (await db.execute(
        select(ProjectGroupMemberModel.name)
        .where(ProjectGroupMemberModel.group_id == resolved.group_id)
        .order_by(ProjectGroupMemberModel.position)
    )).scalars().all()
    return Submitter(
        group_id=resolved.group_id, group_name=resolved.group_name,
        member_id=resolved.member_id, member_name=resolved.member_name,
        student_id=member.student_id if member else None, members=tuple(members),
    )


async def group_materials(db: AsyncSession, group_id: str,
                          link_id: Optional[str] = None) -> list[MaterialModel]:
    query = select(MaterialModel).where(MaterialModel.group_id == group_id)
    if link_id:
        query = query.where(MaterialModel.link_id == link_id)
    return list((await db.execute(query.order_by(MaterialModel.created_at))).scalars().all())


def validate_filename(filename: str) -> str:
    name = (filename or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    if not name:
        raise SubmissionError("file", "Escolha um arquivo para enviar.")
    extension = material_service.extension_of(name)
    if extension == ".ppt":
        raise SubmissionError(
            "format",
            "Arquivo .ppt (PowerPoint antigo) não é lido. No PowerPoint, use "
            "Arquivo > Salvar como e escolha .pptx ou PDF.",
        )
    if extension not in STUDENT_EXTENSIONS:
        raise SubmissionError(
            "format", "Envie o material em PDF, PPTX ou DOCX (" + ", ".join(STUDENT_EXTENSIONS) + ")."
        )
    return name[:255]


async def submit(
    db: AsyncSession,
    link: MaterialSubmissionLinkModel,
    *,
    enrollment: str,
    filename: str,
    data: bytes,
    title: str = "",
) -> tuple[MaterialModel, Submitter, bool]:
    """Recebe o arquivo de um grupo. Devolve o material, quem enviou e se substituiu um."""
    state = link_state(link)
    if state != "open":
        raise SubmissionError(
            state,
            "O professor encerrou o recebimento deste material." if state == "closed"
            else "O prazo para enviar o material terminou.",
            409,
        )
    name = validate_filename(filename)
    if not data:
        raise SubmissionError("file", "O arquivo veio vazio. Escolha de novo.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise SubmissionError(
            "size", f"Arquivo acima de {MAX_UPLOAD_BYTES // (1024 * 1024)} MB. "
                    "Comprima as imagens ou envie em PDF.", 413)

    submitter = await identify(db, link, enrollment)

    try:
        extracted = await material_service.extract(data, name)
    except material_service.MaterialError as exc:
        if str(exc) == material_service.EMPTY_HINT:
            raise SubmissionError(
                "empty",
                "Não achei texto suficiente neste arquivo. Se os slides são imagens, "
                "exporte em PDF com texto ou envie o .pptx original.",
            ) from exc
        raise SubmissionError("extract", str(exc)) from exc

    existing = await group_materials(db, submitter.group_id, link.id)
    same_name = next((item for item in existing
                      if (item.filename or "").casefold() == name.casefold()), None)
    limit = max(1, min(int(link.max_files_per_group or DEFAULT_MAX_FILES_PER_GROUP),
                       MAX_FILES_PER_GROUP_LIMIT))
    if same_name is None and len(existing) >= limit:
        raise SubmissionError(
            "limit",
            f"O grupo já enviou {limit} arquivos. Apague um para enviar outro.",
            409,
        )

    discipline = await db.get(DisciplineModel, link.discipline_id)
    label = " - ".join(part for part in (
        (discipline.code or "").strip() if discipline else "",
        (discipline.name or "").strip() if discipline else "") if part)
    chosen_title = " ".join((title or "").split())[:200] or extracted.title or name.rsplit(".", 1)[0]

    material = same_name or MaterialModel(tutor_id=link.tutor_id)
    material.discipline_id = link.discipline_id
    material.discipline = label
    material.title = chosen_title[:255]
    material.filename = name
    material.source_type = extracted.source_type
    material.page_count = extracted.page_count
    material.char_count = extracted.char_count
    material.truncated = extracted.truncated
    material.content = extracted.text
    material.group_id = submitter.group_id
    material.student_id = submitter.student_id
    material.uploader_name = submitter.member_name[:180]
    material.link_id = link.id
    if same_name is None:
        db.add(material)
    else:
        material.created_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(material)
    return material, submitter, same_name is not None


async def remove_group_material(db: AsyncSession, link: MaterialSubmissionLinkModel, *,
                                enrollment: str, material_id: str) -> None:
    """O aluno tira um arquivo enviado por engano. So os do proprio grupo, pelo mesmo link."""
    if link_state(link) != "open":
        raise SubmissionError("closed", "O recebimento deste material já foi encerrado.", 409)
    submitter = await identify(db, link, enrollment)
    material = await db.get(MaterialModel, material_id)
    if (material is None or material.group_id != submitter.group_id
            or material.link_id != link.id):
        raise SubmissionError("not_found", "Arquivo não encontrado neste grupo.", 404)
    await db.delete(material)
    await db.commit()


# --- visao do professor -----------------------------------------------------------


async def presentations_overview(db: AsyncSession, tutor_id: str, discipline_id: str,
                                 class_id: Optional[str] = None) -> list[dict]:
    """Cada grupo com o material enviado e as gravacoes da apresentacao dele.

    E o que diz ao professor se o grupo ja mandou os slides e se a apresentacao foi
    gravada, e quais fontes o quiz rapido pode usar.
    """
    query = select(ProjectGroupModel).where(
        ProjectGroupModel.tutor_id == tutor_id,
        ProjectGroupModel.discipline_id == discipline_id,
    )
    if class_id:
        query = query.where(project_groups.group_in_class_clause(class_id))
    groups = list((await db.execute(query.order_by(ProjectGroupModel.name))).scalars().all())
    if not groups:
        return []
    ids = [group.id for group in groups]
    turmas = await project_groups.class_ids_of_groups(db, groups)

    materials = (await db.execute(
        select(MaterialModel).where(MaterialModel.tutor_id == tutor_id,
                                    MaterialModel.group_id.in_(ids))
        .order_by(MaterialModel.created_at))).scalars().all()
    lessons = (await db.execute(
        select(LessonModel).where(LessonModel.tutor_id == tutor_id,
                                  LessonModel.kind == "apresentacao",
                                  LessonModel.group_id.in_(ids))
        .order_by(LessonModel.started_at))).scalars().all()
    counts = {}
    if lessons:
        rows = (await db.execute(
            select(LessonSegmentModel.lesson_id, func.count())
            .where(LessonSegmentModel.lesson_id.in_([item.id for item in lessons]))
            .group_by(LessonSegmentModel.lesson_id))).all()
        counts = {lesson_id: total for lesson_id, total in rows}

    by_material: dict[str, list[MaterialModel]] = {}
    for item in materials:
        by_material.setdefault(item.group_id, []).append(item)
    by_lesson: dict[str, list[LessonModel]] = {}
    for item in lessons:
        by_lesson.setdefault(item.group_id, []).append(item)

    return [
        dict(
            group_id=group.id,
            group_name=group.name,
            class_ids=turmas.get(group.id, []),
            materials=[
                dict(id=item.id, title=item.title, filename=item.filename,
                     source_type=item.source_type, page_count=item.page_count or 0,
                     char_count=item.char_count or 0, truncated=bool(item.truncated),
                     uploader_name=item.uploader_name or "",
                     from_link=bool(item.link_id), created_at=item.created_at)
                for item in by_material.get(group.id, [])],
            recordings=[
                dict(id=item.id, title=item.title, status=item.status,
                     started_at=item.started_at, segments=counts.get(item.id, 0),
                     has_summary=bool((item.summary or "").strip()))
                for item in by_lesson.get(group.id, [])],
        )
        for group in groups
    ]


def quiz_source_gaps(overview: dict) -> list[str]:
    """O que falta para o quiz rapido deste grupo, em palavras para o professor."""
    gaps = []
    if not overview["materials"]:
        gaps.append("material")
    if not any(item["segments"] > 0 for item in overview["recordings"]):
        gaps.append("gravação")
    return gaps


async def attach_material_to_group(db: AsyncSession, material: MaterialModel,
                                   group: Optional[ProjectGroupModel]) -> None:
    """Liga (ou solta, com `None`) um material ja existente ao grupo.

    Para o slide que o professor recebeu por e-mail ou pelo chat: entra pela tela de
    Material e depois e ligado ao grupo, e passa a valer como o enviado pelo link.
    """
    if group is not None and material.discipline_id and group.discipline_id != material.discipline_id:
        raise SubmissionError("discipline", "O material e o grupo são de disciplinas diferentes.")
    material.group_id = group.id if group else None
    await db.commit()

