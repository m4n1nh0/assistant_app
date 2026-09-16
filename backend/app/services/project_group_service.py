"""Cadastro de equipes de projeto a partir de listas de nomes."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

from sqlalchemy import select

from ..core.database import (
    AsyncSessionLocal, ClassGroupModel, DisciplineModel, ProjectGroupMemberModel,
    ProjectGroupModel, StudentModel,
)

_GROUP = re.compile(r"^[ \t]*GRUPO\s+(\d+)\b[ \t]*(.*)$", re.I | re.M)
_MEMBER_MARK = re.compile(r"\s+v\s*$", re.I)


def normalize_person(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(char for char in normalized
                            if not unicodedata.combining(char)).split())


def parse_project_group_text(text: str) -> tuple[list[dict], str]:
    """Trata o texto como lista de dados; anotações não viram pontuação."""
    if len(text) > 250_000:
        raise ValueError("Lista maior que 250 mil caracteres")
    groups: list[dict] = []
    context: list[str] = []
    current: dict | None = None
    seen_names: set[str] = set()
    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        header = _GROUP.match(line)
        if header:
            name = f"GRUPO {header.group(1)}"
            if name in seen_names:
                raise ValueError(f"Linha {line_number}: {name} repetido")
            seen_names.add(name)
            current = {"name": name, "note": header.group(2).strip(),
                       "members": []}
            groups.append(current)
            continue
        if current is None:
            if re.search(r"\b(cadastre|cadastrar|crie|criar|salve|salvar|"
                         r"importe|importar|registre|registrar)\b", line, re.I):
                continue
            context.append(line)
            continue
        if re.search(r"\b(cadastre|cadastrar|por favor|segue a lista)\b", line, re.I):
            continue
        marker = bool(_MEMBER_MARK.search(line))
        name = _MEMBER_MARK.sub("", line).strip()
        if not name or not re.fullmatch(r"[\wÀ-ÿ][\wÀ-ÿ .'-]{1,178}", name):
            raise ValueError(f"Linha {line_number}: nome não reconhecido: {line}")
        if any(normalize_person(member["name"]) == normalize_person(name)
               for member in current["members"]):
            raise ValueError(f"Linha {line_number}: nome repetido em {current['name']}")
        current["members"].append({"name": name, "note": "v" if marker else ""})
    if not groups or any(not group["members"] for group in groups):
        raise ValueError("A lista precisa conter GRUPO 1, GRUPO 2... com alunos")
    return groups, "\n".join(context)


def source_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_project_group_chat_action(message: str) -> dict | None:
    """Lista colada no chat vira proposta; o usuário confirma na aba de grupos."""
    first_group = _GROUP.search(message)
    if first_group is None or not re.search(
        r"\b(cadastre|cadastrar|crie|criar|salve|salvar|importe|importar|"
        r"registre|registrar)\b", message, re.I
    ):
        return None
    source = message.strip()
    try:
        groups, _ = parse_project_group_text(source)
    except ValueError:
        return None
    code = re.search(r"\bARA\d{4}\b", message, re.I)
    hint = "IoT" if re.search(r"\biot\b", message, re.I) else ""
    return dict(type="project_group_import", source_text=source,
                discipline_code=code.group().upper() if code else "",
                discipline_hint=hint, group_count=len(groups),
                requires_confirmation=True)


def is_project_group_question(message: str) -> bool:
    return bool(re.search(r"\b(grupo\s+\d+|grupo|grupos|equipes|integrantes)\b", message, re.I)
                and re.search(r"\b(projeto|projetos|an[aá]lis[ea]|avali|membros|"
                              r"integrantes|alunos|quem|qual|quais|pertence|"
                              r"grupo\s+\d+)\w*\b", message, re.I))


async def project_group_chat_data(tutor_id: str, message: str) -> str:
    """Entrega dados cadastrais como JSON no nível da pergunta, sem executar notas."""
    async with AsyncSessionLocal() as db:
        groups = (await db.execute(select(ProjectGroupModel).where(
            ProjectGroupModel.tutor_id == tutor_id
        ))).scalars().all()
        disciplines = (await db.execute(select(DisciplineModel).where(
            DisciplineModel.tutor_id == tutor_id
        ))).scalars().all()
        by_discipline = {item.id: item for item in disciplines}
        code = re.search(r"\bARA\d{4}\b", message, re.I)
        number = re.search(r"\bgrupo\s+(\d+)\b", message, re.I)
        if code:
            groups = [group for group in groups
                      if by_discipline.get(group.discipline_id)
                      and by_discipline[group.discipline_id].code.upper() == code.group().upper()]
        if number:
            groups = [group for group in groups
                      if group.name.upper() == f"GRUPO {number.group(1)}"]
        if re.search(r"\biot\b", message, re.I):
            groups = [group for group in groups
                      if by_discipline.get(group.discipline_id)
                      and "iot" in by_discipline[group.discipline_id].name.lower()]
        groups = groups[:20]
        member_rows = (await db.execute(select(ProjectGroupMemberModel).where(
            ProjectGroupMemberModel.group_id.in_([group.id for group in groups] or [""])
        ))).scalars().all()
    by_group: dict[str, list[str]] = {}
    for member in member_rows:
        by_group.setdefault(member.group_id, []).append(member.name)
    data = [dict(discipline_code=by_discipline[group.discipline_id].code,
                 semester=group.semester, group=group.name,
                 project_title=group.project_title,
                 project_description=group.project_description,
                 review_notes=group.review_notes,
                 penalty_points=group.penalty_points,
                 annotations_from_list=group.source_note,
                 members=by_group.get(group.id, []))
            for group in groups if group.discipline_id in by_discipline]
    return json.dumps(data, ensure_ascii=False)


async def roster_for_discipline(db, tutor_id: str, discipline_id: str) -> list[StudentModel]:
    classes = (await db.execute(select(ClassGroupModel).where(
        ClassGroupModel.tutor_id == tutor_id,
        ClassGroupModel.discipline_id == discipline_id,
    ))).scalars().all()
    class_ids = [item.id for item in classes]
    if not class_ids:
        return []
    return (await db.execute(select(StudentModel).where(
        StudentModel.tutor_id == tutor_id,
        StudentModel.class_id.in_(class_ids),
        StudentModel.active.is_(True),
    ))).scalars().all()


_NAME_PARTICLES = {"de", "da", "do", "das", "dos", "e"}


def _name_tokens(name: str) -> list[str]:
    return [token for token in normalize_person(name).split()
            if token not in _NAME_PARTICLES]


def partial_name_confidence(source_name: str, target_name: str) -> tuple[float, bool]:
    """Compara partes do nome; sinaliza cobertura exata para vínculo seguro."""
    source = _name_tokens(source_name)
    target = _name_tokens(target_name)
    if len(source) < 2 or not target:
        return 0.0, False
    exact_coverage = not (Counter(source) - Counter(target))
    if exact_coverage:
        # Penaliza nomes adicionais: dois nomes da lista são menos conclusivos
        # diante de um nome cadastrado muito longo.
        return round(max(0.0, 1.0 - 0.04 * (len(target) - len(source))), 3), True
    remaining = target.copy()
    similarities = []
    for token in source:
        if not remaining:
            similarities.append(0.0)
            continue
        best = max(remaining, key=lambda item: SequenceMatcher(None, token, item).ratio())
        similarity = SequenceMatcher(None, token, best).ratio()
        remaining.remove(best)
        similarities.append(similarity if similarity >= 0.65 else 0.0)
    coverage = sum(similarities) / len(source)
    whole = SequenceMatcher(None, normalize_person(source_name),
                            normalize_person(target_name)).ratio()
    return round(0.65 * coverage + 0.35 * whole, 3), False


def unique_student_match(name: str, roster: list[StudentModel]) -> StudentModel | None:
    key = normalize_person(name)
    exact = [student for student in roster if normalize_person(student.name) == key]
    if exact:
        return exact[0] if len(exact) == 1 else None
    scored = []
    for student in roster:
        confidence, complete = partial_name_confidence(name, student.name)
        if complete:
            scored.append((confidence, student))
    scored.sort(key=lambda row: -row[0])
    if not scored or scored[0][0] < 0.92:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.08:
        return None
    return scored[0][1]


def suggested_student_matches(name: str, roster: list[StudentModel]) -> list[dict]:
    """Propõe nomes parecidos da própria disciplina, sem vincular automaticamente."""
    proposals = []
    for student in roster:
        confidence, _ = partial_name_confidence(name, student.name)
        if confidence >= 0.55:
            proposals.append(dict(student_id=student.id, student_name=student.name,
                                  enrollment=student.external_id or "",
                                  confidence=confidence))
    return sorted(proposals, key=lambda row: (-row["confidence"], row["student_name"]))[:3]


def preview_member_match(name: str, roster: list[StudentModel]) -> dict:
    student = unique_student_match(name, roster)
    return dict(name=name, linked=student is not None,
                student_name=student.name if student else "",
                enrollment=(student.external_id or "") if student else "",
                confidence=(1.0 if student and normalize_person(name) == normalize_person(student.name)
                            else partial_name_confidence(name, student.name)[0]
                            if student else None))


async def preview_project_groups(db, tutor_id: str, discipline_id: str,
                                 parsed: list[dict]) -> dict:
    roster = await roster_for_discipline(db, tutor_id, discipline_id)
    existing = (await db.execute(select(ProjectGroupModel).where(
        ProjectGroupModel.tutor_id == tutor_id,
        ProjectGroupModel.discipline_id == discipline_id,
    ))).scalars().all()
    existing_names = {group.name for group in existing}
    existing_members = (await db.execute(select(ProjectGroupMemberModel).where(
        ProjectGroupMemberModel.group_id.in_([group.id for group in existing] or [""])
    ))).scalars().all()
    by_group_id: dict[str, set[str]] = {}
    for member in existing_members:
        by_group_id.setdefault(member.group_id, set()).add(normalize_person(member.name))
    existing_by_name = {group.name: group for group in existing}
    removed_members = 0
    for row in parsed:
        prior = existing_by_name.get(row["name"])
        if prior:
            incoming = {normalize_person(member["name"]) for member in row["members"]}
            removed_members += len(by_group_id.get(prior.id, set()) - incoming)
    matched = sum(bool(unique_student_match(member["name"], roster))
                  for group in parsed for member in group["members"])
    member_count = sum(len(group["members"]) for group in parsed)
    return dict(groups=len(parsed), members=member_count, linked=matched,
                names_without_unique_match=member_count - matched,
                new_groups=sum(group["name"] not in existing_names for group in parsed),
                updated_groups=sum(group["name"] in existing_names for group in parsed),
                members_removed_on_update=removed_members,
                group_names=[dict(name=group["name"], members=len(group["members"]),
                                  source_note=group["note"],
                                  names=[preview_member_match(member["name"], roster)
                                         for member in group["members"]])
                             for group in parsed])


async def import_project_groups(db, tutor_id: str, discipline, parsed: list[dict],
                                context: str) -> dict:
    roster = await roster_for_discipline(db, tutor_id, discipline.id)
    existing = (await db.execute(select(ProjectGroupModel).where(
        ProjectGroupModel.tutor_id == tutor_id,
        ProjectGroupModel.discipline_id == discipline.id,
    ))).scalars().all()
    by_name = {group.name: group for group in existing}
    created = updated = linked = 0
    for row in parsed:
        group = by_name.get(row["name"])
        if group is None:
            group = ProjectGroupModel(tutor_id=tutor_id,
                discipline_id=discipline.id, semester=discipline.semester,
                name=row["name"])
            db.add(group)
            await db.flush()
            created += 1
        else:
            updated += 1
        group.source_note = "\n".join(part for part in (context, row["note"]) if part)
        members = (await db.execute(select(ProjectGroupMemberModel).where(
            ProjectGroupMemberModel.group_id == group.id
        ))).scalars().all()
        by_member_name = {normalize_person(member.name): member for member in members}
        incoming_names = set()
        for position, member_row in enumerate(row["members"]):
            key = normalize_person(member_row["name"])
            incoming_names.add(key)
            member = by_member_name.get(key)
            if member is None:
                member = ProjectGroupMemberModel(group_id=group.id,
                    name=member_row["name"])
                db.add(member)
            student = unique_student_match(member_row["name"], roster)
            # Preserva vínculos corrigidos manualmente ao reimportar a lista.
            if student and not member.student_id:
                member.student_id = student.id
            member.name = member_row["name"]
            member.source_note = member_row["note"]
            member.position = position
            linked += bool(member.student_id)
        for member in members:
            if normalize_person(member.name) not in incoming_names:
                await db.delete(member)
    await db.commit()
    return dict(created=created, updated=updated, linked_members=linked,
                names_without_link=sum(len(group["members"]) for group in parsed) - linked)
