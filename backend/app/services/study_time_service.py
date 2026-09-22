"""Leitura e conciliacao de tempo de estudo exportado em XLSX."""

from __future__ import annotations

from io import BytesIO
from collections import Counter

from openpyxl import load_workbook
from sqlalchemy import select

from ..core.database import DisciplineModel, StudentModel, StudyTimeModel

HEADERS = (
    "CURSO", "COD_DISCIPLINA", "NUM_SEQ_TURMA", "MATRICULA",
    "ANO_ENTRADA", "TEMPO DE ESTUDO (MINUTOS)",
)


async def owned_discipline_scope(db, tutor_id: str) -> set[str]:
    """Codigos de disciplina cadastrados para este professor."""
    disciplines = (await db.execute(select(DisciplineModel).where(
        DisciplineModel.tutor_id == tutor_id
    ))).scalars().all()
    return {item.code.strip().upper()
            for item in disciplines if item.code and item.code.strip()}


def belongs_to_scope(code: str, scope: set[str]) -> bool:
    return code.strip().upper() in scope


async def purge_outside_scope(db, tutor_id: str, scope: set[str]) -> int:
    """Remove registros que a importacao antiga aceitou sem conferir disciplina."""
    existing = (await db.execute(select(StudyTimeModel).where(
        StudyTimeModel.tutor_id == tutor_id
    ))).scalars().all()
    removed = 0
    for item in existing:
        if not belongs_to_scope(item.discipline_code, scope):
            await db.delete(item)
            removed += 1
    if removed:
        await db.commit()
    return removed


def parse_study_time_xlsx(content: bytes) -> tuple[list[dict], list[dict]]:
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    sheet = workbook.active
    iterator = sheet.values
    header = next(iterator, None)
    if not header:
        raise ValueError("Planilha vazia")
    columns = {str(value or "").strip().upper(): index for index, value in enumerate(header)}
    missing = [name for name in HEADERS if name not in columns]
    if missing:
        raise ValueError("Colunas ausentes: " + ", ".join(missing))
    result = []
    blank_rows: list[dict] = []
    seen = set()
    for line, cells in enumerate(iterator, start=2):
        def cell(name):
            index = columns[name]
            return cells[index] if index < len(cells) else None
        enrollment = str(cell("MATRICULA") or "").strip()
        if not enrollment:
            continue
        code = str(cell("COD_DISCIPLINA") or "").strip().upper()
        group = str(cell("NUM_SEQ_TURMA") or "").strip()
        semester = str(cell("ANO_ENTRADA") or "").strip()
        course = str(cell("CURSO") or "").strip()
        raw_minutes = cell("TEMPO DE ESTUDO (MINUTOS)")
        if not all((code, group, semester, course)):
            raise ValueError(f"Linha {line}: identificacao incompleta")
        if raw_minutes is None or str(raw_minutes).strip() == "":
            blank_rows.append(dict(discipline_code=code, semester=semester))
            continue
        try:
            minutes = int(raw_minutes)
            if minutes < 0 or float(raw_minutes) != minutes:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError(f"Linha {line}: minutos invalidos") from None
        key = (semester, code, group, enrollment)
        if key in seen:
            raise ValueError(f"Linha {line}: registro duplicado no arquivo")
        seen.add(key)
        result.append(dict(enrollment=enrollment, discipline_code=code,
                           group_sequence=group, semester=semester,
                           course=course, minutes=minutes))
    if not result:
        raise ValueError("Nenhum registro de tempo de estudo encontrado")
    return result, blank_rows


def match_study_student(row: dict, by_enrollment: dict[str, list[StudentModel]]) -> StudentModel | None:
    matches = by_enrollment.get(row["enrollment"], [])
    if len(matches) > 1:
        matches = [student for student in matches
                   if student.class_group == row["group_sequence"]]
    return matches[0] if len(matches) == 1 else None


def unmatched_reason(row: dict, by_enrollment: dict[str, list[StudentModel]]) -> str:
    """Por que esta linha nao achou aluno - a conta tem dois motivos.

    "Nao cadastrada" se resolve cadastrando o aluno; "ambigua" nao, e cadastrar
    de novo so pioraria. Contar as duas juntas mandava o professor pelo caminho
    errado na metade dos casos.
    """
    matches = by_enrollment.get(row["enrollment"], [])
    if not matches:
        return "nao_cadastrada"
    return "ambigua"


async def student_enrollment_index(db, tutor_id: str) -> dict[str, list[StudentModel]]:
    students = (await db.execute(select(StudentModel).where(
        StudentModel.tutor_id == tutor_id
    ))).scalars().all()
    by_enrollment: dict[str, list[StudentModel]] = {}
    for student in students:
        if student.external_id:
            by_enrollment.setdefault(student.external_id.strip(), []).append(student)
    return by_enrollment


async def preview_study_times(db, tutor_id: str, rows: list[dict]) -> dict:
    by_enrollment = await student_enrollment_index(db, tutor_id)
    existing = (await db.execute(select(StudyTimeModel).where(
        StudyTimeModel.tutor_id == tutor_id
    ))).scalars().all()
    keys = {(item.semester, item.discipline_code, item.group_sequence,
             item.enrollment) for item in existing}
    matched = [row for row in rows if match_study_student(row, by_enrollment)]
    existing_by_key = {(item.semester, item.discipline_code, item.group_sequence,
                        item.enrollment): item for item in existing}
    existing_without_student = sum(
        (row["semester"], row["discipline_code"], row["group_sequence"],
         row["enrollment"]) in existing_by_key
        for row in rows if match_study_student(row, by_enrollment) is None)
    return dict(
        with_registered_student=len(matched),
        without_registered_student=len(rows) - len(matched),
        existing_rows_removed_by_default=existing_without_student,
        new=sum((row["semester"], row["discipline_code"],
                 row["group_sequence"], row["enrollment"]) not in keys for row in rows),
        corrections=sum((row["semester"], row["discipline_code"],
                         row["group_sequence"], row["enrollment"]) in keys for row in rows),
        new_with_student=sum((row["semester"], row["discipline_code"],
                              row["group_sequence"], row["enrollment"]) not in keys
                             for row in matched),
        corrections_with_student=sum((row["semester"], row["discipline_code"],
                                      row["group_sequence"], row["enrollment"]) in keys
                                     for row in matched),
        by_period=dict(sorted(Counter(row["semester"] for row in rows).items())),
        by_discipline=dict(sorted(Counter(row["discipline_code"] for row in rows).items())),
        group_mapping=await _group_mapping(db, tutor_id, rows, by_enrollment),
        unmatched=_unmatched_rows(rows, by_enrollment),
        students_without_class=await _students_without_class(
            db, tutor_id, rows, by_enrollment
        ),
    )


#: Teto da lista nominal. Uma planilha pode vir com o semestre inteiro fora do
#: cadastro, e despejar centenas de matriculas num dialogo de conferencia nao
#: ajuda ninguem a decidir. O total exato continua no contador.
_MAX_LISTED = 25


def _unmatched_rows(
    rows: list[dict],
    by_enrollment: dict[str, list[StudentModel]],
) -> list[dict]:
    """As matriculas que nao acharam aluno, com o que a planilha sabe delas.

    Ate aqui a conferencia dizia quantas linhas ficariam sem aluno, e nao
    *quais*. Para agir - cadastrar o aluno, corrigir a matricula - o professor
    precisava abrir a planilha e cruzar na mao. A planilha nao tem coluna de
    nome, entao o que da para mostrar e matricula, curso, disciplina, turma e
    minutos: o bastante para achar a pessoa no sistema da instituicao.
    """
    listadas: dict[str, dict] = {}
    for row in rows:
        if match_study_student(row, by_enrollment) is not None:
            continue
        item = listadas.get(row["enrollment"])
        if item is None:
            if len(listadas) >= _MAX_LISTED:
                continue
            listadas[row["enrollment"]] = dict(
                enrollment=row["enrollment"],
                course=row.get("course", ""),
                reason=unmatched_reason(row, by_enrollment),
                disciplines=[row["discipline_code"]],
                group_sequences=[row["group_sequence"]],
                rows=1,
                minutes=int(row.get("minutes") or 0),
            )
            continue
        # Mesma matricula em mais de uma disciplina e uma pessoa so, e nao duas
        # pendencias: cadastrar o aluno resolve as duas linhas de uma vez.
        item["rows"] += 1
        item["minutes"] += int(row.get("minutes") or 0)
        if row["discipline_code"] not in item["disciplines"]:
            item["disciplines"].append(row["discipline_code"])
        if row["group_sequence"] not in item["group_sequences"]:
            item["group_sequences"].append(row["group_sequence"])
    return sorted(listadas.values(), key=lambda item: item["enrollment"])


async def _students_without_class(
    db, tutor_id: str, rows: list[dict],
    by_enrollment: dict[str, list[StudentModel]],
) -> list[dict]:
    """Alunos que a matricula achou, mas que estao sem turma no cadastro.

    E outra pendencia, com outra correcao: aqui o aluno existe e tem nome - o
    que falta e a turma. Sem separar, "sem turma" e "sem aluno" caiam na mesma
    linha do dialogo e sugeriam cadastrar quem ja estava cadastrado.
    """
    from ..core.database import ClassGroupModel

    turmas = {
        item.id
        for item in (await db.execute(select(ClassGroupModel).where(
            ClassGroupModel.tutor_id == tutor_id
        ))).scalars().all()
    }

    pendentes: dict[str, dict] = {}
    for row in rows:
        aluno = match_study_student(row, by_enrollment)
        if aluno is None or (aluno.class_id and aluno.class_id in turmas):
            continue
        item = pendentes.get(row["enrollment"])
        if item is None:
            if len(pendentes) >= _MAX_LISTED:
                continue
            pendentes[row["enrollment"]] = dict(
                enrollment=row["enrollment"],
                student_id=aluno.id,
                name=aluno.name or "",
                disciplines=[row["discipline_code"]],
                group_sequences=[row["group_sequence"]],
                rows=1,
            )
            continue
        item["rows"] += 1
        if row["discipline_code"] not in item["disciplines"]:
            item["disciplines"].append(row["discipline_code"])
        if row["group_sequence"] not in item["group_sequences"]:
            item["group_sequences"].append(row["group_sequence"])
    return sorted(pendentes.values(), key=lambda item: item["name"] or item["enrollment"])


async def _group_mapping(
    db, tutor_id: str, rows: list[dict],
    by_enrollment: dict[str, list[StudentModel]],
) -> list[dict]:
    """Turma da planilha x turma do cadastro, para conferir antes de gravar.

    A planilha traz a sequencia da instituicao ("15034853"); em sala o professor
    chama a mesma turma de "3001". Sao dois identificadores do mesmo grupo, e
    nada no arquivo diz isso - quem liga os dois e o aluno, pela matricula. Se a
    correspondencia sair torta, e aqui que da para ver antes da importacao.
    """
    from ..core.database import ClassGroupModel

    classes = {
        item.id: item
        for item in (await db.execute(select(ClassGroupModel).where(
            ClassGroupModel.tutor_id == tutor_id
        ))).scalars().all()
    }

    porta_de_entrada: dict[tuple[str, str], Counter] = {}
    total: Counter = Counter()
    for row in rows:
        chave = (row["discipline_code"], row["group_sequence"])
        total[chave] += 1
        aluno = match_study_student(row, by_enrollment)
        destino = porta_de_entrada.setdefault(chave, Counter())
        turma = classes.get(aluno.class_id) if aluno and aluno.class_id else None
        if aluno is None:
            # "Sem aluno" nao e "sem turma": aqui nao ha ninguem a quem dar
            # turma. Contados juntos, o dialogo mandava o professor conferir o
            # vinculo de turma quando o que faltava era o cadastro da pessoa.
            destino["__sem_aluno__"] += 1
        elif turma is None:
            destino["__sem_turma__"] += 1
        else:
            rotulo = " ".join(part for part in (turma.code, turma.name) if part)
            destino[rotulo or turma.id] += 1

    mapeamento = []
    for (disciplina, sequencia), destino in sorted(porta_de_entrada.items()):
        sem_turma = destino.pop("__sem_turma__", 0)
        sem_aluno = destino.pop("__sem_aluno__", 0)
        mapeamento.append(dict(
            discipline_code=disciplina,
            group_sequence=sequencia,
            rows=total[(disciplina, sequencia)],
            classes=[dict(label=rotulo, rows=quantidade)
                     for rotulo, quantidade in destino.most_common()],
            without_class=sem_turma,
            without_student=sem_aluno,
        ))
    return mapeamento


async def remove_unmatched_existing(db, tutor_id: str, rows: list[dict]) -> int:
    """Apaga apenas chaves da planilha que o professor decidiu não guardar."""
    existing = (await db.execute(select(StudyTimeModel).where(
        StudyTimeModel.tutor_id == tutor_id
    ))).scalars().all()
    keys = {(row["semester"], row["discipline_code"], row["group_sequence"],
             row["enrollment"]) for row in rows}
    removed = 0
    for item in existing:
        key = (item.semester, item.discipline_code,
               item.group_sequence, item.enrollment)
        if key in keys:
            await db.delete(item)
            removed += 1
    await db.flush()
    return removed


async def import_study_times(db, tutor_id: str, rows: list[dict]) -> dict:
    by_enrollment = await student_enrollment_index(db, tutor_id)
    existing = (await db.execute(select(StudyTimeModel).where(
        StudyTimeModel.tutor_id == tutor_id
    ))).scalars().all()
    by_key = {(item.semester, item.discipline_code, item.group_sequence,
               item.enrollment): item for item in existing}
    created = updated = linked = pending = 0
    for row in rows:
        key = (row["semester"], row["discipline_code"],
               row["group_sequence"], row["enrollment"])
        item = by_key.get(key)
        if item is None:
            item = StudyTimeModel(tutor_id=tutor_id, **row)
            db.add(item)
            by_key[key] = item
            created += 1
        else:
            for field, value in row.items():
                setattr(item, field, value)
            updated += 1
        student = match_study_student(row, by_enrollment)
        item.student_id = student.id if student else None
        linked += bool(item.student_id)
        pending += not bool(item.student_id)
    await db.commit()
    return dict(created=created, updated=updated, linked=linked, pending=pending)
