from app.core.database import LessonModel, StudentModel, derive_class_groups


def _student(name, class_group="", subject="", tutor_id="t1"):
    return StudentModel(
        id=name.lower(),
        tutor_id=tutor_id,
        name=name,
        class_group=class_group,
        subject=subject,
    )


def _lesson(lesson_id, class_group="", subject="ARA0040", tutor_id="t1"):
    return LessonModel(
        id=lesson_id,
        tutor_id=tutor_id,
        subject=subject,
        class_group=class_group,
        status="closed",
    )


def test_one_group_per_pair_of_subject_and_code():
    students = [
        _student("Ana", "3001", "ARA0040"),
        _student("Bruno", "3001", "ARA0040"),
        _student("Thiago", "3002", "ARA0040"),
        _student("Carla", "4001", "ARA0031"),
    ]

    groups, _ = derive_class_groups(students, [])

    assert sorted((group.code, group.subject) for group in groups) == [
        ("3001", "ARA0040"),
        ("3002", "ARA0040"),
        ("4001", "ARA0031"),
    ]


def test_students_of_the_same_class_share_the_link():
    students = [_student("Ana", "3001", "ARA0040"), _student("Bruno", "3001", "ARA0040")]

    derive_class_groups(students, [])

    assert students[0].class_id == students[1].class_id
    assert students[0].class_id


def test_student_without_class_or_subject_stays_unlinked():
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


def test_lesson_without_class_links_to_every_class_of_the_subject():
    # Era assim que aula reunida existia antes: turma vazia no texto.
    students = [
        _student("Ana", "3001", "ARA0040"),
        _student("Thiago", "3002", "ARA0040"),
        _student("Carla", "4001", "ARA0031"),
    ]
    lesson = _lesson("l1", class_group="", subject="ARA0040")

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
