from app.core.database import (
    ClassGroupModel,
    LessonModel,
    StudentModel,
    derive_class_groups,
    derive_disciplines,
)


def _student(name, class_group="", discipline="", tutor_id="t1"):
    return StudentModel(
        id=name.lower(),
        tutor_id=tutor_id,
        name=name,
        class_group=class_group,
        discipline=discipline,
    )


def _lesson(lesson_id, class_group="", discipline="ARA0040", tutor_id="t1"):
    return LessonModel(
        id=lesson_id,
        tutor_id=tutor_id,
        discipline=discipline,
        class_group=class_group,
        status="closed",
    )


def test_one_group_per_pair_of_discipline_and_code():
    students = [
        _student("Ana", "3001", "ARA0040"),
        _student("Bruno", "3001", "ARA0040"),
        _student("Thiago", "3002", "ARA0040"),
        _student("Carla", "4001", "ARA0031"),
    ]

    groups, _ = derive_class_groups(students, [])

    assert sorted((group.code, group.discipline) for group in groups) == [
        ("3001", "ARA0040"),
        ("3002", "ARA0040"),
        ("4001", "ARA0031"),
    ]


def test_students_of_the_same_class_share_the_link():
    students = [_student("Ana", "3001", "ARA0040"), _student("Bruno", "3001", "ARA0040")]

    derive_class_groups(students, [])

    assert students[0].class_id == students[1].class_id
    assert students[0].class_id


def test_student_without_class_or_discipline_stays_unlinked():
    students = [_student("Sem turma")]

    groups, _ = derive_class_groups(students, [])

    assert groups == []
    assert students[0].class_id is None


def test_lesson_links_only_to_its_own_class():
    students = [_student("Ana", "3001", "ARA0040"), _student("Thiago", "3002", "ARA0040")]
    lesson = _lesson("l1", class_group="3001")

    groups, links = derive_class_groups(students, [lesson])

    assert len(links) == 1
    linked = next(g for g in groups if g.id == links[0].class_group_id)
    assert linked.code == "3001"


def test_lesson_without_class_links_to_every_class_of_the_discipline():
    # Era assim que aula reunida existia antes: turma vazia no texto.
    students = [
        _student("Ana", "3001", "ARA0040"),
        _student("Thiago", "3002", "ARA0040"),
        _student("Carla", "4001", "ARA0031"),
    ]
    lesson = _lesson("l1", class_group="", discipline="ARA0040")

    groups, links = derive_class_groups(students, [lesson])

    codes = sorted(
        next(g for g in groups if g.id == link.class_group_id).code for link in links
    )
    assert codes == ["3001", "3002"]


def test_lessons_of_another_tutor_are_not_linked():
    students = [_student("Ana", "3001", "ARA0040", tutor_id="t1")]
    lesson = _lesson("l1", class_group="3001", tutor_id="t2")

    _, links = derive_class_groups(students, [lesson])

    assert links == []


# --- Disciplinas derivadas das turmas --------------------------------------


def _group(code, discipline, tutor_id="t1"):
    return ClassGroupModel(
        id=f"{tutor_id}-{code}-{discipline}",
        tutor_id=tutor_id,
        code=code,
        name="",
        discipline=discipline,
    )


def test_one_discipline_per_distinct_text():
    groups = [
        _group("3001", "ARA0040"),
        _group("3002", "ARA0040"),
        _group("4001", "ARA0031"),
    ]

    disciplines = derive_disciplines(groups)

    assert sorted(discipline.code for discipline in disciplines) == ["ARA0031", "ARA0040"]


def test_classes_of_the_same_discipline_share_the_link():
    groups = [_group("3001", "ARA0040"), _group("3002", "ARA0040")]

    derive_disciplines(groups)

    assert groups[0].discipline_id == groups[1].discipline_id
    assert groups[0].discipline_id


def test_class_without_discipline_text_stays_unlinked():
    groups = [_group("3001", "")]

    disciplines = derive_disciplines(groups)

    assert disciplines == []
    assert groups[0].discipline_id is None


def test_disciplines_are_not_shared_between_tutors():
    groups = [
        _group("3001", "ARA0040", tutor_id="t1"),
        _group("3001", "ARA0040", tutor_id="t2"),
    ]

    disciplines = derive_disciplines(groups)

    assert len(disciplines) == 2
    assert groups[0].discipline_id != groups[1].discipline_id
