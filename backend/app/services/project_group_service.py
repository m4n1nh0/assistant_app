"""Cadastro de equipes de projeto a partir de listas de nomes."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from functools import lru_cache

from sqlalchemy import select

from ..core.database import (
    AsyncSessionLocal, ClassGroupModel, DisciplineModel, ProjectGroupMemberModel,
    ProjectGroupModel, ProjectGroupNameResolutionModel, StudentModel,
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
    if len(groups) > 100 or sum(len(group["members"]) for group in groups) > 1000:
        raise ValueError("Importe no máximo 100 grupos e 1000 integrantes por vez")
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


async def learned_name_resolutions(db, tutor_id: str, discipline_id: str,
                                   roster: list[StudentModel]) -> dict[str, StudentModel | None]:
    rows = (await db.execute(select(ProjectGroupNameResolutionModel).where(
        ProjectGroupNameResolutionModel.tutor_id == tutor_id,
        ProjectGroupNameResolutionModel.discipline_id == discipline_id,
    ))).scalars().all()
    by_id = {student.id: student for student in roster}
    by_enrollment: dict[str, list[StudentModel]] = {}
    for student in roster:
        if student.external_id:
            by_enrollment.setdefault(student.external_id.strip(), []).append(student)
    learned = {}
    for row in rows:
        if row.blocked:
            learned[row.source_name] = None
            continue
        student = by_id.get(row.student_id)
        if student is None and row.enrollment:
            candidates = by_enrollment.get(row.enrollment.strip(), [])
            student = _single_student_identity(candidates)
        if student is not None:
            learned[row.source_name] = student
    return learned


async def remember_name_resolution(db, tutor_id: str, discipline_id: str,
                                   source_name: str, student: StudentModel | None) -> None:
    key = normalize_person(source_name)
    row = (await db.execute(select(ProjectGroupNameResolutionModel).where(
        ProjectGroupNameResolutionModel.tutor_id == tutor_id,
        ProjectGroupNameResolutionModel.discipline_id == discipline_id,
        ProjectGroupNameResolutionModel.source_name == key,
    ))).scalar_one_or_none()
    if row is None:
        row = ProjectGroupNameResolutionModel(tutor_id=tutor_id,
            discipline_id=discipline_id, source_name=key)
        db.add(row)
    row.student_id = student.id if student else None
    row.enrollment = (student.external_id or None) if student else None
    row.blocked = student is None


_NAME_PARTICLES = {"de", "da", "do", "das", "dos", "e"}


def _name_tokens(name: str) -> list[str]:
    return [token for token in normalize_person(name).split()
            if token not in _NAME_PARTICLES]


def _sound_token(token: str) -> str:
    """Equivalência conservadora para grafias de nome próprio com I/Y."""
    return token.replace("y", "i")


def _character_ngrams(name: str) -> Counter[str]:
    sound = " ".join(map(_sound_token, _name_tokens(name)))
    padded = f" {sound} "
    return Counter(padded[index:index + size]
                   for size in (2, 3) for index in range(len(padded) - size + 1))


class NameSimilarityIndex:
    """Índice TF-IDF de fragmentos dos nomes cadastrados na disciplina."""
    def __init__(self, roster: list[StudentModel]):
        self.rows = [(student.id, _character_ngrams(candidate))
                     for student in roster
                     for candidate in [student.name,
                        *(getattr(student, "aliases", None) or [])]
                     if isinstance(candidate, str) and candidate.strip()]
        documents = len(self.rows)
        frequencies = Counter(fragment for _, counts in self.rows
                              for fragment in counts)
        self.idf = {fragment: math.log((documents + 1) / (frequency + 1)) + 1
                    for fragment, frequency in frequencies.items()}
        self.vectors = [(student_id, self._vector(counts))
                        for student_id, counts in self.rows]

    def _vector(self, counts: Counter[str]) -> dict[str, float]:
        weighted = {fragment: amount * self.idf.get(fragment, 1.0)
                    for fragment, amount in counts.items()}
        length = math.sqrt(sum(value * value for value in weighted.values())) or 1.0
        return {fragment: value / length for fragment, value in weighted.items()}

    def similarities(self, name: str) -> dict[str, float]:
        query = self._vector(_character_ngrams(name))
        scores: dict[str, float] = {}
        for student_id, vector in self.vectors:
            similarity = sum(value * vector.get(fragment, 0.0)
                             for fragment, value in query.items())
            scores[student_id] = max(scores.get(student_id, 0.0), similarity)
        return scores


def damerau_levenshtein(source: str, target: str) -> int:
    """Distância de edição com transposição adjacente, sem dependência externa."""
    if source == target:
        return 0
    previous_previous = list(range(len(target) + 1))
    previous = previous_previous
    for row_index, left in enumerate(source, start=1):
        current = [row_index] + [0] * len(target)
        for column_index, right in enumerate(target, start=1):
            current[column_index] = min(
                previous[column_index] + 1,
                current[column_index - 1] + 1,
                previous[column_index - 1] + (left != right),
            )
            if (row_index > 1 and column_index > 1
                    and left == target[column_index - 2]
                    and source[row_index - 2] == right):
                current[column_index] = min(current[column_index],
                    previous_previous[column_index - 2] + 1)
        previous_previous, previous = previous, current
    return previous[-1]


def _token_edit_similarity(source: str, target: str) -> float:
    left, right = _sound_token(source), _sound_token(target)
    if left == right:
        return 1.0
    edit = 1.0 - damerau_levenshtein(left, right) / max(len(left), len(right))
    prefix = 0.0
    if min(len(left), len(right)) >= 4 and (left.startswith(right) or right.startswith(left)):
        prefix = 0.88 - 0.02 * abs(len(left) - len(right))
    return max(0.0, edit, prefix, SequenceMatcher(None, left, right).ratio())


def _best_token_alignment(source: list[str], target: list[str]) -> float:
    similarities = [[_token_edit_similarity(left, right) for right in target]
                    for left in source]

    @lru_cache(maxsize=None)
    def best(index: int, used: int) -> float:
        if index == len(source):
            return 0.0
        score = best(index + 1, used)
        for target_index, similarity in enumerate(similarities[index]):
            if not used & (1 << target_index) and similarity >= 0.55:
                score = max(score, similarity + best(index + 1,
                    used | (1 << target_index)))
        return score

    return best(0, 0) / len(source)


def _complete_name_confidence(source: list[str], target: list[str]) -> float | None:
    if len(source) < 2 or not target:
        return None
    extra = len(target) - len(source)
    if not (Counter(source) - Counter(target)):
        return round(max(0.0, 1.0 - 0.04 * extra), 3)
    if not (Counter(map(_sound_token, source)) - Counter(map(_sound_token, target))):
        return round(max(0.0, 0.98 - 0.03 * extra), 3)
    return None


def partial_name_confidence(source_name: str, target_name: str) -> tuple[float, bool]:
    """Compara partes do nome; sinaliza cobertura exata para vínculo seguro."""
    source = _name_tokens(source_name)
    target = _name_tokens(target_name)
    if len(source) < 2 or not target:
        return 0.0, False
    complete = _complete_name_confidence(source, target)
    if complete is not None:
        return complete, True
    coverage = _best_token_alignment(source, target)
    whole = SequenceMatcher(None, normalize_person(source_name),
                            normalize_person(target_name)).ratio()
    return round(0.72 * coverage + 0.28 * whole, 3), False


def student_name_confidence(name: str, student: StudentModel) -> float:
    names = [student.name, *(getattr(student, "aliases", None) or [])]
    key = normalize_person(name)
    scores = [(1.0 if normalize_person(candidate) == key else
               partial_name_confidence(name, candidate)[0])
              for candidate in names if isinstance(candidate, str) and candidate.strip()]
    return max(scores, default=0.0)


def _student_identity(student: StudentModel) -> str:
    enrollment = (getattr(student, "external_id", None) or "").strip()
    return f"enrollment:{enrollment}" if enrollment else f"student:{student.id}"


def _single_student_identity(matches: list[StudentModel]) -> StudentModel | None:
    return matches[0] if matches and len({_student_identity(item) for item in matches}) == 1 else None


def unique_student_match(name: str, roster: list[StudentModel],
                         learned: dict[str, StudentModel | None] | None = None) -> StudentModel | None:
    key = normalize_person(name)
    if learned is not None and key in learned:
        return learned[key]
    exact = [student for student in roster if normalize_person(student.name) == key]
    if exact:
        return _single_student_identity(exact)
    if len(_name_tokens(name)) >= 2:
        alias_exact = [student for student in roster
                       if any(isinstance(alias, str) and normalize_person(alias) == key
                              for alias in (getattr(student, "aliases", None) or []))]
        if alias_exact:
            return _single_student_identity(alias_exact)
    scored = []
    source_tokens = _name_tokens(name)
    for student in roster:
        confidence = _complete_name_confidence(source_tokens, _name_tokens(student.name))
        if confidence is not None:
            scored.append((confidence, student))
    scored.sort(key=lambda row: (-row[0], row[1].id))
    seen_identities = set()
    unique_scored = []
    for row in scored:
        identity = _student_identity(row[1])
        if identity not in seen_identities:
            unique_scored.append(row)
            seen_identities.add(identity)
    scored = unique_scored
    if not scored or scored[0][0] < 0.92:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.08:
        return None
    return scored[0][1]


def suggested_student_matches(name: str, roster: list[StudentModel],
                              index: NameSimilarityIndex | None = None) -> list[dict]:
    """Propõe nomes parecidos da própria disciplina, sem vincular automaticamente."""
    proposals = []
    ml_scores = (index or NameSimilarityIndex(roster)).similarities(name)
    shortlist = {student_id for student_id, _ in sorted(ml_scores.items(),
                  key=lambda item: -item[1])[:40]}
    source_parts = set(map(_sound_token, _name_tokens(name)))
    for student in roster:
        if student.id not in shortlist and not source_parts.intersection(
                map(_sound_token, _name_tokens(student.name))):
            continue
        rule_score = student_name_confidence(name, student)
        confidence = round(max(rule_score,
            0.65 * rule_score + 0.35 * ml_scores.get(student.id, 0.0)), 3)
        if confidence >= 0.48:
            proposals.append(dict(student_id=student.id, student_name=student.name,
                                  enrollment=student.external_id or "",
                                  confidence=confidence))
    proposals.sort(key=lambda row: (-row["confidence"], row["student_name"]))
    by_student = {student.id: student for student in roster}
    seen_identities = set()
    unique = []
    for row in proposals:
        identity = _student_identity(by_student[row["student_id"]])
        if identity not in seen_identities:
            unique.append(row)
            seen_identities.add(identity)
    return unique[:3]


def preview_member_match(name: str, roster: list[StudentModel],
                         index: NameSimilarityIndex | None = None,
                         learned: dict[str, StudentModel | None] | None = None) -> dict:
    student = unique_student_match(name, roster, learned)
    confirmed = learned is not None and normalize_person(name) in learned
    return dict(name=name, linked=student is not None,
                student_name=student.name if student else "",
                enrollment=(student.external_id or "") if student else "",
                confidence=student_name_confidence(name, student) if student else None,
                match_source="confirmed" if confirmed and student else "similarity",
                candidates=suggested_student_matches(name, roster, index))


async def preview_project_groups(db, tutor_id: str, discipline_id: str,
                                 parsed: list[dict]) -> dict:
    roster = await roster_for_discipline(db, tutor_id, discipline_id)
    learned = await learned_name_resolutions(db, tutor_id, discipline_id, roster)
    index = NameSimilarityIndex(roster)
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
    matched = sum(bool(unique_student_match(member["name"], roster, learned))
                  for group in parsed for member in group["members"])
    member_count = sum(len(group["members"]) for group in parsed)
    return dict(groups=len(parsed), members=member_count, linked=matched,
                roster_count=len({_student_identity(student) for student in roster}),
                names_without_unique_match=member_count - matched,
                new_groups=sum(group["name"] not in existing_names for group in parsed),
                updated_groups=sum(group["name"] in existing_names for group in parsed),
                members_removed_on_update=removed_members,
                group_names=[dict(name=group["name"], members=len(group["members"]),
                                  source_note=group["note"],
                                  names=[preview_member_match(member["name"], roster, index, learned)
                                         for member in group["members"]])
             for group in parsed])


def validate_import_member_links(parsed: list[dict], links: list,
                                 roster: list[StudentModel]) -> dict[tuple[str, str], str | None]:
    valid_members = {(group["name"], normalize_person(member["name"]))
                     for group in parsed for member in group["members"]}
    valid_students = {student.id for student in roster}
    choices: dict[tuple[str, str], str | None] = {}
    assigned: set[str] = set()
    for link in links:
        key = (link.group_name, normalize_person(link.member_name))
        if key not in valid_members or key in choices:
            raise ValueError("Correção de vínculo repetida ou fora da lista; confira a prévia novamente")
        if link.student_id is not None and link.student_id not in valid_students:
            raise ValueError("Aluno escolhido não pertence às turmas desta disciplina")
        if link.student_id and link.student_id in assigned:
            raise ValueError("O mesmo aluno foi escolhido para dois integrantes")
        choices[key] = link.student_id
        if link.student_id:
            assigned.add(link.student_id)
    return choices


async def import_project_groups(db, tutor_id: str, discipline, parsed: list[dict],
                                context: str, member_links: list | None = None) -> dict:
    roster = await roster_for_discipline(db, tutor_id, discipline.id)
    learned = await learned_name_resolutions(db, tutor_id, discipline.id, roster)
    choices = validate_import_member_links(parsed, member_links or [], roster)
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
            student = unique_student_match(member_row["name"], roster, learned)
            # Preserva vínculos corrigidos manualmente ao reimportar a lista.
            choice_key = (row["name"], key)
            if choice_key in choices:
                member.student_id = choices[choice_key]
                selected_student = next((item for item in roster
                                         if item.id == member.student_id), None)
                await remember_name_resolution(db, tutor_id, discipline.id,
                                               member_row["name"], selected_student)
            elif student and not member.student_id:
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
