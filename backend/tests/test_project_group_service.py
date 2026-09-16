from app.services.project_group_service import (
    build_project_group_chat_action, is_project_group_question,
    parse_project_group_text,
    suggested_student_matches,
    unique_student_match,
    partial_name_confidence,
    validate_import_member_links,
    NameSimilarityIndex,
)


def test_group_list_preserves_annotations_as_data():
    groups, context = parse_project_group_text(
        "QUIZ SERA O TEMA 2 para 13/10\n"
        "GRUPO 1\nNICOLAS ROSA\nRAIAN LUZ v\n"
        "GRUPO 2 -0,5\nSAIMON RUAM v\nLUIZ FERNANDO\n"
    )

    assert [group["name"] for group in groups] == ["GRUPO 1", "GRUPO 2"]
    assert groups[1]["note"] == "-0,5"
    assert groups[0]["members"][1] == {"name": "RAIAN LUZ", "note": "v"}
    assert context == "QUIZ SERA O TEMA 2 para 13/10"


def test_pasted_chat_list_proposes_import_without_writing():
    action = build_project_group_chat_action(
        "Cadastre os grupos de IoT na ARA0058:\n"
        "GRUPO 1\nNICOLAS ROSA\nGRUPO 2\nRAIAN LUZ"
    )

    assert action is not None
    assert action["type"] == "project_group_import"
    assert action["discipline_code"] == "ARA0058"
    assert action["group_count"] == 2


def test_project_question_requests_registered_group_context():
    assert is_project_group_question("Analise o projeto do grupo 3 da ARA0058")
    assert is_project_group_question("Qual grupo tem Nicolas Rosa?")
    assert not is_project_group_question("Quando tenho aula na turma 3001?")


def test_name_suggestions_show_matriculas_without_linking():
    from types import SimpleNamespace
    roster = [
        SimpleNamespace(id="one", name="JOAO VITOR PEREIRA DA SILVA", external_id="20250001"),
        SimpleNamespace(id="two", name="MARIA EDUARDA SOUZA", external_id="20250002"),
    ]
    candidates = suggested_student_matches("JOAO VITOR PEREIRA", roster)
    assert candidates[0]["student_id"] == "one"
    assert candidates[0]["enrollment"] == "20250001"
    assert all(candidate["student_id"] != "two" for candidate in candidates)


def test_unique_name_prefix_is_linked_but_ambiguous_prefix_is_not():
    from types import SimpleNamespace
    nicolas = SimpleNamespace(id="one", name="NICOLAS ROSA SANTOS")
    other = SimpleNamespace(id="two", name="MARIA EDUARDA SOUZA")
    assert unique_student_match("NICOLAS ROSA", [nicolas, other]) is nicolas
    assert unique_student_match("NICOLAS", [nicolas, other]) is None
    assert unique_student_match("NICOLAS ROSA", [nicolas,
        SimpleNamespace(id="three", name="NICOLAS ROSA SILVA")]) is None


def test_non_consecutive_name_parts_match_with_clear_margin():
    from types import SimpleNamespace
    pedro = SimpleNamespace(id="one", name="PEDRO HENRIQUE FEITOSA")
    other = SimpleNamespace(id="two", name="PEDRO LUCAS COSTA")
    assert unique_student_match("PEDRO FEITOSA", [pedro, other]) is pedro
    confidence, complete = partial_name_confidence("PEDRO FEITOSA", pedro.name)
    assert complete and confidence >= 0.92


def test_name_typo_is_suggested_but_not_auto_linked():
    from types import SimpleNamespace
    pedro = SimpleNamespace(id="one", name="PEDRO HENRIQUE FEITOSA", external_id="123")
    assert unique_student_match("PEDRO FEITOZA", [pedro]) is None
    assert suggested_student_matches("PEDRO FEITOZA", [pedro])[0]["student_id"] == "one"


def test_registered_alias_can_resolve_abbreviated_name():
    from types import SimpleNamespace
    student = SimpleNamespace(id="one", name="HENRIQUE JOSE DA SILVA",
                              external_id="123", aliases=["HENRI JOSE"])
    assert unique_student_match("HENRI JOSE", [student]) is student


def test_import_correction_is_scoped_to_list_and_discipline():
    from types import SimpleNamespace
    parsed = [{"name": "GRUPO 1", "members": [{"name": "MATHEUS ALVES"}]}]
    roster = [SimpleNamespace(id="one")]
    choices = validate_import_member_links(parsed,
        [SimpleNamespace(group_name="GRUPO 1", member_name="MATHEUS ALVES",
                         student_id="one")], roster)
    assert choices[("GRUPO 1", "matheus alves")] == "one"
    import pytest
    with pytest.raises(ValueError, match="não pertence"):
        validate_import_member_links(parsed,
            [SimpleNamespace(group_name="GRUPO 1", member_name="MATHEUS ALVES",
                             student_id="outside")], roster)


def test_same_enrollment_in_two_classes_is_one_identity():
    from types import SimpleNamespace
    roster = [
        SimpleNamespace(id="class-a", name="NICOLAS ROSA SANTOS",
                        external_id="789", aliases=[]),
        SimpleNamespace(id="class-b", name="NICOLAS ROSA SANTOS",
                        external_id="789", aliases=[]),
    ]
    assert unique_student_match("NICOLAS ROSA", roster).external_id == "789"
    assert len(suggested_student_matches("NICOLAS ROSA", roster)) == 1


def test_i_y_sound_variation_can_link_unique_student():
    from types import SimpleNamespace
    ryan = SimpleNamespace(id="one", name="RYAN ADRYAN GOMES LEITE",
                           external_id="123", aliases=[])
    assert unique_student_match("RIAN ADRIAN", [ryan]) is ryan
    confidence, covered = partial_name_confidence("RIAN ADRIAN", ryan.name)
    assert covered and confidence >= 0.92
    another = SimpleNamespace(id="two", name="RYAN ADRYAN SILVA COSTA",
                              external_id="456", aliases=[])
    assert unique_student_match("RIAN ADRIAN", [ryan, another]) is None


def test_character_ngram_index_ranks_name_variations():
    from types import SimpleNamespace
    roster = [
        SimpleNamespace(id="ryan", name="RYAN ADRYAN GOMES LEITE",
                        external_id="123", aliases=[]),
        SimpleNamespace(id="pedro", name="PEDRO HENRIQUE FEITOSA",
                        external_id="456", aliases=[]),
    ]
    index = NameSimilarityIndex(roster)
    candidates = suggested_student_matches("RIAN ADRIAN", roster, index)
    assert candidates[0]["student_id"] == "ryan"


def test_confirmed_resolution_takes_precedence_and_can_block_auto_link():
    from types import SimpleNamespace
    student = SimpleNamespace(id="one", name="RYAN ADRYAN GOMES LEITE",
                              external_id="123", aliases=[])
    assert unique_student_match("RIAN ADRIAN", [student],
                                {"rian adrian": None}) is None
    assert unique_student_match("RIAN ADRIAN", [student],
                                {"rian adrian": student}) is student


def test_confirmed_name_resolution_is_scoped_and_persisted():
    import asyncio
    from types import SimpleNamespace
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.core.database import ProjectGroupNameResolutionModel
    from app.services.project_group_service import (
        learned_name_resolutions, remember_name_resolution,
    )

    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(ProjectGroupNameResolutionModel.__table__.create)
        try:
            student = SimpleNamespace(id="one", name="RYAN ADRYAN GOMES LEITE",
                                      external_id="123")
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                await remember_name_resolution(db, "tutor", "iot", "RIAN ADRIAN", student)
                await db.commit()
                learned = await learned_name_resolutions(db, "tutor", "iot", [student])
                assert learned["rian adrian"] is student
                assert await learned_name_resolutions(db, "other", "iot", [student]) == {}
                assert await learned_name_resolutions(db, "tutor", "cloud", [student]) == {}
                await remember_name_resolution(db, "tutor", "iot", "RIAN ADRIAN", None)
                await db.commit()
                learned = await learned_name_resolutions(db, "tutor", "iot", [student])
                assert "rian adrian" in learned and learned["rian adrian"] is None
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_import_uses_confirmed_student_and_learns_name_variation():
    import asyncio
    from types import SimpleNamespace
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.core.database import (
        ClassGroupModel, DisciplineModel, ProjectGroupMemberModel,
        ProjectGroupModel, ProjectGroupNameResolutionModel, StudentModel,
    )
    from app.services.project_group_service import (
        import_project_groups, learned_name_resolutions,
    )

    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        tables = [DisciplineModel.__table__, ClassGroupModel.__table__,
                  StudentModel.__table__, ProjectGroupModel.__table__,
                  ProjectGroupMemberModel.__table__,
                  ProjectGroupNameResolutionModel.__table__]
        async with engine.begin() as conn:
            for table in tables:
                await conn.run_sync(table.create)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                discipline = DisciplineModel(id="iot", tutor_id="tutor", code="ARA0058",
                                             name="IoT", semester="2026.2")
                db.add_all([discipline,
                    ClassGroupModel(id="class", tutor_id="tutor", discipline_id="iot"),
                    StudentModel(id="ryan", tutor_id="tutor", class_id="class",
                                 name="RYAN ADRYAN GOMES LEITE", external_id="123")])
                await db.commit()
                parsed = [{"name": "GRUPO 1", "note": "",
                           "members": [{"name": "RIAN ADRIAN", "note": ""}]}]
                link = SimpleNamespace(group_name="GRUPO 1", member_name="RIAN ADRIAN",
                                       student_id="ryan")
                result = await import_project_groups(db, "tutor", discipline, parsed, "", [link])
                assert result["linked_members"] == 1
                member = (await db.execute(select(ProjectGroupMemberModel))).scalar_one()
                assert member.student_id == "ryan"
                learned = await learned_name_resolutions(db, "tutor", "iot",
                    (await db.execute(select(StudentModel))).scalars().all())
                assert learned["rian adrian"].id == "ryan"
        finally:
            await engine.dispose()

    asyncio.run(scenario())
